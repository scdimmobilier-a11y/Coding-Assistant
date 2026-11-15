"""nexus_unified.orchestrator — orchestrateur maître piloté par requête LLM (point 5).

Point 5 : un orchestrateur maître, et une requête LLM qui définit la tâche des
agents. `MasterOrchestrator.run(goal)` :

1. découvre les actions disponibles (nœuds du graphe composé, pack inclus) ;
2. demande à la passerelle LLM (le cerveau global, externe — points 3/4) de
   décomposer le but en tâches d'agents, chacune liée à UNE action du registre ;
3. valide le plan (aucune action hors registre, pas de cycle) ;
4. pour chaque tâche, vérifie l'autorisation (politique OPA via eval.gate /
   garde-fous) AVANT exécution, acquiert un bail GPU si le nœud l'exige, puis
   exécute la tâche sur le graphe ;
5. journalise succès et échecs dans le magasin d'apprentissage (point 8).

L'orchestrateur n'invente jamais d'action : le plan est contraint au registre.
Les actions irréversibles ou à risque restent soumises à la politique (GA7).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from nexus_compose.graph import ComposabilityGraph
from nexus_compose.orchestrator import Orchestrator

from .llm import LLMGateway, TaskPlan
from .accelerators import AcceleratorLeaseManager, LeaseError

logger = logging.getLogger(__name__)

# Actions irréversibles / à risque : refusées sauf règle de politique explicite (GA7).
RISKY_PREFIXES = ("oh.mcp_create_", )
RISKY_NODES = {"oh.sandbox_delete", "oh.conversation_delete", "ml.checkpoint_promote",
               "oh.secret_delete", "PRODUCTION"}


@dataclass
class StepOutcome:
    task_id: str
    action: str
    success: bool
    authorized: bool
    data: Any = None
    error: Optional[str] = None
    lease_id: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class RunOutcome:
    goal: str
    plan: TaskPlan
    steps: List[StepOutcome] = field(default_factory=list)
    success: bool = True
    context: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        ok = sum(1 for s in self.steps if s.success)
        return (f"MasterOrchestrator: but='{self.goal[:48]}' | plan={self.plan.source} | "
                f"{ok}/{len(self.steps)} tâches réussies")


class MasterOrchestrator:
    def __init__(self, graph: ComposabilityGraph, *,
                 gateway: Optional[LLMGateway] = None,
                 lease_manager: Optional[AcceleratorLeaseManager] = None,
                 authorizer: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
                 learning_store: Optional[Any] = None) -> None:
        self.graph = graph
        self.orch = Orchestrator(graph)
        self.gateway = gateway or LLMGateway()
        self.leases = lease_manager
        self.authorizer = authorizer or self._default_authorizer
        self.store = learning_store

    # ── actions disponibles ──────────────────────────────────────────────────
    def available_actions(self, *, phases: Optional[Set[str]] = None) -> List[str]:
        out = []
        for n in self.graph.nodes():
            if n.meta.virtual:
                continue
            if phases and n.meta.phase not in phases:
                continue
            out.append(n.meta.id)
        return out

    # ── exécution ────────────────────────────────────────────────────────────
    def run(self, goal: str, *, ctx: Optional[Dict[str, Any]] = None,
            phases: Optional[Set[str]] = None, context_note: Optional[str] = None,
            max_tasks: int = 12) -> RunOutcome:
        actions = self.available_actions(phases=phases)
        plan = self.gateway.plan_tasks(goal, available_actions=actions,
                                       context=context_note, max_tasks=max_tasks)
        plan.goal = goal
        shared = dict(ctx or {})
        outcome = RunOutcome(goal=goal, plan=plan, context=shared)

        for task in plan.tasks:
            step = self._run_task(task, shared)
            outcome.steps.append(step)
            if not step.success:
                outcome.success = False
            self._record(goal, task, step)
        return outcome

    def _run_task(self, task, shared: Dict[str, Any]) -> StepOutcome:
        t0 = time.monotonic()
        node = self.graph.node(task.action) if task.action in self.graph._nodes else None  # type: ignore
        if node is None:
            return StepOutcome(task.id, task.action, False, True,
                               error=f"action inconnue du registre : {task.action}")
        # 1. autorisation AVANT exécution (point 5 / GA7)
        if not self.authorizer(task.action, shared):
            return StepOutcome(task.id, task.action, False, False,
                               error=f"action non autorisée par la politique : {task.action}")
        # 2. bail GPU si le nœud l'exige
        lease_id = None
        if node.meta.resources.get("gpu") and self.leases is not None:
            try:
                lease = self.leases.acquire(holder=f"task:{task.id}",
                                            count=node.meta.resources["gpu"])
                lease_id = lease.lease_id
                shared.setdefault("gpu_lease", lease.to_dict())
                shared.update(lease.visibility_env)
            except LeaseError as exc:
                return StepOutcome(task.id, task.action, False, True,
                                   error=f"bail GPU indisponible : {exc}")
        # 3. exécution
        node_ctx = dict(shared, **(task.inputs or {}), instruction=task.goal or shared.get("instruction", ""))
        result = self.orch.run_node(task.action, node_ctx)
        if result.success and isinstance(result.data, dict):
            shared.update({k: v for k, v in result.data.items() if not k.startswith("_")})
            shared.setdefault("_results", {})[task.action] = result.data
        if lease_id and self.leases is not None:
            self.leases.release(lease_id)
        return StepOutcome(task.id, task.action, result.success, True, data=result.data,
                           error=result.error, lease_id=lease_id,
                           duration_ms=(time.monotonic() - t0) * 1000)

    # ── autorisation / apprentissage ─────────────────────────────────────────
    def _default_authorizer(self, action: str, ctx: Dict[str, Any]) -> bool:
        if action in RISKY_NODES or action.startswith(RISKY_PREFIXES):
            # Refusé par défaut : exige un drapeau de politique explicite dans ctx (GA7).
            return bool(ctx.get("policy_allow", {}).get(action)) or \
                   bool(ctx.get("allow_risky"))
        return True

    def _record(self, goal: str, task, step: StepOutcome) -> None:
        if self.store is None:
            return
        try:
            self.store.append("orchestration", {
                "goal": goal, "task_id": task.id, "action": task.action,
                "success": step.success, "authorized": step.authorized,
                "error": step.error, "ts": time.time()})
        except Exception:  # noqa: BLE001 — l'apprentissage est best-effort
            pass
