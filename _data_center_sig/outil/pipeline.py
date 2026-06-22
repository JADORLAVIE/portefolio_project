"""
pipeline.py — Cœur de l'outil : le pipeline geo-data engineer en DuckDB.

Philosophie :
  * Tout le calcul géo reste DANS la base (DuckDB spatial + h3) : zéro
    aller-retour Python, donc ça scalera à la France sans réécriture.
  * Indexation H3 : on ne fait JAMAIS de produit cartésien géométrique.
    Chaque jointure de proximité passe par un préfiltre hexagonal H3.
  * Entonnoir : chaque filtre ne garde que les parcelles qui passent, donc
    le filtre suivant travaille sur MOINS de lignes (optimisation native).
  * Idempotence : CREATE OR REPLACE partout -> on peut relancer sans nettoyer.
  * EPSG:2154 (Lambert-93) pour toutes les surfaces et distances.

Le pipeline est une suite de modèles (tables) organisés en 3 couches :
  staging.*       -> données brutes nettoyées + index H3
  intermediate.*  -> jointures spatiales (parcelle <-> bâti, surface libre)
  marts.*         -> les 5 filtres en cascade, le scoring, la heatmap
"""

import config as C
from db import table_count

RAW = str(C.RAW_DIR).replace("\\", "/")


# ===========================================================================
#  SETUP — macros réutilisables
# ===========================================================================
def setup_macros(con) -> None:
    """Crée les fonctions SQL maison (DRY : définies une seule fois)."""
    # h3_of(geom, res) : index H3 d'une géométrie Lambert-93.
    # On reprojette le centroïde en WGS84 (lat/lng) car H3 vit en sphérique.
    con.execute(f"""
        CREATE OR REPLACE MACRO h3_of(g, res) AS
          h3_latlng_to_cell(
            ST_Y(ST_Transform(ST_Centroid(g), 'EPSG:{C.CRS_METRIQUE}', 'EPSG:{C.CRS_GEO}', true)),
            ST_X(ST_Transform(ST_Centroid(g), 'EPSG:{C.CRS_METRIQUE}', 'EPSG:{C.CRS_GEO}', true)),
            res);
    """)


# ===========================================================================
#  COUCHE 1 — STAGING (nettoyage + index H3)
# ===========================================================================
def build_staging(con) -> dict:
    """Lit les GeoParquet bruts, valide les géométries, ajoute les index H3."""

    # -- Parcelles : table pivot. On calcule la surface (2154) et 2 niveaux H3.
    con.execute(f"""
        CREATE OR REPLACE TABLE staging.stg_parcelles AS
        SELECT
            id_parcelle, dept, commune, commune_insee,
            ST_MakeValid(geometry)              AS geom,
            ST_Area(geometry)                   AS surface_m2,
            h3_of(geometry, {C.H3_RES_JOIN})    AS h3_res9,
            h3_of(geometry, {C.H3_RES_HEATMAP}) AS h3_res8
        FROM read_parquet('{RAW}/parcelles.parquet')
        WHERE ST_IsValid(geometry);
    """)

    # -- Bâtiments résidentiels (la BD TOPO réelle serait pré-filtrée ainsi)
    con.execute(f"""
        CREATE OR REPLACE TABLE staging.stg_batiments AS
        SELECT
            id_batiment, dept, usage, sous_type,
            ST_MakeValid(geometry)           AS geom,
            ST_Area(geometry)                AS surface_m2,
            h3_of(geometry, {C.H3_RES_JOIN}) AS h3_res9
        FROM read_parquet('{RAW}/batiments.parquet')
        WHERE ST_IsValid(geometry);
    """)

    # -- Fibre (ARCEP) : points avec statut de déploiement
    con.execute(f"""
        CREATE OR REPLACE TABLE staging.stg_fibre AS
        SELECT id_locale, dept, statut_deploiement, operateur,
               geometry AS geom, h3_of(geometry, {C.H3_RES_JOIN}) AS h3_res9
        FROM read_parquet('{RAW}/fibre.parquet');
    """)

    # -- Énergie (Enedis) : postes sources + capacité disponible
    con.execute(f"""
        CREATE OR REPLACE TABLE staging.stg_energie AS
        SELECT id_poste_source, dept, puissance_max_kva, puissance_disponible_kva,
               geometry AS geom, h3_of(geometry, {C.H3_RES_JOIN}) AS h3_res9
        FROM read_parquet('{RAW}/energie.parquet');
    """)

    # -- Bonus : bornes VE et installations PV
    con.execute(f"""
        CREATE OR REPLACE TABLE staging.stg_bornes_ve AS
        SELECT id_borne, geometry AS geom, h3_of(geometry, {C.H3_RES_JOIN}) AS h3_res9
        FROM read_parquet('{RAW}/bornes_ve.parquet');
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE staging.stg_pv AS
        SELECT id_pv, geometry AS geom, h3_of(geometry, {C.H3_RES_JOIN}) AS h3_res9
        FROM read_parquet('{RAW}/pv.parquet');
    """)

    # -- Contraintes réglementaires. ABF : on pré-calcule le tampon de 500 m.
    con.execute(f"""
        CREATE OR REPLACE TABLE staging.stg_abf AS
        SELECT id_monument, nom, geometry AS geom,
               ST_Buffer(geometry, {C.ABF_BUFFER_M}) AS geom_buffer
        FROM read_parquet('{RAW}/abf.parquet');
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE staging.stg_ppri AS
        SELECT id_ppri, niveau_risque, ST_MakeValid(geometry) AS geom
        FROM read_parquet('{RAW}/ppri.parquet');
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE staging.stg_ebc AS
        SELECT id_ebc, ST_MakeValid(geometry) AS geom
        FROM read_parquet('{RAW}/ebc.parquet');
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE staging.stg_voirie AS
        SELECT id_troncon, geometry AS geom
        FROM read_parquet('{RAW}/voirie.parquet');
    """)

    # -- Index spatial RTREE sur la grosse table (inutile sur 484 lignes,
    #    mais c'est LE réflexe qui évite l'explosion à l'échelle France).
    try:
        con.execute("CREATE INDEX IF NOT EXISTS idx_parc_geom ON staging.stg_parcelles USING RTREE (geom);")
    except Exception:
        pass  # l'index RTREE n'est pas critique pour le résultat

    return {t: table_count(con, f"staging.{t}") for t in (
        "stg_parcelles", "stg_batiments", "stg_fibre", "stg_energie",
        "stg_bornes_ve", "stg_pv", "stg_abf", "stg_ppri", "stg_ebc", "stg_voirie")}


# ===========================================================================
#  COUCHE 2 — INTERMEDIATE (jointures spatiales)
# ===========================================================================
def build_intermediate(con) -> dict:
    """Associe bâtiments<->parcelles via H3, puis calcule la surface libre."""

    # Jointure parcelle <-> bâtiment :
    #   1) préfiltre H3 (grid_disk k=1) -> très peu de candidats
    #   2) test exact ST_Intersects
    #   3) emprise au sol = surface de l'intersection (un bâtiment à cheval
    #      sur 2 parcelles n'est compté que pour sa part sur chacune)
    con.execute(f"""
        CREATE OR REPLACE TABLE intermediate.int_parcelles_batiments AS
        WITH paires AS (
            SELECT
                p.id_parcelle,
                b.usage, b.sous_type,
                ST_Intersection(p.geom, b.geom) AS inter
            FROM staging.stg_parcelles p
            JOIN staging.stg_batiments b
              ON list_contains(h3_grid_disk(p.h3_res9, {C.H3_DISK_K['batiment']}), b.h3_res9)
             AND ST_Intersects(p.geom, b.geom)
        )
        SELECT
            id_parcelle,
            COUNT(*)                                                              AS count_batiments,
            COUNT(*) FILTER (WHERE usage = '{C.USAGE_RESIDENTIEL}'
                               AND sous_type NOT IN ('{"','".join(C.SOUS_TYPES_EXCLUS)}')) AS count_resid,
            COUNT(*) FILTER (WHERE sous_type IN ('{"','".join(C.SOUS_TYPES_EXCLUS)}'))      AS count_immeuble,
            SUM(ST_Area(inter))                                                   AS emprise_m2,
            ST_Union_Agg(inter)                                                   AS geom_bati
        FROM paires
        GROUP BY id_parcelle;
    """)

    # Surface libre = surface parcelle - emprise des bâtiments.
    con.execute("""
        CREATE OR REPLACE TABLE intermediate.int_surface_libre AS
        SELECT
            p.id_parcelle, p.dept, p.commune, p.commune_insee,
            p.geom, p.h3_res9, p.h3_res8,
            p.surface_m2                              AS surface_parcelle_m2,
            COALESCE(b.emprise_m2, 0)                 AS emprise_batiments_m2,
            p.surface_m2 - COALESCE(b.emprise_m2, 0)  AS surface_libre_m2,
            COALESCE(b.count_resid, 0)                AS count_resid,
            COALESCE(b.count_immeuble, 0)             AS count_immeuble,
            b.geom_bati
        FROM staging.stg_parcelles p
        LEFT JOIN intermediate.int_parcelles_batiments b USING (id_parcelle);
    """)

    return {t: table_count(con, f"intermediate.{t}") for t in
            ("int_parcelles_batiments", "int_surface_libre")}


# ===========================================================================
#  COUCHE 3 — MARTS : les 5 filtres en cascade (entonnoir)
# ===========================================================================
def build_filters(con) -> dict:
    """Applique les 5 filtres ; chaque table ne garde que les survivants."""

    # ---- FILTRE 1 : FONCIER -------------------------------------------------
    # Habitat individuel résidentiel + surface libre suffisante.
    con.execute(f"""
        CREATE OR REPLACE TABLE marts.fct_filtre_01_foncier AS
        SELECT *,
            LEAST(surface_libre_m2 / {C.SCORE_FONCIER_REF_M2} * {C.SCORE_MAX_PAR_AXE}, {C.SCORE_MAX_PAR_AXE}) AS score_foncier
        FROM intermediate.int_surface_libre
        WHERE count_resid > 0                              -- au moins une maison
          AND count_immeuble = 0                           -- pas de copropriété verticale
          AND surface_libre_m2 > {C.SURFACE_LIBRE_MIN_M2}; -- espace dispo
    """)

    # ---- FILTRE 2 : NUISANCES & SÉCURITÉ -----------------------------------
    # Recul de 5 m vers l'intérieur, espace installable réel (hors bâti),
    # proximité du bâtiment (tirage câbles) et accès voirie.
    con.execute(f"""
        CREATE OR REPLACE TABLE marts.fct_filtre_02_nuisances AS
        WITH calc AS (
            SELECT *,
                -- zone installable = recul intérieur PRIVÉ du bâti existant
                ST_Difference(ST_Buffer(geom, -{C.BUFFER_NUISANCE_M}),
                              COALESCE(geom_bati, ST_GeomFromText('POLYGON EMPTY'))) AS geom_install
            FROM marts.fct_filtre_01_foncier
        ),
        mesures AS (
            SELECT *,
                ST_Area(geom_install)                                   AS surface_install_m2,
                ST_Distance(ST_Centroid(geom_install),
                            COALESCE(geom_bati, geom))                  AS dist_bati_m,
                (SELECT MIN(ST_Distance(calc.geom, v.geom))
                   FROM staging.stg_voirie v)                           AS dist_voirie_m
            FROM calc
        )
        SELECT * EXCLUDE (geom_install, geom_bati),
            -- score : surface installable + accès technique + accès voirie
            LEAST(
                8.0 * LEAST(surface_install_m2 / {C.SCORE_NUISANCE_REF_M2}, 1.0)
              + CASE WHEN dist_bati_m  <= {C.DIST_MAX_BATIMENT_M} THEN 8.0 ELSE 0.0 END
              + CASE WHEN dist_voirie_m <= {C.DIST_VOIRIE_ACCES_M} THEN 4.0 ELSE 0.0 END,
                {C.SCORE_MAX_PAR_AXE}) AS score_nuisances
        FROM mesures
        WHERE surface_install_m2 >= {C.BUFFER_USABLE_MIN_M2}
          AND dist_bati_m <= {C.DIST_MAX_BATIMENT_M};
    """)

    # ---- FILTRE 3 : FIBRE (ARCEP) ------------------------------------------
    # Statut de déploiement du point fibre le plus proche (préfiltre H3).
    con.execute(f"""
        CREATE OR REPLACE TABLE marts.fct_filtre_03_fibre AS
        WITH cand AS (
            SELECT p.id_parcelle,
                   f.statut_deploiement AS statut,
                   ST_Distance(p.geom, f.geom) AS d
            FROM marts.fct_filtre_02_nuisances p
            JOIN staging.stg_fibre f
              ON list_contains(h3_grid_disk(p.h3_res9, {C.H3_DISK_K['fibre']}), f.h3_res9)
        ),
        plus_proche AS (
            SELECT id_parcelle,
                   arg_min(statut, d) AS fibre_statut,
                   MIN(d)             AS dist_fibre_m
            FROM cand GROUP BY id_parcelle
        )
        SELECT p.*, n.fibre_statut, n.dist_fibre_m,
            CASE n.fibre_statut
                WHEN 'Déployé'     THEN {C.SCORE_MAX_PAR_AXE}
                WHEN 'Raccordable' THEN 12.0
                ELSE 0.0 END AS score_fibre
        FROM marts.fct_filtre_02_nuisances p
        JOIN plus_proche n USING (id_parcelle)
        WHERE n.fibre_statut IN ('{"','".join(C.FIBRE_STATUTS_OK)}');
    """)

    # ---- FILTRE 4 : ÉNERGIE (Enedis) ---------------------------------------
    # Capacité disponible du poste source le plus proche >= 36 kVA.
    con.execute(f"""
        CREATE OR REPLACE TABLE marts.fct_filtre_04_energie AS
        WITH cand AS (
            SELECT p.id_parcelle,
                   e.puissance_disponible_kva AS pdispo,
                   ST_Distance(p.geom, e.geom) AS d
            FROM marts.fct_filtre_03_fibre p
            JOIN staging.stg_energie e
              ON list_contains(h3_grid_disk(p.h3_res9, {C.H3_DISK_K['energie']}), e.h3_res9)
        ),
        plus_proche AS (
            SELECT id_parcelle,
                   arg_min(pdispo, d) AS puissance_dispo_kva,
                   MIN(d)             AS dist_poste_m
            FROM cand GROUP BY id_parcelle
        )
        SELECT p.*, n.puissance_dispo_kva, n.dist_poste_m,
            LEAST(10.0 + 10.0 * LEAST(
                (n.puissance_dispo_kva - {C.PUISSANCE_MIN_KVA})
                / ({C.PUISSANCE_CONFORT_KVA} - {C.PUISSANCE_MIN_KVA}), 1.0),
                {C.SCORE_MAX_PAR_AXE}) AS score_energie
        FROM marts.fct_filtre_03_fibre p
        JOIN plus_proche n USING (id_parcelle)
        WHERE n.puissance_dispo_kva >= {C.PUISSANCE_MIN_KVA};
    """)

    # ---- FILTRE 5 : RÉGLEMENTAIRE (exclusions strictes) --------------------
    # Rejet si la parcelle touche : tampon ABF 500 m, zone PPRI ou EBC.
    con.execute(f"""
        CREATE OR REPLACE TABLE marts.fct_filtre_05_reglement AS
        WITH violations AS (
            SELECT p.id_parcelle FROM marts.fct_filtre_04_energie p
              JOIN staging.stg_abf a ON ST_Intersects(p.geom, a.geom_buffer)
            UNION
            SELECT p.id_parcelle FROM marts.fct_filtre_04_energie p
              JOIN staging.stg_ppri pp ON ST_Intersects(p.geom, pp.geom)
            UNION
            SELECT p.id_parcelle FROM marts.fct_filtre_04_energie p
              JOIN staging.stg_ebc e ON ST_Intersects(p.geom, e.geom)
        )
        SELECT p.*, {C.SCORE_MAX_PAR_AXE} AS score_environnement
        FROM marts.fct_filtre_04_energie p
        WHERE p.id_parcelle NOT IN (SELECT id_parcelle FROM violations);
    """)

    return {t: table_count(con, f"marts.{t}") for t in (
        "fct_filtre_01_foncier", "fct_filtre_02_nuisances", "fct_filtre_03_fibre",
        "fct_filtre_04_energie", "fct_filtre_05_reglement")}


# ===========================================================================
#  COUCHE 3 — MARTS : scoring final + heatmap
# ===========================================================================
def build_scoring(con) -> None:
    """Ajoute les bonus de proximité, calcule le score total et la classe."""
    con.execute(f"""
        CREATE OR REPLACE TABLE marts.fct_parcelles_eligibles AS
        WITH bonus AS (
            SELECT p.id_parcelle,
                -- bonus PV : une installation PV à moins de 500 m ?
                MAX(CASE WHEN EXISTS (
                    SELECT 1 FROM staging.stg_pv pv
                    WHERE list_contains(h3_grid_disk(p.h3_res9, {C.H3_DISK_K['pv']}), pv.h3_res9)
                      AND ST_Distance(p.geom, pv.geom) <= {C.PROX_BONUS_M['pv']}
                ) THEN {C.SCORE_BONUS} ELSE 0.0 END) AS bonus_pv,
                MAX(CASE WHEN EXISTS (
                    SELECT 1 FROM staging.stg_bornes_ve ve
                    WHERE list_contains(h3_grid_disk(p.h3_res9, {C.H3_DISK_K['borne_ve']}), ve.h3_res9)
                      AND ST_Distance(p.geom, ve.geom) <= {C.PROX_BONUS_M['borne_ve']}
                ) THEN {C.SCORE_BONUS} ELSE 0.0 END) AS bonus_ve,
                MAX(CASE WHEN p.dist_poste_m <= {C.PROX_BONUS_M['poste']}
                         THEN {C.SCORE_BONUS} ELSE 0.0 END) AS bonus_poste
            FROM marts.fct_filtre_05_reglement p
            GROUP BY p.id_parcelle
        )
        SELECT
            p.id_parcelle, p.dept, p.commune, p.commune_insee,
            p.geom, p.h3_res8,
            ROUND(p.surface_parcelle_m2, 1)  AS surface_parcelle_m2,
            ROUND(p.surface_libre_m2, 1)     AS surface_libre_m2,
            ROUND(p.score_foncier, 1)        AS score_foncier,
            ROUND(p.score_nuisances, 1)      AS score_nuisances,
            ROUND(p.score_fibre, 1)          AS score_fibre,
            ROUND(p.score_energie, 1)        AS score_energie,
            ROUND(p.score_environnement, 1)  AS score_environnement,
            b.bonus_pv, b.bonus_ve, b.bonus_poste,
            p.fibre_statut,
            ROUND(p.puissance_dispo_kva, 1)  AS puissance_dispo_kva,
            ROUND(p.dist_poste_m, 1)         AS dist_poste_m,
            -- score total plafonné à 100
            LEAST(ROUND(p.score_foncier + p.score_nuisances + p.score_fibre
                  + p.score_energie + p.score_environnement
                  + b.bonus_pv + b.bonus_ve + b.bonus_poste, 1),
                  {C.SCORE_TOTAL_MAX}) AS score_total,
            CASE
                WHEN LEAST(p.score_foncier + p.score_nuisances + p.score_fibre
                     + p.score_energie + p.score_environnement
                     + b.bonus_pv + b.bonus_ve + b.bonus_poste, {C.SCORE_TOTAL_MAX})
                     >= {C.CLASSE_PREMIUM_MIN} THEN 'Premium'
                WHEN LEAST(p.score_foncier + p.score_nuisances + p.score_fibre
                     + p.score_energie + p.score_environnement
                     + b.bonus_pv + b.bonus_ve + b.bonus_poste, {C.SCORE_TOTAL_MAX})
                     >= {C.CLASSE_BON_MIN} THEN 'Bon'
                ELSE 'Moyen'
            END AS classe
        FROM marts.fct_filtre_05_reglement p
        JOIN bonus b USING (id_parcelle);
    """)


def build_qa_layer(con) -> None:
    """Couche de CONTRÔLE SIG : les 484 parcelles annotées de leur sort.

    Pour chaque parcelle on indique à QUELLE étape elle a été éliminée (ou si
    elle est éligible) + ses scores. Chargée dans QGIS et coloriée par
    `etape_rejet`, cette couche permet de vérifier visuellement l'entonnoir :
    on voit d'un coup d'œil les parcelles ABF (rouge), inondables, sans fibre...
    """
    con.execute(f"""
        CREATE OR REPLACE TABLE marts.fct_parcelles_qa AS
        SELECT
            b.id_parcelle, b.dept, b.commune, b.geom,
            ROUND(b.surface_parcelle_m2, 1) AS surface_parcelle_m2,
            ROUND(b.surface_libre_m2, 1)    AS surface_libre_m2,
            b.count_resid, b.count_immeuble,
            (f1.id_parcelle IS NOT NULL) AS pass_01_foncier,
            (f2.id_parcelle IS NOT NULL) AS pass_02_nuisances,
            (f3.id_parcelle IS NOT NULL) AS pass_03_fibre,
            (f4.id_parcelle IS NOT NULL) AS pass_04_energie,
            (f5.id_parcelle IS NOT NULL) AS pass_05_reglement,
            (el.id_parcelle IS NOT NULL) AS eligible,
            el.classe,
            el.score_total,
            -- première étape échouée = motif de rejet (pour le style QGIS)
            CASE
                WHEN f1.id_parcelle IS NULL THEN '1-Foncier'
                WHEN f2.id_parcelle IS NULL THEN '2-Nuisances'
                WHEN f3.id_parcelle IS NULL THEN '3-Fibre'
                WHEN f4.id_parcelle IS NULL THEN '4-Energie'
                WHEN f5.id_parcelle IS NULL THEN '5-Reglementaire'
                ELSE '0-Eligible'
            END AS etape_rejet
        FROM intermediate.int_surface_libre b
        LEFT JOIN marts.fct_filtre_01_foncier   f1 ON b.id_parcelle = f1.id_parcelle
        LEFT JOIN marts.fct_filtre_02_nuisances f2 ON b.id_parcelle = f2.id_parcelle
        LEFT JOIN marts.fct_filtre_03_fibre     f3 ON b.id_parcelle = f3.id_parcelle
        LEFT JOIN marts.fct_filtre_04_energie   f4 ON b.id_parcelle = f4.id_parcelle
        LEFT JOIN marts.fct_filtre_05_reglement f5 ON b.id_parcelle = f5.id_parcelle
        LEFT JOIN marts.fct_parcelles_eligibles el ON b.id_parcelle = el.id_parcelle;
    """)


def build_heatmap(con) -> None:
    """Agrège les parcelles éligibles par cellule H3 res 8 (grain quartier)."""
    con.execute(f"""
        CREATE OR REPLACE TABLE marts.fct_heatmap_quartiers AS
        SELECT
            h3_res8,
            -- polygone de la cellule (WGS84) pour la cartographie web
            ST_GeomFromText(h3_cell_to_boundary_wkt(h3_res8)) AS geom_wgs84,
            COUNT(*)                                          AS count_eligibles,
            COUNT(*) FILTER (WHERE classe = 'Premium')        AS count_premium,
            COUNT(*) FILTER (WHERE classe = 'Bon')            AS count_bon,
            COUNT(*) FILTER (WHERE classe = 'Moyen')          AS count_moyen,
            ROUND(AVG(score_total), 1)                        AS avg_score,
            ROUND(MAX(score_total), 1)                        AS max_score,
            ROUND(100.0 * COUNT(*) FILTER (WHERE classe = 'Premium') / COUNT(*), 1) AS pct_premium,
            CASE
                WHEN COUNT(*) FILTER (WHERE classe = 'Premium') >= 5 THEN 'Tier1'
                WHEN COUNT(*) >= 5                                   THEN 'Tier2'
                ELSE 'Tier3'
            END AS priorite_deploiement
        FROM marts.fct_parcelles_eligibles
        GROUP BY h3_res8;
    """)


# ===========================================================================
#  ORCHESTRATION
# ===========================================================================
def run(con) -> dict:
    """Exécute tout le pipeline et renvoie les compteurs par étape."""
    setup_macros(con)
    stats = {}
    stats["staging"] = build_staging(con)
    stats["intermediate"] = build_intermediate(con)
    stats["filtres"] = build_filters(con)
    build_scoring(con)
    build_heatmap(con)
    build_qa_layer(con)
    stats["eligibles"] = table_count(con, "marts.fct_parcelles_eligibles")
    stats["heatmap_cellules"] = table_count(con, "marts.fct_heatmap_quartiers")
    stats["qa_parcelles"] = table_count(con, "marts.fct_parcelles_qa")
    return stats
