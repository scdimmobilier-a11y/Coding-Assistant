# ══════════════════════════════════════════════════════════════════════════════
# nexus-ui/Dockerfile — interface Nexus Assistant (Network / Coding / Security /
# Registry)
#
# Contexte de build = ce dossier (contrairement à nexus_core_leon_bridge/
# Dockerfile, cette image n'a besoin d'aucun code d'un dépôt frère — elle ne
# parle à Nexus_Assistant/api et au pont qu'en HTTP depuis le NAVIGATEUR de
# l'utilisateur, jamais depuis l'intérieur de ce conteneur).
# ══════════════════════════════════════════════════════════════════════════════

FROM node:24-slim

ENV NODE_ENV=development

WORKDIR /app

# npm install AU MOMENT DU BUILD — contrairement au service `leon` de
# docker-compose.yml (qui diffère délibérément pnpm install au démarrage du
# conteneur, à cause d'addons natifs node-gyp qui peuvent ne pas correspondre
# entre l'architecture de build et celle d'exécution, cf. son propre
# commentaire). Cette raison ne s'applique pas ici : les dépendances de
# nexus-ui (react, vite, lucide-react, tailwindcss...) sont du JS/TS pur,
# aucun addon natif. Les figer dans l'image au build est donc le choix plus
# simple et plus standard : build reproductible, démarrage de conteneur
# instantané plutôt que 2-3 minutes d'install à chaque `docker compose up`.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# --host 0.0.0.0 : le serveur de dev Vite n'écoute que sur localhost par
# défaut (vite.config.ts fixe server.port mais pas server.host) —
# injoignable depuis l'extérieur du conteneur sans ce drapeau. Passé en
# ligne de commande plutôt qu'ajouté à vite.config.ts, pour laisser le
# workflow `npm run dev` hors-Docker (documenté dans le README) strictement
# inchangé.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
