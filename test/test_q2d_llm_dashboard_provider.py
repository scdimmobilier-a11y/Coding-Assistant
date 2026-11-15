"""
tests/test_q2d_llm_dashboard_provider.py
────────────────────────────────────────────
Vérifie que nexus_compose.drivers._q2d_llm — l'appel LLM réel du pipeline
q2d — utilise bien le fournisseur installé/activé depuis le dashboard
"Connexion API" (endpoint arbitraire, via nexus_compose.llm_http), plutôt
que le SDK openai (qui suppose un base_url compatible OpenAI). C'est le
chemin qui rend le point 1 de la demande ("le système n'appelle plus un
seul LLM codé en dur") effectif de bout en bout, pas seulement au niveau de
get_llm_config().
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_q2d_llm_uses_dashboard_endpoint_directly(tmp_path, monkeypatch):
    from api import db as db_module

    db_path = tmp_path / "test_q2d_llm.sqlite3"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setenv("NEXUS_API_DB_PATH", str(db_path))
    db_module.init_db()

    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received["body"] = json.loads(self.rfile.read(length) or b"{}")
            received["auth"] = self.headers.get("Authorization")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"content": "réponse du serveur auto-hébergé"}}]}).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_port
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        now = "2026-07-07T00:00:00Z"
        db_module.insert_provider("p-vllm", {
            "provider": "vllm", "label": "vLLM local", "model": "Qwen2.5-32B-Instruct",
            "endpoint": f"http://127.0.0.1:{port}/v1/chat/completions",
            "api_type": "chat_completions", "auth_type": "bearer", "api_key": "local-dev-key-123456",
            "headers": {}, "timeout_s": 10, "max_retries": 1, "http2": False, "compression": True,
        }, now)
        db_module.set_active_provider("p-vllm", now)

        from nexus_compose.drivers import _q2d_llm
        result = _q2d_llm({"prompt": "Bonjour"})

        assert result["model"] == "Qwen2.5-32B-Instruct"
        assert result["text"] == "réponse du serveur auto-hébergé"
        assert received["auth"] == "Bearer local-dev-key-123456"
        assert received["body"]["messages"][0]["content"] == "Bonjour"
    finally:
        srv.shutdown()
