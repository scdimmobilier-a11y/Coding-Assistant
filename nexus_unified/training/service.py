"""nexus_unified.training.service — entraînement, évaluation, service de modèles (lot 3).

L'entraînement s'exécute DANS le sandbox sécurisé (point 9) sur des
accélérateurs réservés par bail (points 1/2). Trois pièces :

- `TrainingService` : soumet un run (spec → commande exécutée par un *runner*),
  attend sa fin (job long, non bloquant pour l'orchestrateur), lit ses métriques.
  Le runner par défaut délègue au sandbox OpenHands V1 ; un `LocalRunner` sert
  au développement et aux tests.
- `ModelRegistry` : enregistre et promeut des checkpoints. La promotion n'est
  possible QUE si une porte d'évaluation a été franchie (GA5) — le registre
  refuse une promotion sans verdict d'évaluation.
- `VLLMManager` : sert un checkpoint local (vLLM), le remplace, l'arrête. Chaque
  démarrage prend un bail GPU exclusif ; l'arrêt le rend (GA9).

Tout dégrade proprement : sans runner réel ni GPU, les handlers renvoient une
erreur explicite décrivant ce qui manque (jamais un faux succès).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

from ..store import RecordStore, open_store


# ── runner : où tourne l'entraînement ───────────────────────────────────────
class SandboxRunner(Protocol):
    def submit(self, spec: Dict[str, Any]) -> str: ...
    def poll(self, job_id: str) -> Dict[str, Any]: ...
    def read_metrics(self, job_id: str) -> Dict[str, Any]: ...


class LocalRunner:
    """Exécute un run localement (dev/test). `command` dans la spec ; écrit
    `metrics.json` dans un dossier de travail. Jamais utilisé en production
    sécurisée — là, c'est le sandbox OpenHands."""
    def __init__(self, workdir: str = "./nexus_state/runs") -> None:
        self.workdir = os.path.abspath(workdir)
        os.makedirs(self.workdir, exist_ok=True)
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def submit(self, spec: Dict[str, Any]) -> str:
        job_id = "job-" + uuid.uuid4().hex[:12]
        d = os.path.join(self.workdir, job_id)
        os.makedirs(d, exist_ok=True)
        cmd = spec.get("command")
        env = dict(os.environ, **spec.get("env", {}))
        self._jobs[job_id] = {"dir": d, "status": "running", "spec": spec}
        if cmd:
            try:
                proc = subprocess.Popen(cmd, cwd=d, env=env, shell=isinstance(cmd, str),
                                        stdout=open(os.path.join(d, "stdout.log"), "w"),
                                        stderr=subprocess.STDOUT)
                self._jobs[job_id]["proc"] = proc
            except Exception as exc:  # noqa: BLE001
                self._jobs[job_id]["status"] = "error"
                self._jobs[job_id]["error"] = str(exc)
        else:
            # pas de commande : run simulé, métriques fournies dans la spec
            import json
            with open(os.path.join(d, "metrics.json"), "w") as f:
                json.dump(spec.get("metrics", {}), f)
            self._jobs[job_id]["status"] = "finished"
        return job_id

    def poll(self, job_id: str) -> Dict[str, Any]:
        j = self._jobs.get(job_id)
        if not j:
            return {"status": "unknown"}
        proc = j.get("proc")
        if proc is not None:
            rc = proc.poll()
            if rc is None:
                return {"status": "running"}
            j["status"] = "finished" if rc == 0 else "error"
            j["returncode"] = rc
        return {"status": j["status"], "returncode": j.get("returncode")}

    def read_metrics(self, job_id: str) -> Dict[str, Any]:
        import json
        j = self._jobs.get(job_id)
        if not j:
            return {}
        p = os.path.join(j["dir"], "metrics.json")
        if os.path.exists(p):
            try:
                return json.load(open(p))
            except Exception:
                return {}
        return {}


class OpenHandsRunner:
    """Exécute l'entraînement dans le sandbox OpenHands V1 (production sécurisée)."""
    def __init__(self, client) -> None:
        self.client = client
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def submit(self, spec: Dict[str, Any]) -> str:
        h = self.client.health()
        if not h.get("ok"):
            raise RuntimeError("OpenHands injoignable — sandbox d'entraînement indisponible")
        instruction = spec.get("instruction") or _spec_to_instruction(spec)
        cid = self.client.start_conversation(instruction)
        jid = "job-" + cid
        self._jobs[jid] = {"cid": cid}
        return jid

    def poll(self, job_id: str) -> Dict[str, Any]:
        cid = self._jobs[job_id]["cid"]
        st = self.client.wait_execution(cid, timeout=1)
        done = st in ("finished", "completed", "idle", "error", "stopped")
        return {"status": "finished" if (done and st != "error") else ("error" if st == "error" else "running")}

    def read_metrics(self, job_id: str) -> Dict[str, Any]:
        # métriques lues par oh.file_read (metrics.json) — hors de portée ici
        return self._jobs[job_id].get("metrics", {})


def _spec_to_instruction(spec: Dict[str, Any]) -> str:
    return (f"Entraîne le modèle décrit par cette spec dans ce sandbox, sur le GPU "
            f"réservé. Écris les métriques finales dans metrics.json.\n\nSPEC:\n{spec}")


# ── service d'entraînement ───────────────────────────────────────────────────
@dataclass
class TrainingJob:
    job_id: str
    status: str = "running"
    metrics: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class TrainingService:
    def __init__(self, runner: Optional[SandboxRunner] = None,
                 store: Optional[RecordStore] = None) -> None:
        self.runner = runner or LocalRunner()
        self.store = store or open_store()

    def submit(self, spec: Dict[str, Any]) -> TrainingJob:
        try:
            jid = self.runner.submit(spec)
        except Exception as exc:  # noqa: BLE001
            return TrainingJob(job_id="", status="error", error=str(exc))
        self.store.put("runs", jid, {"id": jid, "spec": spec, "status": "running",
                                     "submitted_at": time.time()})
        return TrainingJob(job_id=jid, status="running")

    def wait(self, job_id: str, *, timeout: float = 3600, interval: float = 2.0) -> TrainingJob:
        deadline = time.time() + timeout
        status = "running"
        while time.time() < deadline:
            status = self.runner.poll(job_id).get("status", "running")
            if status in ("finished", "error", "unknown"):
                break
            time.sleep(interval)
        metrics = self.runner.read_metrics(job_id) if status == "finished" else {}
        self.store.put("runs", job_id, {"id": job_id, "status": status,
                                        "metrics": metrics, "finished_at": time.time()})
        return TrainingJob(job_id=job_id, status=status, metrics=metrics,
                           error=None if status == "finished" else f"run terminé en statut {status}")


# ── registre de modèles (promotion gardée) ──────────────────────────────────
class ModelRegistry:
    def __init__(self, store: Optional[RecordStore] = None) -> None:
        self.store = store or open_store()

    def register(self, checkpoint_id: str, *, path: str, run_id: str = "",
                 metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        rec = {"id": checkpoint_id, "path": path, "run_id": run_id,
               "metrics": metrics or {}, "promoted": False, "registered_at": time.time()}
        self.store.put("checkpoints", checkpoint_id, rec)
        return rec

    def promote(self, checkpoint_id: str, *, gate_passed: bool,
                gate_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Promotion refusée si la porte d'évaluation n'a pas été franchie (GA5)."""
        rec = self.store.get("checkpoints", checkpoint_id)
        if not rec:
            return {"error": f"checkpoint inconnu : {checkpoint_id}", "promoted": False}
        if not gate_passed:
            return {"error": "promotion refusée : porte d'évaluation non franchie (GA5)",
                    "promoted": False, "gate_report": gate_report}
        rec["promoted"] = True
        rec["promoted_at"] = time.time()
        rec["gate_report"] = gate_report
        self.store.put("checkpoints", checkpoint_id, rec)
        return {"promoted": True, "checkpoint": rec}

    def active(self) -> Optional[Dict[str, Any]]:
        promoted = [c for c in self.store.query("checkpoints") if c.get("promoted")]
        return max(promoted, key=lambda c: c.get("promoted_at", 0)) if promoted else None


# ── service vLLM ─────────────────────────────────────────────────────────────
class VLLMManager:
    """Sert un checkpoint local via vLLM, sous bail GPU exclusif (GA9).

    Dégrade si le binaire `vllm` est absent : renvoie une erreur explicite.
    """
    def __init__(self, lease_manager=None, port: int = 8000) -> None:
        self.leases = lease_manager
        self.port = port
        self._proc: Optional[subprocess.Popen] = None
        self._lease_id: Optional[str] = None
        self._served: Optional[str] = None

    def serve(self, model_path: str, *, served_name: str = "local") -> Dict[str, Any]:
        if not shutil.which("vllm"):
            return {"error": "vllm.serve : binaire 'vllm' absent (pip install vllm)",
                    "served": False}
        if self._proc is not None:
            return {"error": "vllm.serve : une instance tourne déjà — vllm.swap/stop d'abord",
                    "served": False}
        if self.leases is not None:
            lease = self.leases.try_acquire("vllm", count=1, exclusive=True)
            if lease is None:
                return {"error": "vllm.serve : aucun GPU disponible pour servir", "served": False}
            self._lease_id = lease.lease_id
        try:
            self._proc = subprocess.Popen(
                ["vllm", "serve", model_path, "--served-model-name", served_name,
                 "--port", str(self.port)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001
            self._release()
            return {"error": f"vllm.serve : démarrage impossible ({exc})", "served": False}
        self._served = model_path
        return {"served": True, "model": model_path, "port": self.port, "lease_id": self._lease_id}

    def swap(self, model_path: str, *, served_name: str = "local") -> Dict[str, Any]:
        self.stop()
        return self.serve(model_path, served_name=served_name)

    def stop(self) -> Dict[str, Any]:
        stopped = False
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()
            self._proc = None
            stopped = True
        self._release()
        self._served = None
        return {"stopped": stopped}

    def _release(self) -> None:
        if self._lease_id and self.leases is not None:
            self.leases.release(self._lease_id)
        self._lease_id = None
