"""
nexus_compose.leon_llm_sync
==============================

Garde Leon (moteur conversationnel) et le reste de Nexus Assistant alignés
sur UN SEUL fournisseur LLM actif — celui installé/activé depuis le
dashboard "Connexion API" (voir `api/providers.py`) — au lieu de deux
sources qui peuvent silencieusement diverger.

Bug corrigé par ce module
--------------------------
`nexus_compose/llm_config.py::get_llm_config()` traite déjà le fournisseur
`is_active = 1` de la table SQLite `llm_providers` comme LA source de
configuration principale du système (voir sa docstring, section "Dashboard
d'installation") — c'est vrai pour tout appelant Python qui invoque
`get_llm_config()` à chaque requête (`nexus_compose/drivers.py`,
`api/providers.py`).

Ce n'était PAS vrai pour Leon. `scripts/bootstrap.sh` patche
`subsystems/leon/config.yml` (`llm.default: "<provider>/<model>"`) et
`.env` (`LEON_<PROVIDER>_API_KEY`) UNE SEULE FOIS, au bootstrap du
conteneur, à partir des seules variables d'environnement `NEXUS_LLM_*` —
jamais depuis la table `llm_providers`, et jamais rejoué après un
changement d'activation fait depuis le dashboard. Concrètement : activer
un fournisseur "B" dans l'UI change bien ce que voient q2d/crewAI/OpenHands
au prochain appel, mais Leon — la moitié conversationnelle du couple
Leon/Nexus Brain — continue de parler au fournisseur "A" (ou au défaut du
`config.sample.yml`) jusqu'au prochain redémarrage complet du conteneur.
Deux moitiés du même couple sur deux fournisseurs différents,
silencieusement : exactement la dérive que le dashboard est censé
éliminer.

Ce module réutilise EXACTEMENT la même logique de patch que
`bootstrap.sh` (mêmes fichiers, même clé YAML, même variable `.env`), mais
la rend rejouable à la demande — appelée par `api/providers.py` juste
après toute écriture qui change le fournisseur actif (activation,
désactivation, suppression du fournisseur actif), pas seulement au
démarrage du conteneur.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .llm_config import LLMConfig, get_llm_config

# Même convention que scripts/bootstrap.sh (SUBSYSTEMS="${REPO_ROOT}/subsystems",
# Leon extrait sous subsystems/leon) — surchageable pour les déploiements où
# Leon vit ailleurs, ou pour les tests.
_DEFAULT_LEON_DIR = "./subsystems/leon"


def _leon_dir() -> Path:
    return Path(os.environ.get("LEON_DIR", _DEFAULT_LEON_DIR))


def sync_leon_llm_config(cfg: Optional[LLMConfig] = None) -> dict[str, object]:
    """Réapplique la configuration LLM actuellement active à Leon
    (`config.yml` + `.env`).

    Ne lève JAMAIS : un appel à `/api/providers/{id}/activate` doit rester
    utilisable même si Leon n'est pas déployé à côté de ce backend (ex :
    `Nexus_Assistant/api` exécuté seul, tests, ou futur déploiement sans
    Leon) — toute impossibilité de synchroniser est retournée dans le
    dict, jamais propagée en exception qui ferait échouer l'endpoint
    appelant.

    Retourne un dict avec au minimum `"synced": bool` ; si `False`, une clé
    `"reason"` explique pourquoi (utile en logs/debug côté appelant).
    """
    cfg = cfg or get_llm_config()
    leon_dir = _leon_dir()
    config_path = leon_dir / "config.yml"

    if not config_path.exists():
        return {"synced": False, "reason": f"{config_path} introuvable — Leon non déployé ici."}

    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as e:
        return {"synced": False, "reason": f"lecture config.yml impossible : {e}"}

    patched, n = re.subn(
        r"(?m)^([ \t]*default:[ \t]*).*$",
        lambda m: f'{m.group(1)}"{cfg.qualified_model}"',
        text,
        count=1,
    )
    if n == 0:
        return {"synced": False, "reason": "clé 'default:' introuvable dans config.yml"}

    try:
        config_path.write_text(patched, encoding="utf-8")
    except OSError as e:
        return {"synced": False, "reason": f"écriture config.yml impossible : {e}"}

    result: dict[str, object] = {"synced": True, "qualified_model": cfg.qualified_model, "env_key_written": False}

    if cfg.api_key:
        env_path = leon_dir / ".env"
        var_name = f"LEON_{cfg.provider.upper()}_API_KEY"
        line = f"{var_name}={cfg.api_key}"
        try:
            existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
            if re.search(rf"(?m)^{re.escape(var_name)}=.*$", existing):
                existing = re.sub(rf"(?m)^{re.escape(var_name)}=.*$", line, existing, count=1)
            else:
                existing = existing + ("\n" if existing and not existing.endswith("\n") else "") + line + "\n"
            env_path.write_text(existing, encoding="utf-8")
            result["env_key_written"] = True
        except OSError as e:
            result["env_key_error"] = f"écriture .env impossible : {e}"

    return result
