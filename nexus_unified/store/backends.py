"""nexus_unified.store — magasins open source enfichables (point 7).

Un seul contrat `RecordStore` (collections de documents JSON, append + requête
par égalité), plusieurs implémentations open source choisies par URL :

- `jsonl:///chemin`          — fichiers append-only, zéro dépendance (toujours dispo) ;
- `sqlite:///chemin.db`      — stdlib `sqlite3` (toujours dispo) ;
- `postgresql://…`           — `psycopg` si installé (JSONB) ;
- `neo4j://… ` / `bolt://…`  — pilote `neo4j` si installé (un nœud par document).

`open_store(url)` rend l'implémentation voulue ; si le pilote manque, il lève
une erreur claire (jamais un magasin silencieusement muet). Le défaut système
est SQLite, qui fonctionne partout. Ces magasins servent les trajectoires RL
(remplaçant la migration `enterprise/` sous licence restreinte), le registre
des checkpoints, les enregistrements d'admission d'artefacts et la banque
d'apprentissage.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse


class RecordStore(ABC):
    """Collections de documents JSON. Clé = (collection, id)."""

    @abstractmethod
    def put(self, collection: str, doc_id: str, data: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def query(self, collection: str, where: Optional[Dict[str, Any]] = None,
              limit: int = 1000) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def append(self, collection: str, data: Dict[str, Any]) -> str: ...

    def count(self, collection: str, where: Optional[Dict[str, Any]] = None) -> int:
        return len(self.query(collection, where, limit=10 ** 9))

    def close(self) -> None:
        pass


def _match(doc: Dict[str, Any], where: Optional[Dict[str, Any]]) -> bool:
    if not where:
        return True
    return all(doc.get(k) == v for k, v in where.items())


# ── JSONL ────────────────────────────────────────────────────────────────────
class JSONLStore(RecordStore):
    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, collection: str) -> str:
        safe = "".join(c for c in collection if c.isalnum() or c in "._-")
        return os.path.join(self.root, f"{safe}.jsonl")

    def append(self, collection: str, data: Dict[str, Any]) -> str:
        doc = dict(data)
        doc_id = str(doc.get("id") or f"{int(time.time()*1e6)}")
        doc["id"] = doc_id
        with self._lock, open(self._path(collection), "a", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
        return doc_id

    def put(self, collection: str, doc_id: str, data: Dict[str, Any]) -> None:
        doc = dict(data, id=doc_id)
        # append-only avec dernière écriture gagnante à la lecture
        with self._lock, open(self._path(collection), "a", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")

    def _read_all(self, collection: str) -> List[Dict[str, Any]]:
        p = self._path(collection)
        if not os.path.exists(p):
            return []
        out: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        with self._lock, open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                i = str(d.get("id"))
                if i not in out:
                    order.append(i)
                out[i] = d
        return [out[i] for i in order]

    def get(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        for d in reversed(self._read_all(collection)):
            if str(d.get("id")) == str(doc_id):
                return d
        return None

    def query(self, collection, where=None, limit=1000):
        return [d for d in self._read_all(collection) if _match(d, where)][:limit]


# ── SQLite ───────────────────────────────────────────────────────────────────
class SQLiteStore(RecordStore):
    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._tables: set = set()

    def _ensure(self, collection: str) -> str:
        t = "c_" + "".join(c if c.isalnum() else "_" for c in collection)
        if t not in self._tables:
            with self._lock:
                self._conn.execute(
                    f'CREATE TABLE IF NOT EXISTS "{t}" '
                    '(id TEXT PRIMARY KEY, ts REAL, data TEXT)')
                self._conn.commit()
            self._tables.add(t)
        return t

    def append(self, collection, data):
        doc = dict(data)
        doc_id = str(doc.get("id") or f"{int(time.time()*1e6)}")
        doc["id"] = doc_id
        self.put(collection, doc_id, doc)
        return doc_id

    def put(self, collection, doc_id, data):
        t = self._ensure(collection)
        doc = dict(data, id=doc_id)
        with self._lock:
            self._conn.execute(f'INSERT OR REPLACE INTO "{t}" (id, ts, data) VALUES (?,?,?)',
                               (doc_id, time.time(), json.dumps(doc, ensure_ascii=False)))
            self._conn.commit()

    def get(self, collection, doc_id):
        t = self._ensure(collection)
        with self._lock:
            row = self._conn.execute(f'SELECT data FROM "{t}" WHERE id=?', (doc_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def query(self, collection, where=None, limit=1000):
        t = self._ensure(collection)
        with self._lock:
            rows = self._conn.execute(
                f'SELECT data FROM "{t}" ORDER BY ts LIMIT ?', (limit * 4,)).fetchall()
        out = [json.loads(r[0]) for r in rows]
        return [d for d in out if _match(d, where)][:limit]

    def close(self):
        self._conn.close()


# ── PostgreSQL ───────────────────────────────────────────────────────────────
class PostgresStore(RecordStore):
    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # type: ignore
            self._pg = psycopg
        except Exception as exc:
            raise StoreUnavailable(
                "magasin PostgreSQL demandé mais 'psycopg' n'est pas installé "
                "(pip install 'psycopg[binary]')") from exc
        self.dsn = dsn
        self._lock = threading.RLock()
        self._conn = self._pg.connect(dsn, autocommit=True)
        self._tables: set = set()

    def _ensure(self, collection: str) -> str:
        t = "c_" + "".join(c if c.isalnum() else "_" for c in collection)
        if t not in self._tables:
            with self._lock, self._conn.cursor() as cur:
                cur.execute(f'CREATE TABLE IF NOT EXISTS "{t}" '
                            '(id TEXT PRIMARY KEY, ts DOUBLE PRECISION, data JSONB)')
            self._tables.add(t)
        return t

    def append(self, collection, data):
        doc = dict(data)
        doc_id = str(doc.get("id") or f"{int(time.time()*1e6)}")
        doc["id"] = doc_id
        self.put(collection, doc_id, doc)
        return doc_id

    def put(self, collection, doc_id, data):
        t = self._ensure(collection)
        doc = dict(data, id=doc_id)
        with self._lock, self._conn.cursor() as cur:
            cur.execute(f'INSERT INTO "{t}" (id, ts, data) VALUES (%s,%s,%s) '
                        'ON CONFLICT (id) DO UPDATE SET ts=EXCLUDED.ts, data=EXCLUDED.data',
                        (doc_id, time.time(), json.dumps(doc)))

    def get(self, collection, doc_id):
        t = self._ensure(collection)
        with self._lock, self._conn.cursor() as cur:
            cur.execute(f'SELECT data FROM "{t}" WHERE id=%s', (doc_id,))
            row = cur.fetchone()
        return row[0] if row else None

    def query(self, collection, where=None, limit=1000):
        t = self._ensure(collection)
        sql = f'SELECT data FROM "{t}"'
        params: List[Any] = []
        if where:
            sql += " WHERE " + " AND ".join("data->>%s = %s" for _ in where)
            for k, v in where.items():
                params += [k, str(v)]
        sql += " ORDER BY ts LIMIT %s"
        params.append(limit)
        with self._lock, self._conn.cursor() as cur:
            cur.execute(sql, params)
            return [r[0] for r in cur.fetchall()]

    def close(self):
        self._conn.close()


# ── Neo4j ────────────────────────────────────────────────────────────────────
class Neo4jStore(RecordStore):
    def __init__(self, url: str, user: str = "neo4j", password: str = "") -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore
        except Exception as exc:
            raise StoreUnavailable(
                "magasin Neo4j demandé mais le pilote 'neo4j' n'est pas installé "
                "(pip install neo4j)") from exc
        user = os.getenv("NEO4J_USER", user)
        password = os.getenv("NEO4J_PASSWORD", password)
        self._driver = GraphDatabase.driver(url, auth=(user, password),
                                            connection_timeout=5,
                                            max_transaction_retry_time=5)

    def _label(self, collection: str) -> str:
        return "Rec_" + "".join(c if c.isalnum() else "_" for c in collection)

    def append(self, collection, data):
        doc = dict(data)
        doc_id = str(doc.get("id") or f"{int(time.time()*1e6)}")
        doc["id"] = doc_id
        self.put(collection, doc_id, doc)
        return doc_id

    def put(self, collection, doc_id, data):
        label = self._label(collection)
        doc = dict(data, id=doc_id)
        with self._driver.session() as s:
            s.run(f"MERGE (n:{label} {{id:$id}}) SET n.ts=$ts, n.data=$data",
                  id=doc_id, ts=time.time(), data=json.dumps(doc, ensure_ascii=False))

    def get(self, collection, doc_id):
        label = self._label(collection)
        with self._driver.session() as s:
            rec = s.run(f"MATCH (n:{label} {{id:$id}}) RETURN n.data AS d", id=doc_id).single()
        return json.loads(rec["d"]) if rec and rec["d"] else None

    def query(self, collection, where=None, limit=1000):
        label = self._label(collection)
        with self._driver.session() as s:
            rows = s.run(f"MATCH (n:{label}) RETURN n.data AS d ORDER BY n.ts LIMIT $lim",
                         lim=limit * 4).data()
        out = [json.loads(r["d"]) for r in rows if r.get("d")]
        return [d for d in out if _match(d, where)][:limit]

    def close(self):
        self._driver.close()


class StoreUnavailable(RuntimeError):
    pass


def open_store(url: Optional[str] = None) -> RecordStore:
    """Ouvre le magasin désigné par `url` (ou `$NEXUS_STORE_URL`, défaut SQLite).

    Schémas : jsonl:// , sqlite:// , postgresql:// (ou postgres://) , neo4j:// / bolt://
    """
    url = url or os.getenv("NEXUS_STORE_URL") or "sqlite:///./nexus_state/store.db"
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme in ("jsonl", "file"):
        return JSONLStore(parsed.path or "./nexus_state/jsonl")
    if scheme == "sqlite":
        path = parsed.path or "/./nexus_state/store.db"
        if path.startswith("/") and not os.path.isabs(parsed.netloc or ""):
            path = path.lstrip("/") if parsed.netloc == "" and path.startswith("//") else path
        return SQLiteStore(url.split("://", 1)[1] or ":memory:")
    if scheme in ("postgresql", "postgres"):
        return PostgresStore(url)
    if scheme in ("neo4j", "neo4j+s", "bolt", "bolt+s"):
        return Neo4jStore(url)
    raise StoreUnavailable(f"schéma de magasin non reconnu : {scheme!r} (url={url!r})")
