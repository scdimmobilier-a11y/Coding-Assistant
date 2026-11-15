"""nexus_unified.pack.catalog — définition des 226 nœuds du pack unified.

Chaque entrée devient un `NodeMeta` enregistré par-dessus les 169 nœuds de
base. Les familles reprennent l'inventaire du constat d'architecture : routes
OpenHands V1 (phase exec), outils crewAI et crewai-tools (research/design),
outils et moteurs OpenManus-RL (learn/eval), et les nœuds à créer
(gpu/ml/vllm/eval/reward/budget). Chaque nœud porte :

- `phase`      : la phase laboratoire (exec/research/design/train/eval/learn/…) ;
- `apex_phase` : la phase de gouvernance Apex (voir nexus_unified.apex) ;
- `capabilities` : étiquettes transversales (registry_schema §2.3 + 5 termes
  nouveaux : recherche, donnees, entrainement, evaluation, gpu) ;
- `resources`  : ex. {"gpu": 1} pour les nœuds qui exigent un accélérateur.

Le tag Apex par phase laboratoire suit la table `PHASE_TO_APEX`.
"""
from __future__ import annotations

from typing import Any, Dict, List

# phase laboratoire → phase Apex (gouvernance, 8 phases)
PHASE_TO_APEX = {
    "exec": "actor_execution",
    "research": "intelligence_validation",
    "design": "co_design",
    "train": "actor_execution",
    "eval": "outcome_audit",
    "learn": "intelligence_validation",
    "codegen": "actor_execution",
    "deploy": "deployment",
    "report": "outcome_audit",
}
# phase laboratoire → capacité dominante
PHASE_CAP = {
    "exec": "execution", "research": "recherche", "design": "codage",
    "train": "entrainement", "eval": "evaluation", "learn": "entrainement",
}


def _n(nid, phase, caps, *, io_in="", io_out="", resources=None, func="", ref="",
       note="", module=None) -> Dict[str, Any]:
    module = module or nid.split(".")[0]
    return {
        "id": nid, "module": module, "module_name": module,
        "function": func or nid.split(".", 1)[-1], "description": note or nid,
        "tag": f"{phase}.{caps[0] if caps else 'op'}", "phase": phase,
        "apex_phase": PHASE_TO_APEX.get(phase, ""), "type": phase,
        "io_in": io_in, "io_out": io_out, "ref": ref, "repo": "nexus_unified",
        "virtual": False, "capabilities": tuple(caps), "resources": resources or {},
    }


def build_catalog() -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []

    # ── OpenHands V1 — phase exec (68 routes utiles) ──────────────────────────
    OH = "unified_system/OpenHands/OpenHands/openhands/app_server/"
    oh_exec = [
        ("oh.health", "GET /health", ["execution", "diagnostic"]),
        ("oh.alive", "GET /alive", ["execution"]),
        ("oh.ready", "GET /ready", ["execution"]),
        ("oh.server_info", "GET /server_info", ["execution", "diagnostic"]),
        ("oh.sandbox_start", "POST /api/v1/sandboxes", ["execution", "gpu", "securite"]),
        ("oh.sandbox_search", "GET /api/v1/sandboxes/search", ["execution"]),
        ("oh.sandbox_get", "GET /api/v1/sandboxes", ["execution"]),
        ("oh.sandbox_pause", "POST /api/v1/sandboxes/{id}/pause", ["execution", "gpu"]),
        ("oh.sandbox_resume", "POST /api/v1/sandboxes/{id}/resume", ["execution"]),
        ("oh.sandbox_delete", "DELETE /api/v1/sandboxes/{id}", ["execution"]),
        ("oh.sandbox_spec_search", "GET /api/v1/sandbox-specs/search", ["execution", "gpu"]),
        ("oh.sandbox_spec_get", "GET /api/v1/sandbox-specs", ["execution"]),
        ("oh.conversation_start", "POST /api/v1/app-conversations", ["execution", "codage"]),
        ("oh.conversation_stream_start", "POST .../stream-start", ["execution"]),
        ("oh.start_task_get", "GET .../start-tasks", ["execution"]),
        ("oh.start_task_search", "GET .../start-tasks/search", ["execution"]),
        ("oh.start_task_count", "GET .../start-tasks/count", ["execution"]),
        ("oh.conversation_get", "GET /api/v1/app-conversations", ["execution"]),
        ("oh.conversation_search", "GET .../search", ["execution"]),
        ("oh.conversation_count", "GET .../count", ["execution"]),
        ("oh.conversation_update", "PATCH .../{id}", ["execution"]),
        ("oh.conversation_delete", "DELETE .../{id}", ["execution"]),
        ("oh.send_message", "POST .../{id}/send-message", ["execution", "codage"]),
        ("oh.switch_profile", "POST .../{id}/switch_profile", ["execution"]),
        ("oh.file_read", "GET .../{id}/file", ["execution", "donnees"]),
        ("oh.git_changes", "GET .../{id}/git/changes", ["execution", "codage"]),
        ("oh.git_diff", "GET .../{id}/git/diff", ["execution", "codage"]),
        ("oh.conversation_skills", "GET .../{id}/skills", ["execution"]),
        ("oh.conversation_hooks", "GET .../{id}/hooks", ["execution"]),
        ("oh.conversation_download", "GET .../{id}/download", ["execution", "donnees"]),
        ("oh.pending_message", "POST .../pending-messages", ["execution"]),
        ("oh.events_search", "GET /api/v1/conversation/{id}/events/search", ["execution", "entrainement"]),
        ("oh.events_count", "GET .../events/count", ["execution"]),
        ("oh.events_get", "GET .../events", ["execution"]),
        ("oh.webhook_conversations", "POST /api/v1/webhooks/conversations", ["execution", "proactivite"]),
        ("oh.webhook_events", "POST /api/v1/webhooks/events/{id}", ["execution", "proactivite"]),
        ("oh.settings_get", "GET /api/v1/settings", ["execution"]),
        ("oh.settings_set", "POST /api/v1/settings", ["execution"]),
        ("oh.settings_agent_schema", "GET .../agent-schema", ["execution"]),
        ("oh.settings_conversation_schema", "GET .../conversation-schema", ["execution"]),
        ("oh.profile_list", "GET /api/v1/settings/profiles", ["execution", "entrainement"]),
        ("oh.profile_get", "GET .../profiles/{name}", ["execution"]),
        ("oh.profile_save", "POST .../profiles/{name}", ["execution", "entrainement"]),
        ("oh.profile_delete", "DELETE .../profiles/{name}", ["execution"]),
        ("oh.profile_activate", "POST .../profiles/{name}/activate", ["execution"]),
        ("oh.profile_rename", "POST .../profiles/{name}/rename", ["execution"]),
        ("oh.secret_search", "GET /api/v1/secrets/search", ["execution", "securite"]),
        ("oh.secret_create", "POST /api/v1/secrets", ["execution", "securite"]),
        ("oh.secret_update", "PUT /api/v1/secrets/{id}", ["execution", "securite"]),
        ("oh.secret_delete", "DELETE /api/v1/secrets/{id}", ["execution", "securite"]),
        ("oh.git_provider_set", "POST /api/v1/secrets/git-providers", ["execution"]),
        ("oh.git_provider_delete", "DELETE /api/v1/secrets/git-providers", ["execution"]),
        ("oh.config_models_search", "GET /api/v1/config/models/search", ["execution"]),
        ("oh.config_providers_search", "GET /api/v1/config/providers/search", ["execution"]),
        ("oh.skills_search", "GET /api/v1/skills/search", ["execution"]),
        ("oh.user_me", "GET /api/v1/users/me", ["execution"]),
        ("oh.user_git_info", "GET /api/v1/users/git-info", ["execution"]),
        ("oh.git_repositories_search", "GET /api/v1/git/repositories/search", ["execution"]),
        ("oh.git_branches_search", "GET /api/v1/git/branches/search", ["execution"]),
        ("oh.rl_create", "POST /api/rl/conversations", ["execution", "entrainement"]),
        ("oh.rl_step", "POST /api/rl/conversations/{id}/step", ["execution", "entrainement"]),
        ("oh.rl_status", "GET /api/rl/conversations/{id}/status", ["execution"]),
    ]
    for nid, route, caps in oh_exec:
        nodes.append(_n(nid, "exec", caps, func=route, ref=OH, note=route))
    nodes.append(_n("oh.git_suggested_tasks", "research", ["recherche", "entrainement"],
                    func="GET /api/v1/git/suggested-tasks/search", ref=OH,
                    note="source de tâches pour le RL"))
    for nid, route in [("oh.mcp_create_pr", "MCP create_pr"), ("oh.mcp_create_mr", "MCP create_mr"),
                       ("oh.mcp_create_bitbucket_pr", "MCP create_bitbucket_pr"),
                       ("oh.mcp_create_bitbucket_dc_pr", "MCP create_bitbucket_data_center_pr"),
                       ("oh.mcp_create_azure_devops_pr", "MCP create_azure_devops_pr")]:
        nodes.append(_n(nid, "deploy", ["codage"], func=route, ref=OH + "mcp/mcp_router.py",
                        note=route + " (irréversible : GA7)"))

    # ── crewAI cœur — design/research/exec/eval ──────────────────────────────
    CR = "unified_system/crewAI/crewAI/lib/crewai/src/crewai/"
    crew = [
        ("crew.kickoff", "design", ["codage", "planification"]),
        ("crew.kickoff_for_each", "research", ["recherche"]),
        ("crew.kickoff_async", "design", ["codage"]),
        ("crew.kickoff_for_each_async", "research", ["recherche"]),
        ("crew.train", "learn", ["entrainement"]),
        ("crew.test", "eval", ["evaluation"]),
        ("crew.replay", "exec", ["execution"]),
        ("crew.fork", "exec", ["execution"]),
        ("crew.from_checkpoint", "exec", ["execution"]),
        ("crew.query_knowledge", "research", ["recherche", "memoire"]),
        ("crew.reset_memories", "exec", ["memoire"]),
        ("crew.reset_knowledge", "exec", ["memoire"]),
        ("crew.usage_metrics", "eval", ["evaluation", "diagnostic"]),
        ("crew.human_input_provider", "learn", ["entrainement"]),
        ("flow.kickoff", "design", ["planification"]),
        ("flow.resume", "exec", ["execution"]),
        ("flow.plot", "report", ["diagnostic"]),
        ("crew.skills_discover", "design", ["codage"]),
        ("crew.skills_activate", "design", ["codage"]),
        ("crew.skills_resources", "design", ["codage"]),
        ("crew.skills_context", "design", ["codage"]),
        ("crew.memory_remember", "research", ["memoire"]),
        ("crew.memory_recall", "research", ["memoire"]),
        ("crew.memory_extract", "research", ["memoire"]),
        ("crew.memory_forget", "exec", ["memoire"]),
        ("crew.memory_update", "research", ["memoire"]),
        ("crew.memory_inspect", "report", ["memoire", "diagnostic"]),
        ("crew.mcp_list_tools", "exec", ["execution"]),
        ("crew.mcp_call_tool", "exec", ["execution"]),
        ("crew.mcp_prompts", "exec", ["execution"]),
        ("crew.a2a_wrap", "exec", ["execution"]),
    ]
    for nid, phase, caps in crew:
        nodes.append(_n(nid, phase, caps, ref=CR, module="crew" if nid.startswith("crew") else "flow"))

    # ── crewai-tools (64 outils retenus) — research/exec ─────────────────────
    research_tools = [
        "brave_search", "exa", "firecrawl_search", "linkup", "parallel", "serpapi",
        "serper_dev", "serply_api", "tavily_search", "tavily_research", "tavily_get_research",
        "tavily_extractor", "oxylabs_google_search_scraper", "github_search", "arxiv_paper",
        "youtube_channel_search", "youtube_video_search", "apify_actors", "brightdata",
        "browserbase_load", "firecrawl_crawl_website", "firecrawl_scrape_website",
        "hyperbrowser_load", "jina_scrape_website", "multion", "oxylabs_amazon_product_scraper",
        "oxylabs_amazon_search_scraper", "oxylabs_universal_scraper", "scrape_element_from_website",
        "scrape_website", "scrapegraph_scrape", "scrapfly_scrape_website", "selenium_scraping",
        "serper_scrape_website", "spider", "stagehand", "csv_search", "directory_search",
        "docx_search", "json_search", "mdx_search", "pdf_search", "txt_search", "xml_search",
        "code_docs_search", "website_search", "rag", "llamaindex", "couchbase",
        "mongodb_vector_search", "qdrant_vector_search", "singlestore_search", "weaviate",
        "mysql_search", "nl2sql", "snowflake_search", "databricks_query", "dalle", "ocr", "vision",
    ]
    file_tools = ["directory_read", "file_read", "file_writer", "files_compressor"]
    CT = "unified_system/crewAI/crewAI/lib/crewai-tools/src/crewai_tools/tools/"
    for t in research_tools:
        nodes.append(_n(f"crewtools.{t}", "research", ["recherche", "donnees"],
                        ref=CT, module="crewtools", note=f"outil crewai-tools {t}"))
    for t in file_tools:
        nodes.append(_n(f"crewtools.{t}", "exec", ["execution"], ref=CT, module="crewtools"))

    # ── OpenManus-RL — learn/eval/exec (44) ──────────────────────────────────
    OM = "unified_system/OpenManus-RL/openmanus_rl/"
    omrl_learn = [
        "env_openhands", "make_envs", "rollout_vanilla", "rollout_dynamic", "rollout_staged",
        "stage_planning", "stage_action", "stage_memory_store", "stage_reflection",
        "gigpo_step_returns", "gigpo_outcome_advantage", "gigpo_episode_norm", "gigpo_step_group",
        "gigpo_step_norm", "reward_episode", "memory_simple", "memory_file", "memory_summarized",
        "ppo_train",
    ]
    omrl_eval = ["env_tool_use", "env_alfworld", "env_webshop", "agent_debugger_detect",
                 "agent_debugger_critical", "gaia_rollout", "gaia_score", "debugbench_generate"]
    omrl_exec = ["engine_chat", "engine_crewai", "tool_registry"]
    omrl_tools = ["advanced_object_detector", "arxiv_paper_searcher", "generalist_solution_generator",
                  "google_search", "image_captioner", "nature_news_fetcher", "object_detector",
                  "pubmed_search", "python_code_generator", "relevant_patch_zoomer", "text_detector",
                  "url_text_extractor", "wikipedia_knowledge_searcher"]
    for t in omrl_learn:
        nodes.append(_n(f"omrl.{t}", "learn", ["entrainement"], ref=OM, module="omrl"))
    for t in omrl_eval:
        nodes.append(_n(f"omrl.{t}", "eval", ["evaluation"], ref=OM, module="omrl"))
    for t in omrl_exec:
        nodes.append(_n(f"omrl.{t}", "exec", ["execution", "entrainement"], ref=OM, module="omrl"))
    nodes.append(_n("omrl.serve_model", "train", ["entrainement", "gpu"], ref=OM, module="omrl",
                    resources={"gpu": 1}))
    gpu_tools = {"advanced_object_detector", "object_detector", "text_detector"}
    for t in omrl_tools:
        res = {"gpu": 1} if t in gpu_tools else {}
        nodes.append(_n(f"omrl.tool_{t}", "research", ["recherche"], ref=OM + "tools/",
                        module="omrl", resources=res))

    # ── bridge ────────────────────────────────────────────────────────────────
    nodes.append(_n("us.health_check", "exec", ["execution", "diagnostic"],
                    ref="unified_system/bridge.py", module="us"))
    nodes.append(_n("us.rl_env_config", "learn", ["entrainement"],
                    ref="unified_system/bridge.py", module="us"))

    # ── nœuds à créer (infrastructure GPU/ML/éval) ───────────────────────────
    created = [
        ("gpu.lease", "exec", ["gpu", "execution"], {"gpu": 1}, "réserver un accélérateur"),
        ("gpu.release", "exec", ["gpu"], {}, "libérer un bail"),
        ("gpu.probe", "exec", ["gpu", "diagnostic"], {}, "détecter le GPU dans le sandbox"),
        ("gpu.discover", "exec", ["gpu", "diagnostic"], {}, "découverte multi-constructeur"),
        ("budget.guard", "exec", ["execution"], {}, "budget GPU-heures/jetons/durée (GA1)"),
        ("ml.dataset_snapshot", "research", ["donnees", "securite"], {}, "figer un jeu de données inspecté"),
        ("ml.artifact_inspect", "exec", ["securite", "donnees"], {}, "inspection obligatoire d'un artefact (point 9)"),
        ("ml.run_submit", "train", ["entrainement", "gpu"], {"gpu": 1}, "lancer un entraînement"),
        ("ml.run_wait", "train", ["entrainement"], {}, "attendre un run long"),
        ("ml.metrics_read", "eval", ["evaluation"], {}, "lire les métriques d'un run"),
        ("ml.checkpoint_register", "train", ["entrainement"], {}, "enregistrer un checkpoint"),
        ("ml.checkpoint_promote", "eval", ["evaluation"], {}, "promouvoir un checkpoint (via eval.gate)"),
        ("eval.gate", "eval", ["evaluation", "securite"], {}, "porte de promotion par politique OPA"),
        ("vllm.serve", "train", ["entrainement", "gpu"], {"gpu": 1}, "servir un checkpoint local"),
        ("vllm.swap", "train", ["entrainement"], {}, "remplacer le modèle servi"),
        ("vllm.stop", "train", ["gpu"], {}, "arrêter vLLM (libère la VRAM)"),
        ("reward.from_tests", "learn", ["entrainement", "evaluation"], {}, "récompense = tests cachés"),
        ("reward.from_audit", "learn", ["entrainement", "securite"], {}, "pénalité = constats d'audit"),
    ]
    for nid, phase, caps, res, note in created:
        nodes.append(_n(nid, phase, caps, resources=res, note=note,
                        module=nid.split(".")[0], ref="nexus_unified"))
    return nodes
