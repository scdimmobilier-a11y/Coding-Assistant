"""
nexus_vendor.tmdd — Threat Model Driven Development (vendorisé)
═══════════════════════════════════════════════════════════════════

TMDD est un outil CLI+lib Python pour piloter le développement par les modèles
de menace. Il lit des fichiers YAML structurés (composants, menaces, mitigations,
flux de données) et génère : prompts d'agent IA, diagrammes Mermaid, rapports HTML/MD.

Structure des fichiers YAML attendus
──────────────────────────────────────
  model/
    components.yaml     → liste des composants du système
    threats.yaml        → catalogue des menaces STRIDE
    mitigations.yaml    → catalogue des contre-mesures
    data_flows.yaml     → flux de données entre composants
    features/           → dossier de features (une par fichier YAML)

Fonctions clés (module tmdd.utils)
────────────────────────────────────
  load_yaml(path, strict=False)
      Charge et valide un fichier YAML TMDD.
      strict=True → lève une erreur si des champs inconnus sont présents.

  load_threat_model(model_dir)
      Charge l'intégralité d'un répertoire de modèle (tous les YAML).
      Retourne un dict structuré {components, threats, mitigations, data_flows, features}.

  resolve_model_dir(path)
      Résout un chemin relatif/absolu vers un répertoire de modèle valide.

  safe_name(text)
      Nettoie un texte pour en faire un identifiant filesystem-safe.

  get_mitigation_desc(entry, fallback="")
      Extrait la description d'une mitigation (str ou dict).

  get_mitigation_refs(entry)
      Retourne les références (OWASP, CWE, NIST) d'une mitigation.

Fonctions clés (module tmdd.generators.agent_prompt)
──────────────────────────────────────────────────────
  generate_agent_prompt(tm, output_path, feature_name=None)
      Génère un fichier agent_prompt.txt à partir d'un threat model chargé.
      C'est le fichier consommé par codegen.unified_system dans nexus_compose.
      Paramètres :
        tm           → dict retourné par load_threat_model()
        output_path  → Path — où écrire agent_prompt.txt
        feature_name → str|None — si défini, filtre sur une seule feature

Fonctions clés (module tmdd.generators.threat_prompt)
───────────────────────────────────────────────────────
  generate_threat_model_prompt(tm, feature_name, feature_description, model_dir)
      Génère un prompt LLM pour aider à créer ou enrichir un modèle de menace.
      Retourne une str (prompt prêt à envoyer à un LLM).

Commandes CLI (module tmdd.commands)
──────────────────────────────────────
  cmd_compile(args)   → Compile le modèle YAML → artefacts (rapport, diagram)
  cmd_lint(args)      → Valide la cohérence du modèle (champs requis, refs)
  cmd_init(args)      → Initialise un nouveau répertoire de modèle squelette
  cmd_feature(args)   → Ajoute ou liste les features du modèle

Rapport (module tmdd.report)
─────────────────────────────
  generate_html_report(threat_model, system_name) → str HTML
  generate_report(model_dir, output_dir, fmt="html"|"md")
      → Génère le rapport complet dans output_dir

Diagramme (module tmdd.diagram)
────────────────────────────────
  generate_diagram(model_dir, highlight_feature=None)
      → Génère un diagramme Mermaid flowchart du modèle de menace.
      highlight_feature → met en évidence une feature spécifique dans le graphe.

Usage typique dans nexus_compose
──────────────────────────────────
    from nexus_vendor.tmdd.utils import load_threat_model, resolve_model_dir
    from nexus_vendor.tmdd.generators.agent_prompt import generate_agent_prompt

    model_dir = resolve_model_dir("./threat_model")
    tm = load_threat_model(model_dir)
    generate_agent_prompt(tm, output_path="./agent_prompt.txt")
"""

try:
    from .utils import (
        load_yaml, load_threat_model, resolve_model_dir,
        safe_name, get_mitigation_desc, get_mitigation_refs,
        TMDDError, ModelNotFoundError,
    )
    from .generators.agent_prompt import generate_agent_prompt
    from .generators.threat_prompt import generate_threat_model_prompt
    from .report import generate_html_report, generate_report
    from .diagram import generate_diagram
except ImportError:
    pass

__all__ = [
    "load_yaml","load_threat_model","resolve_model_dir","safe_name",
    "get_mitigation_desc","get_mitigation_refs","TMDDError","ModelNotFoundError",
    "generate_agent_prompt","generate_threat_model_prompt",
    "generate_html_report","generate_report","generate_diagram",
]
