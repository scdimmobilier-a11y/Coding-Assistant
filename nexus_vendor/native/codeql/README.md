# CodeQL (QL Queries + GitHub Actions integration)
**Source :** codeql.zip → codeql-main/
**Language :** QL (Datalog-like query language) + Python helpers
**Binaire CLI :** https://github.com/github/codeql-action/releases

## Queries QL extraites (par CWE)

| Query | CWE | Prédicat clé | Rôle dans nexus_compose |
|-------|-----|-------------|------------------------|
| `CWE-312/ExcessiveSecretsExposure.ql` | CWE-312 | `isExcessiveSecretUsage(step)` | Secrets dans logs CI |
| `CWE-312/SecretsInArtifacts.ql` | CWE-312 | `secretFlowsToArtifact(secret, artifact)` | Secrets dans artefacts |
| `CWE-312/UnmaskedSecretExposure.ql` | CWE-312 | `isUnmaskedSecret(output)` | Secrets non masqués |
| `CWE-349/CachePoisoningViaDirectCache.ql` | CWE-349 | `isPoisonableCacheKey(expr)` | Empoisonnement de cache |
| `CWE-571/ExpressionIsAlwaysTrueHigh.ql` | CWE-571 | `isAlwaysTrue(expr)` | Conditions toujours vraies |
| `CWE-829/UntrustedCheckoutCritical.ql` | CWE-829 | `isUntrustedCheckout(step)` | Checkout de fork non sécurisé |
| `CWE-285/ImproperAccessControl.ql` | CWE-285 | `hasPullRequestTarget(wf)` | Contrôle d'accès insuffisant |

## Pipeline CodeQL dans nexus_compose

```
codeql database create --language=<lang> <db_path>
    ↓  (crée le graphe sémantique du code)
codeql database analyze --format=sarif-latest <db_path> [queries]
    ↓  (produit results.sarif)
→ nœud codeql.codeql_database_analyze → PRODUCTION
```

## Format SARIF 2.1.0 (sortie)
```json
{
  "runs": [{
    "results": [{
      "ruleId": "CWE-829/UntrustedCheckoutCritical",
      "level": "error",
      "message": { "text": "Untrusted checkout of pull request" },
      "locations": [{
        "physicalLocation": {
          "artifactLocation": { "uri": ".github/workflows/ci.yml" },
          "region": { "startLine": 42, "startColumn": 5 }
        }
      }]
    }]
  }]
}
```
