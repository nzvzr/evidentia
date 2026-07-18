"""Domain modules: versioned data packs, never engine code.

The engine executes module-supplied signatures generically; it never branches
on a taxonomy label (PLATFORM_ARCHITECTURE.md §3). Module content lives in
JSON files under ``app/modules/<id>/<version>/`` and is loaded, validated and
digested by :mod:`app.modules.loader`.
"""
