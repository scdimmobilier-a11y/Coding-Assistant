# Bearer SAST (Go + C tree-sitter parsers)
**Source :** bearer.zip → bearer-main/
**Language :** Go (scanner) + C (parsers AST)
**Compilation :** `go build -o bearer ./cmd/bearer/bearer.go` (nécessite gcc pour les parsers C)

## Packages extraits et rôle

| Package | Rôle |
|---------|------|
| `go/cmd/` | Point d'entrée CLI : `bearer.go`, commandes `scan`, `report`, `ignore` |
| `go/api/client.go` | Client REST Bearer Cloud : `New()`, `makeRequest()` |
| `go/external/run/` | Moteur principal : `Run()`, `NewEngine()`, `DefaultLanguages()` |
| `go/pkg/engine/` | Orchestrateur de scan multi-langage |
| `go/pkg/languages/` | Détecteurs par langage (Python, JS, Ruby, Java, Go, PHP) |
| `go/pkg/parser/sitter/` | Parsers Tree-sitter (C compilé + binding Go) |
| `go/pkg/report/` | Générateur de rapports (JSON, SARIF, HTML, CSV) |
| `go/pkg/detectors/` | Règles de détection (CWE, privacy, secrets) |

## Parsers Tree-sitter inclus

| Langage | Fichiers C |
|---------|-----------|
| SQL | `sitter/sql/parser.c` |
| XML | `sitter/xml/parser.c` + `scanner.c` |
| GraphQL | `sitter/graphql/parser.c` |
| PHP | `sitter/php2/parser.c` + `scanner.c` |
| HTML | `sitter/html2/parser.c` + `scanner.c` |
| Python | `sitter/python/parser.c` (téléchargé depuis tree-sitter/tree-sitter-python) |
| JavaScript | `sitter/javascript/parser.c` |
| Ruby | `sitter/ruby/parser.c` |
| Java | `sitter/java/parser.c` |
| Go | `sitter/go/parser.c` |

## Fonctions Go clés

```go
// external/run/run.go
func Run(version, commitSHA string, engine Engine)
func NewEngine(languages []Language) Engine
func DefaultLanguages() []Language
func GetNonVirtualObjects(detectorContext, node) ([]*types.Detection, error)
func StripQuotes(input string) string
func ConcatenateChildStrings(node, detectorContext) ([]interface{}, error)

// api/client.go
func New(config API) *API
func (api *API) makeRequest(route, httpMethod string, data interface{}) ([]byte, error)
```
