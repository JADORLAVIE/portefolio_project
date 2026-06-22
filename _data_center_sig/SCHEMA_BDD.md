# Schéma Complet de la Base de Données

## 🏗️ Architecture générale

```
mini_data_center.duckdb
├── SCHEMA: staging         (Données nettoyées, source unique de vérité pour inputs)
├── SCHEMA: intermediate    (Jointures spatiales, indexing H3)
├── SCHEMA: marts           (Tables métier finales)
└── SCHEMA: ref             (Tables de référence statiques)
```

---

## 1. SCHEMA: STAGING (Nettoyage & Validation)

Chaque table `stg_*` représente une source brute nettoyée, validée, en CRS cohérent (EPSG:2154).

### 1.1 `stg_parcelles`

**Source :** Cadastre (PCI Vecteur / GéoFLA)  
**Volume :** ~140M lignes  
**Partitionnement :** par département (75 partitions)

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `id_parcelle` | VARCHAR | ✅ | PRIMARY KEY | Format: "75056C0001-00001" |
| `dept` | VARCHAR(2) | ✅ | ✅ BTREE | Code département (01–95) |
| `commune` | VARCHAR | ✅ | | Nom commune |
| `commune_insee` | VARCHAR(5) | ✅ | ✅ BTREE | Code INSEE commune |
| `surface_m2` | DOUBLE | ✅ | | Surface parcelle en m² |
| `geom` | GEOMETRY | ✅ | ✅ RTREE | Polygon, EPSG:2154, validé |
| `geom_envelope` | GEOMETRY | | | Envelope (bbox) pour optimisation |
| `h3_res9_id` | VARCHAR | ✅ | ✅ BTREE | Index H3 résolution 9 |
| `is_valid_geom` | BOOLEAN | ✅ | | ST_IsValid(geom) |
| `loaded_at` | TIMESTAMP | ✅ | | Date chargement |

**Contraintes & Tests dbt :**
```sql
-- Unicité
SELECT id_parcelle, COUNT(*) FROM stg_parcelles 
GROUP BY id_parcelle HAVING COUNT(*) > 1  -- Doit être 0

-- Géométries valides
SELECT COUNT(*) FROM stg_parcelles WHERE NOT ST_IsValid(geom)  -- Doit être 0

-- Couverture spatiale
SELECT dept, COUNT(*) FROM stg_parcelles GROUP BY dept  -- Min ~200k par dept
```

---

### 1.2 `stg_batiments`

**Source :** BD TOPO IGN (bâtiments résidentiels)  
**Volume :** ~5M lignes  
**Filtre appliqué :** `usage = 'Résidentiel'` ET NOT `sous_type = 'Immeuble'`

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `id_batiment` | VARCHAR | ✅ | PRIMARY KEY | ID TOPO |
| `dept` | VARCHAR(2) | ✅ | ✅ BTREE | |
| `usage` | VARCHAR | ✅ | | "Résidentiel" (filtre appliqué) |
| `sous_type` | VARCHAR | | | "Maison", "Bungalow", etc. |
| `surface_m2` | DOUBLE | | | Surface emprise au sol |
| `geom` | GEOMETRY | ✅ | ✅ RTREE | Polygon, EPSG:2154 |
| `h3_res9_id` | VARCHAR | ✅ | ✅ BTREE | Index H3 |
| `loaded_at` | TIMESTAMP | ✅ | | |

**Notes :**
- Exclusion : Immeubles (copropriétés verticales)
- Inclusion : Maisons individuelles, bungalows, petits collectifs
- Validation : ST_IsValid, ST_Intersects avec bbox France valide

---

### 1.3 `stg_fibre`

**Source :** ARCEP Locaux (Points d'accès Fibre) / IPE (Immeubles de Production)  
**Volume :** ~1.2M lignes  
**Partition :** par département

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `id_locale` | VARCHAR | ✅ | PRIMARY KEY | Identifiant ARCEP local |
| `dept` | VARCHAR(2) | ✅ | ✅ BTREE | |
| `commune` | VARCHAR | ✅ | | |
| `statut_deploiement` | VARCHAR | ✅ | ✅ BTREE | "Déployé", "Raccordable", "En cours", "Non prévu" |
| `distance_raccordement_m` | DOUBLE | | | Distance à la fibre la + proche |
| `operateur_principal` | VARCHAR | | | Orange, Bouygues, etc. |
| `debit_annonce_mbps` | DOUBLE | | | Débit annoncé |
| `geom` | GEOMETRY | ✅ | ✅ RTREE | Point, EPSG:2154 |
| `h3_res9_id` | VARCHAR | ✅ | ✅ BTREE | |
| `loaded_at` | TIMESTAMP | ✅ | | |

**Validation :**
```sql
-- Vérifier statuts valides
SELECT DISTINCT statut_deploiement FROM stg_fibre  
-- IN ('Déployé', 'Raccordable', 'En cours', 'Non prévu')

-- Coverage
SELECT COUNT(DISTINCT h3_res9_id) FROM stg_fibre  -- ~500k h3 cells
```

---

### 1.4 `stg_energie`

**Source :** Enedis (Capacités réseau BT, Postes sources)  
**Volume :** ~500k lignes (postes sources)

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `id_poste_source` | VARCHAR | ✅ | PRIMARY KEY | ID Enedis |
| `dept` | VARCHAR(2) | ✅ | ✅ BTREE | |
| `commune` | VARCHAR | ✅ | | |
| `puissance_max_kva` | DOUBLE | ✅ | | Capacité max |
| `puissance_utilisee_kva` | DOUBLE | ✅ | | Actuellement utilisée |
| `puissance_disponible_kva` | DOUBLE | ✅ | ✅ BTREE | Clé pour scoring |
| `tension_basse_lignes` | VARCHAR[] | | | ["ligne_1", "ligne_2", ...] |
| `geom` | GEOMETRY | ✅ | ✅ RTREE | Point, EPSG:2154 |
| `h3_res9_id` | VARCHAR | ✅ | ✅ BTREE | |
| `loaded_at` | TIMESTAMP | ✅ | | |

**Validation :**
```sql
-- Capacité disponible > 0
SELECT COUNT(*) FROM stg_energie 
WHERE puissance_disponible_kva <= 0  -- Doit être minimal

-- Cohérence puissances
SELECT COUNT(*) FROM stg_energie 
WHERE puissance_utilisee_kva > puissance_max_kva  -- Doit être 0
```

---

### 1.5 `stg_abf` (Avis des Bâtiments de France)

**Source :** Géoportail Urbanisme  
**Volume :** ~15k monuments

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `id_monument` | VARCHAR | ✅ | PRIMARY KEY | |
| `dept` | VARCHAR(2) | ✅ | ✅ BTREE | |
| `nom` | VARCHAR | ✅ | | Nom du monument |
| `type` | VARCHAR | | | "Château", "Église", "Bridge", etc. |
| `geom_monument` | GEOMETRY | ✅ | ✅ RTREE | Point ou Polygon |
| `geom_buffer_500m` | GEOMETRY | ✅ | ✅ RTREE | Buffer 500m autour |
| `loaded_at` | TIMESTAMP | ✅ | | |

**Notes :**
- Buffer 500m = zone d'interdiction (ABF consulte tout projet dans ce rayon)
- Pour scoring : Intersection de parcelle avec buffer = rejet strict (filtre 05)

---

### 1.6 `stg_ppri` (Zones inondables)

**Source :** Géorisques / PPRI (Plans de Prévention du Risque Inondation)  
**Volume :** Varie par région (~500 polygones France)

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `id_ppri` | VARCHAR | ✅ | PRIMARY KEY | |
| `dept` | VARCHAR(2) | ✅ | ✅ BTREE | |
| `commune` | VARCHAR | ✅ | | |
| `niveau_risque` | VARCHAR | ✅ | | "Fort", "Moyen", "Faible" |
| `type_alea` | VARCHAR | | | "Inondation fluviale", "Remontée nappe", etc. |
| `geom_zone` | GEOMETRY | ✅ | ✅ RTREE | Polygon, EPSG:2154 |
| `loaded_at` | TIMESTAMP | ✅ | | |

**Validation :**
```sql
-- Rejet strict : toute intersection = exclusion
-- ST_Intersects(parcelle.geom, ppri.geom_zone) = TRUE → REJET
```

---

### 1.7 `stg_ebc` (Espaces Boisés Classés)

**Source :** PLU/Documents d'urbanisme  
**Volume :** ~100k EBC France

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `id_ebc` | VARCHAR | ✅ | PRIMARY KEY | |
| `dept` | VARCHAR(2) | ✅ | ✅ BTREE | |
| `commune` | VARCHAR | ✅ | | |
| `designation` | VARCHAR | | | Nom du boisement |
| `protection_niveau` | VARCHAR | | | "Strict", "Relatif", etc. |
| `geom_zone` | GEOMETRY | ✅ | ✅ RTREE | Polygon, EPSG:2154 |
| `loaded_at` | TIMESTAMP | ✅ | | |

**Validation :**
```sql
-- Rejet strict : toute intersection = exclusion
SELECT COUNT(*) FROM stg_ebc 
WHERE NOT ST_IsValid(geom_zone)  -- Doit être 0
```

---

## 2. SCHEMA: INTERMEDIATE (Jointures spatiales & Indexing)

Tables intermédiaires construites via `dbt/models/intermediate/`.

### 2.1 `int_parcelles_h3grid`

**But :** Créer une structure d'indexation H3 pour eviter ST_Intersects massif

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `h3_res9_id` | VARCHAR | ✅ | PRIMARY KEY | Index H3 résolution 9 (~170m²) |
| `h3_centroid` | GEOMETRY | ✅ | | Point représentatif de la cellule |
| `h3_bbox_polygon` | GEOMETRY | ✅ | ✅ RTREE | Polygon cellule H3 |
| `count_parcelles_in_cell` | BIGINT | ✅ | | Nombre parcelles ∩ cellule |
| `count_batiments_in_cell` | BIGINT | | | Nombre bâtiments ∩ cellule |
| `list_depts` | VARCHAR[] | | | Departments intersecting this cell |
| `spatial_coverage_pct` | DOUBLE | | | % coverage of H3 cell |

**Usage :** Point de départ pour toutes les jointures spatiales par étapes.

---

### 2.2 `int_parcelles_batiments`

**But :** Mapper chaque parcelle avec ses bâtiments associés via H3 join

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `id_parcelle` | VARCHAR | ✅ | PRIMARY KEY | |
| `h3_res9_id` | VARCHAR | ✅ | ✅ BTREE | Joint key |
| `id_batiments` | VARCHAR[] | | | Array IDs bâtiments sur/près parcelle |
| `count_batiments` | BIGINT | ✅ | | Nombre bâtiments |
| `emprise_batiments_total_m2` | DOUBLE | ✅ | | Somme emprises |
| `batiment_closest_distance_m` | DOUBLE | | | Distance au plus proche |
| `geom_parcelle` | GEOMETRY | | | Ref to stg_parcelles |

**Logic :**
```sql
-- Spatial join: parcelles ↔ bâtiments per H3 cell
SELECT 
  p.id_parcelle,
  ARRAY_AGG(b.id_batiment) as id_batiments,
  COUNT(b.id_batiment) as count_batiments,
  SUM(b.surface_m2) as emprise_batiments_total_m2,
  MIN(ST_Distance(p.geom, b.geom)) as batiment_closest_distance_m
FROM stg_parcelles p
JOIN stg_batiments b ON p.h3_res9_id = b.h3_res9_id
GROUP BY p.id_parcelle
```

---

### 2.3 `int_surface_libre`

**But :** Calculer surface disponible pour chaque parcelle

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `id_parcelle` | VARCHAR | ✅ | PRIMARY KEY | |
| `surface_parcelle_m2` | DOUBLE | ✅ | | De stg_parcelles |
| `emprise_batiments_m2` | DOUBLE | ✅ | | De int_parcelles_batiments |
| `surface_libre_m2` | DOUBLE | ✅ | ✅ BTREE | surface_parcelle - emprise_batiments |
| `pct_libre` | DOUBLE | ✅ | | (surface_libre / surface_parcelle) × 100 |
| `pass_filtre_surface_50m2` | BOOLEAN | ✅ | | surface_libre > 50 |

**Validation :**
```sql
-- Sanity check
SELECT COUNT(*) FROM int_surface_libre 
WHERE surface_libre_m2 > surface_parcelle_m2  -- Doit être 0
```

---

## 3. SCHEMA: MARTS (Tables métier finales)

### 3.1 `fct_parcelles_base`

**But :** Base centrale avant filtrage

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `id_parcelle` | VARCHAR | ✅ | PRIMARY KEY | |
| `dept` | VARCHAR(2) | ✅ | ✅ BTREE | |
| `commune` | VARCHAR | ✅ | | |
| `commune_insee` | VARCHAR(5) | ✅ | | |
| `surface_parcelle_m2` | DOUBLE | ✅ | | |
| `emprise_batiments_m2` | DOUBLE | | | |
| `surface_libre_m2` | DOUBLE | ✅ | ✅ BTREE | Key métier |
| `geom_parcelle` | GEOMETRY | ✅ | ✅ RTREE | |
| `h3_res9_id` | VARCHAR | ✅ | ✅ BTREE | |
| `h3_res8_id` | VARCHAR | ✅ | ✅ BTREE | Pour heatmap |
| `run_date` | TIMESTAMP | ✅ | | Date exécution pipeline |
| `data_version` | VARCHAR | ✅ | | Version dataset (ex: "2026-06-18") |

---

### 3.2 `fct_filtre_01_foncier` through `fct_filtre_05_reglement`

Progressive output of each filtering step. **Pattern** for each table:

| Colonne | Type | NOT NULL | Description |
|---------|------|----------|-------------|
| `id_parcelle` | VARCHAR | ✅ | Primary key |
| `dept` | VARCHAR(2) | ✅ | |
| `geom_parcelle` | GEOMETRY | | |
| `pass_filtre_XX` | BOOLEAN | ✅ | TRUE = passed this filter |
| `raison_rejet_XX` | VARCHAR | | Rejection reason if fail (for debugging) |
| `score_filtre_XX` | DOUBLE | ✅ | Points (0–20) for this filter |
| `count_rows_after_filter` | BIGINT | | Row count after this step |

**Exemple: fct_filtre_01_foncier**

| Colonne | Type | Description |
|---------|------|-------------|
| `id_parcelle` | VARCHAR | |
| `surface_libre_m2` | DOUBLE | |
| `pass_filtre_01_foncier` | BOOLEAN | surface_libre_m2 > 50 |
| `raison_rejet_01` | VARCHAR | "surface_libre < 50m2" si fail |
| `score_foncier` | DOUBLE | Min(surface_libre_m2 / 200 × 20, 20) |

**Exemple: fct_filtre_02_nuisances**

| Colonne | Type | Description |
|---------|------|-------------|
| `id_parcelle` | VARCHAR | |
| `buffer_5m_polygon` | GEOMETRY | Buffer 5m inward from limits |
| `pass_filtre_02_nuisances` | BOOLEAN | buffer_area ≥ min zone installation |
| `distance_building_m` | DOUBLE | Closest building distance |
| `pass_accesibilite_technique` | BOOLEAN | distance_building_m ≤ 15 |
| `score_nuisances` | DOUBLE | (0–20) |

**Example: fct_filtre_03_fibre**

| Colonne | Type | Description |
|---------|------|-------------|
| `id_parcelle` | VARCHAR | |
| `fibre_statut` | VARCHAR | "Déployé", "Raccordable", "Non" |
| `pass_filtre_03_fibre` | BOOLEAN | fibre_statut IN ('Déployé', 'Raccordable') |
| `distance_fibre_m` | DOUBLE | Distance à local ARCEP le + proche |
| `score_fibre` | DOUBLE | Déployé=20, Raccordable=10 |

**Example: fct_filtre_04_energie**

| Colonne | Type | Description |
|---------|------|-------------|
| `id_parcelle` | VARCHAR | |
| `poste_source_id` | VARCHAR | Closest Enedis poste source |
| `distance_poste_m` | DOUBLE | Distance (m) |
| `puissance_disponible_kva` | DOUBLE | From stg_energie |
| `pass_filtre_04_energie` | BOOLEAN | puissance_disponible_kva ≥ 36 |
| `score_energie` | DOUBLE | (0–20) |

**Example: fct_filtre_05_reglement**

| Colonne | Type | Description |
|---------|------|-------------|
| `id_parcelle` | VARCHAR | |
| `pass_abf_500m` | BOOLEAN | NOT ST_Intersects(geom, abf_buffer_500m) |
| `pass_ppri` | BOOLEAN | NOT ST_Intersects(geom, ppri_zone) |
| `pass_ebc` | BOOLEAN | NOT ST_Intersects(geom, ebc_zone) |
| `pass_plu_non_n` | BOOLEAN | PLU zone ≠ 'N' (if data available) |
| `pass_filtre_05_reglement` | BOOLEAN | ALL above = TRUE |
| `raison_rejet_05` | VARCHAR | Which constraints failed |
| `score_environnement` | DOUBLE | 0 si fail, 20 si all pass |

---

### 3.3 `fct_parcelles_eligibles` (MAIN OUTPUT)

**Volume :** ~500k lignes  
**Format :** GeoParquet (partitionné par département)

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `id_parcelle` | VARCHAR | ✅ | PRIMARY KEY | |
| `dept` | VARCHAR(2) | ✅ | ✅ BTREE | |
| `commune` | VARCHAR | ✅ | | |
| `commune_insee` | VARCHAR(5) | ✅ | | |
| `surface_parcelle_m2` | DOUBLE | ✅ | | |
| `surface_libre_m2` | DOUBLE | ✅ | ✅ BTREE | |
| `geom_parcelle` | GEOMETRY | ✅ | ✅ RTREE | |
| **Filter Results** | | | | |
| `pass_01_foncier` | BOOLEAN | ✅ | | Toutes TRUE |
| `pass_02_nuisances` | BOOLEAN | ✅ | | Toutes TRUE |
| `pass_03_fibre` | BOOLEAN | ✅ | | Toutes TRUE |
| `pass_04_energie` | BOOLEAN | ✅ | | Toutes TRUE |
| `pass_05_reglement` | BOOLEAN | ✅ | | Toutes TRUE |
| **Scoring** | | | | |
| `score_total` | DOUBLE | ✅ | ✅ BTREE | [0, 100] |
| `score_foncier` | DOUBLE | ✅ | | [0, 20] |
| `score_nuisances` | DOUBLE | ✅ | | [0, 20] |
| `score_fibre` | DOUBLE | ✅ | | [0, 20] |
| `score_energie` | DOUBLE | ✅ | | [0, 20] |
| `score_environnement` | DOUBLE | ✅ | | [0, 20] |
| `bonus_pv_proximite` | DOUBLE | ✅ | | 0 or 5 |
| `bonus_borne_ve` | DOUBLE | ✅ | | 0 or 5 |
| `bonus_poste_proche` | DOUBLE | ✅ | | 0 or 5 |
| **Ranking** | | | | |
| `eligibilite_classe` | VARCHAR | ✅ | ✅ BTREE | "Premium", "Bon", "Moyen" |
| `percentile_score` | DOUBLE | ✅ | | [0, 100] percentile |
| **Commercial** | | | | |
| `poste_source_distance_m` | DOUBLE | | | For accessibility |
| `borne_ve_distance_m` | DOUBLE | | | For bonus context |
| `fibre_statut` | VARCHAR | | | "Déployé" or "Raccordable" |
| `contact_proprietaire_nom` | VARCHAR | | | If data available (optional) |
| `contact_proprietaire_email` | VARCHAR | | | If data available (optional) |
| **Metadata** | | | | |
| `h3_res8_id` | VARCHAR | ✅ | ✅ BTREE | For heatmap join |
| `h3_res9_id` | VARCHAR | | | Original H3 index |
| `run_date` | TIMESTAMP | ✅ | | Pipeline execution date |
| `data_version` | VARCHAR | ✅ | | Dataset version |

---

### 3.4 `fct_scoring` (Detailed scores)

**Volume :** ~500k lignes (same as fct_parcelles_eligibles)

| Colonne | Type | Description |
|---------|------|-------------|
| `id_parcelle` | VARCHAR | PRIMARY KEY |
| `dept` | VARCHAR(2) | |
| **Component Scores** | | |
| `score_foncier` | DOUBLE | Surface libre points |
| `score_nuisances` | DOUBLE | Buffer + accès technique points |
| `score_fibre` | DOUBLE | ARCEP statut points |
| `score_energie` | DOUBLE | Enedis capacité points |
| `score_environnement` | DOUBLE | Réglementaire points |
| **Breakdown** | | |
| `surface_libre_m2` | DOUBLE | For foncier calculation |
| `pct_libre` | DOUBLE | % of parcelle |
| `fibre_statut` | VARCHAR | For fibre score |
| `puissance_dispo_kva` | DOUBLE | For energie score |
| `pv_proximity_m` | DOUBLE | Distance PV installation |
| `pv_proximity_points` | DOUBLE | 0 or 5 |
| `borne_ve_distance_m` | DOUBLE | Distance borne VE |
| `borne_ve_points` | DOUBLE | 0 or 5 |
| `poste_source_distance_m` | DOUBLE | Distance poste |
| `poste_source_points` | DOUBLE | 0 or 5 |
| **Final** | | |
| `score_total` | DOUBLE | Sum all components |
| `percentile` | DOUBLE | Ranking percentile |
| `classe` | VARCHAR | "Premium" / "Bon" / "Moyen" |

---

### 3.5 `fct_heatmap_quartiers` (Aggregation for mapping)

**Volume :** ~15k lignes (H3 resolution 8, 500m cells)  
**Format :** GeoJSON + Parquet

| Colonne | Type | NOT NULL | Index | Description |
|---------|------|----------|-------|-------------|
| `h3_res8_id` | VARCHAR | ✅ | PRIMARY KEY | H3 cell ~500m |
| `geom_h3_cell` | GEOMETRY | ✅ | ✅ RTREE | Polygon of H3 cell |
| `geom_h3_centroid` | GEOMETRY | | | Center point |
| **Aggregates** | | | | |
| `count_parcelles_eligibles` | BIGINT | ✅ | | Total eligible in cell |
| `count_premium` | BIGINT | ✅ | | Count score ≥ 80 |
| `count_bon` | BIGINT | ✅ | | Count score 60–79 |
| `count_moyen` | BIGINT | ✅ | | Count score <60 |
| `avg_score` | DOUBLE | ✅ | | Average score in cell |
| `max_score` | DOUBLE | ✅ | | Best score in cell |
| `pct_premium` | DOUBLE | ✅ | | % premium parcelles |
| **Context** | | | | |
| `communes_list` | VARCHAR[] | | | Communes ∩ cell |
| `depts_list` | VARCHAR[] | | | Departments ∩ cell |
| `dept_dominant` | VARCHAR(2) | ✅ | ✅ BTREE | Majority department |
| **Commercial** | | | | |
| `densité_indice` | DOUBLE | ✅ | ✅ BTREE | (count_premium / count_all) × 100 |
| `priorité_déploiement` | VARCHAR | ✅ | | "Tier1", "Tier2", "Tier3" |

**Example Tier classification :**
- **Tier1 (Premium)** : densité_indice ≥ 50% && count_parcelles ≥ 50
- **Tier2 (Bon)** : densité_indice 20–49% && count_parcelles ≥ 30
- **Tier3 (Moyen)** : Reste

---

## 4. SCHEMA: REF (Références statiques)

Petites tables statiques, rar eement mises à jour.

### 4.1 `ref_departements`

| Colonne | Type | Description |
|---------|------|-------------|
| `code_dept` | VARCHAR(2) | PRIMARY KEY |
| `nom_dept` | VARCHAR | Nom complet |
| `region` | VARCHAR | Région (optionnel) |

### 4.2 `ref_communes_insee`

| Colonne | Type | Description |
|---------|------|-------------|
| `commune_insee` | VARCHAR(5) | PRIMARY KEY |
| `commune_nom` | VARCHAR | Nom |
| `dept` | VARCHAR(2) | Département FK |

### 4.3 `ref_data_versions`

**Historique des versions du dataset**

| Colonne | Type | Description |
|---------|------|-------------|
| `version_id` | VARCHAR | PRIMARY KEY (ex: "2026-06-18") |
| `execution_date` | TIMESTAMP | Date run |
| `source_versions` | JSON | {"parcelles": "2024-q2", "bdtopo": "2024", ...} |
| `record_count` | BIGINT | Output rows |
| `duration_minutes` | DOUBLE | Execution time |

---

## 5. INDEXES STRATÉGIQUES

| Table | Index | Type | Colonne(s) | Rationale |
|-------|-------|------|-----------|-----------|
| `stg_parcelles` | idx_h3_res9 | BTREE | h3_res9_id | Jointures spatiales |
| `stg_parcelles` | idx_dept | BTREE | dept | Partitioning |
| `stg_parcelles` | idx_geom | RTREE | geom | ST_Intersects queries |
| `int_surface_libre` | idx_surface_libre | BTREE | surface_libre_m2 | Filtre 01 |
| `fct_parcelles_eligibles` | idx_score | BTREE | score_total | Ranking |
| `fct_parcelles_eligibles` | idx_classe | BTREE | eligibilite_classe | Filtering by tier |
| `fct_heatmap_quartiers` | idx_densité | BTREE | densité_indice | Commercial prioritization |

---

## 6. PARTITIONING STRATEGY

**Par département (75 partitions) pour :**
- `stg_parcelles` (140M rows)
- `stg_batiments` (5M rows)
- `stg_fibre` (1.2M rows)
- `stg_energie` (500k rows)
- `fct_parcelles_eligibles` (500k rows)

**Avantage :** Prune predicate, parallel reads, isolation par région pour debug.

---

## 7. VOLUMÉTRIE ESTIMÉE

| Table | Lignes | Taille estimée (Parquet) | Partition clé |
|-------|--------|--------------------------|----------------|
| `stg_parcelles` | 140M | 35 GB | dept |
| `stg_batiments` | 5M | 1.2 GB | dept |
| `stg_fibre` | 1.2M | 300 MB | dept |
| `stg_energie` | 500k | 150 MB | dept |
| `stg_abf`, `stg_ppri`, `stg_ebc` | 100k total | 50 MB | N/A |
| **INTERMEDIATE** | | | |
| `int_parcelles_h3grid` | 2M | 500 MB | N/A |
| `int_surface_libre` | 140M | 8 GB | dept |
| **MARTS** | | | |
| `fct_parcelles_eligibles` | 500k | 50 MB | dept |
| `fct_scoring` | 500k | 48 MB | dept |
| `fct_heatmap_quartiers` | 15k | 8 MB | N/A |
| **TOTAL** | | **~45 GB input, ~150 MB output** | |

---

## 8. VALIDATION QUERIES (dbt tests)

```sql
-- Test 1: Unicité parcelles
SELECT id_parcelle, COUNT(*) FROM fct_parcelles_eligibles 
GROUP BY id_parcelle HAVING COUNT(*) > 1
-- Doit être vide (0 rows)

-- Test 2: Géométries valides
SELECT COUNT(*) FROM fct_parcelles_eligibles 
WHERE NOT ST_IsValid(geom_parcelle)
-- Doit être 0

-- Test 3: Scoring cohérent
SELECT COUNT(*) FROM fct_parcelles_eligibles 
WHERE score_total < 0 OR score_total > 100
-- Doit être 0

-- Test 4: Filtre progressif cohérent
SELECT COUNT(*) FROM fct_parcelles_eligibles 
WHERE NOT (pass_01_foncier AND pass_02_nuisances AND pass_03_fibre 
          AND pass_04_energie AND pass_05_reglement)
-- Doit être 0 (tous TRUE pour cette table)

-- Test 5: Couverture géographique
SELECT dept, COUNT(*) FROM fct_parcelles_eligibles 
GROUP BY dept ORDER BY dept
-- Vérifier min ~1000 par dept (exception depts montagne/eau)

-- Test 6: Scoring distribution (anomaly detection)
SELECT percentile_approx(score_total, 0.5) as median,
       percentile_approx(score_total, 0.25) as p25,
       percentile_approx(score_total, 0.75) as p75
FROM fct_parcelles_eligibles
-- Vérifier distribution raisonnable (pas bimodal, pas skewed)

-- Test 7: H3 consistency
SELECT COUNT(*) FROM fct_heatmap_quartiers 
WHERE SUM(count_parcelles_eligibles) != SELECT COUNT(*) FROM fct_parcelles_eligibles
-- Vérifier agrégation cohérente
```

---

## 9. MAINTENANCE & UPDATES

**Frequences de update :**
- `stg_parcelles` : Annuel (IGN, Q2)
- `stg_batiments` : Annuel (BD TOPO 2024)
- `stg_fibre` : Trimestriel (ARCEP)
- `stg_energie` : Mensuel (Enedis)
- `stg_abf`, `stg_ppri`, `stg_ebc` : Annuel (Géoportail)

**Refresh process :**
```bash
dbt run --models staging intermediate marts --full-refresh
dbt test
# → New version created in ref_data_versions
```

