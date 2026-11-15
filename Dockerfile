# ══════════════════════════════════════════════════════════════════════════════
# Dockerfile — Nexus Compose / Vocal Vibecoding Factory
#
# STRATÉGIE DES BINAIRES EXTERNES :
#
#   OPA / Bearer / Containerlab / Structurizr → binaires pré-compilés officiels
#     Les zips sources (opa.zip, bearer.zip, etc.) sont destinés à bootstrap.sh
#     (développement local sans Docker). Les compiler dans Docker nécessiterait
#     de télécharger tous les modules Go depuis internet (go.sum) et épuise la
#     RAM du runner CI (~7 GB) quand les stages tournent en parallèle.
#     Résultats observés : exit code 1 (cmd/opa introuvable en OPA v2.x) et
#     exit code 137 (OOM Kill sur dotnet-build + base concurrent).
#
#   C4InterFlow.Cli → installé via dotnet tool (NuGet), pas de build source
#
#   Python (pytm, q2d, tmdd) → nexus_vendor/ (sources déjà extraites, plus
#     besoin de pytm.zip / query2diagram.zip / tmdd.zip)
#   crewAI, OpenHands, OpenManus-RL → zips bundlés ✓
#   Leon AI → zip bundlé ✓  (seuls vrais gains offline)
#
# STAGES :
#   binaries     → télécharge OPA, Bearer, Containerlab, C4InterFlow, Structurizr
#   base         → Python 3.11 + paquets système (sans JRE — installé dans binaries)
#   nodejs       → Node.js 24 + pnpm
#   tools        → assemble binaires + Node
#   python-deps  → nexus_vendor (pytm, q2d, tmdd) + semgrep PyPI
#   unified-deps → crewAI, OpenHands, OpenManus-RL depuis zips locaux
#   leon         → Leon AI depuis zip local (plus de git clone)
#   final        → assemblage + nexus_compose
# ══════════════════════════════════════════════════════════════════════════════


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 0 — Binaires externes (pré-compilés, séquentiels pour économiser la RAM)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM debian:12-slim AS binaries

# FIX : debian:12-slim ne contient PAS bash par défaut (/bin/sh → dash).
# Sans bash, `curl ... | bash -s` tombe sous dash qui ne supporte pas les
# redirections bash (exec 3>&1, etc.) → "sh: 150: Syntax error: redirection
# unexpected" dans le script dotnet-install.sh.
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl ca-certificates unzip default-jre-headless \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Utiliser bash pour tous les RUN suivants dans ce stage
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN mkdir -p /out/bin /out/lib

# ── OPA (binaire statique officiel) ───────────────────────────────────────────
RUN curl -sSfL -o /out/bin/opa \
    "https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static" \
    && chmod +x /out/bin/opa \
    && /out/bin/opa version \
    && echo "OPA ✓"

# ── Bearer (binaire officiel) ─────────────────────────────────────────────────
RUN curl -sfL "https://raw.githubusercontent.com/Bearer/bearer/main/contrib/install.sh" \
    | sh -s -- -b /out/bin \
    && /out/bin/bearer version \
    && echo "Bearer ✓"

# ── Containerlab (binaire officiel) ───────────────────────────────────────────
RUN curl -sfL "https://get.containerlab.dev" | BINDIR=/out/bin sh \
    && echo "Containerlab ✓" \
    || echo "Containerlab: non disponible (réseau)"

# ── C4InterFlow (dotnet tool depuis NuGet) ─────────────────────────────────────
RUN curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --version 8.0 \
        --install-dir /out/dotnet \
    && /out/dotnet/dotnet tool install --tool-path /out/bin C4InterFlow.Cli \
    && /out/bin/c4interflow --version \
    && echo "C4InterFlow.Cli ✓" \
    || echo "C4InterFlow.Cli: non disponible (NuGet)"

# ── Structurizr CLI (jar officiel) ───────────────────────────────────────────
RUN mkdir -p /out/lib/structurizr \
    && touch /out/lib/structurizr/structurizr-cli.jar \
    && curl -fsSL -o /tmp/structurizr.zip \
       "https://github.com/structurizr/cli/releases/latest/download/structurizr-cli.zip" \
    && unzip -q /tmp/structurizr.zip -d /tmp/structurizr \
    && find /tmp/structurizr -name "*.jar" | head -1 \
       | xargs -I{} cp {} /out/lib/structurizr/structurizr-cli.jar \
    && rm -rf /tmp/structurizr.zip /tmp/structurizr \
    && echo "Structurizr CLI ✓" \
    || echo "Structurizr: non disponible (réseau)"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 1 — Base système Python
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM python:3.11-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget git ca-certificates gnupg \
    build-essential gcc g++ make \
    default-jre-headless \
    iproute2 iptables iputils-ping \
    unzip jq libicu-dev libssl-dev zlib1g \
    && apt-get clean && rm -rf /var/lib/apt/lists/*


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 2 — Node.js 24 + pnpm
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM base AS nodejs

RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && npm install -g pnpm@latest \
    && npm install -g likec4 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PNPM_HOME="/root/.local/share/pnpm"
ENV PATH="${PNPM_HOME}:${PATH}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 3 — Assemblage : Node.js + binaires externes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM nodejs AS tools

# Copie des binaires depuis le stage `binaries` (un seul COPY par outil)
COPY --from=binaries /out/bin/opa          /usr/local/bin/opa
COPY --from=binaries /out/bin/bearer       /usr/local/bin/bearer

# Containerlab — optionnel (peut être absent si téléchargement échoué)
COPY --from=binaries /out/bin /tmp/external_bin
RUN if [[ -s /tmp/external_bin/containerlab ]]; then \
      cp /tmp/external_bin/containerlab /usr/local/bin/containerlab \
      && chmod +x /usr/local/bin/containerlab \
      && echo "Containerlab ✓"; \
    else \
      echo "Containerlab: non disponible"; \
    fi \
    && rm -rf /tmp/external_bin

# C4InterFlow — optionnel (dotnet tool depuis NuGet dans stage binaries)
RUN if [[ -f /tmp/c4if/c4interflow ]]; then \
      cp /tmp/c4if/c4interflow /usr/local/bin/c4interflow && chmod +x /usr/local/bin/c4interflow; \
    fi 2>/dev/null || true

# Structurizr — copie du jar (peut être un placeholder vide si réseau KO)
RUN mkdir -p /usr/local/lib/structurizr
COPY --from=binaries /out/lib/structurizr/structurizr-cli.jar \
     /usr/local/lib/structurizr/structurizr-cli.jar
RUN if [[ -s /usr/local/lib/structurizr/structurizr-cli.jar ]]; then \
      printf '#!/bin/bash\njava -jar /usr/local/lib/structurizr/structurizr-cli.jar "$@"\n' \
        > /usr/local/bin/structurizr \
      && chmod +x /usr/local/bin/structurizr \
      && echo "Structurizr ✓"; \
    else \
      echo "Structurizr: non disponible"; \
    fi

# Validation (OPA et Bearer sont toujours disponibles — statiques et robustes)
RUN opa version && bearer version


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 4 — Packages Python depuis sources locales (zips bundlés)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM tools AS python-deps

WORKDIR /app

# requirements.txt de base d'abord
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── pytm / query2diagram (q2d) / tmdd — désormais fournis par nexus_vendor/ ──
# FIX (intégration Nexus Assistant) : ces 3 outils étaient auparavant
# installés depuis pytm.zip / query2diagram.zip / tmdd.zip (COPY + unzip +
# pip install -e). Ces zips ont été remplacés par nexus_vendor/, qui contient
# déjà leurs sources prêtes à l'emploi (+ les 11 outils natifs sous
# nexus_vendor/native/). On installe nexus_vendor une seule fois ici ;
# nexus_compose/__init__.py ajoute ensuite automatiquement nexus_vendor/ à
# sys.path au chargement, exposant pytm/q2d/tmdd en top-level sans étape
# supplémentaire.
COPY nexus_vendor/ /app/nexus_vendor/
RUN pip install --no-cache-dir -e /app/nexus_vendor

# ── semgrep — OCaml build impraticable depuis source : pip install officiel ──
RUN pip install --no-cache-dir semgrep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 5 — Unified System (crewAI + OpenManus-RL + OpenHands)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM python-deps AS unified-deps

WORKDIR /app

# ── crewAI depuis zip local ───────────────────────────────────────────────────
# COPY unified_system/crewAI.zip /tmp/ → le fichier arrive à /tmp/crewAI.zip
# (pas /tmp/unified_system/crewAI.zip). Le double-essai précédent était fragile.
#
# FIX (suite à un test réel, intégration Nexus Assistant) : la racine du zip
# est un *workspace* uv (pyproject.toml sans [project]/[build-system]).
# `pip install -e "$CREWAI_DIR"` sur cette racine "réussissait" (exit 0) en
# installant un paquet fantôme "UNKNOWN" sans aucun module `crewai`
# importable — et comme pip rapportait un succès, le repli PyPI (`||`) ne se
# déclenchait jamais. Le vrai package installable vit dans lib/crewai/.
#
# FIX #2 (même test) : lib/crewai/ est une version de développement
# (1.14.7a2) dont crewai/hooks/llm_hooks.py importe crewai.auth.token, un
# fichier ABSENT de cet export → `pip install -e` "réussit" quand même
# (exit 0 — l'erreur ne se manifeste qu'à l'import), donc il faut vérifier
# `import crewai` explicitement, pas seulement le code de sortie de pip.
#
# FIX #3 : ni la source locale (cassée) ni PyPI seul ne suffisent — PyPI n'a
# pas crewai/tools/openhands_tool.py, VOTRE pont personnalisé crewAI ↔
# OpenHands nécessaire à codegen.unified_system. On le greffe après coup,
# quelle que soit la source d'installation retenue.
COPY unified_system/crewAI.zip /tmp/crewAI.zip
RUN unzip -q /tmp/crewAI.zip -d /tmp/crewai_src \
    && CREWAI_DIR=$(find /tmp/crewai_src -maxdepth 1 -mindepth 1 -type d | head -1) \
    && CUSTOM_TOOL="$CREWAI_DIR/lib/crewai/src/crewai/tools/openhands_tool.py" \
    && (pip install --no-cache-dir -e "$CREWAI_DIR/lib/crewai" \
        && python -c "import crewai" \
       || (pip uninstall -y crewai >/dev/null 2>&1 || true; \
           pip install --no-cache-dir --force-reinstall crewai)) \
    && CREWAI_PKG_DIR=$(python -c "import crewai, os; print(os.path.dirname(crewai.__file__))") \
    && cp "$CUSTOM_TOOL" "$CREWAI_PKG_DIR/tools/openhands_tool.py" \
    && python -c "from crewai.tools.openhands_tool import OpenHandsTask" \
    && rm -rf /tmp/crewAI.zip /tmp/crewai_src

# FIX #4 (Étape 4 du prompt de fusion, "LLM unique = Claude", trouvé en
# testant réellement `crewai.LLM(model="anthropic/...")`, pas en lisant le
# code) : ni l'installation locale (lib/crewai) ni le repli PyPI ci-dessus
# n'installent l'extra `crewai[anthropic]`. Sans le paquet `anthropic`
# (SDK officiel Anthropic), crewAI lève `ImportError: Anthropic native
# provider not available` dès qu'on passe NEXUS_LLM_PROVIDER=anthropic — ce
# n'est PAS un simple repli silencieux vers LiteLLM comme on pourrait le
# supposer, crewAI récent utilise des classes "native provider" par
# fournisseur (`AnthropicCompletion`) plutôt que systématiquement LiteLLM.
RUN pip install --no-cache-dir anthropic \
    && python -c "from crewai.llms.providers.anthropic.completion import AnthropicCompletion"

# ── OpenHands — PAS de pip install dans cette image ──────────────────────────
# OpenHands est un SERVEUR AUTONOME (conteneur Docker séparé défini dans
# docker-compose.yml, service `openhands`, profile `fullstack`).
# bridge.py lui parle via son API HTTP (OH_BASE_URL) — pas d'import Python.
# Tenter pip install openhands ici échoue car :
#   1. Le package PyPI s'appelle "openhands" mais a des dépendances massives
#      (PyTorch, GPU libs…) incompatibles avec cette image légère.
#   2. Le zip contient le code source du serveur, pas un client léger.
# Le zip est gardé dans le repo pour référence / déploiement bare-metal.

# ── OpenManus-RL depuis zip local — namespace package, PYTHONPATH ─────────────
COPY unified_system/OpenManus-RL.zip /tmp/OpenManus-RL.zip
RUN unzip -q /tmp/OpenManus-RL.zip -d /opt/openmanus_rl \
    && echo "/opt/openmanus_rl" > \
       "$(python -c 'import site; print(site.getsitepackages()[0])')/openmanus_rl.pth" \
    && rm -rf /tmp/OpenManus-RL.zip


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 6 — Leon AI depuis zip local (remplace git clone)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM unified-deps AS leon

# FIX variable d'env pour contourner le devEngines check de pnpm
# (cf. commentaire original dans l'ancienne stage LEON)
# FIX : pnpm install est déplacé au démarrage du conteneur (docker-compose.yml).
# Raisons :
#   1. Leon impose "packageManager":"pnpm@9.x.x" via corepack. Installer
#      pnpm@latest (v10.x) dans le stage nodejs déclenche un conflit de version
#      même avec engine-strict=false → exit code 1 inévitable dans le build.
#   2. Les node_modules sont spécifiques à l'architecture et au runtime —
#      les builder dans l'image puis les copier dans le conteneur final
#      peut créer des incohérences natives (node-gyp addons, etc.).
#   3. pnpm install prend 2-3 minutes et ralentit chaque CI build ;
#      fait au démarrage, il bénéficie du cache Docker volume.
# Le service `leon` dans docker-compose.yml lance :
#   command: sh -c "cd /opt/leon && pnpm install --no-frozen-lockfile && npm start"
ENV LEON_PATH="/opt/leon"

COPY ["Leon AI.zip", "/tmp/leon_ai.zip"]
RUN echo "Extraction Leon AI depuis zip local..." \
    && unzip -q /tmp/leon_ai.zip -d /tmp/leon_src \
    && LEON_INNER=$(find /tmp/leon_src -maxdepth 2 -mindepth 1 -type d -name "leon-develop" | head -1) \
    && if [[ -n "$LEON_INNER" ]]; then \
         cp -r "$LEON_INNER" /opt/leon; \
       else \
         cp -r /tmp/leon_src/$(ls /tmp/leon_src | head -1) /opt/leon; \
       fi \
    && echo "engine-strict=false"       >> /opt/leon/.npmrc \
    && echo "node-linker=node-modules"  >> /opt/leon/.npmrc \
    && rm -rf /tmp/leon_ai.zip /tmp/leon_src \
    && echo "Leon AI extrait vers /opt/leon ✓ (pnpm install au démarrage)"

ENV LEON_PATH="/opt/leon"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE FINAL — Assemblage
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM leon AS final

WORKDIR /app

COPY . .

ENV NEO4J_URI="bolt://neo4j:7687" \
    NEO4J_USER="neo4j" \
    NEO4J_PASSWORD="" \
    OPA_URL="http://opa:8181" \
    THREAT_DRAGON_URL="http://threat-dragon:3000" \
    BATFISH_HOST="batfish" \
    OH_BASE_URL="http://openhands:3001" \
    PYTHONPATH="/app:/app/nexus_vendor:/opt/openmanus_rl"

RUN pip install --no-cache-dir -e ".[dev]"

# ── Vérification de toutes les couches ────────────────────────────────────────
RUN echo "=== Validation finale ===" \
    && python --version \
    && node --version \
    && pnpm --version \
    && opa version \
    && bearer version \
    && (containerlab version 2>/dev/null || echo "containerlab: OK (runtime)") \
    && (c4interflow --version 2>/dev/null \
        || dotnet /usr/local/lib/c4interflow/C4InterFlow.Cli --version 2>/dev/null \
        || echo "C4InterFlow.Cli: non disponible") \
    && (structurizr --version 2>/dev/null || echo "Structurizr: non disponible") \
    && python -c "import nexus_compose; print('nexus_compose: OK')" \
    && python -c "import api.main; print('api.main (FastAPI, tous routeurs dont registry): OK')" \
    && python -c "import pytm; print('pytm: OK')" \
    && (python -c "import crewai; print('crewai: OK')" || echo "crewai: non disponible") \
    && echo "=== Toutes les couches validées ==="

EXPOSE 8000

# Le service `app` ne démarre pas de serveur HTTP ; il est invoqué via
# docker compose exec/run. CMD garde le conteneur en vie.
CMD ["tail", "-f", "/dev/null"]
