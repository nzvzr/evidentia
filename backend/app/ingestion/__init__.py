"""Document ingestion (M2): normalization, MD/TXT parsers, sectionizer,
pipeline state machine and the in-process worker.

Layer map (PLATFORM_ARCHITECTURE.md §1): this package is L2 (ingestion and
parsing), L3 (DocIR — the typed contract lives in app/contracts.py) and the
sectionizing half of L4. It contains no classification (M3), no retrieval, no
claims, and nothing here is reachable while EVIDENTIA_TENANT_CORPUS_ENABLED is
off (the default).
"""
