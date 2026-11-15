"""
nexus_vendor.q2d.generation.generate_api — Génération de diagrammes via API LLM
══════════════════════════════════════════════════════════════════════════════════

Orchestre la génération de diagrammes par lot en appelant un LLM via API.

Classes
────────
  Config(SubscriptableBaseModel)
    .prompt        : BasePrompt       — template de prompt (système + utilisateur)
    .engine        : Type[InferenceEngine] — classe du moteur d'inférence
    .engine_config : InferenceEngineConfig — paramètres du moteur (API key, modèle, etc.)
    .seed          : int = 42         — graine pour la reproductibilité

Fonctions
──────────
  generate(input_dataset, config) → list[dict]
      Génère des diagrammes pour un batch d'entrées.
      Algorithme :
        1. seed_everything(config.seed)      — fixe la graine aléatoire
        2. Construit messages_batch          — applique les templates de prompts
        3. engine.generate_batched(batch)    — appels API parallèles
        4. Fusionne entrée + sortie          — retourne input + "output" JSON
      Chaque item du dataset doit avoir les champs attendus par le prompt.
      Chaque item de retour contient tous les champs source + "output" (graphe JSON).
"""
from typing import Any, Dict, List, Type

from nexus_vendor.q2d.common.types import SubscriptableBaseModel
from nexus_vendor.q2d.common.utils import apply_template, seed_everything
from nexus_vendor.q2d.generation.generate_utils import InferenceEngine, InferenceEngineConfig
from nexus_vendor.q2d.generation.prompts import BasePrompt


class Config(SubscriptableBaseModel):
    prompt: BasePrompt
    engine: Type[InferenceEngine]
    engine_config: InferenceEngineConfig
    seed: int = 42


def generate(input_dataset: List[Dict[str, Any]], config: Config) -> List[Dict[str, Any]]:
    seed_everything(config.seed)

    messages_batch = [
        apply_template(
            system_prompt_template=config.prompt.system_prompt_template,
            user_prompt_template=config.prompt.user_prompt_template,
            user_prompt_kwargs=data,
        )
        for data in input_dataset
    ]

    engine = config.engine(config.engine_config)
    generated_outputs = engine.generate_batched(messages_batch)

    generated_output_json = [
        {
            **data,
            "output": output.get_output(),
        }
        for data, output in zip(input_dataset, generated_outputs)
    ]

    return generated_output_json
