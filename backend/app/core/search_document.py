"""Weighted catalog document, kept in a stored/generated PostgreSQL column."""

SEARCH_DOCUMENT_SQL = """
setweight(to_tsvector('english'::regconfig, title), 'A') ||
setweight(to_tsvector('english'::regconfig, genres::text || ' ' || keywords::text), 'B') ||
setweight(to_tsvector('english'::regconfig, coalesce(overview, '')), 'C')
"""
