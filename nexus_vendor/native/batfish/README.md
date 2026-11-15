# Batfish + pybatfish (Java serveur + Python client)
**Sources :** Batfish.zip (Java) + pybatfish (PyPI)
**Architecture :** Serveur Java (port 9996) + client Python pybatfish

## Python — pybatfish client

| Module Python | Rôle |
|---------------|------|
| `python/pybatfish/client/session.py` | `Session(host)` — connexion Batfish |
| `python/pybatfish/client/commands.py` | `bf_init_snapshot()`, `bf_set_network()`, `bf_load_questions()` |
| `python/pybatfish/question/` | Questions disponibles : routes, BGP, reachability, traceroute |
| `python/pybatfish/datamodel/` | Types de données : `Flow`, `PathConstraints`, `HeaderConstraints` |

## Java — packages clés

| Package | Rôle |
|---------|------|
| `java/batfish/bgp/` | Analyse des sessions BGP (état, attributs, routes) |
| `java/batfish/topology/` | Modélisation de la topologie réseau (liens, interfaces, nœuds) |
| `java/batfish/dataplane/` | Plan de données : tables de routage, FIB, ECMP |
| `java/common/` | Types partagés : `BatfishException`, `NetworkSnapshot`, `Warnings` |
| `java/client/` | `BfCoordWorkHelper.java` — client REST vers le coordinateur |

## API pybatfish clé

```python
from pybatfish.client.session import Session
from pybatfish.client import commands as bfc
from pybatfish.datamodel import PathConstraints, HeaderConstraints

# 1. Connexion
session = Session(host="localhost")

# 2. Upload des configurations réseau
bfc.bf_set_network("my-network")
bfc.bf_init_snapshot("./configs/", name="prod", overwrite=True)

# 3. Requêtes
routes = session.q.routes().answer().frame()
    # → DataFrame pandas : Node, VRF, Network, NextHop, Protocol, Metric

reach = session.q.reachability(
    pathConstraints=PathConstraints(startLocation="host1", endLocation="host2"),
    headers=HeaderConstraints(dstPorts="443")
).answer().frame()
    # → disposition ACCEPTED/DENIED/... par chemin

traceroute = session.q.traceroute(
    startLocation="host1",
    headers=HeaderConstraints(dstIps="10.0.0.1")
).answer().frame()
    # → liste de hops avec équipement, interface, action
```
