# nexus_vendor 2.0.0

Code source extrait des **14 outils tiers** du pipeline
[Nexus Compose](https://github.com/KELEBA-LAM/Vocale-vibecoding-).

---

## Modules Python installables (`pip install .`)

```python
from nexus_vendor.pytm import TM, Actor, Process, Dataflow, Datastore, Boundary
from nexus_vendor.tmdd.utils import load_threat_model
from nexus_vendor.tmdd.generators.agent_prompt import generate_agent_prompt
from nexus_vendor.q2d.graph_to_plantuml import convert_graph
```

| Module | Outil | Fichiers |
|--------|-------|----------|
| `nexus_vendor.q2d` | Query2Diagram | 29 .py |
| `nexus_vendor.pytm` | pytm OWASP | 19 .py |
| `nexus_vendor.tmdd` | TMDD | 15 .py |

---

## Sources natifs (`native/`)

Chaque dossier contient le code source dans le langage d'origine.
Voir le `README.md` de chaque outil pour les fonctions clés et les instructions de build.

| Dossier | Outil | Langage | Build |
|---------|-------|---------|-------|
| `native/opa/` | OPA | Go | `go build ./cmd/opa/main.go` |
| `native/bearer/` | Bearer + tree-sitter | Go + C | `go build ./cmd/bearer/bearer.go` |
| `native/semgrep/` | Semgrep CLI | Python | `pip install semgrep` |
| `native/containerlab/` | Containerlab | Go | `go build ./cmd/containerlab/main.go` |
| `native/likec4/` | LikeC4 + langium + remeda | TypeScript | `pnpm build` |
| `native/c4interflow/` | C4InterFlow | C# .NET 8 | `dotnet build` |
| `native/batfish/` | Batfish + pybatfish | Java + Python | `mvn package` / `pip install pybatfish` |
| `native/threat_dragon/` | Threat Dragon | Node.js | `npm start` |
| `native/codeql/` | CodeQL queries | QL | binaire CLI séparé |
| `native/structurizr/` | Structurizr DSL | Java | `./gradlew build` |
| `native/neo4j/` | Neo4j driver | Python | `pip install neo4j` |

> **⚠️ Note importante (vérifiée lors de l'intégration Nexus Assistant, juillet 2026) :**
> cet export "propre" contient le **code source** de chaque outil (`.go`, `.java`,
> `.cs`, `.ts`, `.ql`) mais **pas les fichiers de manifeste de build**
> (`go.mod`/`go.sum`, `pom.xml`, `package.json`/`pnpm-lock.yaml`, `.csproj`/`.sln`,
> `build.gradle`). Les commandes de build ci-dessus ne fonctionneront donc pas
> telles quelles sur ces dossiers : il manque les fichiers qui déclarent le
> module/les dépendances. Deux options :
>  1. **Binaires officiels pré-compilés** (recommandé, aucune compilation
>     requise) — OPA, Bearer et Containerlab distribuent des binaires
>     statiques ; C4InterFlow.Cli s'installe via `dotnet tool install --global
>     C4InterFlow.Cli` (NuGet) ; Structurizr CLI se télécharge en `.zip` depuis
>     ses releases GitHub. C'est l'approche utilisée par `Dockerfile` et
>     `.github/workflows/ci.yml` du projet.
>  2. **Reconstituer le manifeste manquant** en clonant le dépôt officiel
>     correspondant (voir le `README.md` de chaque sous-dossier pour l'URL) et
>     en copiant son `go.mod`/`pom.xml`/`package.json`/`.csproj` à côté des
>     sources déjà présentes ici, si vous voulez compiler depuis nexus_vendor
>     plutôt que depuis un clone complet.
> Cette limite ne concerne que les **11 outils natifs** ; les **3 modules
> Python** (pytm, q2d, tmdd) ci-dessus sont, eux, directement installables et
> pleinement fonctionnels tels quels (`pip install .`).

---

## Installation

```bash
pip install .          # modules Python uniquement
pip install ".[all]"   # + dépendances optionnelles (neo4j, pybatfish, LLM)
```
