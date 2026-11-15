"""
api.db
========

Persistance minimale (SQLite) pour les décisions humaines que le frontend
doit retenir après un rechargement — conversations, findings de sécurité
(ignore/unignore), fichiers générés (accept/request-fix). Choix documenté
dans le prompt de fusion ("SQLite acceptable en v1, PAS de mock en mémoire
perdu au restart").

`sqlite3` (stdlib) est un driver BLOQUANT — même principe que pour
`Orchestrator` (voir state.py) : jamais d'appel direct depuis un handler
async. Chaque fonction publique de ce module est synchrone et blocking par
design ; les routers l'appellent via `asyncio.to_thread(...)`.

Schéma volontairement plat (pas d'ORM) — trois tables, un seul fichier
SQLite, cohérent avec "reste minimal" (contrainte non négociable du
prompt).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(os.environ.get("NEXUS_API_DB_PATH", "./nexus_api.sqlite3"))

_write_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # concurrence lecture/écriture correcte pour un usage multi-thread
    return conn


def init_db() -> None:
    with _write_lock, _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                transcript TEXT NOT NULL DEFAULT '[]'
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY,
                tool TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                related_node_id TEXT,
                ignored_reason TEXT,
                ignored_expires_on TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                branch_id TEXT NOT NULL,
                path TEXT NOT NULL,
                summary TEXT NOT NULL,
                lines_added INTEGER NOT NULL,
                lines_removed INTEGER NOT NULL,
                status TEXT NOT NULL,
                branch_label TEXT NOT NULL,
                branch_agent TEXT NOT NULL,
                branch_status TEXT NOT NULL
            )"""
        )
        # Fournisseurs LLM installés depuis le dashboard (pop-up "Connexion
        # API", voir api/providers.py) — remplace la config LLM unique
        # autrefois codée en dur / lue uniquement depuis des variables
        # d'environnement (voir nexus_compose/llm_config.py). Au plus une
        # ligne avec is_active=1 à la fois (appliqué par set_active_provider,
        # jamais par une contrainte SQL — SQLite n'a pas d'index partiel
        # portable ici, et l'appliquer en Python garde ce fichier lisible).
        conn.execute(
            """CREATE TABLE IF NOT EXISTS llm_providers (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                label TEXT NOT NULL,
                model TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                api_type TEXT NOT NULL DEFAULT 'chat_completions',
                auth_type TEXT NOT NULL DEFAULT 'bearer',
                api_key TEXT,
                headers TEXT NOT NULL DEFAULT '{}',
                timeout_s INTEGER NOT NULL DEFAULT 30,
                max_retries INTEGER NOT NULL DEFAULT 3,
                http2 INTEGER NOT NULL DEFAULT 1,
                compression INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        conn.commit()


def seed_if_empty(findings_seed: list[dict[str, Any]], branches_seed: list[dict[str, Any]]) -> None:
    """Amorce les tables `findings`/`files` avec des données réalistes si
    elles sont vides (premier démarrage). Ce ne sont PAS de vraies sorties
    de Bearer/Semgrep/CodeQL/crewAI — parser leur sortie réelle en
    SecurityFinding/GeneratedFile est une fonctionnalité séparée, plus
    substantielle, hors du périmètre "connecter frontend et backend" de ce
    prompt. Documenté explicitement plutôt que présenté comme une
    intégration complète."""
    with _write_lock, _connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 0:
            for f in findings_seed:
                conn.execute(
                    "INSERT INTO findings (id, tool, severity, title, detail, related_node_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (f["id"], f["tool"], f["severity"], f["title"], f["detail"], f.get("relatedNodeId")),
                )
        if conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0:
            for b in branches_seed:
                for f in b["files"]:
                    conn.execute(
                        "INSERT INTO files (id, branch_id, path, summary, lines_added, lines_removed, "
                        "status, branch_label, branch_agent, branch_status) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            f["id"], b["id"], f["path"], f["summary"], f["linesAdded"], f["linesRemoved"],
                            f["status"], b["label"], b["agent"], b["status"],
                        ),
                    )
        conn.commit()


# ── conversations ───────────────────────────────────────────────────────────

def insert_conversation(conv_id: str, title: str, date: str, transcript: list[dict]) -> None:
    with _write_lock, _connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, date, transcript) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, date=excluded.date, "
            "transcript=excluded.transcript",
            (conv_id, title, date, json.dumps(transcript)),
        )
        conn.commit()


def get_conversation(conv_id: str) -> Optional[dict[str, Any]]:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "date": row["date"],
        "transcript": json.loads(row["transcript"]),
    }


# ── findings ─────────────────────────────────────────────────────────────────

def list_findings() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM findings").fetchall()
    finally:
        conn.close()
    findings = []
    for row in rows:
        finding: dict[str, Any] = {
            "id": row["id"],
            "tool": row["tool"],
            "severity": row["severity"],
            "title": row["title"],
            "detail": row["detail"],
            "relatedNodeId": row["related_node_id"],
        }
        if row["ignored_reason"] is not None:
            finding["ignored"] = {"reason": row["ignored_reason"], "expiresOn": row["ignored_expires_on"]}
        findings.append(finding)
    return findings


def set_finding_ignored(finding_id: str, reason: Optional[str], expires_on: Optional[str]) -> bool:
    """reason=None efface l'état ignoré (unignore)."""
    with _write_lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE findings SET ignored_reason = ?, ignored_expires_on = ? WHERE id = ?",
            (reason, expires_on, finding_id),
        )
        conn.commit()
        return cur.rowcount > 0


# ── fichiers générés ─────────────────────────────────────────────────────────

def set_file_status(file_id: str, status: str) -> bool:
    with _write_lock, _connect() as conn:
        cur = conn.execute("UPDATE files SET status = ? WHERE id = ?", (status, file_id))
        conn.commit()
        return cur.rowcount > 0


def list_branches() -> list[dict[str, Any]]:
    """Reconstruit les CodeBranch[] à partir de la table plate `files`."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM files ORDER BY branch_id, id").fetchall()
    finally:
        conn.close()
    branches: dict[str, dict[str, Any]] = {}
    for row in rows:
        b = branches.setdefault(
            row["branch_id"],
            {"id": row["branch_id"], "label": row["branch_label"], "agent": row["branch_agent"],
             "status": row["branch_status"], "files": []},
        )
        b["files"].append(
            {
                "id": row["id"],
                "path": row["path"],
                "summary": row["summary"],
                "linesAdded": row["lines_added"],
                "linesRemoved": row["lines_removed"],
                "status": row["status"],
            }
        )
    return list(branches.values())


# ── fournisseurs LLM (dashboard "Connexion API") ────────────────────────────
#
# Table `llm_providers` — voir init_db() pour le schéma. La clé API n'est
# JAMAIS renvoyée en clair par `_row_to_public_dict` (utilisé par
# list_providers/get_provider/... côté API) ; seul `get_provider_secret`
# renvoie la valeur brute, réservé aux appels internes (test de connexion,
# résolution par nexus_compose.llm_config).

def _mask_api_key(api_key: Optional[str]) -> Optional[str]:
    if not api_key:
        return None
    if len(api_key) <= 4:
        return "•" * len(api_key)
    hidden = min(8, len(api_key) - 4)
    return ("•" * hidden) + api_key[-4:]


def _row_to_public_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Représentation renvoyée par l'API : clé API masquée, jamais en clair."""
    return {
        "id": row["id"],
        "provider": row["provider"],
        "label": row["label"],
        "model": row["model"],
        "endpoint": row["endpoint"],
        "apiType": row["api_type"],
        "authType": row["auth_type"],
        "hasApiKey": bool(row["api_key"]),
        "apiKeyMasked": _mask_api_key(row["api_key"]),
        "headers": json.loads(row["headers"] or "{}"),
        "timeoutS": row["timeout_s"],
        "maxRetries": row["max_retries"],
        "http2": bool(row["http2"]),
        "compression": bool(row["compression"]),
        "isActive": bool(row["is_active"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def list_providers() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM llm_providers ORDER BY created_at").fetchall()
    finally:
        conn.close()
    return [_row_to_public_dict(r) for r in rows]


def get_provider(provider_id: str) -> Optional[dict[str, Any]]:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM llm_providers WHERE id = ?", (provider_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_public_dict(row) if row is not None else None


def get_provider_secret(provider_id: str) -> Optional[dict[str, Any]]:
    """Comme get_provider, mais avec `api_key` en clair — réservé aux appels
    internes (test de connexion réel). Jamais exposé tel quel par un
    endpoint HTTP."""
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM llm_providers WHERE id = ?", (provider_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    data = dict(row)
    data["headers"] = json.loads(data["headers"] or "{}")
    return data


def insert_provider(provider_id: str, fields: dict[str, Any], now: str) -> dict[str, Any]:
    with _write_lock, _connect() as conn:
        conn.execute(
            """INSERT INTO llm_providers
               (id, provider, label, model, endpoint, api_type, auth_type, api_key,
                headers, timeout_s, max_retries, http2, compression, is_active,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (
                provider_id, fields["provider"], fields["label"], fields["model"], fields["endpoint"],
                fields["api_type"], fields["auth_type"], fields.get("api_key"),
                json.dumps(fields.get("headers") or {}), fields["timeout_s"], fields["max_retries"],
                int(fields["http2"]), int(fields["compression"]), now, now,
            ),
        )
        conn.commit()
    return get_provider(provider_id)  # type: ignore[return-value]


def update_provider(provider_id: str, fields: dict[str, Any], now: str) -> Optional[dict[str, Any]]:
    """Mise à jour partielle : seules les clés présentes dans `fields` sont
    modifiées. `headers`, si présent, remplace entièrement le dict existant
    (pas de fusion partielle — cohérent avec un formulaire qui renvoie
    toujours l'état complet de sa table d'en-têtes)."""
    if not fields:
        return get_provider(provider_id)

    columns_map = {
        "provider": "provider", "label": "label", "model": "model", "endpoint": "endpoint",
        "api_type": "api_type", "auth_type": "auth_type", "api_key": "api_key",
        "timeout_s": "timeout_s", "max_retries": "max_retries",
        "http2": "http2", "compression": "compression",
    }
    set_clauses = []
    values: list[Any] = []
    for key, column in columns_map.items():
        if key in fields:
            value = fields[key]
            if key in ("http2", "compression"):
                value = int(value)
            set_clauses.append(f"{column} = ?")
            values.append(value)
    if "headers" in fields:
        set_clauses.append("headers = ?")
        values.append(json.dumps(fields["headers"] or {}))

    set_clauses.append("updated_at = ?")
    values.append(now)
    values.append(provider_id)

    with _write_lock, _connect() as conn:
        cur = conn.execute(
            f"UPDATE llm_providers SET {', '.join(set_clauses)} WHERE id = ?", values,
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    return get_provider(provider_id)


def delete_provider(provider_id: str) -> bool:
    with _write_lock, _connect() as conn:
        cur = conn.execute("DELETE FROM llm_providers WHERE id = ?", (provider_id,))
        conn.commit()
        return cur.rowcount > 0


def set_active_provider(provider_id: str, now: str) -> Optional[dict[str, Any]]:
    """Active `provider_id` et désactive tous les autres, de façon atomique
    (une seule transaction) — garantit qu'au plus un fournisseur est actif
    à la fois, sans dépendre d'une contrainte SQL."""
    with _write_lock, _connect() as conn:
        exists = conn.execute("SELECT 1 FROM llm_providers WHERE id = ?", (provider_id,)).fetchone()
        if exists is None:
            return None
        conn.execute("UPDATE llm_providers SET is_active = 0, updated_at = ? WHERE is_active = 1", (now,))
        conn.execute("UPDATE llm_providers SET is_active = 1, updated_at = ? WHERE id = ?", (now, provider_id))
        conn.commit()
    return get_provider(provider_id)


def deactivate_all_providers(now: str) -> None:
    """Désactive tout fournisseur actif, sans en activer un autre — utilisé
    quand l'utilisateur explicite qu'aucun fournisseur ne doit être actif
    (le système retombe alors sur les variables d'environnement, voir
    nexus_compose/llm_config.py)."""
    with _write_lock, _connect() as conn:
        conn.execute("UPDATE llm_providers SET is_active = 0, updated_at = ? WHERE is_active = 1", (now,))
        conn.commit()
