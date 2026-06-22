# Guide de contrôle SIG (QGIS)

Après `python run.py`, le dossier `data/outputs/sig/` contient **9 couches
GeoParquet** prêtes à charger dans QGIS (≥ 3.28) pour vérifier *visuellement*
chaque décision du pipeline. Tout est en **EPSG:2154 (Lambert-93)**, sauf la
heatmap en WGS84.

## Charger dans QGIS

`Couche > Ajouter une couche > Ajouter une couche vecteur` puis sélectionner les
`.parquet`. (QGIS lit le GeoParquet nativement via GDAL.)

Ordre d'empilement conseillé (du dessous vers le dessus) :

| Couche | Géométrie | Rôle |
|---|---|---|
| `batiments.parquet` | polygones | contexte bâti |
| `reseau_voirie.parquet` | lignes | accès voirie |
| `contrainte_abf_500m.parquet` | polygone | périmètre Monuments Historiques |
| `contrainte_ppri.parquet` | polygone | zone inondable |
| `contrainte_ebc.parquet` | polygones | boisements classés |
| `reseau_fibre.parquet` | points | statut fibre ARCEP |
| `reseau_energie.parquet` | points | postes + capacité kVA |
| **`parcelles_qa.parquet`** | polygones | **LA couche de contrôle** |
| `heatmap_quartiers.parquet` | polygones | densité par quartier (WGS84) |

## La couche maîtresse : `parcelles_qa`

Elle contient **les 484 parcelles** (éligibles ET rejetées) avec, pour chacune,
l'étape exacte où elle est sortie de l'entonnoir.

Colonnes utiles :
- `etape_rejet` : `0-Eligible`, `1-Foncier`, `2-Nuisances`, `3-Fibre`,
  `4-Energie`, `5-Reglementaire`
- `pass_01_foncier` … `pass_05_reglement` : booléens étape par étape
- `eligible`, `classe` (`Premium`/`Bon`/`Moyen`), `score_total`
- `surface_parcelle_m2`, `surface_libre_m2`, `count_resid`, `count_immeuble`

### Style recommandé n°1 — l'entonnoir (catégorisé sur `etape_rejet`)

`Propriétés > Symbologie > Catégorisé > Valeur = etape_rejet > Classer`, puis :

| Valeur | Couleur conseillée |
|---|---|
| `0-Eligible` | vert vif |
| `1-Foncier` | gris clair |
| `2-Nuisances` | jaune |
| `3-Fibre` | orange |
| `4-Energie` | rouge |
| `5-Reglementaire` | violet |

→ On voit d'un coup d'œil **pourquoi** chaque parcelle est écartée, et où se
concentrent les éligibles.

### Style recommandé n°2 — le classement commercial

Filtrer `eligible = true`, puis catégoriser sur `classe`
(Premium = vert foncé, Bon = vert clair, Moyen = jaune).

## Contrôles à faire (validation visuelle)

1. **Aucune parcelle verte (éligible) ne doit toucher** le tampon ABF, le PPRI
   ou un EBC → le filtre 5 est respecté.
2. Les parcelles `3-Fibre` (orange) doivent être **loin des points fibre
   "Déployé/Raccordable"** ou près des points "Non prévu / En cours".
3. Les parcelles `4-Energie` (rouge) doivent être **dans la zone d'influence
   d'un poste saturé** (faible `puissance_disponible_kva`).
4. Les `1-Foncier` (gris) sont les **petites parcelles** ou les non-résidentielles.
5. La `heatmap_quartiers` doit concentrer les `Tier1` là où les éligibles
   "Premium" sont regroupés.

## Astuce

Pour rejouer avec d'autres seuils (ex. surface libre mini, rayon ABF), modifier
`config.py` puis relancer `python run.py` : toutes les couches SIG sont
régénérées automatiquement.
