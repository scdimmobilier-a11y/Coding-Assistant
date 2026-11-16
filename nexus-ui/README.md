# Nexus Assistant — UI

Implémentation React + TypeScript + Tailwind de la maquette fournie :
conversation (voix/texte), suivi du pipeline en 10 phases, et vue
multi-onglets (Network / Coding / Security) centrée sur le diagramme C4.

## Démarrer

```bash
npm install
npm run dev       # http://localhost:5173
```

```bash
npm run build      # build de production dans dist/
npm run preview    # sert le build de production
```

Stack : Vite, React 18, TypeScript strict, Tailwind CSS, icônes
[lucide-react](https://lucide.dev). Aucune dépendance à un framework
serveur — ce paquet est un frontend statique déployable tel quel.

## Structure

```
src/
├── App.tsx                    layout 2 colonnes + panneaux latéraux (phase / nœud) + dialog API
├── types.ts                   types partagés, alignés sur le vocabulaire nexus_compose
├── data/mockPipeline.ts       données de démo (169 nœuds, branches, findings, historique)
├── lib/
│   ├── apiConnection.ts       testApiConnection() — vrai appel réseau avec timeout
│   ├── pipelineApi.ts         client GET /api/pipeline/* (Nexus_Assistant)
│   ├── providersApi.ts        client GET/POST/PATCH /api/providers/* (Nexus_Assistant)
│   └── registryApi.ts         client GET /registry/full (le PONT — pas Nexus_Assistant, cf. plus bas)
└── components/
    ├── Header.tsx             logo, statut, avatar, bouton "···"
    ├── HeaderMenu.tsx         menu déroulant : nouvelle discussion / historique / connexion API
    ├── ApiConnectionDialog.tsx pop-up de connexion API (URL + Connecter/Annuler)
    ├── ApiStatusToast.tsx     bulle "API connectée"/"non connectée", auto-fermée après 5s
    ├── ConversationPanel.tsx  fil de discussion + saisie
    ├── PipelinePanel.tsx      grille des 10 phases, statut pending/running/done/failed
    ├── PhaseDetailPanel.tsx   contenu du panneau : nœuds d'une phase + relance
    ├── TabBar.tsx             Network / Coding / Security / Registry + badges de comptage
    ├── SidePanel.tsx          panneau latéral générique (overlay + Échap)
    ├── NodeDetailPanel.tsx    métadonnées d'un nœud C4 + menaces liées + drill-down
    ├── RegistryNodeDetail.tsx métadonnées d'un nœud du registre (NodeMeta) + arêtes touchantes
    ├── Breadcrumb.tsx         fil d'Ariane Système / Conteneurs / Composant
    ├── diagram/
    │   ├── tones.ts               classes Tailwind par teinte de nœud
    │   ├── NodeBox.tsx            rectangle C4 partagé, cliquable
    │   ├── SystemDiagram.tsx      niveau Système
    │   ├── ContainerDiagram.tsx   niveau Conteneur (vue par défaut)
    │   └── ComponentDiagram.tsx   niveau Composant (drill-down)
    └── views/
        ├── NetworkView.tsx    orchestre les 3 niveaux + fil d'Ariane + pastilles outils
        ├── CodingView.tsx     branches parallèles + compteur de dette de revue
        ├── SecurityView.tsx   findings filtrables par sévérité + accessibilité Neo4j
        └── RegistryView.tsx   explorateur du registre unifié — recherche, filtres, détail (D5.1)
```

Tout composant qui affiche des données dynamiques les reçoit en props —
rien n'est codé en dur en dehors de `data/mockPipeline.ts`. Ce fichier
est le seul point à remplacer pour brancher de vraies données.

**Header — menu "···" (historique, nouvelle discussion, connexion API).**
Le bouton à trois points ouvre `HeaderMenu` : "Nouvelle discussion" archive
d'abord la conversation en cours dans l'historique (`archiveCurrentConversation`
dans `App.tsx`) puis réinitialise le fil — l'historique n'a **aucune limite** :
`setHistory` ajoute une entrée en tête de liste à chaque appel, sans plafond
ni troncature ; le conteneur `max-h-56 overflow-y-auto` de `HeaderMenu` rend
juste la liste défilable, il ne masque ni ne supprime rien au-delà d'une
certaine taille. Sélectionner une entrée de l'historique charge un message
annonçant la conversation choisie (le transcript complet reste à brancher
sur un vrai backend). "Connexion API" ouvre `ApiConnectionDialog`, qui a
deux façons de fermer sans rien tenter : le bouton "Annuler" et le bouton
"X" en haut à droite (comportement standard de pop-up, présent dès la
première version de `SidePanel` mais qu'il manquait ici). "Connecter"
effectue un vrai appel réseau (`fetch` avec timeout de 5 s, pas une
simulation) vers l'URL saisie ; le résultat s'affiche ensuite pendant 5
secondes via `ApiStatusToast` — "API connectée" en vert ou "API non
connectée" en rouge. **Hypothèse à valider** : j'ai interprété "entrer une
API" comme "entrer l'URL de l'API" plutôt qu'une clé, car c'est la seule
donnée permettant un test de connexion réel ; si vous vouliez un champ de
clé d'authentification en plus, dites-le et je l'ajoute.

## Fonctionnalités ajoutées (itération 2)

**Pipeline — état d'échec et détail par phase.** Chaque `PipelineNode` a un
statut (`pending` / `running` / `done` / `failed`) et un message d'erreur
optionnel. Un clic sur une phase ouvre un panneau latéral listant ses nœuds
individuels, avec un bouton "Relancer" par nœud en échec ou pour toute la
phase. La donnée de démo inclut un échec réel et cohérent avec le code
vendorisé (`bearer.bearer_scan` → binaire introuvable, façon
`ToolNotFoundError`).

**Coding — dette de revue explicite.** `CodingView` affiche un bandeau
permanent "N branches actives · M diffs en attente de revue" au-dessus des
branches. Chaque fichier généré a une action explicite (Accepter /
Corriger) — rien n'est fusionné silencieusement vers `PRODUCTION`. Le
badge rouge sur l'onglet "Coding" reflète le même compteur sans avoir à
ouvrir l'onglet.

**Network — fil d'Ariane à 3 niveaux + nœuds cliquables.** `Breadcrumb`
navigue entre Système / Conteneurs / Composant. Chaque boîte du diagramme
est cliquable et ouvre `NodeDetailPanel` (technologie, tags, responsable,
menaces liées). Le conteneur `Payment Service` porte `drillable: true` et
propose un bouton "Voir les composants" qui descend au niveau Composant.

**Security — filtres de sévérité et accessibilité.** Une bande de compteurs
cliquables (Critique / Avertissement / Info) filtre la liste. Chaque
finding affiche un badge "Atteignable depuis Marchand" ou non — voir la
section suivante pour son origine. "Ignorer" exige une raison et une date
d'expiration (jamais un rejet silencieux) ; le badge rouge sur l'onglet
"Security" compte les critiques non ignorés.

## Fusion avec le backend — les 6 étapes du prompt, complètes

`src/lib/pipelineApi.ts` contient le client complet (`fetch` + `EventSource`)
pour tous les endpoints de `Nexus_Assistant/api/`. `App.tsx` ne contient
plus aucun `// TODO :` — chacun a été remplacé par le vrai appel réseau
correspondant, y compris `unignoreFinding` qui n'avait pourtant pas de
commentaire `// TODO :` dans la version d'origine (piège documenté dans le
prompt de fusion, câblé quand même). Détail complet, preuve d'exécution
étape par étape, bugs trouvés en testant et corrigés : voir le README de
`Nexus_Assistant/`, section "Fusion frontend ↔ backend".

Points spécifiques au frontend :

- `src/lib/phaseLabels.ts` (nouveau) : mapping centralisé, UN SEUL fichier,
  des 10 id de phase réels (`elicit, arch, net, policy, threat, graph,
  codegen, audit, report, deploy` — **10, pas 8**, voir la correction
  documentée côté backend) vers leur libellé FR.
- `App.tsx` charge son état initial (`phases`, `findings`, `branches`)
  depuis l'API au montage (`useEffect` + `GET /api/pipeline/phases` +
  `GET /api/security/findings` + `GET /api/codegen/branches`) — `mockPhases`/
  `mockFindings`/`mockBranches` ne sont plus utilisés comme état de
  démarrage. `src/data/mockPipeline.ts` reste dans le repo (mode démo
  hors-ligne explicite si besoin) mais n'est plus importé par défaut.
- `src/vite-env.d.ts` (nouveau) : nécessaire pour `import.meta.env`, absent
  du projet jusqu'ici (100 % mock avant cette fusion).
- Toute erreur réseau déclenche `ApiStatusToast("error")` — jamais de
  repli silencieux vers les données mock (contrainte explicite du prompt).
- Un `retry` (nœud ou phase) ouvre un nouveau flux SSE pour ce run et met
  à jour les mêmes nœuds en direct, avec le même code de fusion d'état que
  `handleSend` (`applyNodeEvent`/`subscribeAndApply` dans `App.tsx`).

Hors périmètre de cette fusion (le prompt ne spécifiait aucun endpoint
pour ça) : le diagramme C4 (`NetworkView`/`diagram/*`) et la liste des
outils (`mockToolStatus`) restent alimentés par des données de démo — voir
plus bas, section "3. Peupler le diagramme C4", conservée telle quelle
pour un travail futur.

## Onglets Coding et Security

La maquette fournie ne montrait que l'onglet **Network** actif. `CodingView`
et `SecurityView` ont été construits dans le même langage visuel mais
sont une extrapolation — à ajuster une fois que vous aurez une maquette
ou des retours utilisateurs sur ces deux vues. Les deux sont maintenant
branchés sur l'API réelle (voir section précédente).

## Onglet Registry — Nexus Studio (Mission 2, D5.1)

Quatrième onglet, ajouté par `MISSION2_meta_framework_nexus_studio.md`,
livrable D5 ("un explorateur minimal... une page nexus-ui qui consomme
`GET /registry/full` et affiche nœuds/arêtes"). Contrairement aux 3 autres
onglets, `RegistryView` ne parle **pas** à `Nexus_Assistant/api/` mais au
**pont** (`nexus_core_leon_bridge`, port 8420 par défaut) — c'est là
qu'habite le catalogue déjà fusionné nexus_compose + Nexus Brain (D4 de
cette même mission). D'où une variable d'environnement séparée :

```bash
# .env.local (facultatif — la valeur ci-dessous est déjà le défaut)
VITE_BRIDGE_BASE_URL=http://127.0.0.1:8420
```

`RegistryView` est volontairement auto-suffisante : son propre
chargement/erreur/`SidePanel`, sans passer par l'état partagé d'`App.tsx`
(aucune autre vue n'a besoin de ces données). Elle charge tout le
registre une fois (183 nœuds aujourd'hui — largement gérable en mémoire) et
filtre côté client — recherche texte, phase, et capacité (D1) — plutôt que
de refaire un aller-retour réseau par filtre. Un nœud sélectionné ouvre le
détail complet (`RegistryNodeDetail.tsx`) : tous les champs `NodeMeta`
(cf. `Nexus_Assistant/docs/registry_schema.md`) plus les arêtes entrantes/
sortantes qui le touchent.

Si le pont répond mais que **nexus_compose**, lui, est injoignable, D4
dégrade en douceur côté backend (retourne les 14 nœuds Nexus Brain sans
planter) — `RegistryView` le détecte (tous les nœuds reçus seraient alors
`phase: "brain"`) et l'affiche comme un bandeau d'avertissement plutôt que
de laisser deviner pourquoi la liste est soudain plus courte.

**Note CORS** : `nexus_core_leon_bridge/bridge/server.py` n'avait, avant
cette mission, aucun middleware CORS (contrairement à
`Nexus_Assistant/api/main.py`) — personne n'avait encore eu besoin
d'appeler le pont depuis un navigateur. Ajouté avec les mêmes origines
(`localhost:5173` / `127.0.0.1:5173`) que le reste de l'appli.

## Peupler le diagramme C4 (hors périmètre de la fusion actuelle)

`ContainerDiagram`, `ComponentDiagram` et `SystemDiagram` prennent chacun
une forme fixe qui correspond à la maquette (personne → hub → éventail →
secondaire pour le niveau conteneur). C'est suffisant pour représenter un
microservice et ses dépendances directes, mais **pas un graphe C4
générique** à topologie variable. Le prompt de fusion exécuté ici ne
spécifiait aucun endpoint pour ça (`/api/pipeline/*`, `/api/security/*`,
`/api/codegen/*`, `/api/conversations/*` seulement) — laissé en l'état
intentionnellement plutôt que d'improviser un contrat d'API non demandé.

Pour un graphe arbitraire, le jour où c'est demandé, deux options :

- **Réutiliser le générateur LikeC4 déjà vendorisé** dans votre paquet
  `nexus_vendor` (`native/likec4/typescript/generators/src/puml/` et
  `core/src/model/`) pour produire un layout calculé côté serveur, puis
  l'exporter en JSON et le rendre ici.
- **Remplacer les 3 composants `diagram/*` par un rendu piloté par
  `dagre` ou `elkjs`** côté client, alimenté par les nœuds/arêtes bruts
  renvoyés par `nexus_compose.registry.build()` (169 nœuds, 218 arêtes).

Le format `DiagramNode` (`types.ts`) — `tone`, `kind`, `title`, `meta`,
`detail`, `technology`, `tags`, `linkedThreats` — est conçu pour rester
valable quel que soit le moteur de layout choisi ensuite ; `NodeBox.tsx`
(dans `diagram/`) est le seul point de rendu visuel à adapter.
