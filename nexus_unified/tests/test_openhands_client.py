"""Tests du client OpenHands V1 : vérifie qu'on appelle les BONNES routes V1.

C'est exactement le défaut que le constat a identifié : les clients existants
tapaient l'API V0 (/api/conversations). On monte un serveur httpx factice qui
n'expose QUE les routes V1 et refuse les routes V0, et on vérifie le flux.
"""
from __future__ import annotations

import json

import httpx
import pytest

from nexus_unified.openhands_client import OpenHandsV1Client


class _FakeOpenHands:
    """Serveur V1 minimal en mémoire (transport httpx)."""
    def __init__(self):
        self.calls = []
        self.conv_id = "conv-123"
        self._exec = "running"
        self._sends = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        # Routes V0 explicitement refusées
        if path.startswith("/api/conversations") or path == "/api/conversations":
            return httpx.Response(404, json={"error": "V0 route absente"})
        if path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/api/v1/app-conversations" and request.method == "POST":
            body = json.loads(request.content)
            assert "initial_message" in body
            im = body["initial_message"]
            assert im["role"] == "user"
            assert isinstance(im["content"], list) and im["content"][0]["type"] == "text"
            return httpx.Response(201, json={"conversation_id": self.conv_id})
        if path == "/api/v1/app-conversations/start-tasks":
            return httpx.Response(200, json={"items": [
                {"conversation_id": self.conv_id, "status": "READY"}]})
        if path == "/api/v1/app-conversations" and request.method == "GET":
            self._exec = "finished"   # terminé au premier poll
            return httpx.Response(200, json={"items": [
                {"id": self.conv_id, "execution_status": self._exec}]})
        if path.endswith("/send-message"):
            body = json.loads(request.content)
            assert isinstance(body["content"], list)   # pas une chaîne nue (défaut 2)
            self._sends += 1
            return httpx.Response(200, json={"success": True})
        if path.endswith("/events/search"):
            return httpx.Response(200, json={"items": [
                {"source": "user", "message": "fais X"},
                {"source": "agent", "message": "X fait : fichier créé"}]})
        if path.endswith("/git/diff"):
            return httpx.Response(200, json={"diff": "--- a\n+++ b\n+print(1)\n"})
        return httpx.Response(404, json={"error": f"route inconnue {path}"})


def _client():
    fake = _FakeOpenHands()
    transport = httpx.MockTransport(fake.handler)
    return OpenHandsV1Client(transport=transport, poll_interval=0.0), fake


def test_run_task_uses_v1_routes_and_succeeds():
    client, fake = _client()
    res = client.run_task("écris un hello world")
    assert res.ok, res.error
    assert res.conversation_id == "conv-123"
    assert "X fait" in res.output
    assert "print(1)" in res.git_diff
    assert res.execution_status == "finished"
    # aucune route V0 appelée
    assert not any("/api/conversations" in c and "/api/v1/" not in c for c in fake.calls)
    assert "POST /api/v1/app-conversations" in fake.calls


def test_message_shape_is_content_list():
    client, fake = _client()
    client.send_message("conv-123", "salut")
    assert fake._sends == 1


def test_health_ok():
    client, _ = _client()
    assert client.health()["ok"] is True


def test_connection_refused_is_explicit_error():
    def boom(request):
        raise httpx.ConnectError("refused")
    client = OpenHandsV1Client(transport=httpx.MockTransport(boom), poll_interval=0.0)
    res = client.run_task("x")
    assert not res.ok and "impossible" in (res.error or "")


def test_start_error_status_reported():
    class _ErrStart(_FakeOpenHands):
        def handler(self, request):
            if request.url.path == "/api/v1/app-conversations/start-tasks":
                self.calls.append("start")
                return httpx.Response(200, json={"items": [
                    {"conversation_id": self.conv_id, "status": "ERROR"}]})
            return super().handler(request)
    fake = _ErrStart()
    client = OpenHandsV1Client(transport=httpx.MockTransport(fake.handler), poll_interval=0.0)
    res = client.run_task("x")
    assert not res.ok and "sandbox" in (res.error or "")
