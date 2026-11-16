# ══════════════════════════════════════════════════════════════════════════════
# nexus_core_leon_bridge/Dockerfile — Nexus Core <-> Leon bridge
#
# CONTEXTE DE BUILD = LA RACINE DU MONOREPO (..), PAS CE DOSSIER.
# Voir docker-compose.yml, service `bridge` :
#   build: { context: .., dockerfile: nexus_core_leon_bridge/Dockerfile }
# Un Dockerfile ne peut jamais COPY un fichier situé hors de son contexte de
# build — et ce pont a besoin du code de Nexus_Brain/ (nexus_brain +
# nexus_functor), un dépôt FRÈRE, pas un sous-dossier de celui-ci. C'est la
# seule façon de les réunir dans une image sans dupliquer leur code ici.
#
# CE QUI N'EST DÉLIBÉRÉMENT PAS COPIÉ :
#   - Nexus_Brain/vendor/nexus_harness/ et vendor/nexus_planner/ → jamais
#     importés par le code réellement utilisé ici (harness_adapter.py ne
#     fait que MENTIONNER vendor/nexus_harness/... dans un docstring ;
#     nexus_planner est invoqué hors-process, en subprocess, jamais en
#     `import`). Exclus aussi de Nexus_Brain/pyproject.toml lui-même
#     ([tool.setuptools.packages.find] exclude = ["vendor*", ...]).
#     ATTENTION : vendor/nexus_exec/ et vendor/nexus_proactive_when/, EUX,
#     SONT des imports durs (exec_adapter.py, proactive_adapter.py) —
#     copiés ci-dessous (juste le paquet Python interne, pas le dépôt
#     entier avec ses scripts d'entraînement/docs/assets). Trouvé en
#     simulant réellement `import bridge.server` avant ce correctif, pas
#     en relisant le code : c'est justement le genre d'erreur qu'une
#     lecture de code seule peut manquer.
#   - Nexus_Assistant/nexus_compose/ (donc pas de vrai `import nexus_compose`
#     possible ici) → bridge/llm_config.py a un repli VOLONTAIRE et déjà
#     testé pour ce cas exact (`_fallback_get_llm_config`, cf. son propre
#     docstring : "intentionally a read-only mirror, not a second source of
#     truth"). Ce conteneur parle à nexus_compose UNIQUEMENT en HTTP, via
#     NEXUS_COMPOSE_API_URL (voir bridge/registry_aggregator.py et
#     Nexus_Assistant/docs/registry_schema.md §0, "conteneurs séparés") —
#     copier son code source ici recréerait exactement le risque de
#     divergence à deux copies que cette architecture évite.
# ══════════════════════════════════════════════════════════════════════════════

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

WORKDIR /app

# ── Nexus Functor (F0-F3, sans dépendance) ────────────────────────────────────
COPY Nexus_Brain/nexus_functor /app/Nexus_Brain/nexus_functor
RUN pip install --no-cache-dir -e /app/Nexus_Brain/nexus_functor

# ── Nexus Brain (core cognitif + adapters) ─────────────────────────────────────
# dependencies déclarées dans son pyproject.toml (openai, numpy, requests)
# installées automatiquement par ce -e — pas besoin de les lister ici.
# README.md copié aussi : Nexus_Brain/pyproject.toml déclare
# `readme = "README.md"` — sans lui, `pip install -e` échoue à la lecture
# des métadonnées du paquet (vérifié, pas supposé).
COPY Nexus_Brain/pyproject.toml Nexus_Brain/README.md /app/Nexus_Brain/
COPY Nexus_Brain/nexus_brain /app/Nexus_Brain/nexus_brain

# vendor/nexus_exec et vendor/nexus_proactive_when : imports DURS de
# exec_adapter.py / proactive_adapter.py (contrairement à nexus_harness et
# nexus_planner, cf. note plus haut). Seul le paquet Python interne de
# chacun est copié (68K / 140K) — pas le dépôt vendor entier (816K / 2.1M,
# scripts d'entraînement/docs/assets non nécessaires à l'exécution) — même
# structure relative que nexus_brain/__init__.py attend
# (`vendor/<nom>/<nom>/...`, cf. ce fichier pour le détail du sys.path).
# mini.py (nexus_exec) n'a besoin que de numpy, déjà installé via
# Nexus_Brain/pyproject.toml ; nexus_proactive_when a besoin d'openai
# (>=1.108.0 dans son propre pyproject.toml), déjà installé via
# Nexus_Brain/pyproject.toml aussi (>=1.0 — compatible, pip résout une
# version qui satisfait les deux contraintes).
COPY Nexus_Brain/vendor/nexus_exec/nexus_exec /app/Nexus_Brain/vendor/nexus_exec/nexus_exec
COPY Nexus_Brain/vendor/nexus_proactive_when/nexus_proactive_when /app/Nexus_Brain/vendor/nexus_proactive_when/nexus_proactive_when

RUN pip install --no-cache-dir -e /app/Nexus_Brain

# pyperplan (optionnel, GPLv3, invoqué hors-process uniquement) : même
# amélioration que nexus_core_leon_bridge/requirements.txt recommande déjà
# — un vrai solveur STRIPS plutôt que le repli heuristique de
# NexusPlannerAdapter. Cf. le commentaire de ce fichier pour le comparatif
# mesuré (28 tests, 2 qui se comportent différemment sans lui).
RUN pip install --no-cache-dir pyperplan

# ── Le pont lui-même ────────────────────────────────────────────────────────
COPY nexus_core_leon_bridge/requirements.txt /app/nexus_core_leon_bridge/requirements.txt
RUN pip install --no-cache-dir -r /app/nexus_core_leon_bridge/requirements.txt

COPY nexus_core_leon_bridge /app/nexus_core_leon_bridge
WORKDIR /app/nexus_core_leon_bridge

# Validation : seulement `import bridge` (le paquet nu), jamais
# `import bridge.server` — ce dernier exécute `app = create_app()` au
# niveau module (construit un vrai NexusCore), et un build Docker doit
# rester reproductible hors-ligne, sans dépendre de l'ordre de démarrage
# des autres conteneurs. Toute cette séquence de COPY + pip install a été
# rejouée dans un venv propre hors-Docker avant publication (COPY simulés
# à l'identique + `import bridge.server` + TestClient + la suite de tests
# complète) — c'est ce qui a révélé les deux dépendances vendor ci-dessus,
# absentes d'une simple relecture du code.
RUN python -c "import bridge; import nexus_brain; import nexus_functor; print('bridge / nexus_brain / nexus_functor: OK')"

# NOTE (découverte pendant cette même simulation, pas un défaut de ce
# Dockerfile) : `docker compose exec bridge python -m pytest tests/ -v`
# donnera 38 passed + 2 skipped + **1 failed** —
# test_leon_memory_digest_populated.py::test_real_leon_checkout_and_the_leon_patch_mirror_agree.
# Ce test analyse le VRAI source TypeScript de Leon
# (Nexus_Assistant/Leon AI/leon-develop/...) pour vérifier que
# leon_patch/ reste synchronisé avec lui — un test de cohérence
# inter-dépôts au niveau développement, pas un test de correction du
# pont lui-même. Nexus_Assistant n'est délibérément pas copié dans CETTE
# image (cf. plus haut) : cet unique échec est donc attendu ici et
# n'indique aucun problème avec le pont en tant que tel.
EXPOSE 8420

# --host 0.0.0.0 n'est PAS optionnel : bridge/config.py déclare
# NEXUS_BRIDGE_HOST (défaut 127.0.0.1) mais rien dans ce dépôt ne le lit
# réellement pour démarrer uvicorn (vérifié — aucun appel à uvicorn.run()
# ni de __main__.py qui le consulterait) ; seul ce --host explicite rend
# le pont joignable depuis l'extérieur du conteneur.
CMD ["uvicorn", "bridge.server:app", "--host", "0.0.0.0", "--port", "8420"]
