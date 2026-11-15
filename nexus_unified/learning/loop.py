"""nexus_unified.learning — apprentissage par succès ET échecs après requête LLM (point 8).

Point 8 : l'apprentissage vient des échecs et des succès des agents, après que
la requête LLM a défini leurs tâches (point 5). Ce module ferme la boucle :

1. l'orchestrateur maître exécute un but (le LLM décompose en tâches d'agents) ;
2. chaque tâche produit un pas de **trajectoire** (action, succès/échec,
   récompense, observation) ;
3. les trajectoires de **succès** et d'**échec** sont stockées SÉPARÉMENT
   (magasin open source, point 7) — comme la RetrievalMemory de SkillRL ;
4. quand le taux d'échec d'une catégorie de tâche dépasse un seuil, une
   **distillation** (via la passerelle LLM) produit des leçons : compétences
   générales, compétences spécifiques à la tâche, erreurs courantes ;
5. ces compétences sont réinjectées dans le contexte de la requête suivante
   (boucle contexte), sans toucher aux poids — séparation « boucle poids /
   boucle contexte » du blueprint SkillRL de l'utilisateur.

La « boucle poids » (RL par GiGPO/verl) est distincte et vit dans OpenManus-RL ;
ici c'est la boucle contexte, exploitable sans GPU.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..llm import LLMGateway
from ..store import RecordStore, open_store


@dataclass
class TrajStep:
    action: str
    success: bool
    reward: float
    observation: str = ""
    error: Optional[str] = None


@dataclass
class Trajectory:
    goal: str
    category: str
    steps: List[TrajStep] = field(default_factory=list)
    total_reward: float = 0.0
    outcome: str = "unknown"     # success | failure
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {"goal": self.goal, "category": self.category, "outcome": self.outcome,
                "total_reward": self.total_reward, "ts": self.ts,
                "steps": [vars(s) for s in self.steps]}


class SkillBank:
    """Banque de compétences hiérarchique (SkillRL) : générales / spécifiques /
    erreurs courantes. Persistée dans le magasin."""

    def __init__(self, store: RecordStore) -> None:
        self.store = store

    def add_general(self, text: str, source: str = "") -> str:
        return self.store.append("skills_general", {"text": text, "source": source})

    def add_task_specific(self, category: str, text: str, source: str = "") -> str:
        return self.store.append("skills_task", {"category": category, "text": text, "source": source})

    def add_mistake(self, category: str, text: str, source: str = "") -> str:
        return self.store.append("skills_mistakes", {"category": category, "text": text, "source": source})

    def retrieve(self, category: str, k: int = 5) -> Dict[str, List[str]]:
        gen = [r["text"] for r in self.store.query("skills_general", limit=k)]
        spec = [r["text"] for r in self.store.query("skills_task", {"category": category}, limit=k)]
        mist = [r["text"] for r in self.store.query("skills_mistakes", {"category": category}, limit=k)]
        return {"general": gen, "task_specific": spec, "common_mistakes": mist}

    def as_context(self, category: str, k: int = 5) -> str:
        s = self.retrieve(category, k)
        parts = []
        if s["general"]:
            parts.append("Compétences générales:\n" + "\n".join(f"- {t}" for t in s["general"]))
        if s["task_specific"]:
            parts.append(f"Compétences pour '{category}':\n" + "\n".join(f"- {t}" for t in s["task_specific"]))
        if s["common_mistakes"]:
            parts.append("Erreurs à éviter:\n" + "\n".join(f"- {t}" for t in s["common_mistakes"]))
        return "\n\n".join(parts)


class LearningLoop:
    """Exécute un but, apprend de la trajectoire (succès et échecs), distille.

    `master` : MasterOrchestrator (ou objet avec .run(goal, ctx, context_note)).
    """

    def __init__(self, master: Any, *, store: Optional[RecordStore] = None,
                 gateway: Optional[LLMGateway] = None,
                 fail_threshold: float = 0.5, min_episodes: int = 3) -> None:
        self.master = master
        self.store = store or open_store()
        self.bank = SkillBank(self.store)
        self.gateway = gateway or LLMGateway()
        self.fail_threshold = fail_threshold
        self.min_episodes = min_episodes

    # ── un épisode ───────────────────────────────────────────────────────────
    def run_episode(self, goal: str, *, category: Optional[str] = None,
                    ctx: Optional[Dict[str, Any]] = None) -> Trajectory:
        category = category or _category_of(goal)
        # boucle contexte : on injecte les compétences apprises dans la requête
        skills_ctx = self.bank.as_context(category)
        outcome = self.master.run(goal, ctx=ctx, context_note=skills_ctx or None)

        traj = Trajectory(goal=goal, category=category)
        for s in outcome.steps:
            reward = self._step_reward(s)
            traj.steps.append(TrajStep(
                action=s.action, success=s.success, reward=reward,
                observation=_obs(s.data), error=s.error))
            traj.total_reward += reward
        traj.outcome = "success" if outcome.success and traj.steps else "failure"

        # stockage SÉPARÉ succès / échec (RetrievalMemory SkillRL)
        coll = "traj_success" if traj.outcome == "success" else "traj_failure"
        self.store.append(coll, traj.to_dict())

        # distillation si le taux d'échec de la catégorie dépasse le seuil
        self._maybe_distill(category)
        return traj

    def _step_reward(self, step) -> float:
        if isinstance(step.data, dict) and isinstance(step.data.get("reward"), (int, float)):
            return float(step.data["reward"])
        return 1.0 if step.success else 0.0

    # ── distillation (compétences + erreurs) ─────────────────────────────────
    def _maybe_distill(self, category: str) -> Optional[Dict[str, Any]]:
        fails = self.store.query("traj_failure", {"category": category}, limit=1000)
        succ = self.store.query("traj_success", {"category": category}, limit=1000)
        total = len(fails) + len(succ)
        if total < self.min_episodes:
            return None
        fail_rate = len(fails) / total if total else 0.0
        if fail_rate < self.fail_threshold:
            # succès : distille une compétence réutilisable du dernier succès
            if succ:
                self._distill_success(category, succ[-1])
            return None
        # échecs : distille une leçon et une erreur courante
        return self._distill_failure(category, fails[-self.min_episodes:])

    def _distill_failure(self, category: str, episodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary = "\n\n".join(
            f"ÉCHEC: {e['goal']}\n" + "\n".join(
                f"  {s['action']} -> {'ok' if s['success'] else 'échec'}"
                + (f" ({s['error']})" if s.get('error') else "")
                for s in e["steps"])
            for e in episodes)
        prompt = (
            f"Catégorie de tâche: {category}\nVoici des épisodes d'agents qui ont ÉCHOUÉ:\n\n"
            f"{summary}\n\nEn 4 points maximum, rédige : (1) une erreur courante à éviter, "
            f"(2) une compétence spécifique à cette catégorie pour réussir la prochaine fois. "
            f'Réponds en JSON : {{"mistake": "...", "skill": "..."}}')
        res = self.gateway.chat([{"role": "user", "content": prompt}],
                                max_tokens=400, temperature=0.0, json_mode=True)
        mistake, skill = self._parse_lesson(res, episodes, category)
        ids = {}
        if mistake:
            ids["mistake"] = self.bank.add_mistake(category, mistake, source="distill_failure")
        if skill:
            ids["skill"] = self.bank.add_task_specific(category, skill, source="distill_failure")
        return {"distilled": "failure", "category": category, **ids}

    def _distill_success(self, category: str, episode: Dict[str, Any]) -> Dict[str, Any]:
        actions = " → ".join(s["action"] for s in episode["steps"])
        skill = f"Séquence efficace pour '{category}' : {actions}"
        sid = self.bank.add_task_specific(category, skill, source="distill_success")
        return {"distilled": "success", "skill_id": sid}

    def _parse_lesson(self, res, episodes, category):
        if res.ok and res.text:
            from ..llm.gateway import _extract_json
            obj = _extract_json(res.text)
            if isinstance(obj, dict):
                return obj.get("mistake", ""), obj.get("skill", "")
        # repli déterministe sans LLM : leçon tirée des actions en échec
        failed = [s["action"] for e in episodes for s in e["steps"] if not s["success"]]
        common = failed[0] if failed else ""
        mistake = f"L'action '{common}' échoue souvent pour '{category}' — vérifier ses préconditions." if common else ""
        return mistake, ""

    # ── statistiques ─────────────────────────────────────────────────────────
    def stats(self, category: Optional[str] = None) -> Dict[str, Any]:
        where = {"category": category} if category else None
        succ = self.store.count("traj_success", where)
        fail = self.store.count("traj_failure", where)
        total = succ + fail
        return {"category": category, "success": succ, "failure": fail,
                "total": total, "success_rate": (succ / total) if total else 0.0}


def _category_of(goal: str) -> str:
    g = goal.lower()
    for key in ("entraîn", "train", "model", "modèle"):
        if key in g:
            return "training"
    for key in ("recherche", "search", "données", "data"):
        if key in g:
            return "research"
    for key in ("code", "implément", "bug", "test"):
        if key in g:
            return "coding"
    return "general"


def _obs(data: Any) -> str:
    if isinstance(data, dict):
        for k in ("output", "verdict", "reward", "error"):
            if k in data:
                return f"{k}={str(data[k])[:120]}"
    return ""
