# Prompt pour Claude Web → Document Word

Copie-colle ce prompt dans https://claude.ai (version web), puis demande-lui de générer un document Word `.docx`.

---

## PROMPT COMPLET

Tu es un expert en géomatique et geo-data engineering. Tu vas générer un **document Word professionnel** (`.docx`) qui explique une méthodologie complète pour construire un outil de sélection de sites pour mini data centers résidentiels.

### Contexte du projet

**Objectif métier :** Identifier les parcelles cadastrales en France métropolitaine éligibles à l'installation de mini data centers résidentiels (boîtiers de la taille d'une pompe à chaleur, consommation 36 kVA triphasé, connexion fibre obligatoire, impact sonore 60 dB).

**Approche :** Applique une logique **geo-data engineer** systématique : coût d'abord, pipeline orchestré, cloud-native, stack standard, validation stricte.

### Structure du document Word

Génère un document `.docx` avec la structure suivante :

#### **Page de titre**
- Titre : "Mini Data Centers Résidentiels — Méthodologie de Sélection de Sites"
- Sous-titre : "Approche Geo-Data Engineer"
- Auteur : [À compléter]
- Date : [Date du jour]
- Logo/couleurs : Professionnel, sobre

#### **Table des matières**
- Générée automatiquement par Word (styles Heading 1/2/3)

---

### **1. Résumé Exécutif**
(½ page)

Résume en 3 paragraphes :
- Le défi : identifier des parcelles aptes à recevoir une infrastructure lourde (36 kVA, fibre, bruit)
- L'approche : pipeline dbt orchestré, cloud-native (zéro téléchargement massif), validation spatiale
- Le résultat attendu : table de 400–500k parcelles éligibles France métro, scoring 0–100, heatmap quartiers

---

### **2. Contexte & Enjeux**
(1–2 pages)

#### 2.1 Le "Pitch" technique
- Boîtier extérieur ≈ pompe à chaleur
- Raccordement électrique : 36 kVA triphasé
- Connexion fibre : latence critique, très haut débit
- Nuisance : 60 dB continu
- Sécurisation requise
- Placement : extérieur, propriété privée résidentielle

#### 2.2 Défi géomatique
- Volumétrie : 140M parcelles cadastrales, 5M bâtiments, 1M locaux fibre, 500k postes électriques
- Complexité : 5 filtres spatiaux enchaînés = danger de ST_Intersects non optimisé
- Enjeu coût : réduire 50 Go de données brutes → requêtes ciblées par région

#### 2.3 Justification de l'approche geo-engineer
- Pourquoi pas QGIS/ArcGIS classique ? Pas de reproductibilité, pas de scalabilité, pas de tests
- Pourquoi pas Spark ? Overkill, overhead, budget infra
- Pourquoi dbt-duckdb ? Léger, reproductible, spatial natif, git-friendly, coût maîtrisé

---

### **3. Méthodologie : Les 5 Filtres Spatiaux**
(3–4 pages)

#### 3.1 Filtre 1 : Foncier & Bâti
**Objectif :** Isoler l'habitat individuel résidentiel

**Étapes :**
- Filtre BD TOPO : bâtiments avec usage "Résidentiel" ou "Constructions légères"
- Exclusion : copropriétés verticales (immeubles), terrains agricoles
- Jointure : bâtiments ↔ parcelles cadastrales
- Calcul surface libre : (Surface parcelle) − (Emprise bâtiments)
- **Seuil critère :** Surface libre > 50 m²

**Rationale :** L'équipement + accès maintenance + recul de sécurité = 50 m² minimum

#### 3.2 Filtre 2 : Modélisation Nuisances & Sécurité
**Objectif :** Garantir compatibilité voisinage + accessibilité technique

**Étapes :**
- **Buffer sonore :** 5 m vers l'intérieur depuis limites séparatives (60 dB = "Pas collé à la fenêtre du voisin")
- **Accessibilité électrique/réseau :** ≤ 15 m du bâtiment principal (longueur câbles acceptables)
- **Accès voirie :** Pour installation initiale (maintenance requiert passage camion)

**Critère :** Espace restant après buffer doit contenir la zone d'installation + tirage câbles

#### 3.3 Filtre 3 : Connectivité (ARCEP FttH)
**Objectif :** Garantir fibre déployée ou très proche

**Étapes :**
- Croisement avec base ARCEP des Locaux (IPE = points d'accès fibre)
- Filtre statut : "Déployé" ou "Raccordable" SEULEMENT
- Exclusion : ADSL, Satellite (latence trop élevée)

**Rationale :** Data center résidentiel = latence critique (trading, cloud gaming)

#### 3.4 Filtre 4 : Énergie (Enedis BT)
**Objectif :** Vérifier capacité réseau basse tension

**Étapes :**
- Croisement avec carte capacités d'accueil Enedis (postes sources, lignes BT)
- Critère : marge de puissance disponible (pas en contrainte)
- **Bonus scoring :** +points si densité bornes VE ou installations PV existantes (réseau déjà dimensionné)

**Rationale :** 36 kVA permanent = charge importante ; réseau surchargé = refus raccordement ou coûts énormes

#### 3.5 Filtre 5 : Réglementaire & Environnemental
**Objectif :** Éviter blocages administratifs ou risques

**Exclusions strictes (Intersect = Rejet) :**
- **ABF :** Périmètre 500 m des Monuments Historiques (avis obligatoire, souvent défavorable)
- **PPRI :** Zones inondables (court-circuit électrique, assurance impossible)
- **EBC :** Espaces Boisés Classés (protection paysagère, impossibilité légale)
- **PLU-N :** Zones naturelles (protection environnementale)

**Rationale :** Blocages juridi-administratifs = infaisable, aucune marge de négociation

---

### **4. Stack Technique**
(2 pages)

#### 4.1 Architecture générale

```
Données brutes (S3/GCS, 40–50 Go)
         ↓
dbt-duckdb (transformation spatiale)
         ↓
GeoParquet partitionné (outputs intermédiaires)
         ↓
Tests SQL + Validation spatiale
         ↓
PMTiles (carto interactive) + Exports analytiques
```

#### 4.2 Composants détaillés

| **Composant** | **Technologie** | **Rationale** |
|---------------|-----------------|---------------|
| **Transformation** | dbt-duckdb + extension spatial | Reproduit sans effort, testable, cost-effective |
| **Stockage vecteur brut** | GeoParquet partitionné (par département) | 10× plus compact que Shapefile, queryable sans chargement total |
| **Indexation spatiale** | H3 résolution 9 (~170 m²) + R-tree natif DuckDB | Évite ST_Intersects sur 140M lignes |
| **Reprojection** | EPSG:2154 (Lambert 93) pour calculs, WGS84 pour échange | Précision surface/distance, compatibilité standard |
| **Scoring** | Modèle dbt (règles métier) + validation spatiale (BlockCV) | Pas de K-Fold classique (interdit : spatial leakage) |
| **Carto sortie** | PMTiles serverless | GeoJSON 2 Go → PMTiles 50 Mo, web-ready |

#### 4.3 Outils associés

- **Versioning :** Git (dbt models, SQL, tests)
- **Orchestration :** dbt run (local) ou Dagster (production)
- **Conteneurisation :** Docker (reproductibilité 100%)
- **Exposition API :** OGC API Features (optionnel, selon demande)

---

### **5. Logique Geo-Data Engineer Systématique**
(2–3 pages)

#### 5.1 Principe 1 : COÛT D'ABORD

Avant toute requête :
- **Volumes ?** 140M parcelles, 5M bâtiments, 1M points fibre
- **Problème :** ST_Intersects sans index = O(n × m) = **140M × 5M scans = crash**
- **Solution :** H3 grid (résolution 9), puis jointure H3 ↔ géométries
- **Impact :** 140M parcelles → groupées en ~2M cellules H3 → jointure 2M × 5M = gérable

**Anti-pattern :** "Ça marche sur le test (100k lignes), je force la prod." → Non. Coût dicte la tech.

#### 5.2 Principe 2 : PIPELINE = LOGICIEL

Livrable = **code versionné**, pas `.py` one-shot.

4 conditions non-négociables :
1. **Versionné :** Git commit avec message clair ("Ajout filtre PPRI", pas "v3_final2")
2. **Reproductible :** `docker run` sur machine vierge = tourne
3. **Testé :** ST_IsValid, unicité, couverture géographique
4. **Documenté :** README (inputs, outputs, commande), DATA_SOURCES.md, METHODOLOGY.md

Structure dbt :
```
dbt/models/
├── staging/        (nettoyage sources brutes)
├── marts/          (outputs métier : parcelles éligibles, scoring, heatmap)
└── tests/          (validation SQL)
```

#### 5.3 Principe 3 : CLOUD-NATIVE PAR DÉFAUT

Ordre de préférence d'accès données :

1. **Query directe sans DL** : S3/GCS via httpfs (DuckDB lit byte-range) → BD TOPO par département sous COG
2. **Format optimisé local** : GeoParquet partitionné → Cadastre par dept
3. **API REST** : ARCEP Locaux (petit volume, stable)
4. **Téléchargement 1× justifié** : Enedis, géorisques (volumétrie acceptable, stable)
5. **JAMAIS :** `wget` 40 Go BD TOPO complète

**Impact :** 40 Go → 1 Go transfert / département / run

#### 5.4 Principe 4 : STACK STANDARD

Choix tech validés par industrie, pas custom.

**Spatialisation :**
- DuckDB extension spatial (vs PostGIS : pas besoin server)
- H3 pour indexation (vs Quadtree : maintenance lourd)
- GeoParquet (vs Shapefile : obsolète, vs GeoJSON : lourd)

**Validation :**
- ST_IsValid (détecte géométries cassées)
- Tests uniqueness par ID parcelle
- BlockCV spatial (pas K-Fold standard = **interdit**)

#### 5.5 Principe 5 : VALIDATION AVANT LIVRAISON

Checklist systématique :

```
☐ Géométries valides : SELECT COUNT(*) WHERE NOT ST_IsValid(geom) = 0
☐ CRS cohérent : SELECT DISTINCT ST_SRID(geom) = 2154
☐ Pas doublons : GROUP BY id_parcelle HAVING COUNT(*) = 1
☐ Couverture complète : Parcelles/département >= seuil minimum
☐ Scoring cohérent : MIN/MAX/AVG ∈ [0, 100], distribution raisonnable
☐ Perf documentée : JSON avec durée, volumétrie in/out
```

#### 5.6 Anti-patterns INTERDITS

| Anti-pattern | Danger | Remède |
|--------------|--------|--------|
| ST_Intersects sans INDEX | 2h timeout | RTREE ou H3 |
| WGS84 pour calcul surface | ±25% erreur | Reprojeter EPSG:2154 |
| Buffer sur 140M géoms en mémoire | OOM | H3 grid → buffer H3 cells |
| Script écrase données | Perte données | dbt versioning + snapshot |
| K-Fold standard sur géodata | Spatial leakage | BlockCV ou k-fold par région |
| GeoJSON 500k entités | 2 Go, freeze navigateur | PMTiles |

---

### **6. Livrables Attendus**
(2 pages)

#### 6.1 Structure Git

```
mini-data-center-tool/
├── README.md                          # Comment lancer, inputs/outputs
├── DATA_SOURCES.md                    # Sources données, licences, coût, update freq
├── METHODOLOGY.md                     # Rationale seuils métier
├── docker/
│   ├── Dockerfile                     # dbt + duckdb + python
│   └── requirements.txt
├── dbt/
│   ├── dbt_project.yml
│   ├── models/
│   │   ├── staging/                   # Nettoyage brut
│   │   │   ├── stg_parcelles.sql
│   │   │   ├── stg_batiments.sql
│   │   │   ├── stg_fibre.sql
│   │   │   ├── stg_energie.sql
│   │   │   └── stg_reglementaire.sql
│   │   └── marts/                     # Livrables métier
│   │       ├── parcelles_h3grid.sql   # Indexation spatiale
│   │       ├── filtres_appliques.sql  # Étapes 1–5
│   │       ├── scoring.sql            # 0–100
│   │       └── heatmap_quartiers.sql
│   └── tests/
│       ├── not_null.sql
│       ├── valid_geometries.sql
│       └── no_duplicates.sql
├── .github/workflows/
│   └── nightly.yml                    # dbt run si données fraîches
└── outputs/
    ├── parcelles_eligibles.parquet
    ├── scoring.parquet
    ├── heatmap.geojson
    └── performance.json
```

#### 6.2 Commande de reproduction

```bash
# Build image Docker
docker build -t data-center-selector .

# Lancer pipeline
docker run --rm \
  -v $(pwd)/data:/data \
  data-center-selector \
  dbt run --models marts.parcelles_eligibles \
          --profiles-dir /root/.dbt

# Résultat → /data/outputs/parcelles_eligibles.parquet
```

#### 6.3 Outputs principaux

**1. `parcelles_eligibles.parquet`**
- ~500k lignes, 50 Mo (GeoParquet)
- Colonnes : id_parcelle, commune, surface_libre, geom, score
- Filtrées selon 5 critères

**2. `scoring.parquet`**
- Score 0–100 par parcelle
- Composantes : surface libre (+20), fibre déployée (+15), poste source <500m (+20), etc.

**3. `heatmap_quartiers.geojson`**
- Agrégation spatiale (H3 résolution 8) : count(parcelles éligibles) par cellule
- Densité quartiers "premium" pour déploiement commercial ciblé

**4. `performance.json`**
```json
{
  "execution_date": "2026-06-18T14:32:00Z",
  "duration_seconds": 3420,
  "region": "France métro",
  "input_volumes": {
    "parcelles_total": 140000000,
    "parcelles_processed": 2500000
  },
  "output_volumes": {
    "parcelles_eligibles": 487000,
    "outputs_total_mb": 48
  },
  "validation": {
    "invalid_geometries": 0,
    "duplicates": 0
  }
}
```

---

### **7. Tableau Comparatif : Approches**
(1 page)

| **Aspect** | **QGIS/ArcGIS classique** | **Spark** | **Geo-Data Engineer (dbt-duckdb)** |
|------------|---------------------------|-----------|-------------------------------------|
| **Reproductibilité** | Non (UI, clics) | Possible (complexe) | ✅ Git, Docker |
| **Coût infra** | 1 PC + licences | 10+ VMs / Kubernetes | ✅ Local + GCS query |
| **Scalabilité** | France = 1 dept max | ✅ Très haute | ✅ Bonne (H3 grid) |
| **Testabilité** | Manuelle (vérif QGIS) | Code tests dispo | ✅ Tests SQL natifs |
| **Temps itération** | Heures (interface) | 10–30 min | ✅ < 5 min local |
| **Documentation** | "Lis les clics" | Code + docs ad-hoc | ✅ dbt YML, README |
| **Maintenance** | Personne quitte = perdu | Possible | ✅ Versionné, documenté |

**Verdict :** Geo-engineer = sweet spot transparence/coût/scalabilité.

---

### **8. Prochaines Étapes — Roadmap Implémentation**
(1 page)

#### Phase 1 : Pilote (1 département, 1–2 semaines)
1. Fixer 1 département test (ex. 75 ou 38 pour volumétrie manageable)
2. Préparer **connecteurs dbt** pour chaque source
   - BD TOPO → COG + httpfs query
   - Cadastre → GeoParquet
   - ARCEP → API REST
   - Enedis, PPRI → téléchargement 1×
3. Implémenter **étape 1 (foncier)** + tests SQL
4. Valider sur données réelles

#### Phase 2 : Chaîne complète (1–2 semaines)
5. Ajouter étapes 2–5
6. Générer performance.json
7. Test validation spatiale (BlockCV)

#### Phase 3 : Production (1 semaine)
8. Montée à l'échelle : France métro (140M parcelles)
9. Générer PMTiles + GeoJSON heatmap
10. Documenter DATA_SOURCES.md, METHODOLOGY.md
11. GitHub + CI/CD (dbt run nightly)

#### Phase 4 : Exposition (optionnel)
12. OGC API Features serverless
13. Dashboard Streamlit (visualisation parcelles, exploration)

---

### **9. Conclusion**
(½ page)

L'approche **geo-data engineer** pour le mini data center tool repose sur :
- **Coût avant tout** : requêtes ciblées, cloud-native, jamais 50 Go brutes
- **Pipeline reproductible** : dbt orchestré, versionné, testé, documenté
- **Stack standard** : DuckDB + H3 + GeoParquet + PMTiles (pas de custom)
- **Validation stricte** : géométries, unicité, spatial CV

**Résultat attendu :** Dataset de 400–500k parcelles éligibles, scoring 0–100, heatmap quartiers.
**Timeline :** 3–4 semaines pour production France complète.
**Avantage concurrentiel :** Reproductible, testable, maintainable vs. QGIS one-shot.

---

## INSTRUCTIONS POUR CLAUDE WEB

1. **Copie ce prompt entièrement** (du titre jusqu'à "INSTRUCTIONS POUR CLAUDE WEB")
2. **Ouvre https://claude.ai** en conversation nouvelle
3. **Colle le prompt** dans la zone de chat
4. **Ajoute au prompt :** "Génère-moi un document Word `.docx` avec cette structure. Formate-le professionnellement (couleurs sobres, polices lisibles, titre/sous-titres, puces, tableaux)."
5. **Clique Envoyer**
6. Claude web va générer un fichier `.docx` que tu peux **télécharger immédiatement**

---

**Alternative si Claude web ne génère pas le `.docx` :** Claude web peut te proposer une version HTML ou Markdown complet. Utilise alors la skill `/docx` dans Claude Code (appel local) pour convertir Markdown → DOCX avec mise en forme.

