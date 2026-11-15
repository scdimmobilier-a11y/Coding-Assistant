# Neo4j Python Driver (v6.2.0)
**Source :** PyPI neo4j==6.2.0
**Language :** Python 3.9+
**Installation :** `pip install neo4j`

## Modules extraits

| Module | Rôle |
|--------|------|
| `python/neo4j/__init__.py` | Exports publics : `GraphDatabase`, `Driver`, `Session`, etc. |
| `python/neo4j/_sync/driver.py` | `Driver` synchrone : `.session()`, `.execute_query()`, `.close()` |
| `python/neo4j/_sync/session.py` | `Session` : `.run()`, `.execute_write()`, `.execute_read()` |
| `python/neo4j/_sync/transaction.py` | `Transaction` : `.run(query, **params)` → `Result` |
| `python/neo4j/graph.py` | Types de données : `Node`, `Relationship`, `Path` |
| `python/neo4j/work/result.py` | `Result` : `.data()`, `.single()`, `.consume()` → `ResultSummary` |
| `python/neo4j/work/summary.py` | `ResultSummary.counters` : `nodes_created`, `relationships_created`, ... |
| `python/neo4j/exceptions.py` | `ServiceUnavailable`, `AuthError`, `CypherSyntaxError`, ... |
| `python/neo4j/auth_managers.py` | Gestion des credentials (basic, bearer, kerberos) |

## Fonctions clés

```python
# GraphDatabase (neo4j/__init__.py)
GraphDatabase.driver(uri, auth=(user, password)) → Driver
    # uri : "bolt://host:7687" | "neo4j://host:7687" | "neo4j+s://host:7687"
    # auth : (user, password) | neo4j.basic_auth(user, pass) | neo4j.bearer_auth(token)

# Driver (_sync/driver.py)
driver.session(database="neo4j") → Session
driver.execute_query(query, parameters, database) → EagerResult
driver.close() → None

# Session (_sync/session.py)
session.run(query, **params) → Result
session.execute_write(work_function) → T
session.execute_read(work_function) → T

# Transaction (_sync/transaction.py)
tx.run("MATCH (n:Component {id: $id}) RETURN n", id="api-gw") → Result

# Result (work/result.py)
result.data() → list[dict]        # tous les records
result.single() → Record | None   # un seul record (lève si >1)
result.consume() → ResultSummary  # stats de la requête

# Cypher patterns utilisés dans nexus_compose
CREATE (c:Component {id: $id, name: $name})
MERGE (a)-[:DATA_FLOW {label: $label}]->(b)
MATCH p=(s:Component {id: $id})-[:DATA_FLOW*1..5]->(e) RETURN nodes(p)
UNWIND $rows AS r MERGE (c:Component {id: r.id}) SET c += r.props
```
