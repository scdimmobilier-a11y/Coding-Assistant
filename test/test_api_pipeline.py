"""
tests/test_api_pipeline.py
─────────────────────────────
Tests d'intégration pour l'API HTTP (Étape 1a du prompt de fusion) —
POST /api/pipeline/run et GET /api/pipeline/events. Exécute le VRAI
Orchestrator sur la VRAIE phase "elicit" (pas de mock) : ce sont des tests
d'intégration, pas des tests unitaires isolés — cohérent avec le principe
directeur du prompt de tests de déploiement ("un test qui mock le LLM/
l'orchestrateur ne valide rien ici").

Pourquoi httpx.AsyncClient + ASGITransport, et pas fastapi.testclient.
TestClient : TestClient (synchrone) exécute chaque appel dans SA PROPRE
boucle asyncio éphémère, fermée dès que l'appel retourne. Le code de
api/state.py capture `asyncio.get_running_loop()` pendant le POST
/api/pipeline/run et s'en sert plus tard, depuis un thread, pour livrer des
événements dans la Queue consommée par le GET /api/pipeline/events suivant
— si POST et GET tournent chacun dans une boucle différente (ce que fait
TestClient), la boucle capturée pendant le POST est déjà fermée quand le
thread tente de s'en servir ("RuntimeError: Event loop is closed"), et le
GET, lui, tourne encore dans une troisième boucle qui ne reçoit jamais
l'événement. C'est un artefact de la méthode de test, PAS un bug de
production : preuve détaillée contre un vrai serveur uvicorn (curl + client
EventSource réel) dans nexus_core_leon_bridge-style evidence, run manuel
documenté dans README.md. httpx.AsyncClient + ASGITransport exécute tout —
POST et GET — dans LA MÊME boucle asyncio du test, exactement comme le fait
un unique process uvicorn ; c'est l'approche documentée par FastAPI lui-même
pour ce cas (fastapi.tiangolo.com/advanced/async-tests/).

ASGITransport ne fait pas de streaming incrémental (issue connue,
encode/httpx#2186) : il attend la fin de la réponse avant de la livrer.
Sans conséquence ici puisque notre flux SSE est fini (toujours terminé par
un événement "done"/"error"), contrairement aux flux infinis qui déclenchent
ce problème ailleurs — voir la note dans _run_and_collect.

Run:
    cd Nexus_Assistant
    python -m pytest test/test_api_pipeline.py -v
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from api.state import RUNS


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _drain_events(client: AsyncClient, run_id: str) -> list[dict]:
    """Consomme un flux SSE jusqu'à "done"/"error". Toujours appeler ceci
    (ou _run_and_collect) pour CHAQUE run déclenché dans un test, même si le
    test ne s'intéresse pas au contenu des événements : sans ça, le thread
    d'exécution du run continue de tourner après la fin du test, et plante
    bruyamment ("Event loop is closed") quand pytest ferme la boucle
    asyncio du test suivant avant que le thread orphelin n'ait fini."""
    events: list[dict] = []
    async with client.stream("GET", f"/api/pipeline/events?run_id={run_id}") as stream:
        async for line in stream.aiter_lines():
            if not line or not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            events.append(event)
            if event.get("type") in ("done", "error"):
                break
    return events


async def _run_and_collect(client: AsyncClient, instruction: str, phase: str) -> tuple[str, list[dict]]:
    resp = await client.post("/api/pipeline/run", json={"instruction": instruction, "phase": phase})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    events = await _drain_events(client, run_id)
    return run_id, events


@pytest.mark.anyio
async def test_run_returns_a_run_id_and_the_requested_phase(client: AsyncClient):
    resp = await client.post("/api/pipeline/run", json={"instruction": "test", "phase": "elicit"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["phases"] == ["elicit"]
    assert len(body["run_id"]) > 0
    # Toujours drainer un run déclenché dans un test, même quand seule la
    # réponse du POST nous intéresse — sinon le thread d'exécution devient
    # orphelin dès que ce test se termine (voir _drain_events).
    await _drain_events(client, body["run_id"])


@pytest.mark.anyio
async def test_unknown_phase_returns_400_not_a_500(client: AsyncClient):
    resp = await client.post("/api/pipeline/run", json={"instruction": "test", "phase": "not-a-real-phase"})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_unknown_run_id_on_events_returns_404(client: AsyncClient):
    resp = await client.get("/api/pipeline/events?run_id=00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_full_elicit_run_emits_pending_running_done_or_failed_and_terminates(client: AsyncClient):
    run_id, events = await _run_and_collect(client, "API REST de paiement avec authentification JWT", "elicit")

    node_events = [e for e in events if e["type"] == "node"]
    assert len(node_events) > 0
    assert all(e["phaseId"] == "elicit" for e in node_events)
    assert all(e["status"] in ("pending", "running", "done", "failed") for e in node_events)

    # Le flux doit se terminer par un "done" (ou "error"), jamais rester
    # ouvert indéfiniment.
    assert events[-1]["type"] in ("done", "error")

    # Chaque nœud qui a atteint un état terminal (done/failed) doit être
    # passé par "pending" puis "running" avant — pas de saut d'état.
    by_node: dict[str, list[str]] = {}
    for e in node_events:
        by_node.setdefault(e["nodeId"], []).append(e["status"])
    for node_id, statuses in by_node.items():
        assert statuses[0] == "pending", f"{node_id} n'a pas commencé par 'pending' : {statuses}"
        assert statuses[-1] in ("done", "failed"), f"{node_id} ne termine pas en état terminal : {statuses}"


@pytest.mark.anyio
async def test_terminal_events_never_have_an_unknown_phase_id(client: AsyncClient):
    """Régression : `node_phase = dict(flat_order)` (flat_order étant une
    liste de tuples (phase, node_id)) construit silencieusement un dict
    {phase: node_id} au lieu de {node_id: phase} — `.get(rec.node_id,
    "unknown")` retombe alors TOUJOURS sur "unknown" pour tout event
    "done"/"failed", sans qu'aucune autre assertion ne le remarque (les
    statuts progressent normalement). Trouvé en exécutant un run complet et
    en inspectant les events un par un, pas en relisant le code — d'où ce
    test dédié pour qu'il ne revienne pas silencieusement."""
    _, events = await _run_and_collect(client, "test", "elicit")
    terminal = [e for e in events if e.get("type") == "node" and e["status"] in ("done", "failed")]
    assert len(terminal) > 0
    assert all(e["phaseId"] == "elicit" for e in terminal), (
        f"phaseId incorrect sur des events terminaux : {[e for e in terminal if e['phaseId'] != 'elicit']}"
    )


@pytest.mark.anyio
@pytest.mark.timeout(150)  # pyproject.toml impose 30s par défaut (pytest-timeout) ;
# ce test exécute réellement les 169 nœuds du graphe (dont plusieurs
# backoffs multi-secondes pour des services externes absents, ex. Batfish
# ~4.8s par requête bf.*) — ~60s mesurés, marge prise pour un sandbox plus
# lent. Trouvé en cherchant pourquoi ce test échouait sans AssertionError
# visible : pytest-timeout le tuait silencieusement à 30s.
async def test_full_pipeline_run_covers_all_ten_phases_and_169_nodes(client: AsyncClient):
    """Étape 1b : phase omise -> pipeline complet. Couvre les 10 phases
    réelles (elicit, arch, net, policy, threat, graph, codegen, audit,
    report, deploy — pas 8, voir state.py pour la correction de cette
    hypothèse) et les 169 nœuds du graphe, pas seulement les 106
    atteignables par run_from("LEON") (voir docstring de state.py pour
    pourquoi run_from/greenfield_pipeline ont été écartés pour ce endpoint)."""
    from nexus_compose import build_graph

    from api.state import FULL_PIPELINE_PHASE_ORDER

    resp = await client.post("/api/pipeline/run", json={"instruction": "Pipeline complet de test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["phases"] == FULL_PIPELINE_PHASE_ORDER
    run_id = body["run_id"]

    events = await _drain_events(client, run_id)
    assert events[-1]["type"] in ("done", "error")

    terminal = [e for e in events if e["type"] == "node" and e["status"] in ("done", "failed")]
    graph = build_graph()
    assert len(terminal) == len(graph.list_nodes()) == 169

    # Chaque phase réelle est bien représentée avec le bon décompte de
    # nœuds (mêmes chiffres que Counter(NodeMeta.phase) sur les 169 nœuds).
    from collections import Counter

    by_phase = Counter(e["phaseId"] for e in terminal)
    expected = Counter(graph.node(nid).meta.phase for nid in graph.list_nodes())
    assert by_phase == expected
    assert "unknown" not in by_phase


@pytest.mark.anyio
async def test_retry_unknown_node_returns_404(client: AsyncClient):
    resp = await client.post("/api/pipeline/nodes/not-a-real-node/retry")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_retry_unknown_phase_returns_404(client: AsyncClient):
    resp = await client.post("/api/pipeline/phases/not-a-real-phase/retry")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_retry_node_emits_running_then_terminal_status(client: AsyncClient):
    """Régression : `Orchestrator.run_node` ne déclenche PAS `on_step_done`
    (seul `run_pipeline`, utilisé par `run_phase`/`run_from`, le fait) —
    trouvé en exécutant un vrai retry et en observant qu'aucun event
    "done"/"failed" n'arrivait jamais, juste "running" puis la fin du flux."""
    resp = await client.post("/api/pipeline/nodes/q2d.generate/retry")
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    events = await _drain_events(client, run_id)
    node_events = [e for e in events if e["type"] == "node"]
    assert len(node_events) == 2, f"attendu running puis done/failed, reçu : {node_events}"
    assert node_events[0]["status"] == "running"
    assert node_events[1]["status"] in ("done", "failed")
    assert node_events[0]["nodeId"] == node_events[1]["nodeId"] == "q2d.generate"
    assert node_events[0]["phaseId"] == node_events[1]["phaseId"] == "elicit"


@pytest.mark.anyio
async def test_retry_phase_reuses_the_full_pipeline_thread_pattern(client: AsyncClient):
    resp = await client.post("/api/pipeline/phases/elicit/retry")
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    events = await _drain_events(client, run_id)
    terminal = [e for e in events if e["type"] == "node" and e["status"] in ("done", "failed")]
    assert len(terminal) == 9  # nombre de nœuds réels de la phase "elicit"
    assert all(e["phaseId"] == "elicit" for e in terminal)


@pytest.mark.anyio
async def test_node_id_never_collides_with_backend_tag_field(client: AsyncClient):
    """Piège documenté dans le prompt de fusion : nodes.json a un champ
    `id` (ex. "bearer.bearer_scan") et un champ `tag` (ex. "audit.analyze"),
    ce dernier étant partagé par plusieurs nœuds. Le `nodeId` envoyé au
    frontend doit toujours venir de `NodeMeta.id`, jamais de `NodeMeta.tag`
    — cette régression ne casserait aucune autre assertion (les statuts
    avanceraient normalement), c'est pourquoi elle a son propre test."""
    from nexus_compose import build_graph

    graph = build_graph()
    elicit_ids = set(graph.list_nodes(phase="elicit"))
    elicit_tags = {n.meta.tag for n in graph.nodes(phase="elicit")}

    _, events = await _run_and_collect(client, "test", "elicit")
    node_events = [e for e in events if e["type"] == "node"]
    seen_node_ids = {e["nodeId"] for e in node_events}

    assert seen_node_ids == elicit_ids
    # Si jamais nodeId venait de NodeMeta.tag par erreur, on verrait des
    # valeurs de `elicit_tags` (souvent bien MOINS nombreuses que
    # `elicit_ids`, car partagées) au lieu des vrais id.
    if elicit_tags != elicit_ids:
        collision = seen_node_ids & (elicit_tags - elicit_ids)
        assert not collision, (
            "des nodeId envoyés au frontend viennent du champ 'tag' du "
            f"backend au lieu du champ 'id' — collision reproduite : {collision}"
        )


@pytest.mark.anyio
async def test_two_concurrent_runs_do_not_cross_contaminate(client: AsyncClient):
    import asyncio

    resp_a, resp_b = await asyncio.gather(
        client.post("/api/pipeline/run", json={"instruction": "run A", "phase": "elicit"}),
        client.post("/api/pipeline/run", json={"instruction": "run B", "phase": "elicit"}),
    )
    run_id_a = resp_a.json()["run_id"]
    run_id_b = resp_b.json()["run_id"]
    assert run_id_a != run_id_b

    # Les deux runs existent bien indépendamment dans le registre.
    assert run_id_a in RUNS
    assert run_id_b in RUNS
    assert RUNS[run_id_a] is not RUNS[run_id_b]
    assert RUNS[run_id_a].queue is not RUNS[run_id_b].queue

    # Drainer les deux en parallèle (jamais laisser un thread orphelin —
    # voir _drain_events) et vérifier qu'aucun des deux flux n'a été
    # tronqué ou dupliqué par l'autre : même nombre d'événements que pour
    # un run "elicit" solo (9 nœuds x 3 transitions pending/running/done
    # ou failed, capé à ce que le graphe réel produit).
    events_a, events_b = await asyncio.gather(
        _drain_events(client, run_id_a),
        _drain_events(client, run_id_b),
    )
    assert events_a[-1]["type"] in ("done", "error")
    assert events_b[-1]["type"] in ("done", "error")
    assert len(events_a) == len(events_b), "les deux runs 'elicit' devraient produire le même nombre d'événements"
