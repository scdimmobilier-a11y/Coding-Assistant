"""
nexus_vendor.pytm — pytm OWASP Threat Modelling (vendorisé)
═════════════════════════════════════════════════════════════

pytm est la bibliothèque Python OWASP pour modéliser les menaces de sécurité
de manière programmatique. Elle génère des diagrammes DFD, des rapports de
menaces et des recommandations STRIDE.

Classes principales (module pytm.tm)
──────────────────────────────────────
  TM(name, description)
      Threat Model central. Contient tous les éléments du modèle.
      Méthodes :
        .process()      → Analyse STRIDE et génère findings
        .to_json()      → Sérialise en JSON
        .to_plantuml()  → Génère diagramme PlantUML DFD

  Actor(name)           Acteur externe (humain, système tiers)
  Process(name)         Processus applicatif (backend, service)
  Datastore(name)       Stockage de données (DB, fichier, cache)
  Dataflow(name, src, dst)  Flux de données entre deux éléments
  Boundary(name)        Frontière de confiance (DMZ, réseau interne)
  Server(name)          Serveur (hérite de Process)
  Lambda(name)          Fonction serverless

Enums (module pytm.enums)
──────────────────────────
  TLSVersion            v1_0 | v1_1 | v1_2 | v1_3
  Classification        Unknown | Public | Proprietary | Restricted | TopSecret
  Lifetime              Unknown | Stored | ... | Transient

Analyse de menaces (module pytm.threat)
────────────────────────────────────────
  Threat                Représente une menace STRIDE avec CVSS, références
  Finding               Résultat d'une analyse (threat × target)
  .check(target)        → bool  — la menace s'applique-t-elle à cette cible ?

Rapport (module pytm.report_util)
───────────────────────────────────
  ReportFormat          html | md | rst | docx
  get_report()          → str  — génère le rapport final

Usage typique dans nexus_compose
──────────────────────────────────
    from nexus_vendor.pytm import TM, Actor, Process, Datastore, Dataflow, Boundary
    tm = TM("Mon système", description="Architecture micro-services")
    user    = Actor("Utilisateur")
    api     = Process("API Gateway")
    db      = Datastore("PostgreSQL")
    Dataflow("Requête HTTP", user, api, protocol="HTTPS", isEncrypted=True)
    Dataflow("Query SQL",   api,  db, protocol="SQL")
    tm.process()   # analyse STRIDE
"""

try:
    from .tm import TM
    from .actor import Actor
    from .process import Process
    from .datastore import Datastore
    from .dataflow import Dataflow
    from .boundary import Boundary
    from .element import Element
    from .finding import Finding
    from .threat import Threat
    from .data import Data
    from .enums import TLSVersion, Classification, Lifetime, Action, DatastoreType
    # FIX (intégration Nexus Assistant) : plusieurs classes sont documentées
    # ci-dessus et/ou nécessaires à l'exécution (nexus_compose/drivers.py fait
    # `from pytm import TM, Server, Datastore, Dataflow, Boundary, Actor` ;
    # pytm/threat.py::_build_eval_globals() fait `pytm.Agent`, `pytm.Asset`,
    # `pytm.ExternalEntity`, `pytm.SetOfProcesses`, etc. au moment d'évaluer
    # les conditions STRIDE) mais n'étaient pas ré-exportées ici — l'import
    # ou l'évaluation des menaces échouait silencieusement / avec AttributeError.
    from .asset import Server, Lambda, Asset, Agent, ExternalEntity
    from .process import SetOfProcesses

    # FIX (intégration Nexus Assistant) : plusieurs classes pydantic de pytm
    # (Element, Boundary, Actor, Process, Datastore, Asset, Server, Lambda,
    # Agent, ExternalEntity, SetOfProcesses, Data, Threat, Finding, TM …)
    # déclarent des champs en référence différée (`from __future__ import
    # annotations` + `List["Finding"]`, `List["Dataflow"]`, etc.) dont le nom
    # réel n'est importé QUE sous `if TYPE_CHECKING:` dans chaque fichier —
    # donc invisible à l'exécution. Résultat : `TM("...")`, `Boundary("...")`,
    # etc. levaient tous `pydantic.errors.PydanticUserError:
    # "<Classe> is not fully defined ; you should define <Nom>, then call
    # <Classe>.model_rebuild()"`.
    #
    # On répare une bonne fois pour toutes : pour chaque sous-module concerné,
    # on injecte les classes réelles dans son namespace, puis on force la
    # reconstruction du schéma pydantic de toutes les classes concernées.
    import sys as _sys

    _resolved = {
        "Element": Element, "Data": Data, "Threat": Threat, "Finding": Finding,
        "Dataflow": Dataflow, "Boundary": Boundary, "Asset": Asset, "Actor": Actor,
    }
    for _modname in ("actor", "asset", "base", "boundary", "data",
                      "datastore", "element", "finding", "process", "tm"):
        _mod = _sys.modules.get(f"{__name__}.{_modname}")
        if _mod is None:
            continue
        for _name, _cls in _resolved.items():
            if not hasattr(_mod, _name):
                setattr(_mod, _name, _cls)

    for _cls in (Element, Data, Threat, Finding, Boundary, Actor, Process,
                 Datastore, Dataflow, Asset, Server, Lambda, Agent,
                 ExternalEntity, SetOfProcesses, TM):
        _rebuild = getattr(_cls, "model_rebuild", None)
        if callable(_rebuild):
            try:
                _rebuild(force=True)
            except Exception as _e:  # pragma: no cover — dégrade sans casser l'import
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "%s.model_rebuild() a échoué : %s", _cls.__name__, _e
                )
except ImportError:
    pass

__all__ = [
    "TM","Actor","Process","Datastore","Dataflow","Boundary",
    "Element","Finding","Threat","Data",
    "TLSVersion","Classification","Lifetime","Action","DatastoreType",
    "Server","Lambda","Asset","Agent","ExternalEntity","SetOfProcesses",
]
