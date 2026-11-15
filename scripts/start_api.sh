#!/usr/bin/env bash
# scripts/start_api.sh
# ══════════════════════════════════════════════════════════════════════════════
# Démarre l'API HTTP (Nexus_Assistant/api/, Étape 1 du prompt de fusion) —
# le service `app` de docker-compose.yml reste volontairement en
# `tail -f /dev/null` par défaut (pour ne pas casser les workflows CLI déjà
# documentés : `docker compose exec app python -m pytest test/ -v`, etc.),
# donc l'API se lance à la demande via ce script plutôt qu'automatiquement.
#
# Usage :
#   depuis l'hôte  : docker compose exec app scripts/start_api.sh
#   ou en tâche de fond : docker compose exec -d app scripts/start_api.sh
#   depuis le conteneur : ./scripts/start_api.sh
#   en local, hors Docker : ./scripts/start_api.sh (utilise 127.0.0.1)
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

HOST="${NEXUS_API_HOST:-0.0.0.0}"
PORT="${NEXUS_API_PORT:-8000}"

echo "Démarrage de l'API Nexus Assistant sur ${HOST}:${PORT}..."
exec uvicorn api.main:app --host "$HOST" --port "$PORT"
