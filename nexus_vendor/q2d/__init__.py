"""
nexus_vendor.q2d — Query2Diagram (vendorisé depuis KELEBA-LAM/Vocale-vibecoding-)
══════════════════════════════════════════════════════════════════════════════════════

Query2Diagram convertit des questions en langage naturel ou du code source en
diagrammes d'architecture (PlantUML, Mermaid, Structurizr DSL) à l'aide de LLMs.

Modules clés
────────────
  cli.py               Point d'entrée CLI principal (`q2d generate`, `q2d convert`)
  checker.py           Vérifie la validité syntaxique des diagrammes générés
  graph_to_plantuml.py Transforme un graphe JSON en diagramme PlantUML
  generation/          Générateurs de diagrammes (API OpenAI, Claude, modèles locaux)
    generate_api.py        → Appels LLM via API distante
    generate_utils.py      → Utilitaires communs (prompts, post-processing)
    prompts.py             → Templates de prompts pour la génération
  common/              Types partagés et utilitaires
    types.py               → DiagramType, GraphNode, GraphEdge, etc.
    utils.py               → helpers I/O, détection de langage, sanitisation
  datasets/            Gestion des datasets d'entraînement
    nearest_neighbours.py  → Recherche de similarité pour few-shot prompting

Usage direct
────────────
    from nexus_vendor.q2d.generation.generate_api import generate_diagram
    from nexus_vendor.q2d.graph_to_plantuml import graph_to_plantuml
    from nexus_vendor.q2d.common.types import DiagramRequest
"""

# Re-export des interfaces publiques principales
try:
    from .graph_to_plantuml import graph_to_plantuml
    from .common.types import *
    from .checker import check_diagram
except ImportError:
    pass  # Dépendances optionnelles (openai, etc.) non installées

__all__ = ["graph_to_plantuml", "check_diagram"]
