# Containerlab (Go)
**Source :** containerlab.zip → containerlab-main/
**Language :** Go 1.21
**Compilation :** `go build -o containerlab ./cmd/containerlab/main.go`

## Packages extraits et rôle

| Package Go | Rôle |
|-----------|------|
| `go/cmd/` | Commandes CLI Cobra : `deploy.go`, `destroy.go`, `inspect.go`, `exec.go`, `graph.go`, `save.go` |
| `go/types/` | Types fondamentaux : `Topology`, `Node`, `Link`, `MgmtNet`, `NodeDefinition` |
| `go/core/` | Logique de déploiement : création des conteneurs Docker, configuration réseau, liens veth |
| `go/constants/` | Constantes partagées (labels Docker, noms de répertoires) |

## Fonctions Go clés

```go
// cmd/deploy.go
func deployFn(cobraCmd *cobra.Command, args []string) error
  // 1. Parse YAML topologie  2. Crée réseau Docker  3. Pull images
  // 4. Crée conteneurs parallèlement  5. Configure liens veth  6. Génère inventaire

// cmd/destroy.go
func destroyFn(cobraCmd *cobra.Command, args []string) error
  // 1. Charge topologie  2. Arrête/supprime conteneurs  3. Supprime liens  4. Nettoie réseau

// cmd/inspect.go
func listContainers(ctx, name, labels) ([]types.GenericContainer, error)
func toTableData(contDetails, options) [][]string
func printContainerDetailsJSON(containers) error
func parseStatus(status string) string

// types/topology.go
type Topology struct {
    Name  string
    Nodes map[string]*Node
    Links []*Link
}
type Node struct {
    Kind  string; Image string; Mgmt *MgmtNet
    Startup string; Env map[string]string; Ports []string
}
type Link struct { Endpoints [2]string; MTU int }
```

## Dépendance principale
- Docker client Go SDK (`docker/docker/client`) — inclus via go.mod
