#!/usr/bin/env bash
# scripts/bootstrap.sh
# ══════════════════════════════════════════════════════════════════════════════
# Bootstrap Nexus Assistant — SANS téléchargements internet
#
# Depuis l'intégration de nexus_vendor/ : 14 des 15 anciens zips racine
# (tous sauf Leon AI.zip) sont remplacés par le code source déjà extrait et
# prêt à l'emploi dans nexus_vendor/ (3 modules Python pip-installables —
# pytm, q2d, tmdd — + 11 outils natifs sous nexus_vendor/native/, à compiler
# localement avec les toolchains adéquats : Go, Java/Maven, .NET, Node/pnpm).
# Leon AI reste séparé : c'est un service Node.js autonome (serveur vocal
# HTTP sur :1337), pas une dépendance Python — il continue donc à nécessiter
# son propre dézippage + build (npm install && npm run build).
#
# Ce script :
#   1. Dézipe Leon AI vers subsystems/leon (seul zip restant à ce niveau)
#   2. Dézipe crewAI / OpenManus-RL / OpenHands vers unified_system/
#   3. Installe nexus_vendor (pytm/q2d/tmdd + deps) puis nexus_compose,
#      installe crewAI/OpenHands depuis les sources locales, ajoute
#      openmanus_rl au PYTHONPATH
#   4. Génère .env si absent
#   5. Valide que tout est importable
#
# Usage :
#   ./scripts/bootstrap.sh           # installation complète
#   ./scripts/bootstrap.sh --ci      # mode CI (pip --break-system-packages)
#   ./scripts/bootstrap.sh --check   # vérifie sans réinstaller
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
IFS=$'\n\t'

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUBSYSTEMS="${REPO_ROOT}/subsystems"
UNIFIED="${REPO_ROOT}/unified_system"
VENDOR="${REPO_ROOT}/nexus_vendor"

MODE_CI=false
MODE_CHECK=false
for arg in "$@"; do
  case "$arg" in
    --ci)    MODE_CI=true   ;;
    --check) MODE_CHECK=true;;
  esac
done

PIP_FLAGS="--quiet"
if $MODE_CI; then PIP_FLAGS="${PIP_FLAGS} --break-system-packages"; fi

# ── Utilitaires d'affichage ────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "  ${RED}✗${NC}  $*"; }
step() { echo -e "\n${BOLD}${CYAN}▶  $*${NC}"; }

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  Nexus Assistant — Bootstrap                                    ║"
echo "║  nexus_vendor (14 outils) + Leon AI + unified_system             ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

cd "$REPO_ROOT"

# ══════════════════════════════════════════════════════════════════════════════
# MODE --check : valide sans rien installer
# ══════════════════════════════════════════════════════════════════════════════
if $MODE_CHECK; then
  step "Vérification de l'état du bootstrap..."
  MISSING=()

  [[ -d "$SUBSYSTEMS/leon" ]] && ok "subsystems/leon" || { MISSING+=("leon"); warn "subsystems/leon manquant"; }

  [[ -d "$VENDOR" ]] && ok "nexus_vendor/" || { MISSING+=("nexus_vendor"); warn "nexus_vendor/ manquant — remplace 14 des 15 anciens zips"; }
  for tool in opa bearer semgrep containerlab likec4 c4interflow batfish threat_dragon codeql structurizr neo4j; do
    [[ -d "$VENDOR/native/$tool" ]] && ok "nexus_vendor/native/$tool (source, à compiler localement)" \
                                     || warn "nexus_vendor/native/$tool manquant"
  done

  for dir in crewAI openmanus_rl OpenHands; do
    [[ -d "$UNIFIED/$dir" ]] && ok "unified_system/$dir" || { MISSING+=("$dir"); warn "unified_system/$dir manquant"; }
  done
  python3 -c "import nexus_compose" 2>/dev/null && ok "nexus_compose importable" || { MISSING+=("nexus_compose"); warn "nexus_compose non installé"; }
  python3 -c "import nexus_compose, pytm" 2>/dev/null && ok "pytm importable (via nexus_vendor)" || warn "pytm non importable"
  python3 -c "import nexus_compose, q2d"  2>/dev/null && ok "q2d importable (via nexus_vendor)"  || warn "q2d non importable"
  python3 -c "import nexus_compose, tmdd" 2>/dev/null && ok "tmdd importable (via nexus_vendor)" || warn "tmdd non importable"
  if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo -e "\n${YELLOW}Bootstrap incomplet — relancer sans --check pour corriger.${NC}"
    exit 1
  fi
  echo -e "\n${GREEN}Bootstrap complet ✓${NC}"
  echo -e "${YELLOW}Note :${NC} les outils natifs (opa, bearer, semgrep, containerlab, likec4,"
  echo "  c4interflow, batfish, threat_dragon, codeql, structurizr, neo4j) ont leur"
  echo "  code source dans nexus_vendor/native/ mais nécessitent une compilation"
  echo "  locale (Go / Java-Maven / .NET / Node selon l'outil, cf. nexus_vendor/README.md)"
  echo "  pour être détectés sur le PATH. nexus_compose dégrade en mode stub sinon."
  exit 0
fi

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 1 — Extraction de Leon AI (seul zip restant à ce niveau) + vérification
#           de la présence de nexus_vendor (remplace les 14 autres zips)
# ══════════════════════════════════════════════════════════════════════════════
step "1/5 — Extraction de Leon AI + vérification de nexus_vendor/"
mkdir -p "$SUBSYSTEMS"

#
# unzip_nested ZIP OUTER_DIR DEST_NAME
#   Gère le double-nesting de GitHub : repo.zip → outer/outer/...files
#   Si OUTER_DIR == "" : extraction directe (pas de nesting)
#
unzip_nested() {
  local zip="$1"    # chemin du zip
  local outer="$2"  # nom du répertoire externe (ex: "leon-develop")
  local dest="$3"   # nom final dans subsystems/

  if [[ -d "$SUBSYSTEMS/$dest" ]]; then
    ok "$dest (déjà extrait)"
    return 0
  fi

  if [[ ! -f "$zip" ]]; then
    warn "$dest ignoré — zip introuvable : $zip"
    return 0
  fi

  local tmp; tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' RETURN

  unzip -q "$zip" -d "$tmp" 2>/dev/null || { fail "unzip échoué : $zip"; return 1; }

  # Le zip GitHub a la structure outer/outer/...
  if [[ -n "$outer" ]] && [[ -d "$tmp/$outer/$outer" ]]; then
    mv "$tmp/$outer/$outer" "$SUBSYSTEMS/$dest"
  elif [[ -n "$outer" ]] && [[ -d "$tmp/$outer" ]]; then
    mv "$tmp/$outer" "$SUBSYSTEMS/$dest"
  else
    # Extraction directe — prendre le premier répertoire présent
    local first; first=$(find "$tmp" -maxdepth 1 -mindepth 1 -type d | head -1)
    if [[ -n "$first" ]]; then
      mv "$first" "$SUBSYSTEMS/$dest"
    else
      fail "Impossible de trouver le répertoire racine dans $zip"
      return 1
    fi
  fi
  ok "$dest"
}

#         ZIP                    OUTER_DIR           DEST
unzip_nested "Leon AI.zip"       "leon-develop"      "leon"

# FIX (logique LLM unique, intégration Nexus Assistant) : Leon choisit son
# modèle via config.yml (`llm.default: "<provider>/<model>"`), pas une
# variable d'environnement — sans ce patch, Leon tournait sans lien avec le
# modèle utilisé par q2d/crewAI/OpenHands (voir docker-compose.yml pour la
# même logique appliquée au conteneur `leon`).
if [[ -d "$SUBSYSTEMS/leon" ]]; then
  LEON_DIR="$SUBSYSTEMS/leon"
  [[ -f "$LEON_DIR/config.yml" ]] || cp "$LEON_DIR/config.sample.yml" "$LEON_DIR/config.yml" 2>/dev/null
  if [[ -f "$LEON_DIR/config.yml" ]]; then
    NEXUS_LLM_PROVIDER="${NEXUS_LLM_PROVIDER:-openai}"
    NEXUS_LLM_MODEL="${NEXUS_LLM_MODEL:-gpt-4o-mini}"
    sed -i "s|^\([[:space:]]*default:[[:space:]]*\).*|\1\"${NEXUS_LLM_PROVIDER}/${NEXUS_LLM_MODEL}\"|" \
      "$LEON_DIR/config.yml"
    PROVIDER_UPPER=$(echo "$NEXUS_LLM_PROVIDER" | tr '[:lower:]' '[:upper:]')
    if [[ -n "${NEXUS_LLM_API_KEY:-}" ]]; then
      # dotenv ne remplace pas process.env existant, mais Leon lit aussi son
      # propre .env — on écrit les deux pour couvrir usage direct (npm start)
      # et usage via variable d'environnement exportée par l'appelant.
      grep -q "^LEON_${PROVIDER_UPPER}_API_KEY=" "$LEON_DIR/.env" 2>/dev/null \
        && sed -i "s|^LEON_${PROVIDER_UPPER}_API_KEY=.*|LEON_${PROVIDER_UPPER}_API_KEY=${NEXUS_LLM_API_KEY}|" "$LEON_DIR/.env" \
        || echo "LEON_${PROVIDER_UPPER}_API_KEY=${NEXUS_LLM_API_KEY}" >> "$LEON_DIR/.env"
    fi
    ok "leon/config.yml patché → llm.default = \"${NEXUS_LLM_PROVIDER}/${NEXUS_LLM_MODEL}\""
  fi
fi

# nexus_vendor/ remplace 14 des 15 anciens zips (tout sauf Leon AI) :
#   query2diagram, pytm, tmdd (→ Python pip-installables)
#   opa, bearer, containerlab, likec4, semgrep, codeql, Batfish, neo4j,
#   threat-dragon, dsl (→ Structurizr), C4InterFlow (→ nexus_vendor/native/*)
if [[ -d "$VENDOR" ]]; then
  ok "nexus_vendor/ présent — 14 outils tiers déjà vendorisés (pas de dézippage requis)"
else
  fail "nexus_vendor/ absent ! Les phases pytm/q2d/tmdd et les outils natifs ne seront pas disponibles."
  warn "→ vérifier que nexus_vendor/ a bien été placé à la racine du projet, à côté de nexus_compose/"
fi

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 2 — Extraction unified_system (pas de double-nesting)
# ══════════════════════════════════════════════════════════════════════════════
step "2/5 — Extraction unified_system/ (crewAI, OpenManus-RL, OpenHands)"

unzip_direct() {
  local zip="$1"
  local dest="$2"

  if [[ -d "$dest" ]]; then
    ok "$(basename "$dest") (déjà extrait)"
    return 0
  fi

  if [[ ! -f "$zip" ]]; then
    warn "$(basename "$dest") ignoré — zip introuvable : $zip"
    return 0
  fi

  local tmp; tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' RETURN

  unzip -q "$zip" -d "$tmp" 2>/dev/null || { fail "unzip échoué : $zip"; return 1; }

  # Prendre le premier (et unique) dossier extrait
  local root; root=$(find "$tmp" -maxdepth 1 -mindepth 1 | head -1)
  if [[ -d "$root" ]]; then
    mv "$root" "$dest"
  else
    # Le zip déverse ses fichiers directement sans dossier racine
    mkdir -p "$dest"
    mv "$tmp"/* "$dest/" 2>/dev/null || true
  fi
  ok "$(basename "$dest")"
}

unzip_direct "$UNIFIED/crewAI.zip"       "$UNIFIED/crewAI"
unzip_direct "$UNIFIED/OpenManus-RL.zip" "$UNIFIED/openmanus_rl"
unzip_direct "$UNIFIED/OpenHands.zip"    "$UNIFIED/OpenHands"

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 3 — Installation des packages Python depuis les sources locales
# ══════════════════════════════════════════════════════════════════════════════
step "3/5 — Installation pip depuis sources locales"

pip_install_local() {
  local label="$1"
  local path="$2"
  local fallback="${3:-}"

  if [[ ! -d "$path" ]]; then
    if [[ -n "$fallback" ]]; then
      warn "$label introuvable ($path) — fallback PyPI : pip install $fallback"
      pip install $PIP_FLAGS "$fallback" || fail "Échec de l'installation de $label"
    else
      warn "$label ignoré (répertoire absent)"
    fi
    return 0
  fi

  echo -n "  Installation $label depuis $path ... "
  # FIX (suite à un test réel, intégration Nexus Assistant) : `pip install -e`
  # peut réussir (exit 0) tout en installant un paquet non-importable —
  # observé avec crewAI 1.14.7a2 (import cassé : crewai.auth.token absent
  # de cet export local). L'ancienne version ne vérifiait QUE le code de
  # sortie de pip, donc le repli PyPI ne se déclenchait jamais dans ce cas.
  # On vérifie maintenant `import $label` après coup, pas seulement pip.
  if pip install $PIP_FLAGS -e "$path" 2>/tmp/pip_err \
     && python3 -c "import ${label}" 2>/tmp/pip_import_err; then
    ok ""
  else
    if [[ -n "$fallback" ]]; then
      echo ""
      warn "Échec local (install et/ou import), fallback PyPI : pip install $fallback"
      # FIX : un `pip install $fallback` simple voit souvent l'install
      # editable cassée comme "already satisfied" (même métadonnée de
      # version) et ne fait RIEN — observé avec crewai==1.14.7a2. On
      # désinstalle explicitement avant de réinstaller depuis PyPI.
      pip uninstall -y "$label" >/dev/null 2>&1 || true
      pip install $PIP_FLAGS --force-reinstall --no-deps "$fallback" \
        || { fail "Impossible d'installer $label (local + PyPI)"; cat /tmp/pip_err >&2; }
      pip install $PIP_FLAGS "$fallback" >/dev/null 2>&1 || true  # dépendances
      python3 -c "import ${label}" 2>/dev/null \
        && ok "$label importable après repli PyPI" \
        || warn "$label toujours non importable après repli PyPI — vérifier manuellement"
    else
      fail ""
      cat /tmp/pip_err /tmp/pip_import_err >&2 2>/dev/null
    fi
  fi
}

# Packages Python purs — désormais fournis par nexus_vendor (plus besoin des
# anciens dossiers subsystems/pytm, subsystems/query2diagram, subsystems/tmdd
# ni de leurs zips). L'installation de nexus_vendor résout aussi ses propres
# dépendances (pydantic, networkx, pyyaml, jinja2).
pip_install_local "nexus_vendor" "$VENDOR" ""

# crewAI — FIX (suite à un test réel) : la racine du zip est un *workspace*
# uv (pyproject.toml sans [project]/[build-system]) ; `pip install -e` dessus
# "réussit" silencieusement en installant un paquet fantôme nommé "UNKNOWN"
# (aucun module `crewai` importable, et comme pip rapporte succès, le repli
# PyPI ne se déclenche jamais). Le vrai package installable vit dans lib/crewai/.
pip_install_local "crewai"   "$UNIFIED/crewAI/lib/crewai" "crewai"

# FIX (suite à un test réel) : lib/crewai/ contient une version de
# développement (1.14.7a2) dont crewai/hooks/llm_hooks.py importe
# crewai.auth.token, un fichier ABSENT de cet export → `import crewai`
# échoue et pip_install_local bascule sur le repli PyPI (crewai stable). Mais
# le repli PyPI ne contient PAS crewai/tools/openhands_tool.py — c'est VOTRE
# pont personnalisé crewAI ↔ OpenHands (nécessaire à codegen.unified_system).
# On le greffe systématiquement sur l'installation active de crewai, qu'elle
# vienne du zip local ou de PyPI.
CREWAI_PKG_DIR=$(python3 -c "import crewai, os; print(os.path.dirname(crewai.__file__))" 2>/dev/null || true)
CUSTOM_TOOL="$UNIFIED/crewAI/lib/crewai/src/crewai/tools/openhands_tool.py"
if [[ -n "$CREWAI_PKG_DIR" ]] && [[ -f "$CUSTOM_TOOL" ]]; then
  cp "$CUSTOM_TOOL" "$CREWAI_PKG_DIR/tools/openhands_tool.py"
  python3 -c "from crewai.tools.openhands_tool import OpenHandsTask" 2>/dev/null \
    && ok "crewai.tools.openhands_tool (greffé, pont vers OpenHands)" \
    || warn "greffe openhands_tool.py effectuée mais import échoué — vérifier crewai.tools.base_tool"
else
  warn "crewai non installé ou openhands_tool.py introuvable — greffe ignorée"
fi

# OpenHands — pyproject.toml à la racine (nom PyPI réel : openhands-ai)
# ATTENTION : dépendances très lourdes (PyTorch, libs GPU) — installation
# longue / gourmande en RAM. Conçu pour tourner comme service HTTP séparé
# (docker compose --profile fullstack) plutôt que d'être pip-installé dans
# l'image légère ; cf. commentaire dans le Dockerfile, stage unified-deps.
pip_install_local "openhands" "$UNIFIED/OpenHands"       "openhands-ai"

# OpenManus-RL — namespace package sans pyproject.toml
# → ajout au sys.path via fichier .pth dans site-packages
OPENMANUS_SRC="$UNIFIED/openmanus_rl"
if [[ -d "$OPENMANUS_SRC" ]]; then
  SITE_PKG=$(python3 -c "import site; print(site.getsitepackages()[0])" 2>/dev/null \
             || python3 -c "import sys; print(next(p for p in sys.path if 'site-packages' in p))")
  echo "$UNIFIED" > "$SITE_PKG/openmanus_rl.pth"
  ok "openmanus_rl (PYTHONPATH via .pth)"
else
  warn "openmanus_rl non extrait — bridge.py ne pourra pas importer OpenManus-RL"
fi

# Package principal nexus_compose — son __init__.py ajoute automatiquement
# nexus_vendor/ à sys.path au chargement, exposant pytm/q2d/tmdd en top-level
# sans configuration supplémentaire (cf. nexus_compose/__init__.py).
echo -n "  Installation nexus_compose[dev] ... "
pip install $PIP_FLAGS -e "${REPO_ROOT}[dev]" && ok "" || fail ""

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 4 — Génération de l'environnement .env si absent
# ══════════════════════════════════════════════════════════════════════════════
step "4/5 — Génération du fichier .env"

ENV_FILE="${REPO_ROOT}/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'ENVEOF'
# Nexus Compose — Variables d'environnement
# Généré automatiquement par scripts/bootstrap.sh
# Renseigne les valeurs manquantes (*)

# ── Infrastructure ──────────────────────────────────────────────────────────
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=nexuscompose

OPA_URL=http://localhost:8181
THREAT_DRAGON_URL=http://localhost:3000
BATFISH_HOST=localhost

# ── Unified System (crewAI + OpenHands + OpenManus-RL) ──────────────────────
OH_BASE_URL=http://localhost:3000      # URL du serveur OpenHands
OH_TOKEN=                              # Bearer token (vide si auth off)
OPENAI_API_KEY=                        # * Clé OpenAI (requis pour crewAI)
CREWAI_LLM_MODEL=gpt-4o-mini          # Modèle LLM du crew
RL_MAX_STEPS=1000
RL_BATCH_SIZE=4

# ── Leon AI ─────────────────────────────────────────────────────────────────
LEON_LANG=fr-FR

# ── GitHub (optionnel, pour Threat Dragon) ──────────────────────────────────
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
ENVEOF
  ok ".env créé"
else
  ok ".env existant conservé"
fi

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 5 — Validation finale
# ══════════════════════════════════════════════════════════════════════════════
step "5/5 — Validation"

validate_import() {
  local pkg="$1"
  if python3 -c "import $pkg" 2>/dev/null; then
    ok "$pkg importable"
  else
    warn "$pkg non importable — certaines fonctionnalités seront désactivées"
  fi
}

validate_import nexus_compose
python3 -c "import nexus_compose, pytm" 2>/dev/null && ok "pytm importable (via nexus_vendor)" || warn "pytm non importable"
python3 -c "import nexus_compose, q2d"  2>/dev/null && ok "q2d importable (via nexus_vendor)"  || warn "q2d non importable"
python3 -c "import nexus_compose, tmdd" 2>/dev/null && ok "tmdd importable (via nexus_vendor)" || warn "tmdd non importable"
validate_import crewai
validate_import openhands
# openmanus_rl peut nécessiter des dépendances supplémentaires
python3 -c "import sys; sys.path.insert(0,'$UNIFIED'); import openmanus_rl" 2>/dev/null \
  && ok "openmanus_rl importable" \
  || warn "openmanus_rl non importable (les dépendances RL peuvent manquer)"

echo ""
echo -e "${YELLOW}Outils natifs (opa, bearer, semgrep, containerlab, likec4, c4interflow,"
echo -e "batfish, threat_dragon, codeql, structurizr, neo4j) :${NC}"
echo "  Code source déjà présent dans nexus_vendor/native/<outil>/ — à compiler"
echo "  localement (Go / Java-Maven / .NET / Node selon l'outil) pour être détectés"
echo "  sur le PATH. Voir nexus_vendor/README.md pour la commande de build exacte"
echo "  de chaque outil. Sans binaire compilé, nexus_compose dégrade proprement en"
echo "  mode stub pour les nœuds correspondants (aucun crash)."

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗"
echo -e "║  Bootstrap terminé ✓                                ║"
echo -e "╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Pour lancer le système complet :"
echo "    docker compose up --build -d                 # tous les services"
echo "    docker compose --profile fullstack up -d     # + OpenHands"
echo "  Ou directement :"
echo "    ./scripts/launch.sh"
echo ""
