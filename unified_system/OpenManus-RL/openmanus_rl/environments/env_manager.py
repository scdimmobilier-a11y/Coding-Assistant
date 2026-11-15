from typing import List, Tuple, Dict, Union, Any, Optional
from collections import defaultdict
import torch
import numpy as np
from functools import partial
import os
from openmanus_rl.environments.prompts import *
from openmanus_rl.environments.base import EnvironmentManagerBase, to_numpy
from openmanus_rl.memory import SimpleMemory, SummarizedMemory

def parse_gamefile(infos):
    gamefile = []
    for info in infos:
        if 'extra.gamefile' in info:
            gamefile.append(info['extra.gamefile'])
        else:
            gamefile.append(None)
    return gamefile

def set_gamefile(infos, gamefile):
    for i in range(len(infos)):
        if 'extra.gamefile' in infos[i]:
            infos[i]['extra.gamefile'] = gamefile[i]
        else:
            infos[i]['extra.gamefile'] = None
    return infos


class AlfWorldEnvironmentManager(EnvironmentManagerBase):
    def __init__(self, envs, projection_f, config):
        # Choose memory type based on config
        if hasattr(config.env, 'use_summary') and config.env.use_summary:
            self.memory = SummarizedMemory()
        else:
            self.memory = SimpleMemory()
        super().__init__(envs, projection_f, config)
        self.step_counts = defaultdict(int)  # Track step count for each environment
    
    def reset(self):
        text_obs, image_obs, infos = self.envs.reset()
        self.gamefile = parse_gamefile(infos)
        # initialize the history buffer
        self.memory.reset(batch_size = len(text_obs))
        self.tasks = []
        self.pre_text_obs = text_obs
        self.extract_task(text_obs)
        
        # Reset step counts
        for i in range(len(text_obs)):
            self.step_counts[i] = 0

        full_text_obs = self.build_text_obs(text_obs, self.envs.get_admissible_commands, init=True)
        return {'text': full_text_obs, 'image': image_obs, 'anchor': text_obs}, infos
    
    def step(self, text_actions: List[str]):
        actions, valids = self.projection_f(text_actions, self.envs.get_admissible_commands)
        text_obs, image_obs, rewards, dones, infos = self.envs.step(actions)
        
        # Always store previous observation and action to memory (step 0 becomes history for step 1)
        self.memory.store({'text_obs': self.pre_text_obs, 'action': actions})
        self.pre_text_obs = text_obs

        # Increment step counts BEFORE building observations for correct feedback injection timing
        for i in range(len(text_actions)):
            self.step_counts[i] += 1
            
        # Build text observations with history (init=False means use history template)
        full_text_obs = self.build_text_obs(text_obs, self.envs.get_admissible_commands, init=False)
            
        if infos[0].get("extra.gamefile") is None:
            infos = set_gamefile(infos, self.gamefile)

        # add action_valid to infos
        for i, info in enumerate(infos):
            info['is_action_valid'] = to_numpy(valids[i])

        next_observations = {'text': full_text_obs, 'image': image_obs, 'anchor': text_obs}
        rewards = to_numpy(rewards)
        dones = to_numpy(dones)

        return next_observations, rewards, dones, infos
    
    def extract_task(self, text_obs: List[str]):
        for obs in text_obs:
            task_start = obs.find('Your task is to: ')
            
            if task_start != -1:
                self.tasks.append(obs[task_start + len('Your task is to: '):].strip())
            else:
                raise ValueError("Task description not found in text observation.")
        

    def build_text_obs(self, text_obs: List[str], admissible_actions: List[List[str]], init: bool = False) -> List[str]:
        """
        This function builds the text observation for the agent.
        """
        postprocess_text_obs = []
        if not init and self.config.env.history_length > 0:
            # Check if using summary mode
            use_summary = hasattr(self.config.env, 'use_summary') and self.config.env.use_summary
            
            if use_summary:
                memory_contexts, valid_lens = self.memory.fetch(
                    self.config.env.history_length,
                    obs_key="text_obs",
                    action_key="action",
                    use_summary=True,
                    summary_api_key=getattr(self.config.env, 'summary_api_key', None),
                    summary_endpoint=getattr(self.config.env, 'summary_endpoint', None)
                )
            else:
                memory_contexts, valid_lens = self.memory.fetch(
                    self.config.env.history_length,
                    obs_key="text_obs",
                    action_key="action"
                )
            
        for i in range(len(text_obs)):
            # exclude 'help' in admissible_actions[i]
            reformatted_admissible_actions = "\n ".join(f"'{s}'" for s in admissible_actions[i] if s != 'help')

            # Determine which trajectory step this observation corresponds to
            current_step_index = self.step_counts.get(i, 0)

            debugger_feedback = self.get_debugger_feedback(i, current_step_index)
            persistent_guidance = self.get_persistent_guidance(i, current_step_index)

            if init or self.config.env.history_length <= 0:
                # Include task_description to satisfy ALFWORLD_TEMPLATE_NO_HIS placeholders.
                obs = ALFWORLD_TEMPLATE_NO_HIS.format(
                    task_description=self.tasks[i],
                    current_observation=text_obs[i],
                    admissible_actions=reformatted_admissible_actions,
                )
            else:
                obs = ALFWORLD_TEMPLATE.format(
                    task_description=self.tasks[i],
                    step_count=len(self.memory[i]),
                    history_length=valid_lens[i],
                    action_history=memory_contexts[i],
                    current_step=len(self.memory[i]) + 1,
                    current_observation=text_obs[i],
                    admissible_actions=reformatted_admissible_actions
                )
            
            # Inject debugger feedback if available
            if debugger_feedback:
                obs = obs + "\n\n" + debugger_feedback

            if persistent_guidance:
                obs = obs + "\n\n" + persistent_guidance

            postprocess_text_obs.append(obs)
        return postprocess_text_obs

    def _process_batch(self, batch_idx, total_batch_list, total_infos, success):
        # Find the last entry with active masks
        for i in reversed(range(len(total_batch_list[batch_idx]))):
            batch_item = total_batch_list[batch_idx][i]
            if batch_item['active_masks']:
                info = total_infos[batch_idx][i]
                won_value = float(info['won'])
                success['success_rate'].append(won_value)
                
                # Process game file if it exists
                gamefile = info.get("extra.gamefile")
                if gamefile:
                    self._process_gamefile(gamefile, won_value, success)
                return  # Exit after finding the first active mask

    def _process_gamefile(self, gamefile, won_value, success):
        tasks = [
            "pick_and_place",
            "pick_two_obj_and_place",
            "look_at_obj_in_light",
            "pick_heat_then_place_in_recep",
            "pick_cool_then_place_in_recep",
            "pick_clean_then_place_in_recep",
        ]
        
        for task in tasks:
            if task in gamefile:
                success[f"{task}_success_rate"].append(won_value)
                break


class WebshopEnvironmentManager(EnvironmentManagerBase):
    def __init__(self, envs, projection_f, config):
        # Choose memory type based on config
        if hasattr(config.env, 'use_summary') and config.env.use_summary:
            self.memory = SummarizedMemory()
        else:
            self.memory = SimpleMemory()
        super().__init__(envs, projection_f, config)
        self.step_counts = defaultdict(int)  # Track step count for each environment
    
    def reset(self, session_indices: Optional[List[int]] = None) -> Dict[str, Any]:
        obs, infos = self.envs.reset(session_indices=session_indices)
        self.tasks = self.extract_task(obs)
        obs = self.format_obs(obs)
        # infos = [None] * self.envs.num_envs
        observations = {'text': self.build_text_obs(obs, infos, init=True), 
                        'image': None, 
                        'anchor': obs.copy()
                        }
        self.pre_text_obs = obs
        self.memory.reset(batch_size = len(infos))
        
        # Reset step counts
        for i in range(len(obs)):
            self.step_counts[i] = 0
            
        return observations, infos

    def step(self, text_actions: List[str]):
        actions, valids = self.projection_f(text_actions)
        next_obs, rewards, dones, infos = self.envs.step(actions)

        next_obs = self.format_obs(next_obs)
        
        # Always store previous observation and action to memory (step 0 becomes history for step 1)
        self.memory.store({'text_obs': self.pre_text_obs, 'action': actions})
        self.pre_text_obs = next_obs

        # Increment step counts BEFORE building observations for correct feedback injection timing
        for i in range(len(text_actions)):
            self.step_counts[i] += 1
        
        # Build text observations with history (init=False means use history template)
        next_observations = {
            'text': self.build_text_obs(next_obs, infos, init=False),
            'image': None,
            'anchor': next_obs.copy()
        }
            
        # add action_valid to infos
        for i, info in enumerate(infos):
            info['is_action_valid'] = to_numpy(valids[i])

        rewards = to_numpy(rewards)
        dones = to_numpy(dones)
        
        return next_observations, rewards, dones, infos

    def extract_task(self, text_obs: List[str]):
        tasks = []
        for obs in text_obs:
            parts = obs.split(" [SEP] ")
            assert parts[1]=='Instruction:'
            tasks.append(parts[2])
        return tasks
    
    def format_obs(self, text_obs):
        postprocess_text_obs = []
        for i in range(len(text_obs)):
            parts = text_obs[i].split(" [SEP] ")
            # the index of self.tasks[i] in parts
            try:
                index = parts.index(self.tasks[i])
                reformatted_obs = " [SEP] ".join(f"'{p}'" for p in parts[index+1:])
            except:
                reformatted_obs = text_obs[i]

            postprocess_text_obs.append(reformatted_obs)

        return postprocess_text_obs
    
    def format_avail_actions(self, avail):
        actions = []

        for key in avail.keys():
            if key not in ["has_search_bar", "clickables"]:
                raise ValueError(f"Unknown key in available actions: {key}")

        if avail["has_search_bar"]:
            actions.append("search[<your query>]")

        for txt in avail["clickables"]:
            actions.append(f"click[{txt}]")

        return actions
            
    def build_text_obs(self, text_obs: List[str], infos: List[List[str]], init: bool = False) -> List[str]:
        """
        This function builds the text observation for the agent.
        """
        postprocess_text_obs = []
        if not init and self.config.env.history_length > 0:
            # Check if using summary mode
            use_summary = hasattr(self.config.env, 'use_summary') and self.config.env.use_summary
            if use_summary:
                memory_contexts, valid_lens = self.memory.fetch(
                    self.config.env.history_length,
                    obs_key="text_obs",
                    action_key="action",
                    use_summary=True,
                    summary_api_key=getattr(self.config.env, 'summary_api_key', None),
                    summary_endpoint=getattr(self.config.env, 'summary_endpoint', None),
                )
            else:
                memory_contexts, valid_lens = self.memory.fetch(
                    self.config.env.history_length,
                    obs_key="text_obs",
                    action_key="action")
            
        for i in range(len(text_obs)):

            available_actions = self.format_avail_actions(infos[i]['available_actions'])
            reformatted_available_actions = "\n".join(f"'{s}'," for s in available_actions)

            current_step_index = self.step_counts.get(i, 0)
            debugger_feedback = self.get_debugger_feedback(i, current_step_index)
            persistent_guidance = self.get_persistent_guidance(i, current_step_index)

            if init or self.config.env.history_length <= 0:
                obs = WEBSHOP_TEMPLATE_NO_HIS.format(
                    task_description=self.tasks[i],
                    current_observation=text_obs[i],
                    available_actions=reformatted_available_actions
                )
            else:
                obs = WEBSHOP_TEMPLATE.format(
                    task_description=self.tasks[i],
                    step_count=len(self.memory[i]),
                    history_length=valid_lens[i],
                    action_history=memory_contexts[i],
                    current_step=len(self.memory[i]) + 1,
                    current_observation=text_obs[i],
                    available_actions=reformatted_available_actions
                )
                if len(obs) > 13000:
                    print(f"Warning len(obs)={len(obs)} is too long")
                    obs = WEBSHOP_TEMPLATE_NO_HIS.format(
                        task_description=self.tasks[i],
                        current_observation=text_obs[i],
                        available_actions=reformatted_available_actions
                    )
            
            # Inject debugger feedback if available
            if debugger_feedback:
                obs = obs + "\n\n" + debugger_feedback

            if persistent_guidance:
                obs = obs + "\n\n" + persistent_guidance

            postprocess_text_obs.append(obs)

        return postprocess_text_obs

    def _process_batch(self, batch_idx, total_batch_list, total_infos, success):
        for i in reversed(range(len(total_batch_list[batch_idx]))):
            batch_item = total_batch_list[batch_idx][i]
            if batch_item['active_masks']:
                info = total_infos[batch_idx][i]
                won_value = float(info['won'])
                score_value = float(info['task_score'])
                success['success_rate'].append(won_value)
                success['webshop_task_score (not success_rate)'].append(score_value)
                return


def make_envs(config):
    """
    Create enviroments 
    """ 
    # check if config.env.rollout.n is an integer
    if not isinstance(config.env.rollout.n, int):
        raise ValueError("config.env.rollout.n should be an integer")
    group_n = config.env.rollout.n if config.env.rollout.n > 0 else 1

    if "alfworld" in config.env.env_name.lower():
        from openmanus_rl.environments.env_package.alfworld import build_alfworld_envs, alfworld_projection
        if config.env.env_name == 'alfworld/AlfredThorEnv':
            alf_config_path = os.path.join(os.path.dirname(__file__), 'env_package/alfworld/configs/config_tw.yaml')
        elif config.env.env_name == 'alfworld/AlfredTWEnv':
            alf_config_path = os.path.join(os.path.dirname(__file__), 'env_package/alfworld/configs/config_tw.yaml')
        else:
            raise ValueError(f"Unsupported environment: {config.env.env_name}")

        env_kwargs = {
            'eval_dataset': 'eval_in_distribution', # 'eval_in_distribution' or 'eval_out_of_distribution'
        }
        _envs = build_alfworld_envs(alf_config_path, config.env.seed, config.data.train_batch_size, group_n, is_train=True, env_kwargs=env_kwargs)
        _val_envs = build_alfworld_envs(alf_config_path, config.env.seed + 1000, config.data.val_batch_size, 1, is_train=False, env_kwargs=env_kwargs)
        
        projection_f = partial(alfworld_projection)
        envs = AlfWorldEnvironmentManager(_envs, projection_f, config)
        val_envs = AlfWorldEnvironmentManager(_val_envs, projection_f, config)
        return envs, val_envs

    elif "webshop" in config.env.env_name.lower():
        from openmanus_rl.environments.env_package.webshop import build_webshop_envs, webshop_projection
        if config.env.webshop.use_small:
            file_path = os.path.join(os.path.dirname(__file__), 'env_package/webshop/webshop/data/items_shuffle_1000.json')
            attr_path = os.path.join(os.path.dirname(__file__), 'env_package/webshop/webshop/data/items_ins_v2_1000.json')
        else:
            file_path = os.path.join(os.path.dirname(__file__), 'env_package/webshop/webshop/data/items_shuffle.json')
            attr_path = os.path.join(os.path.dirname(__file__), 'env_package/webshop/webshop/data/items_ins_v2.json')
        env_kwargs = {
                    'observation_mode': 'text', 
                    'num_products': None, 
                    'human_goals': config.env.webshop.human_goals,
                    'file_path': file_path,
                    'attr_path': attr_path
                    }
        _envs = build_webshop_envs(seed=config.env.seed, env_num=config.data.train_batch_size, group_n=group_n, is_train=True, env_kwargs=env_kwargs)
        _val_envs = build_webshop_envs(seed=config.env.seed + 1000, env_num=config.data.val_batch_size, group_n=1, is_train=False, env_kwargs=env_kwargs)

        projection_f = partial(webshop_projection)
        envs = WebshopEnvironmentManager(_envs, projection_f, config)
        val_envs = WebshopEnvironmentManager(_val_envs, projection_f, config)
        import time
        time.sleep((config.data.train_batch_size * group_n + config.data.val_batch_size) * 0.1) # wait for the envs to be ready
        return envs, val_envs
    elif "tool_use" in config.env.env_name.lower():
        from openmanus_rl.environments.env_package.tool_use.envs import build_tool_use_envs
        from openmanus_rl.environments.env_package.tool_use.projection import tool_use_projection
        from openmanus_rl.environments.env_package.tool_use.manager import ToolUseEnvironmentManager
        
        # Load task data
        import json
        data_path = getattr(config.env, 'data_path', 'data/gaia/val.json')
        with open(data_path, 'r') as f:
            tasks_data = json.load(f)
        
        # Get available tools from config
        available_tools = getattr(config.env, 'available_tools', [
            'google_search', 'wikipedia_knowledge_searcher', 'arxiv_paper_searcher'
        ])
        
        # Build environments
        tool_llm_config = getattr(config.env, 'tool_llm_config', None)

        _envs = build_tool_use_envs(
            tasks_data=tasks_data,
            available_tools=available_tools,
            seed=config.env.seed,
            env_num=config.data.train_batch_size,
            group_n=group_n,
            is_train=True,
            tool_llm_config=tool_llm_config,
        )
        _val_envs = build_tool_use_envs(
            tasks_data=tasks_data,
            available_tools=available_tools,
            seed=config.env.seed + 1000,
            env_num=config.data.val_batch_size,
            group_n=1,
            is_train=False,
            tool_llm_config=tool_llm_config,
        )
        
        projection_f = partial(tool_use_projection)
        envs = ToolUseEnvironmentManager(_envs, projection_f, config)
        val_envs = ToolUseEnvironmentManager(_val_envs, projection_f, config)
        return envs, val_envs
    else:
        print("Environment not supported")
        exit(1)


# ──────────────────────────────────────────────────────────────────────────────
# UNIFIED SYSTEM — OpenHands environment manager
# Wraps the OpenHands REST API as a vectorised RL environment.
# Each "env slot" is one OpenHands conversation (sandbox session).
# Observations = the last agent message content.
# Rewards      = 1.0 if the task was marked successful, 0.0 otherwise.
# ──────────────────────────────────────────────────────────────────────────────

import time
import uuid
import json as _json

try:
    from crewai_tools.security.safe_requests import safe_get, create_safe_session
    _SAFE_REQUESTS_AVAILABLE = True
except ImportError:
    _SAFE_REQUESTS_AVAILABLE = False


class OpenHandsEnvironmentManager(EnvironmentManagerBase):
    """RL environment backed by the OpenHands conversation API.

    Each parallel "env slot" maps to one OpenHands conversation.  The manager
    creates conversations on reset, sends messages on step, and polls the
    conversation status to derive scalar rewards.

    Args:
        config: standard OpenManus-RL config object.  Expected extra keys::

            config.env.openhands_base_url   str   e.g. "http://localhost:3000"
            config.env.openhands_token      str   bearer token (or empty)
            config.env.openhands_timeout    int   seconds to wait for agent (default 120)

        n_envs: number of parallel conversation slots.
    """

    # ── Constants ─────────────────────────────────────────────────────────

    _POLL_INTERVAL = 2   # seconds between status polls
    _DEFAULT_TIMEOUT = 120

    def __init__(self, config, n_envs: int = 1) -> None:
        # EnvironmentManagerBase expects (envs, projection_f, config).
        # We pass lightweight sentinels because we manage our own I/O.
        super().__init__(
            envs=None,          # not used — we call REST directly
            projection_f=None,  # not used
            config=config,
        )
        self.n_envs = n_envs
        self._base_url: str = getattr(config.env, "openhands_base_url", "http://localhost:3000").rstrip("/")
        self._token: str = getattr(config.env, "openhands_token", "")
        self._timeout: int = int(getattr(config.env, "openhands_timeout", self._DEFAULT_TIMEOUT))

        # conversation_ids[i] holds the active OpenHands conversation id for slot i
        self._conversation_ids: List[Optional[str]] = [None] * n_envs
        self._last_obs: List[str] = [""] * n_envs
        self._done: List[bool] = [True] * n_envs

        # Use crewAI SSRF-safe session when available, else plain requests
        if _SAFE_REQUESTS_AVAILABLE:
            self._session = create_safe_session()
        else:
            import requests
            self._session = requests.Session()

        if self._token:
            self._session.headers["Authorization"] = f"Bearer {self._token}"
        self._session.headers["Content-Type"] = "application/json"

    # ── Internal helpers ───────────────────────────────────────────────────

    def _api(self, method: str, path: str, **kwargs) -> dict:
        """Make an API call to OpenHands and return the JSON body."""
        url = f"{self._base_url}{path}"
        resp = self._session.request(method, url, **kwargs)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {}

    # ── API OpenHands V1 (corrigé — constat lot 0) ────────────────────────
    # L'ancien code parlait l'API V0 (/api/conversations), absente du serveur
    # V1 fourni dans le système. Les trois méthodes ci-dessous utilisent les
    # vraies routes V1 ; la tâche est transmise DÈS la création (le message
    # initial est un SendMessageRequest), et l'observation initiale EST la
    # tâche — pas une chaîne générique — pour que l'ancrage GiGPO
    # (build_step_group) regroupe les observations par tâche, et non par un
    # identifiant de conversation unique (constat, défaut d'ancrage).
    @staticmethod
    def _v1_message(text: str) -> dict:
        return {"role": "user", "content": [{"type": "text", "text": text}], "run": True}

    def _create_conversation(self, task: str = "") -> str:
        """Démarre une conversation V1, en transmettant la tâche."""
        body = {"initial_message": self._v1_message(task)} if task else {}
        data = self._api("POST", "/api/v1/app-conversations", json=body)
        return (data.get("conversation_id") or data.get("id")
                or (data.get("conversation") or {}).get("id") or str(uuid.uuid4()))

    def _send_message(self, conv_id: str, text: str) -> None:
        """Envoie un message (content = liste de blocs, schéma V1)."""
        self._api(
            "POST",
            f"/api/v1/app-conversations/{conv_id}/send-message",
            json=self._v1_message(text),
        )

    def _poll_until_done(self, conv_id: str) -> tuple:
        """Interroge la conversation V1 jusqu'à la fin de l'agent.

        Statut via `execution_status` (V1) ; dernier message agent via la
        recherche d'événements. Retourne (dernier_message, succès)."""
        deadline = time.time() + self._timeout
        last_text = ""
        terminal = {"finished", "completed", "stopped", "error", "idle", "awaiting_user_input"}
        ok_states = {"finished", "completed", "idle", "awaiting_user_input"}
        while time.time() < deadline:
            try:
                data = self._api("GET", "/api/v1/app-conversations",
                                 params={"conversation_id": conv_id})
                conv = self._first_matching(data, conv_id)
                status = str((conv or {}).get("execution_status", "")).lower()
                ev = self._api("GET", f"/api/v1/conversation/{conv_id}/events/search",
                               params={"limit": 100})
                last_text = self._last_agent_text(ev) or last_text
                if status in terminal:
                    return last_text, status in ok_states
            except Exception:
                pass
            time.sleep(self._POLL_INTERVAL)
        return last_text, False  # timeout → échec

    @staticmethod
    def _first_matching(data, conv_id):
        items = data if isinstance(data, list) else (
            data.get("items") or data.get("conversations") or [data]) if isinstance(data, dict) else []
        for c in items:
            if isinstance(c, dict) and str(c.get("id") or c.get("conversation_id")) == conv_id:
                return c
        return items[0] if items and isinstance(items[0], dict) else {}

    @staticmethod
    def _last_agent_text(data) -> str:
        items = data if isinstance(data, list) else (
            data.get("items") or data.get("events") or []) if isinstance(data, dict) else []
        for ev in reversed(items):
            if not isinstance(ev, dict):
                continue
            if (ev.get("source") or ev.get("role")) in ("agent", "assistant"):
                msg = ev.get("message") or ev.get("content") or ev.get("text") or ""
                if isinstance(msg, list):
                    msg = " ".join(p.get("text", "") for p in msg if isinstance(p, dict))
                if msg:
                    return str(msg)
        return ""

    # ── EnvironmentManagerBase interface ──────────────────────────────────

    def reset(self, tasks: Optional[List[str]] = None):
        """Crée des conversations fraîches, seedées avec leur tâche.

        `tasks[i]` est la consigne du slot i ; à défaut, on réutilise la
        dernière observation connue. L'observation initiale EST la tâche, pour
        un ancrage GiGPO par tâche (pas par identifiant de conversation)."""
        obs_texts = []
        infos = []
        tasks = tasks or getattr(self, "tasks", None) or [""] * self.n_envs
        for i in range(self.n_envs):
            task = tasks[i] if i < len(tasks) else ""
            conv_id = self._create_conversation(task)
            self._conversation_ids[i] = conv_id
            self._done[i] = False
            # l'ancre est la TÂCHE (observation), pas l'id de conversation
            obs_texts.append(task or f"OpenHands task {i}")
            infos.append({"conversation_id": conv_id, "task": task})
        self._last_obs = obs_texts
        return {"text": obs_texts, "image": None, "anchor": obs_texts}, infos

    def step(self, text_actions: List[str]):
        """Send each action to its conversation and collect rewards."""
        next_obs = []
        rewards = np.zeros(self.n_envs, dtype=np.float32)
        dones = np.zeros(self.n_envs, dtype=bool)
        infos = []

        for i, action in enumerate(text_actions):
            conv_id = self._conversation_ids[i]
            if conv_id is None or self._done[i]:
                next_obs.append(self._last_obs[i])
                dones[i] = True
                infos.append({"won": False})
                continue

            try:
                self._send_message(conv_id, action)
                last_text, success = self._poll_until_done(conv_id)
            except Exception as exc:
                last_text = f"[OpenHands error: {exc}]"
                success = False

            rewards[i] = 1.0 if success else 0.0
            dones[i] = True          # one-shot: each task is a single episode
            self._done[i] = True
            self._last_obs[i] = last_text
            next_obs.append(last_text)
            infos.append({"won": bool(success), "conversation_id": conv_id})

        return {"text": next_obs, "image": None, "anchor": next_obs}, rewards, dones, infos

    def build_text_obs(self) -> List[str]:
        return self._last_obs

    def close(self) -> None:
        self._session.close()

    def success_evaluator(self, *args, **kwargs):
        total_infos = kwargs["total_infos"]
        total_batch_list = kwargs["total_batch_list"]
        batch_size = len(total_batch_list)
        success = defaultdict(list)
        for bs in range(batch_size):
            self._process_batch(bs, total_batch_list, total_infos, success)
        if not success["success_rate"]:
            success["success_rate"] = [0.0] * batch_size
        return {k: np.array(v) for k, v in success.items()}


# ── Patch make_envs to register the new environment ───────────────────────

_original_make_envs = make_envs


def make_envs(config):
    """Extended make_envs that supports ``env_name: "openhands"``."""
    env_name = getattr(config.env, "env_name", "").lower()
    if env_name == "openhands":
        group_n = config.env.rollout.n if config.env.rollout.n > 0 else 1
        n_train = config.data.train_batch_size * group_n
        n_val = config.data.val_batch_size

        train_envs = OpenHandsEnvironmentManager(config, n_envs=n_train)
        val_envs = OpenHandsEnvironmentManager(config, n_envs=n_val)
        return train_envs, val_envs

    # Fall through to the original factory for all other environments
    return _original_make_envs(config)
