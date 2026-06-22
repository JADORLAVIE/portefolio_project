"""
tests_pipeline.py — Validation "geo-data engineer" du résultat.

Un pipeline n'est pas terminé tant qu'il n'est pas testé. On vérifie ici les
invariants qui DOIVENT être vrais, sinon le livrable est faux :
  * unicité des identifiants,
  * géométries valides,
  * score dans [0, 100],
  * cohérence de l'entonnoir (chaque filtre <= le précédent),
  * cohérence de l'agrégation heatmap (somme = total).

Chaque test renvoie (nom, ok, detail). Le pipeline échoue si un test casse.
"""


import config as C


def run_tests(con) -> list[tuple[str, bool, str]]:
    res = []

    def check(nom, sql, attendu=0, comparateur="=="):
        val = con.execute(sql).fetchone()[0]
        if comparateur == "==":
            ok = val == attendu
        elif comparateur == ">":
            ok = val > attendu
        else:
            ok = bool(val)
        res.append((nom, ok, f"{val}"))

    # 1. Unicité des parcelles éligibles
    check("Unicité id_parcelle",
          """SELECT COUNT(*) - COUNT(DISTINCT id_parcelle)
             FROM marts.fct_parcelles_eligibles""", 0)

    # 2. Géométries valides
    check("Géométries valides",
          """SELECT COUNT(*) FROM marts.fct_parcelles_eligibles
             WHERE NOT ST_IsValid(geom)""", 0)

    # 3. Score dans [0, 100]
    check("Score dans [0,100]",
          """SELECT COUNT(*) FROM marts.fct_parcelles_eligibles
             WHERE score_total < 0 OR score_total > 100""", 0)

    # 4. Classe cohérente avec le score (seuils pilotés par config.py)
    check("Classe cohérente",
          f"""SELECT COUNT(*) FROM marts.fct_parcelles_eligibles
             WHERE (classe='Premium' AND score_total < {C.CLASSE_PREMIUM_MIN})
                OR (classe='Bon'     AND (score_total < {C.CLASSE_BON_MIN} OR score_total >= {C.CLASSE_PREMIUM_MIN}))
                OR (classe='Moyen'   AND score_total >= {C.CLASSE_BON_MIN})""", 0)

    # 5. Entonnoir décroissant (chaque filtre garde <= le précédent)
    check("Entonnoir décroissant",
          """SELECT
               (SELECT COUNT(*) FROM marts.fct_filtre_01_foncier)   >= (SELECT COUNT(*) FROM marts.fct_filtre_02_nuisances)
           AND (SELECT COUNT(*) FROM marts.fct_filtre_02_nuisances)  >= (SELECT COUNT(*) FROM marts.fct_filtre_03_fibre)
           AND (SELECT COUNT(*) FROM marts.fct_filtre_03_fibre)      >= (SELECT COUNT(*) FROM marts.fct_filtre_04_energie)
           AND (SELECT COUNT(*) FROM marts.fct_filtre_04_energie)    >= (SELECT COUNT(*) FROM marts.fct_filtre_05_reglement)""",
          comparateur="bool")

    # 6. Agrégation heatmap = total éligibles
    check("Cohérence heatmap",
          """SELECT (SELECT SUM(count_eligibles) FROM marts.fct_heatmap_quartiers)
                  - (SELECT COUNT(*) FROM marts.fct_parcelles_eligibles)""", 0)

    # 7. Aucune parcelle éligible en zone interdite (double sécurité)
    check("Zéro éligible en zone ABF/PPRI/EBC",
          """SELECT COUNT(*) FROM marts.fct_parcelles_eligibles p
             WHERE EXISTS (SELECT 1 FROM staging.stg_abf a  WHERE ST_Intersects(p.geom, a.geom_buffer))
                OR EXISTS (SELECT 1 FROM staging.stg_ppri pp WHERE ST_Intersects(p.geom, pp.geom))
                OR EXISTS (SELECT 1 FROM staging.stg_ebc e  WHERE ST_Intersects(p.geom, e.geom))""", 0)

    # 8. Il reste au moins une parcelle éligible (sinon le jeu est vide)
    check("Au moins 1 éligible",
          "SELECT COUNT(*) FROM marts.fct_parcelles_eligibles", 0, ">")

    return res
