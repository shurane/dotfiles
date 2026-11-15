"""Quote literal search terms; SQLite owns the grammar for explicit raw queries."""


def sanitize_fts5_query(query: str) -> str:
    return " ".join('"' + term.replace('"', '""') + '"' for term in query.split())
