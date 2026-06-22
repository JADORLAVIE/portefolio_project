"""
db.py — Connexion DuckDB et chargement des extensions géospatiales.

Un seul point d'entrée (`connect`) garantit que TOUTE connexion du pipeline
dispose des extensions `spatial` (fonctions ST_*) et `h3` (indexation
hexagonale). On crée aussi les schémas logiques du projet.
"""

import duckdb

from config import DB_PATH


SCHEMAS = ("staging", "intermediate", "marts", "ref")


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Ouvre la base DuckDB du projet, prête à l'emploi.

    - charge l'extension `spatial` (géométries, ST_*, reprojection PROJ)
    - charge l'extension communautaire `h3` (jointures par index hexagonal)
    - crée les schémas staging / intermediate / marts / ref s'ils manquent
    """
    con = duckdb.connect(str(DB_PATH), read_only=read_only)

    # Extensions. INSTALL est idempotent : si déjà présent, ne re-télécharge pas.
    con.execute("INSTALL spatial;  LOAD spatial;")
    con.execute("INSTALL h3 FROM community;  LOAD h3;")

    if not read_only:
        for schema in SCHEMAS:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")

    return con


def table_count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    """Nombre de lignes d'une table (0 si elle n'existe pas)."""
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except duckdb.Error:
        return 0
