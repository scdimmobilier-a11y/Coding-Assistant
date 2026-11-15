"""
Nexus Assistant — API HTTP
=============================

Étape 1a / 1b du prompt de fusion : expose nexus_compose.Orchestrator (et,
plus tard, unified_system.UnifiedSystem) au frontend nexus-ui par-dessus
HTTP + SSE. Cette couche n'implémente aucune logique métier elle-même —
elle appelle Orchestrator et relaie ses résultats ; voir state.py pour le
détail du pont thread -> asyncio.
"""

__version__ = "0.1.0"
