"""nexus_unified.pack.drivers — handlers des nœuds du pack unified.

Les nœuds d'infrastructure (gpu.*, budget.*, ml.*, eval.gate, vllm.*, reward.*,
oh.*, us.*) ont des handlers RÉELS adossés aux gestionnaires du paquet
(accélérateurs, magasins, passerelle LLM, client OpenHands V1, porte
d'inspection). Les nœuds de catalogue (crewtools.*, omrl.*, crew.*) qui
enveloppent des bibliothèques tierces non installées ici dégradent proprement
en renvoyant `{"error": ...}` — ce qui, les nœuds du pack étant en mode
`strict_errors`, compte comme un échec explicite (jamais un faux succès).

Un handler ne lève jamais : il renvoie un dict. Les effets réels (démarrer un
sandbox, lancer un entraînement) exigent le serveur OpenHands/le GPU ; sans
eux, le handler renvoie une erreur décrivant précisément ce qui manque.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Callable, Dict, Optional

from ..accelerators import AcceleratorLeaseManager, LeaseError, discovery_report
from ..llm import LLMGateway
from ..openhands_client import OpenHandsV1Client
from ..security import ArtifactGate
from ..store import open_store
from ..training import TrainingService, ModelRegistry, VLLMManager, OpenHandsRunner

Handler = Callable[[Dict[str, Any]], Dict[str, Any]]


# ── contexte partagé (singletons paresseux) ─────────────────────────────────
class PackContext:
    _instance: Optional["PackContext"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._lease: Optional[AcceleratorLeaseManager] = None
        self._store = None
        self._gateway: Optional[LLMGateway] = None
        self._gate: Optional[ArtifactGate] = None
        self._training: Optional[TrainingService] = None
        self._registry: Optional[ModelRegistry] = None
        self._vllm: Optional[VLLMManager] = None

    @classmethod
    def get(cls) -> "PackContext":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def lease(self) -> AcceleratorLeaseManager:
        if self._lease is None:
            self._lease = AcceleratorLeaseManager()
        return self._lease

    @property
    def store(self):
        if self._store is None:
            self._store = open_store()
        return self._store

    @property
    def gateway(self) -> LLMGateway:
        if self._gateway is None:
            self._gateway = LLMGateway()
        return self._gateway

    @property
    def gate(self) -> ArtifactGate:
        if self._gate is None:
            root = os.getenv("NEXUS_ARTIFACT_ROOT", "./nexus_state/artifacts")
            self._gate = ArtifactGate(os.path.join(root, "admitted"),
                                      os.path.join(root, "quarantine"))
        return self._gate

    @property
    def training(self) -> TrainingService:
        if self._training is None:
            self._training = TrainingService(store=self.store)
        return self._training

    @property
    def registry(self) -> ModelRegistry:
        if self._registry is None:
            self._registry = ModelRegistry(store=self.store)
        return self._registry

    @property
    def vllm(self) -> VLLMManager:
        if self._vllm is None:
            self._vllm = VLLMManager(lease_manager=self.lease)
        return self._vllm

    def oh_client(self, ctx: Dict[str, Any]) -> OpenHandsV1Client:
        return OpenHandsV1Client(
            base_url=ctx.get("oh_base_url", os.getenv("OH_BASE_URL", "http://localhost:3000")),
            token=ctx.get("oh_token", os.getenv("OH_TOKEN", "")),
            timeout=int(ctx.get("oh_timeout", 120)))


def _unavailable(node: str, dep: str, how: str) -> Dict[str, Any]:
    return {"error": f"{node} : dépendance absente — {dep}", "install": how, "node": node}


# ── GPU / baux ───────────────────────────────────────────────────────────────
def _gpu_discover(ctx):
    return {"discovery": discovery_report()}


def _gpu_lease(ctx):
    mgr = PackContext.get().lease
    try:
        lease = mgr.acquire(
            holder=ctx.get("holder", "pipeline"),
            count=int(ctx.get("gpu_count", 1)),
            exclusive=bool(ctx.get("exclusive", True)),
            memory_mib=int(ctx.get("memory_mib", 0)),
            vendor=ctx.get("vendor"),
            ttl=float(ctx.get("ttl", 3600)))
    except LeaseError as exc:
        return {"error": f"gpu.lease : {exc}", "node": "gpu.lease",
                "snapshot": mgr.snapshot()}
    return {"lease_id": lease.lease_id, "device_indices": lease.device_indices,
            "visibility_env": lease.visibility_env, "run_kwargs": lease.run_kwargs,
            "lease": lease.to_dict()}


def _gpu_release(ctx):
    mgr = PackContext.get().lease
    lid = ctx.get("lease_id")
    if lid:
        return {"released": mgr.release(lid)}
    holder = ctx.get("holder")
    if holder:
        return {"released_count": mgr.release_holder(holder)}
    return {"error": "gpu.release : lease_id ou holder requis", "node": "gpu.release"}


def _gpu_probe(ctx):
    rep = discovery_report()
    if rep["count"] == 0:
        return {"error": "gpu.probe : aucun accélérateur visible dans ce sandbox",
                "node": "gpu.probe", "discovery": rep}
    return {"accelerators": rep["count"], "by_vendor": rep["by_vendor"]}


def _budget_guard(ctx):
    # Vérifie un budget passé dans le contexte ; en l'absence, laisse passer.
    spent_gpu = float(ctx.get("spent_gpu_hours", 0))
    max_gpu = float(ctx.get("max_gpu_hours", 0))
    spent_tok = int(ctx.get("spent_tokens", 0))
    max_tok = int(ctx.get("max_tokens", 0))
    if max_gpu and spent_gpu >= max_gpu:
        return {"error": f"budget.guard : GPU-heures épuisées ({spent_gpu}/{max_gpu})",
                "node": "budget.guard", "stop": True}
    if max_tok and spent_tok >= max_tok:
        return {"error": f"budget.guard : jetons épuisés ({spent_tok}/{max_tok})",
                "node": "budget.guard", "stop": True}
    return {"within_budget": True, "spent_gpu_hours": spent_gpu, "spent_tokens": spent_tok}


# ── inspection obligatoire d'artefacts (point 9) ────────────────────────────
def _ml_artifact_inspect(ctx):
    path = ctx.get("artifact_path")
    name = ctx.get("artifact_name") or (os.path.basename(path.rstrip("/")) if path else "artifact")
    if not path or not os.path.exists(path):
        return {"error": "ml.artifact_inspect : artifact_path introuvable", "node": "ml.artifact_inspect"}
    res = PackContext.get().gate.inspect_and_admit(path, name)
    out = {"admitted": res.admitted, "verdict": res.verdict.value, "path": res.path,
           "quarantined": res.quarantined, "report": res.report.to_dict()}
    if not res.admitted:
        out["error"] = f"artefact refusé ({res.verdict.value}) : mis en quarantaine"
        out["node"] = "ml.artifact_inspect"
    return out


def _ml_dataset_snapshot(ctx):
    path = ctx.get("dataset_path")
    if not path or not os.path.exists(path):
        return {"error": "ml.dataset_snapshot : dataset_path introuvable", "node": "ml.dataset_snapshot"}
    # Un dataset passe par la même inspection obligatoire avant d'être figé.
    insp = _ml_artifact_inspect({"artifact_path": path,
                                 "artifact_name": ctx.get("name", "dataset")})
    if insp.get("error"):
        return insp
    from ..security import sha256_file
    snap_id = ctx.get("snapshot_id") or f"ds-{int(__import__('time').time())}"
    rec = {"id": snap_id, "path": insp["path"], "license": ctx.get("license", "unknown"),
           "verdict": insp["verdict"], "sha256": insp["report"]["sha256"]}
    PackContext.get().store.put("datasets", snap_id, rec)
    return {"snapshot_id": snap_id, "record": rec}


# ── OpenHands V1 — exécution ─────────────────────────────────────────────────
def _oh_health(ctx):
    h = PackContext.get().oh_client(ctx).health()
    if not h.get("ok"):
        return {"error": f"oh.health : OpenHands injoignable ({h.get('error') or h.get('status_code')})",
                "node": "oh.health", **h}
    return h


def _oh_send_message(ctx):
    instruction = ctx.get("instruction") or ctx.get("prompt") or ""
    if not instruction:
        return {"error": "oh.send_message : 'instruction' requise", "node": "oh.send_message"}
    client = PackContext.get().oh_client(ctx)
    h = client.health()
    if not h.get("ok"):
        return {"error": "oh.send_message : OpenHands injoignable — démarrer le serveur",
                "node": "oh.send_message", "health": h}
    res = client.run_task(instruction)
    out = {"ok": res.ok, "conversation_id": res.conversation_id, "output": res.output,
           "git_diff": res.git_diff, "execution_status": res.execution_status,
           "events_count": len(res.events)}
    if not res.ok:
        out["error"] = res.error or "oh.send_message : exécution non terminée"
        out["node"] = "oh.send_message"
    return out


def _oh_events(ctx):
    cid = ctx.get("conversation_id")
    if not cid:
        return {"error": "oh.events_search : conversation_id requis", "node": "oh.events_search"}
    client = PackContext.get().oh_client(ctx)
    evs = client.events(cid)
    return {"events": evs, "count": len(evs)}


def _oh_git_diff(ctx):
    cid = ctx.get("conversation_id")
    if not cid:
        return {"error": "oh.git_diff : conversation_id requis", "node": "oh.git_diff"}
    diff = PackContext.get().oh_client(ctx).git_diff(cid)
    return {"git_diff": diff, "has_changes": bool(diff.strip())}


# ── évaluation / apprentissage ───────────────────────────────────────────────
def _eval_gate(ctx):
    """Porte de promotion : s'appuie sur opa.opa_eval si disponible, sinon seuils
    numériques directs. Refuse par défaut si les métriques manquent."""
    metrics = ctx.get("metrics") or {}
    thresholds = ctx.get("thresholds") or {}
    if not metrics:
        return {"error": "eval.gate : aucune métrique à évaluer", "node": "eval.gate", "pass": False}
    failed = {k: (metrics.get(k), v) for k, v in thresholds.items()
              if not (isinstance(metrics.get(k), (int, float)) and metrics[k] >= v)}
    passed = not failed
    out = {"pass": passed, "metrics": metrics, "thresholds": thresholds}
    if not passed:
        out["error"] = f"eval.gate : seuils non atteints : {failed}"
        out["node"] = "eval.gate"
    return out


def _reward_from_audit(ctx):
    """Pénalité agrégée à partir des constats Semgrep/Bearer/CodeQL présents dans ctx."""
    findings = ctx.get("audit_findings") or []
    weights = {"ERROR": 1.0, "HIGH": 1.0, "WARNING": 0.3, "MEDIUM": 0.3, "INFO": 0.0, "LOW": 0.1}
    penalty = sum(weights.get(str(f.get("severity", "")).upper(), 0.2) for f in findings)
    reward = -min(penalty, 10.0)
    return {"reward": reward, "penalty": penalty, "n_findings": len(findings)}


def _reward_from_tests(ctx):
    passed = int(ctx.get("tests_passed", 0))
    total = int(ctx.get("tests_total", 0))
    if total <= 0:
        return {"error": "reward.from_tests : tests_total requis (> 0)", "node": "reward.from_tests"}
    reward = passed / total
    return {"reward": reward, "passed": passed, "total": total}


# ── entraînement / service (lot 3) ───────────────────────────────────────────
def _ml_run_submit(ctx):
    spec = ctx.get("spec")
    if not isinstance(spec, dict):
        # permet un run simulé par métriques fournies (tests, dry-run)
        if isinstance(ctx.get("metrics"), dict):
            spec = {"metrics": ctx["metrics"]}
        else:
            return {"error": "ml.run_submit : 'spec' (dict) requise", "node": "ml.run_submit"}
    # un entraînement réel exige un bail GPU ; en l'absence de GPU on refuse,
    # sauf run simulé (spec sans commande) toléré pour les tests.
    job = PackContext.get().training.submit(spec)
    if job.status == "error":
        return {"error": f"ml.run_submit : {job.error}", "node": "ml.run_submit"}
    return {"job_id": job.job_id, "status": job.status}


def _ml_run_wait(ctx):
    jid = ctx.get("job_id")
    if not jid:
        return {"error": "ml.run_wait : job_id requis", "node": "ml.run_wait"}
    job = PackContext.get().training.wait(jid, timeout=float(ctx.get("timeout", 600)),
                                          interval=float(ctx.get("interval", 0.5)))
    out = {"status": job.status, "metrics": job.metrics, "job_id": jid}
    if job.status != "finished":
        out["error"] = job.error or f"ml.run_wait : statut {job.status}"
        out["node"] = "ml.run_wait"
    return out


def _ml_checkpoint_promote(ctx):
    cid = ctx.get("checkpoint_id")
    if not cid:
        return {"error": "ml.checkpoint_promote : checkpoint_id requis", "node": "ml.checkpoint_promote"}
    gate_passed = bool(ctx.get("gate_passed"))
    res = PackContext.get().registry.promote(cid, gate_passed=gate_passed,
                                              gate_report=ctx.get("gate_report"))
    if not res.get("promoted"):
        res.setdefault("error", "promotion refusée")
        res["node"] = "ml.checkpoint_promote"
    return res


def _vllm_serve(ctx):
    path = ctx.get("model_path")
    if not path:
        return {"error": "vllm.serve : model_path requis", "node": "vllm.serve"}
    res = PackContext.get().vllm.serve(path, served_name=ctx.get("served_name", "local"))
    if not res.get("served"):
        res["node"] = "vllm.serve"
    return res


def _vllm_swap(ctx):
    path = ctx.get("model_path")
    if not path:
        return {"error": "vllm.swap : model_path requis", "node": "vllm.swap"}
    res = PackContext.get().vllm.swap(path, served_name=ctx.get("served_name", "local"))
    if not res.get("served"):
        res["node"] = "vllm.swap"
    return res


def _vllm_stop(ctx):
    return PackContext.get().vllm.stop()


def _ml_checkpoint_register(ctx):
    cid = ctx.get("checkpoint_id") or f"ckpt-{int(__import__('time').time())}"
    path = ctx.get("path", "")
    rec = PackContext.get().registry.register(cid, path=path, run_id=ctx.get("run_id", ""),
                                              metrics=ctx.get("metrics"))
    return {"checkpoint_id": cid, "record": rec}


def _store_record(collection: str):
    def _h(ctx):
        rec = ctx.get("record")
        if not isinstance(rec, dict):
            return {"error": f"{collection} : 'record' (dict) requis", "node": collection}
        rid = PackContext.get().store.append(collection, rec)
        return {"stored_id": rid, "collection": collection}
    return _h


# ── stubs de catalogue (dépendances tierces) ─────────────────────────────────
def _needs(dep: str, how: str):
    def _h(ctx):
        return _unavailable(ctx.get("_node_id", "node"), dep, how)
    return _h


# ── table de dispatch ────────────────────────────────────────────────────────
def build_handlers() -> Dict[str, Handler]:
    h: Dict[str, Handler] = {
        "gpu.discover": _gpu_discover, "gpu.lease": _gpu_lease, "gpu.release": _gpu_release,
        "gpu.probe": _gpu_probe, "budget.guard": _budget_guard,
        "ml.artifact_inspect": _ml_artifact_inspect, "ml.dataset_snapshot": _ml_dataset_snapshot,
        "ml.checkpoint_register": _ml_checkpoint_register,
        "ml.checkpoint_promote": _ml_checkpoint_promote,
        "ml.run_submit": _ml_run_submit, "ml.run_wait": _ml_run_wait,
        "ml.metrics_read": lambda c: ({"metrics": c["metrics"]} if isinstance(c.get("metrics"), dict)
                                      else {"error": "ml.metrics_read : metrics absentes", "node": "ml.metrics_read"}),
        "vllm.serve": _vllm_serve, "vllm.swap": _vllm_swap, "vllm.stop": _vllm_stop,
        "eval.gate": _eval_gate, "reward.from_audit": _reward_from_audit,
        "reward.from_tests": _reward_from_tests,
        "oh.health": _oh_health, "us.health_check": _oh_health,
        "oh.send_message": _oh_send_message, "oh.conversation_start": _oh_send_message,
        "oh.events_search": _oh_events, "oh.git_diff": _oh_git_diff,
    }
    # Nœuds qui exigent impérativement un serveur OpenHands/GPU démarré : sans
    # eux, erreur explicite (jamais un faux succès).
    for nid in ("oh.sandbox_start", "oh.rl_create", "oh.rl_step"):
        h[nid] = _needs("serveur OpenHands/GPU requis",
                        "démarrer OpenHands (docker compose --profile fullstack up) et réserver un GPU")
    return h
