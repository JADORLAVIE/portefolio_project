"""
config.py — Paramètres centraux de l'outil Mini Data Center Selector.

Tout est centralisé ici (chemins, seuils métier, pondérations de score) pour
qu'un changement de règle (ex : passer le seuil de surface libre de 50 à 60 m²)
se fasse à UN seul endroit, sans toucher au code du pipeline.

Logique geo-data engineer : aucune valeur "magique" éparpillée dans les requêtes.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# 1. CHEMINS  (tout reste confiné dans le dossier du projet)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent          # .../_data_center_sig/outil
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"                           # données brutes (synthétiques)
PROCESSED_DIR = DATA_DIR / "processed"              # sorties intermédiaires
OUTPUTS_DIR = DATA_DIR / "outputs"                  # livrables finaux
DB_PATH = DATA_DIR / "mini_data_center.duckdb"      # base DuckDB persistée

for _d in (RAW_DIR, PROCESSED_DIR, OUTPUTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 2. ZONE D'ÉTUDE  (commune de dev)
# ---------------------------------------------------------------------------
COMMUNE_NOM = "Alba-la-Romaine"
COMMUNE_INSEE = "07006"        # code INSEE réel d'Alba-la-Romaine
CODE_POSTAL = "07400"
DEPT = "07"                    # Ardèche — clé de partition du pipeline
# Centre approximatif de la commune en WGS84 (lon, lat) — sert d'ancrage
# pour générer la donnée synthétique, puis on reprojette en Lambert-93.
CENTRE_WGS84 = (4.6017, 44.5556)

# ---------------------------------------------------------------------------
# 3. SYSTÈMES DE COORDONNÉES
# ---------------------------------------------------------------------------
CRS_METRIQUE = 2154    # Lambert-93 : OBLIGATOIRE pour surfaces & distances en France
CRS_GEO = 4326         # WGS84 : pour l'export web (GeoJSON) et le calcul H3

# ---------------------------------------------------------------------------
# 4. INDEXATION SPATIALE H3
# ---------------------------------------------------------------------------
H3_RES_JOIN = 9        # ~0,1 km² par cellule : grain des jointures de proximité
H3_RES_HEATMAP = 8     # ~0,7 km² par cellule : grain d'agrégation "quartier"
# Rayon (en anneaux H3) pour la recherche du plus proche voisin par couche.
# En production France ces k restent petits (2-3) : le préfiltre H3 réduit
# drastiquement le nombre de candidats avant le calcul exact de distance.
H3_DISK_K = {
    "batiment": 1,     # bâtiments forcément sur/à côté de la parcelle
    "fibre": 6,        # points ARCEP : recherche élargie
    "energie": 12,     # postes sources rares : recherche très élargie
    "borne_ve": 8,
    "pv": 8,
}

# ---------------------------------------------------------------------------
# 5. SEUILS MÉTIER  (les règles des 5 filtres)
# ---------------------------------------------------------------------------
# Filtre 1 — Foncier
SURFACE_LIBRE_MIN_M2 = 50.0        # espace libre minimal sur la parcelle
USAGE_RESIDENTIEL = "Résidentiel"  # usage retenu en BD TOPO
SOUS_TYPES_EXCLUS = ("Immeuble",)  # exclusion des copropriétés verticales

# Filtre 2 — Nuisances & sécurité
BUFFER_NUISANCE_M = 5.0            # recul intérieur depuis les limites (bruit 60 dB)
BUFFER_USABLE_MIN_M2 = 4.0        # surface installable minimale après recul
DIST_MAX_BATIMENT_M = 15.0        # longueur max de tirage des câbles
DIST_VOIRIE_ACCES_M = 30.0        # accès voirie (critère "idéal" -> bonus)

# Filtre 3 — Connectivité fibre (ARCEP)
FIBRE_STATUTS_OK = ("Déployé", "Raccordable")  # le reste est éliminé

# Filtre 4 — Énergie (Enedis)
PUISSANCE_MIN_KVA = 36.0          # charge permanente du data center
PUISSANCE_CONFORT_KVA = 72.0      # au-delà : score énergie maximal

# Filtre 5 — Réglementaire (exclusions strictes)
ABF_BUFFER_M = 500.0              # périmètre Monuments Historiques

# Bonus de proximité (mètres) — volontairement serrés pour différencier
PROX_BONUS_M = {
    "pv": 250.0,        # installation photovoltaïque proche
    "borne_ve": 250.0,  # borne de recharge VE proche
    "poste": 300.0,     # poste source électrique proche
}

# ---------------------------------------------------------------------------
# 6. PONDÉRATIONS DU SCORE  (total plafonné à 100)
# ---------------------------------------------------------------------------
SCORE_MAX_PAR_AXE = 20.0          # chacun des 5 filtres pèse 0..20
SCORE_BONUS = 5.0                 # chaque bonus ajoute +5
SCORE_TOTAL_MAX = 100.0
# Références d'étalement : surface au-delà de laquelle l'axe est au maximum.
# Plus la référence est basse, plus le score "monte vite" (moins discriminant).
SCORE_FONCIER_REF_M2 = 400.0      # surface libre donnant 20/20 au foncier
SCORE_NUISANCE_REF_M2 = 40.0      # surface installable donnant le max "espace"

# Seuils de classification commerciale (un survivant des 5 filtres est déjà
# bon : on place la barre "Premium" haut pour distinguer l'élite commerciale)
CLASSE_PREMIUM_MIN = 90.0
CLASSE_BON_MIN = 70.0
# < 70 -> "Moyen"

# ---------------------------------------------------------------------------
# 7. PARAMÈTRES DE GÉNÉRATION SYNTHÉTIQUE
# ---------------------------------------------------------------------------
SEED = 42                          # reproductibilité
N_PARCELLES_GRILLE = 22            # grille 22x22 -> ~480 parcelles brutes
TAILLE_AOI_M = 1600                # côté de la zone d'étude (mètres)
