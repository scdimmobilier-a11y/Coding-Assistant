"""
nexus_vendor
═════════════════════════════════════════════════════════════════════════════
Code source extrait des 14 outils tiers du pipeline Nexus Compose.

Modules Python (source intégral vendorisé)
───────────────────────────────────────────
  nexus_vendor.q2d   — Query2Diagram  : graphes architecture → PlantUML
  nexus_vendor.pytm  — pytm OWASP     : threat modelling STRIDE
  nexus_vendor.tmdd  — TMDD           : Threat Model Driven Development

Sources natifs (code source dans leurs langages d'origine)
───────────────────────────────────────────────────────────
  native/opa/          Go  — moteur Rego (ast/, topdown/, bundle/, cmd/)
  native/bearer/       Go  — SAST + tree-sitter C parsers
  native/semgrep/      Py  — CLI Semgrep (rule, rule_match, output)
  native/containerlab/ Go  — déploiement lab réseau (cmd/, types/, core/)
  native/likec4/       TS  — générateurs (PlantUML, Mermaid, D2, React)
  native/c4interflow/  C#  — C4InterFlow .NET (readers, writers, CLI)
  native/batfish/      Java+Py — plan de données réseau + pybatfish client
  native/threat_dragon/JS  — serveur REST OWASP Threat Dragon
  native/codeql/       QL  — queries SAST par CWE + GitHub Actions
  native/structurizr/  Java — parseurs DSL (WorkspaceParser et 85 autres)
  native/neo4j/        Py  — driver officiel Neo4j 6.2.0

Usage
─────
  from nexus_vendor.pytm import TM, Actor, Process, Dataflow
  from nexus_vendor.tmdd.utils import load_threat_model
  from nexus_vendor.tmdd.generators.agent_prompt import generate_agent_prompt
  from nexus_vendor.q2d.graph_to_plantuml import convert_graph
"""

__version__ = "2.0.0"
__all__ = ["q2d", "pytm", "tmdd"]
