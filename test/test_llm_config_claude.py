"""
tests/test_llm_config_claude.py
───────────────────────────────────
Étape 4 du prompt de fusion : "LLM unique = Claude". Vérifie réellement
(pas seulement en lisant le code) que :
  1. get_llm_config() avec NEXUS_LLM_PROVIDER=anthropic retourne bien
     provider="anthropic" et le bon modèle.
  2. Un vrai objet crewai.LLM construit avec ce provider route bien vers
     Claude (pas un repli silencieux vers un autre fournisseur).

Le test 2 est skip si `crewai`/`anthropic` ne sont pas installés dans
l'environnement d'exécution — dans ce cas il ne prétend PAS avoir vérifié
quelque chose qu'il n'a pas vérifié.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


def test_get_llm_config_returns_anthropic_claude(monkeypatch):
    monkeypatch.setenv("NEXUS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("NEXUS_LLM_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("NEXUS_LLM_API_KEY", "test-key")

    from nexus_compose.llm_config import get_llm_config

    cfg = get_llm_config()
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-sonnet-5"
    assert cfg.qualified_model == "anthropic/claude-sonnet-5"


def test_crewai_llm_actually_routes_to_anthropic_native_provider(monkeypatch):
    """Trouvé en testant réellement (pas en lisant le code) : crewAI récent
    n'utilise pas systématiquement LiteLLM — il a des classes "native
    provider" par fournisseur (AnthropicCompletion pour anthropic/*), et
    lève `ImportError: Anthropic native provider not available` si le
    paquet `anthropic` n'est pas installé, plutôt que de retomber
    silencieusement sur un autre routage. Voir Dockerfile (FIX #4) et
    requirements.txt pour le correctif correspondant."""
    crewai = pytest.importorskip("crewai", reason="crewai non installé dans cet environnement")
    pytest.importorskip("anthropic", reason="paquet anthropic non installé — voir Dockerfile FIX #4")

    monkeypatch.setenv("NEXUS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("NEXUS_LLM_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("NEXUS_LLM_API_KEY", "test-key")

    from nexus_compose.llm_config import get_llm_config

    cfg = get_llm_config()
    llm = crewai.LLM(model=cfg.qualified_model, api_key=cfg.api_key)

    # AnthropicCompletion (pas un LLM générique LiteLLM) -> confirme que le
    # provider natif Anthropic a bien été sélectionné, pas un repli.
    assert type(llm).__name__ == "AnthropicCompletion"
    assert "claude" in llm.model
