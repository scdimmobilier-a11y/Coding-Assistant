# OPA — Open Policy Agent (Go)
**Source :** opa.zip → opa-main/
**Language :** Go 1.25
**Compilation :** `go build -o opa ./cmd/opa/main.go`

## Packages extraits et rôle

| Package Go | Rôle dans nexus_compose |
|-----------|------------------------|
| `go/ast/` | Parse et compile les modules Rego en AST. `Compiler.Compile(modules)` — point d'entrée de validation. |
| `go/topdown/` | Moteur d'évaluation Rego. `(e *eval).Run()` — évalue une query contre un input JSON. |
| `go/bundle/` | `LoadDir(path)` — charge un bundle OPA (policies + data + manifest.json). |
| `go/cmd/` | Points d'entrée CLI : `eval.go`, `run.go`, `check.go`, `test.go`, `fmt.go`, `build.go`. |
| `go/rego/` | API Go haut-niveau : `rego.New(rego.Query(...), rego.Module(...)).Eval(ctx)`. |
| `go/plugins/` | Système de plugins : REST API, logs, bundles distants. `plugins/rest/client.go` — client HTTP OPA. |
| `go/storage/` | Stockage persistant des données OPA (in-memory ou disque). |

## Fonctions clés

```go
// ast/compile.go
func (c *Compiler) Compile(modules map[string]*Module) *Compiler

// topdown/eval.go
func (e *eval) Run() error

// bundle/bundle.go
func LoadDir(path string) (*Bundle, error)

// cmd/eval.go
func runEval(args []string) error   // opa eval -d policy.rego -i input.json 'data.allow'

// rego/rego.go
func New(options ...func(*Rego)) *Rego
func (r *Rego) Eval(ctx context.Context) (ResultSet, error)
```

## Dépendances transitives OPA
- `github.com/bytecodealliance/wasmtime-go` — exécution de modules Wasm (optionnel)
- `github.com/dgraph-io/badger` — stockage persistant (optionnel)
- Toutes les autres dépendances sont standard library Go
