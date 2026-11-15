# LikeC4 (TypeScript)
**Source :** likec4.zip → likec4-main/packages/
**Language :** TypeScript (Node.js)
**Build :** `pnpm install && pnpm build` (depuis la racine du monorepo)

## Packages extraits et rôle

| Package TS | Dossier | Rôle |
|-----------|---------|------|
| `generators` | `typescript/generators/src/` | Générateurs de code : PlantUML, Mermaid, D2, DrawIO, React |
| `core/types` | `typescript/core/src/types/` | Types TypeScript : Node, Edge, View, Relation, Deployment |
| `core/model` | `typescript/core/src/model/` | `LikeC4Model` — API de manipulation du modèle calculé |
| `language-server` | `typescript/language-server/src/` | LSP (Language Server Protocol) — parse les .c4 |

## Dépendances transitives extraites

| Dépendance | Dossier | Rôle |
|-----------|---------|------|
| `langium@4.3.1` | `typescript/_deps/langium/` | Framework DSL — `CompositeGeneratorNode`, `joinToNode`, `NL`, `toString` utilisés par generate-puml.ts |
| `remeda@2.39.0` | `typescript/_deps/remeda/` | Utilitaires fonctionnels — `isNullish`, `isEmptyish` utilisés par les générateurs |

## Fonctions clés — Générateur PlantUML (generators/src/puml/generate-puml.ts)

```typescript
// Fonctions principales
function fqnName(nodeId: string): string
    // Convertit "payment-gateway.api" → "PaymentGatewayApi" (PascalCase)

function pumlColor(color, customColorProvider, defaultColor): string
    // Résout un ThemeColor en couleur hex PlantUML

function pumlDirection(view: ProcessedView): "top to bottom" | "left to right"
    // TB → "top to bottom", LR → "left to right"

function pumlShape(node: ComputedNode): string
    // "cylinder" → "database", "component" → "component", ...

export function generatePlantUml(view: ProcessedView | LikeC4ViewModel): string
    // Point d'entrée principal : view calculée → source @startuml...@enduml

// Fonctions internes de génération
function generateNode(node: ComputedNode, indent): CompositeGeneratorNode
function generateEdge(edge: ComputedEdge): string
function generateSkinparams(view): CompositeGeneratorNode
```

## Générateurs disponibles

| Fichier | Export | Format sortie |
|---------|--------|---------------|
| `puml/generate-puml.ts` | `generatePlantUml(view)` | PlantUML (@startuml) |
| `mmd/generate-mmd.ts` | `generateMmd(view)` | Mermaid (graph TD) |
| `d2/generate-d2.ts` | `generateD2(view)` | D2 diagram |
| `drawio/generate-drawio.ts` | `generateDrawio(view)` | Draw.io XML |
| `react/generate-react-types.ts` | `generateReactTypes(model)` | TypeScript React types |
| `model/generate-likec4-model.ts` | `generateLikeC4Model(model)` | JSON model dump |
