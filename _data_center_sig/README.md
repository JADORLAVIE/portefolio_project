# Mini Data Centers Résidentiels — Sélection de Sites

## 📋 Description

Projet de géospatialisation et scoring des parcelles cadastrales éligibles à l'installation de mini data centers résidentiels (boîtiers type pompe à chaleur, 36 kVA triphasé, raccordement fibre, impact sonore 60dB).

Ce dossier contient les **prompts et méthodologie** pour construire un outil complet d'identification de sites éligibles, selon une approche **geo-data engineer** systématique (coût d'abord, cloud-native, pipeline reproductible, validation stricte).

---

## 📁 Fichiers du dossier

### `PROMPT.md`
**Prompt expert SIG** pour identifier les parcelles éligibles.
- 5 étapes de filtrage spatial (foncier, nuisances, connectivité, énergie, réglementaire)
- Appliquable directement dans QGIS, ArcGIS, ou script Python/PostGIS
- **Public :** Géomaticien, data scientist SIG

### `PROMPT_WORD_DOC.md`
**Prompt pour Claude web** générant un document Word complet.
- Explication complète de la méthodologie (9 sections)
- Table des matières auto-générée, tableaux, mise en forme professionnelle
- **Usage :** Copie-colle sur claude.ai pour générer un `.docx`

---

## 🚀 Démarrage rapide

### Option 1 : Utiliser le prompt SIG directement
1. Ouvre `PROMPT.md`
2. Copie son contenu
3. Colle dans QGIS (Python console), ou un script Python/SQL

### Option 2 : Générer un document Word explicatif
1. Ouvre `PROMPT_WORD_DOC.md`
2. Copie le contenu (du titre jusqu'à "INSTRUCTIONS POUR CLAUDE WEB")
3. Colle sur https://claude.ai (conversation nouvelle)
4. Ajoute : *"Génère-moi un document Word `.docx` avec cette structure, formaté professionnellement."*
5. Télécharge le fichier `.docx` généré

---

## 🏗️ Architecture de la solution (Geo-Data Engineer)

```
Données brutes (S3/GCS, 40–50 Go)
         ↓
dbt-duckdb (transformation spatiale optimisée)
         ↓
GeoParquet partitionné (outputs intermédiaires)
         ↓
Tests SQL + Validation spatiale (ST_IsValid, unicité)
         ↓
PMTiles (carto interactive) + GeoJSON exports
```

### Stack recommandée
- **Transformation :** dbt-duckdb + extension spatial
- **Stockage vecteur :** GeoParquet partitionné (par département)
- **Indexation :** H3 résolution 9 (~170 m²) + R-tree natif DuckDB
- **Carto :** PMTiles serverless (vs. GeoJSON 2 Go)
- **Versioning :** Git (dbt models, SQL, tests)
- **Conteneurisation :** Docker (reproductibilité 100%)

---

## 📊 Les 5 Filtres Spatiaux

| Filtre | Objectif | Seuil critique |
|--------|----------|-----------------|
| **1. Foncier & Bâti** | Habitat individuel résidentiel | Surface libre > 50 m² |
| **2. Nuisances & Sécurité** | Recul voisins + accessibilité | Buffer 5m, ≤15m du bâtiment |
| **3. Connectivité (ARCEP)** | Fibre déployée ou raccordable | Statut "Déployé"/"Raccordable" |
| **4. Énergie (Enedis)** | Capacité réseau BT 36 kVA | Marge puissance disponible |
| **5. Réglementaire** | Pas de blocages légaux | ABF, PPRI, EBC = exclusion |

---

## 💡 Principes Geo-Data Engineer appliqués

1. **COÛT D'ABORD** : 140M parcelles → H3 grid → jointures gérables
2. **PIPELINE = LOGICIEL** : dbt orchestré, versionné, testé, documenté
3. **CLOUD-NATIVE** : Zéro téléchargement 50 Go ; requêtes ciblées (httpfs + COG)
4. **STACK STANDARD** : DuckDB, GeoParquet, H3, PMTiles (validé industrie)
5. **VALIDATION STRICTE** : ST_IsValid, unicité, spatial CV (jamais K-Fold classique)

---

## 📦 Livrables attendus

Après implémentation :
- `parcelles_eligibles.parquet` (500k lignes, 50 Mo)
- `scoring.parquet` (scores 0–100 par parcelle)
- `heatmap_quartiers.geojson` (densité parcelles "premium" par région)
- `performance.json` (métriques d'exécution)
- Docker image + dbt project versionné

---

## 🎯 Roadmap implémentation

**Phase 1 : Pilote (1 département, 1–2 sem)**
- Connecteurs dbt pour chaque source (BD TOPO, Cadastre, ARCEP, Enedis, PPRI)
- Filtre 1 (foncier) + tests SQL
- Validation sur données réelles

**Phase 2 : Chaîne complète (1–2 sem)**
- Filtres 2–5
- Scoring + BlockCV spatial
- performance.json

**Phase 3 : Production (1 sem)**
- Montée à l'échelle France métro (140M parcelles)
- PMTiles + GeoJSON heatmap
- Documentation complète

**Phase 4 : Exposition (optionnel)**
- OGC API Features serverless
- Dashboard Streamlit interactif

---

## 📚 Ressources

- **QGIS :** Utilise Processing API avec les filtres spatiaux
- **Python :** GeoPandas + PostGIS ou DuckDB spatial
- **dbt :** dbt-duckdb pour orchestration cloud-native
- **Données :** 
  - BD TOPO : ignf-open-data (S3 public)
  - Cadastre : PCI Vecteur / GéoFLA (IGN)
  - ARCEP : API ou téléchargement
  - Enedis : Open data publique
  - Géoportail : WMS ou téléchargement

---

## ✅ Prochaines étapes

1. **Choisir une région pilote** (Île-de-France, Rhône-Alpes) pour POC
2. **Installer l'environnement** (Docker + dbt)
3. **Implémenter étape 1** (foncier) et la valider
4. **Chaîner les filtres** progressivement
5. **Générer les livrables** et mesurer perf

---

**Auteur :** Expert SIG / Geo-Data Engineer  
**Date :** 2026-06-18  
**Status :** Méthodologie définie, ready for implementation
