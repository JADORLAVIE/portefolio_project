"""
run.py — Point d'entrée unique de l'outil (orchestrateur).

Enchaîne : génération synthétique (optionnelle) -> pipeline DuckDB ->
tests de validation -> export des livrables -> rapport de performance.

Usage :
    python run.py                # tout : (re)génère les données puis exécute
    python run.py --no-generate  # réutilise les données brutes existantes
    python run.py --quiet        # moins de logs
"""

import sys
import json
import time
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")  # accents OK même en console cp1252
except Exception:
    pass

import geopandas as gpd
from shapely import from_wkb

import config as C
from db import connect
import generate_synthetic
import pipeline
import tests_pipeline


def _print_funnel(stats: dict) -> None:
    """Affiche l'entonnoir de filtrage avec le taux de rétention."""
    base = stats["staging"]["stg_parcelles"]
    etapes = [
        ("Parcelles (base)", base),
        ("1. Foncier",      stats["filtres"]["fct_filtre_01_foncier"]),
        ("2. Nuisances",    stats["filtres"]["fct_filtre_02_nuisances"]),
        ("3. Fibre",        stats["filtres"]["fct_filtre_03_fibre"]),
        ("4. Énergie",      stats["filtres"]["fct_filtre_04_energie"]),
        ("5. Réglementaire", stats["filtres"]["fct_filtre_05_reglement"]),
    ]
    print("\n  ENTONNOIR DE FILTRAGE")
    print("  " + "-" * 46)
    for nom, n in etapes:
        pct = 100.0 * n / base if base else 0
        barre = "#" * int(pct / 2.5)
        print(f"  {nom:<18} {n:>5}  {pct:5.1f}%  {barre}")
    print("  " + "-" * 46)


def _wkb_gdf(con, sql: str, crs: int) -> gpd.GeoDataFrame:
    """Exécute une requête (avec une colonne `wkb`) et renvoie un GeoDataFrame.

    DuckDB sérialise la géométrie en WKB via ST_AsWKB ; on la décode côté
    Python (en convertissant les bytearray en bytes pour shapely).
    """
    df = con.execute(sql).fetchdf()
    return gpd.GeoDataFrame(
        df.drop(columns=["wkb"]),
        geometry=from_wkb([bytes(b) for b in df["wkb"]]),
        crs=crs,
    )


def _export(con) -> dict:
    """Écrit les livrables finaux dans data/outputs/ et renvoie leurs tailles."""
    out = {}

    # -- Parcelles éligibles : GeoParquet (2154) + GeoJSON (4326) + CSV --
    gdf = _wkb_gdf(con, """
        SELECT * EXCLUDE (geom), ST_AsWKB(geom) AS wkb
        FROM marts.fct_parcelles_eligibles ORDER BY score_total DESC
    """, C.CRS_METRIQUE)
    gdf.to_parquet(C.OUTPUTS_DIR / "parcelles_eligibles.parquet", index=False)
    gdf.to_crs(C.CRS_GEO).to_file(
        C.OUTPUTS_DIR / "parcelles_eligibles.geojson", driver="GeoJSON")
    gdf.drop(columns="geometry").to_csv(
        C.OUTPUTS_DIR / "parcelles_eligibles.csv", index=False, encoding="utf-8-sig")
    gdf.head(20).drop(columns="geometry").to_csv(
        C.OUTPUTS_DIR / "top20_premium.csv", index=False, encoding="utf-8-sig")
    out["parcelles_eligibles"] = len(gdf)

    # -- Heatmap quartiers : GeoJSON (déjà en WGS84) --
    gh = _wkb_gdf(con, """
        SELECT * EXCLUDE (geom_wgs84), ST_AsWKB(geom_wgs84) AS wkb
        FROM marts.fct_heatmap_quartiers
    """, C.CRS_GEO)
    gh.to_file(C.OUTPUTS_DIR / "heatmap_quartiers.geojson", driver="GeoJSON")
    out["heatmap_cellules"] = len(gh)

    return out


def _export_sig(con) -> dict:
    """Couches de CONTRÔLE pour QGIS, en GeoParquet (data/outputs/sig/).

    Tout est en EPSG:2154 (sauf la heatmap en WGS84) pour superposition directe.
    L'objectif : pouvoir vérifier visuellement chaque décision du pipeline.
    """
    sigdir = C.OUTPUTS_DIR / "sig"
    sigdir.mkdir(parents=True, exist_ok=True)
    couches = {
        # LA couche de contrôle : toutes les parcelles + leur étape de rejet
        "parcelles_qa": ("SELECT * EXCLUDE (geom), ST_AsWKB(geom) AS wkb FROM marts.fct_parcelles_qa", C.CRS_METRIQUE),
        # Contraintes réglementaires (pour voir QUI elles excluent)
        "contrainte_abf_500m": ("SELECT id_monument, nom, ST_AsWKB(geom_buffer) AS wkb FROM staging.stg_abf", C.CRS_METRIQUE),
        "contrainte_ppri": ("SELECT id_ppri, niveau_risque, ST_AsWKB(geom) AS wkb FROM staging.stg_ppri", C.CRS_METRIQUE),
        "contrainte_ebc": ("SELECT id_ebc, ST_AsWKB(geom) AS wkb FROM staging.stg_ebc", C.CRS_METRIQUE),
        # Réseaux (pour contrôler fibre/énergie)
        "reseau_fibre": ("SELECT id_locale, statut_deploiement, operateur, ST_AsWKB(geom) AS wkb FROM staging.stg_fibre", C.CRS_METRIQUE),
        "reseau_energie": ("SELECT id_poste_source, puissance_disponible_kva, ST_AsWKB(geom) AS wkb FROM staging.stg_energie", C.CRS_METRIQUE),
        "reseau_voirie": ("SELECT id_troncon, ST_AsWKB(geom) AS wkb FROM staging.stg_voirie", C.CRS_METRIQUE),
        # Bâti (contexte)
        "batiments": ("SELECT id_batiment, usage, sous_type, ST_AsWKB(geom) AS wkb FROM staging.stg_batiments", C.CRS_METRIQUE),
        # Heatmap (WGS84)
        "heatmap_quartiers": ("SELECT * EXCLUDE (geom_wgs84), ST_AsWKB(geom_wgs84) AS wkb FROM marts.fct_heatmap_quartiers", C.CRS_GEO),
    }
    counts = {}
    for nom, (sql, crs) in couches.items():
        g = _wkb_gdf(con, sql, crs)
        g.to_parquet(sigdir / f"{nom}.parquet", index=False)
        counts[nom] = len(g)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Pipeline Mini Data Center Selector")
    ap.add_argument("--no-generate", action="store_true",
                    help="ne pas régénérer les données synthétiques")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    t0 = time.perf_counter()
    print("=" * 52)
    print(f"  MINI DATA CENTER SELECTOR — {C.COMMUNE_NOM} ({C.CODE_POSTAL})")
    print("=" * 52)

    # 1. Données -----------------------------------------------------------
    if not args.no_generate:
        generate_synthetic.generer()

    # 2. Pipeline ----------------------------------------------------------
    con = connect()
    t_pipe = time.perf_counter()
    stats = pipeline.run(con)
    duree_pipe = time.perf_counter() - t_pipe

    if not args.quiet:
        _print_funnel(stats)

    # 3. Scoring / classes -------------------------------------------------
    classes = con.execute("""
        SELECT classe, COUNT(*) n, ROUND(AVG(score_total),1) score_moy
        FROM marts.fct_parcelles_eligibles
        GROUP BY classe ORDER BY score_moy DESC
    """).fetchall()
    print("\n  CLASSEMENT DES PARCELLES ÉLIGIBLES")
    print("  " + "-" * 46)
    for cl, n, sm in classes:
        print(f"  {cl:<10} {n:>5} parcelles   score moyen {sm}")

    # 4. Tests ------------------------------------------------------------
    print("\n  TESTS DE VALIDATION")
    print("  " + "-" * 46)
    resultats = tests_pipeline.run_tests(con)
    tous_ok = True
    for nom, ok, detail in resultats:
        print(f"  [{'OK ' if ok else 'KO!'}] {nom:<34} ({detail})")
        tous_ok = tous_ok and ok

    # 5. Exports ----------------------------------------------------------
    exports = _export(con)
    exports_sig = _export_sig(con)
    duree_totale = time.perf_counter() - t0

    # Récap de la couche de contrôle (répartition des motifs de rejet)
    print("\n  COUCHE DE CONTRÔLE SIG (motifs de rejet)")
    print("  " + "-" * 46)
    for motif, n in con.execute("""
        SELECT etape_rejet, COUNT(*) FROM marts.fct_parcelles_qa
        GROUP BY etape_rejet ORDER BY etape_rejet""").fetchall():
        print(f"  {motif:<18} {n:>5}")

    # 6. Rapport de performance ------------------------------------------
    perf = {
        "commune": f"{C.COMMUNE_NOM} ({C.CODE_POSTAL})",
        "dept": C.DEPT,
        "duree_pipeline_s": round(duree_pipe, 3),
        "duree_totale_s": round(duree_totale, 3),
        "volumes_entree": stats["staging"],
        "entonnoir": stats["filtres"],
        "parcelles_eligibles": stats["eligibles"],
        "heatmap_cellules": stats["heatmap_cellules"],
        "tests_ok": tous_ok,
        "exports": exports,
        "exports_sig": exports_sig,
    }
    with open(C.OUTPUTS_DIR / "performance.json", "w", encoding="utf-8") as f:
        json.dump(perf, f, ensure_ascii=False, indent=2)

    print("\n  LIVRABLES écrits dans data/outputs/ :")
    for nom in ("parcelles_eligibles.parquet", "parcelles_eligibles.geojson",
                "parcelles_eligibles.csv", "top20_premium.csv",
                "heatmap_quartiers.geojson", "performance.json"):
        print(f"    - {nom}")
    print(f"  + {len(exports_sig)} couches de contrôle SIG dans data/outputs/sig/ (GeoParquet)")
    print(f"\n  Pipeline : {duree_pipe:.2f}s | Total : {duree_totale:.2f}s | "
          f"Tests : {'TOUS OK' if tous_ok else 'ÉCHEC'}")
    con.close()
    return 0 if tous_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
