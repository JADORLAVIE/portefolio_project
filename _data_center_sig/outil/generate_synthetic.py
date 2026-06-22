"""
generate_synthetic.py — Fabrique un jeu de données SYNTHÉTIQUE et réaliste
pour la commune d'Alba-la-Romaine (07400), en EPSG:2154 (Lambert-93).

Aucune donnée réelle / personnelle : tout est inventé mais géographiquement
plausible (tissu cadastral, bâtiments, fibre, postes électriques, et les
contraintes réglementaires : site antique romain -> ABF, rivière Escoutay ->
PPRI, coteaux boisés -> EBC).

Sorties : des fichiers GeoParquet dans data/raw/, que le pipeline lira ensuite.
La géométrie est stockée en WKB (Well-Known Binary), standard GeoParquet.
"""

import sys

import numpy as np
import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Polygon, Point, LineString, box
from shapely.affinity import rotate

import config as C

try:  # console Windows en cp1252 -> on force l'UTF-8 pour les accents/symboles
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _centre_lambert93() -> tuple[float, float]:
    """Convertit le centre WGS84 de la commune en Lambert-93 (mètres)."""
    tr = Transformer.from_crs(C.CRS_GEO, C.CRS_METRIQUE, always_xy=True)
    x, y = tr.transform(*C.CENTRE_WGS84)
    return x, y


def _save(gdf: gpd.GeoDataFrame, nom: str) -> None:
    """Écrit une couche en GeoParquet (EPSG:2154) dans data/raw/."""
    gdf = gdf.set_crs(C.CRS_METRIQUE, allow_override=True)
    chemin = C.RAW_DIR / f"{nom}.parquet"
    gdf.to_parquet(chemin, index=False)
    print(f"  raw/{nom}.parquet  ({len(gdf)} entités)")


def generer() -> None:
    """Génère toutes les couches sources et les écrit sur disque."""
    rng = np.random.default_rng(C.SEED)
    cx, cy = _centre_lambert93()
    demi = C.TAILLE_AOI_M / 2
    x0, y0 = cx - demi, cy - demi          # coin sud-ouest de l'AOI

    print(f"Génération synthétique — {C.COMMUNE_NOM} ({C.CODE_POSTAL})")
    print(f"  centre Lambert-93 ≈ ({cx:.0f}, {cy:.0f})")

    # -------------------------------------------------------------------
    # 1. PARCELLES — grille cadastrale jitterée
    # -------------------------------------------------------------------
    n = C.N_PARCELLES_GRILLE
    pas = C.TAILLE_AOI_M / n                # ~73 m par cellule
    parcelles, batiments = [], []
    pid, bid = 0, 0
    for i in range(n):
        for j in range(n):
            # Coin de la cellule + jitter pour casser la régularité parfaite
            px = x0 + i * pas + rng.uniform(-4, 4)
            py = y0 + j * pas + rng.uniform(-4, 4)
            # Dimensions "village" : côtés tirés d'une loi log-normale ->
            # beaucoup de petites parcelles (~15-25 m), quelques grandes.
            w = float(np.clip(rng.lognormal(mean=np.log(17), sigma=0.42), 9, pas * 0.95))
            h = float(np.clip(rng.lognormal(mean=np.log(17), sigma=0.42), 9, pas * 0.95))
            poly = box(px, py, px + w, py + h)
            poly = rotate(poly, rng.uniform(-15, 15), origin="centroid")
            pid += 1
            id_parcelle = f"{C.COMMUNE_INSEE}A{pid:04d}"

            # Profil d'usage : 68% résidentiel, 12% immeuble (exclu), 20% autre
            tirage = rng.random()
            if tirage < 0.68:
                usage, sous_type, batie = "Résidentiel", "Maison", True
            elif tirage < 0.80:
                usage, sous_type, batie = "Résidentiel", "Immeuble", True
            else:
                usage, sous_type, batie = "Indifférencié", "Annexe", rng.random() < 0.4

            parcelles.append(
                {"id_parcelle": id_parcelle, "dept": C.DEPT,
                 "commune": C.COMMUNE_NOM, "commune_insee": C.COMMUNE_INSEE,
                 "geometry": poly}
            )

            # Bâtiment(s) à l'intérieur de la parcelle
            if batie:
                surf_parc = poly.area
                # Emprise visée : maison ~30-58%, immeuble ~60-85% de la parcelle
                ratio = rng.uniform(0.60, 0.85) if sous_type == "Immeuble" else rng.uniform(0.30, 0.58)
                cible = surf_parc * ratio
                cote = max(5.0, np.sqrt(cible))
                c = poly.centroid
                bpoly = box(c.x - cote / 2, c.y - cote / 2, c.x + cote / 2, c.y + cote / 2)
                bpoly = bpoly.intersection(poly.buffer(-1.0)) if poly.buffer(-1.0).area > 0 else bpoly
                if not bpoly.is_empty and bpoly.area > 4:
                    bid += 1
                    batiments.append(
                        {"id_batiment": f"BAT{bid:05d}", "dept": C.DEPT,
                         "usage": usage, "sous_type": sous_type,
                         "geometry": bpoly}
                    )

    _save(gpd.GeoDataFrame(parcelles, geometry="geometry"), "parcelles")
    _save(gpd.GeoDataFrame(batiments, geometry="geometry"), "batiments")

    # -------------------------------------------------------------------
    # 2. FIBRE (ARCEP) — points avec gradient géographique ouest->est
    #    Est de la commune mieux desservi (Déployé), ouest en retard.
    # -------------------------------------------------------------------
    fibre = []
    for k in range(70):
        fx = x0 + rng.uniform(0, C.TAILLE_AOI_M)
        fy = y0 + rng.uniform(0, C.TAILLE_AOI_M)
        frac_est = (fx - x0) / C.TAILLE_AOI_M          # 0=ouest, 1=est
        r = rng.random()
        if r < 0.25 + 0.55 * frac_est:
            statut = "Déployé"
        elif r < 0.45 + 0.50 * frac_est:
            statut = "Raccordable"
        elif r < 0.75:
            statut = "En cours"
        else:
            statut = "Non prévu"
        fibre.append(
            {"id_locale": f"IPE{k:05d}", "dept": C.DEPT,
             "statut_deploiement": statut,
             "operateur": rng.choice(["Orange", "SFR", "Free"]),
             "geometry": Point(fx, fy)}
        )
    _save(gpd.GeoDataFrame(fibre, geometry="geometry"), "fibre")

    # -------------------------------------------------------------------
    # 3. ÉNERGIE (Enedis) — quelques postes sources, capacités variables
    # -------------------------------------------------------------------
    energie = []
    postes = [
        (0.25, 0.30, 120.0, 95.0),   # marge confortable
        (0.70, 0.65, 100.0, 30.0),   # quasi saturé -> filtre énergie KO autour
        (0.55, 0.20, 160.0, 140.0),  # gros poste, large marge
        (0.85, 0.85, 90.0, 60.0),
        (0.15, 0.80, 80.0, 18.0),    # saturé
    ]
    for k, (fx, fy, pmax, pdispo) in enumerate(postes):
        energie.append(
            {"id_poste_source": f"PS{k:03d}", "dept": C.DEPT,
             "puissance_max_kva": pmax, "puissance_disponible_kva": pdispo,
             "geometry": Point(x0 + fx * C.TAILLE_AOI_M, y0 + fy * C.TAILLE_AOI_M)}
        )
    _save(gpd.GeoDataFrame(energie, geometry="geometry"), "energie")

    # -------------------------------------------------------------------
    # 4. BONUS — bornes VE et installations PV (points épars)
    # -------------------------------------------------------------------
    bornes = [{"id_borne": f"VE{k:03d}", "geometry":
               Point(x0 + rng.uniform(0, C.TAILLE_AOI_M), y0 + rng.uniform(0, C.TAILLE_AOI_M))}
              for k in range(7)]
    _save(gpd.GeoDataFrame(bornes, geometry="geometry"), "bornes_ve")

    pv = [{"id_pv": f"PV{k:03d}", "geometry":
           Point(x0 + rng.uniform(0, C.TAILLE_AOI_M), y0 + rng.uniform(0, C.TAILLE_AOI_M))}
          for k in range(9)]
    _save(gpd.GeoDataFrame(pv, geometry="geometry"), "pv")

    # -------------------------------------------------------------------
    # 5. CONTRAINTES RÉGLEMENTAIRES (filtre 5)
    # -------------------------------------------------------------------
    # 5a. ABF — site antique romain d'Alba-la-Romaine (monument ponctuel)
    abf = [{"id_monument": "MH001",
            "nom": "Site antique d'Alba-la-Romaine",
            "geometry": Point(cx - 120, cy + 60)}]
    _save(gpd.GeoDataFrame(abf, geometry="geometry"), "abf")

    # 5b. PPRI — bande inondable de l'Escoutay traversant la commune (NO->SE)
    riviere = LineString([
        (x0 - 50, y0 + C.TAILLE_AOI_M * 0.75),
        (x0 + C.TAILLE_AOI_M * 0.45, y0 + C.TAILLE_AOI_M * 0.45),
        (x0 + C.TAILLE_AOI_M * 0.95, y0 + C.TAILLE_AOI_M * 0.15),
        (x0 + C.TAILLE_AOI_M + 50, y0 - 30),
    ])
    ppri = [{"id_ppri": "PPRI07-001", "niveau_risque": "Fort",
             "geometry": riviere.buffer(70)}]   # zone inondable ~70 m de large
    _save(gpd.GeoDataFrame(ppri, geometry="geometry"), "ppri")

    # 5c. EBC — deux boisements classés sur les coteaux (coins de l'AOI)
    ebc = [
        {"id_ebc": "EBC001", "geometry":
         Point(x0 + C.TAILLE_AOI_M * 0.10, y0 + C.TAILLE_AOI_M * 0.12).buffer(140)},
        {"id_ebc": "EBC002", "geometry":
         Point(x0 + C.TAILLE_AOI_M * 0.90, y0 + C.TAILLE_AOI_M * 0.92).buffer(120)},
    ]
    _save(gpd.GeoDataFrame(ebc, geometry="geometry"), "ebc")

    # 5d. VOIRIE — quelques tronçons de route (pour le critère d'accès)
    voirie = [
        {"id_troncon": "V001", "geometry": LineString(
            [(x0, y0 + C.TAILLE_AOI_M * 0.5), (x0 + C.TAILLE_AOI_M, y0 + C.TAILLE_AOI_M * 0.55)])},
        {"id_troncon": "V002", "geometry": LineString(
            [(x0 + C.TAILLE_AOI_M * 0.5, y0), (x0 + C.TAILLE_AOI_M * 0.48, y0 + C.TAILLE_AOI_M)])},
        {"id_troncon": "V003", "geometry": LineString(
            [(x0 + C.TAILLE_AOI_M * 0.2, y0 + C.TAILLE_AOI_M * 0.2),
             (x0 + C.TAILLE_AOI_M * 0.8, y0 + C.TAILLE_AOI_M * 0.85)])},
    ]
    _save(gpd.GeoDataFrame(voirie, geometry="geometry"), "voirie")

    print("Génération terminée.\n")


if __name__ == "__main__":
    generer()
