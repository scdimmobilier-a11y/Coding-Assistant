"""Tests des accélérateurs : découverte CDI (puce personnalisée) et baux bornés par ressources."""
from __future__ import annotations

import json
import os

import pytest

from nexus_unified.accelerators import (
    Accelerator, AcceleratorLeaseManager, LeaseError, discover_cdi, discover_accelerators,
)
from nexus_unified.accelerators.discovery import _CDI_DIRS


def _fleet(n_nvidia=0, n_amd=0, n_custom=0, mem=16000):
    accs = []
    idx = 0
    for i in range(n_nvidia):
        accs.append(Accelerator("nvidia", i, "A100", f"GPU-{i:03d}", mem, "gpu")); idx += 1
    for i in range(n_amd):
        accs.append(Accelerator("amd", i, "MI300", "", mem, "gpu",
                                device_nodes=["/dev/kfd", f"/dev/dri/renderD{128+i}"])); idx += 1
    for i in range(n_custom):
        accs.append(Accelerator("acme", i, "acme.com/npu", "", mem, "npu",
                                cdi_device=f"acme.com/npu=npu{i}")); idx += 1
    return accs


def test_nvidia_run_kwargs():
    a = Accelerator("nvidia", 0, "A100", "GPU-abc", 80000, "gpu")
    kw = a.to_run_kwargs(prefer_cdi=False)
    assert "device_requests" in kw
    assert kw["device_requests"][0]["DeviceIDs"] == ["GPU-abc"]


def test_amd_run_kwargs_adds_kfd():
    a = Accelerator("amd", 0, "MI300", "", 0, "gpu", device_nodes=["/dev/dri/renderD128"])
    kw = a.to_run_kwargs(prefer_cdi=False)
    assert any("/dev/kfd" in d for d in kw["devices"])


def test_custom_chip_via_cdi():
    a = Accelerator("acme", 0, "acme.com/npu", "", 0, "npu", cdi_device="acme.com/npu=npu0")
    kw = a.to_run_kwargs(prefer_cdi=True)
    assert kw == {"cdi_devices": ["acme.com/npu=npu0"]}


def test_discover_cdi_reads_custom_spec(tmp_path, monkeypatch):
    cdi_dir = tmp_path / "cdi"
    cdi_dir.mkdir()
    spec = {"cdiVersion": "0.6.0", "kind": "acme.com/npu",
            "devices": [{"name": "npu0"}, {"name": "npu1"}]}
    (cdi_dir / "acme.json").write_text(json.dumps(spec))
    monkeypatch.setattr("nexus_unified.accelerators.discovery._CDI_DIRS", (str(cdi_dir),))
    accs = discover_cdi()
    assert len(accs) == 2
    assert all(a.vendor == "acme.com" and a.cdi_device.startswith("acme.com/npu=") for a in accs)


def test_discover_degrades_to_empty():
    # Dans ce bac à sable sans accélérateur, la découverte ne doit pas lever.
    accs = discover_accelerators()
    assert isinstance(accs, list)


# ── baux ─────────────────────────────────────────────────────────────────────
def test_exclusive_lease_blocks_device():
    mgr = AcceleratorLeaseManager(_fleet(n_nvidia=2), default_ttl=100)
    l1 = mgr.acquire("run-a", count=2, exclusive=True)
    assert len(l1.device_indices) == 2
    # plus aucun périphérique libre
    with pytest.raises(LeaseError):
        mgr.acquire("run-b", count=1, exclusive=True)
    mgr.release(l1.lease_id)
    l2 = mgr.acquire("run-b", count=1, exclusive=True)
    assert l2.device_indices


def test_unlimited_within_resources():
    # 8 périphériques → 8 baux exclusifs concurrents, pas de plafond artificiel
    mgr = AcceleratorLeaseManager(_fleet(n_nvidia=8), default_ttl=100)
    leases = [mgr.acquire(f"run-{i}", count=1) for i in range(8)]
    assert len({l.device_indices[0] for l in leases}) == 8
    with pytest.raises(LeaseError):
        mgr.acquire("run-9", count=1)


def test_shared_memory_leases_coexist():
    mgr = AcceleratorLeaseManager(_fleet(n_nvidia=1, mem=16000), default_ttl=100)
    a = mgr.acquire("a", count=1, exclusive=False, memory_mib=8000)
    b = mgr.acquire("b", count=1, exclusive=False, memory_mib=8000)
    assert a.device_indices == b.device_indices == [0]
    # mémoire épuisée
    with pytest.raises(LeaseError):
        mgr.acquire("c", count=1, exclusive=False, memory_mib=1000)
    mgr.release(a.lease_id)
    assert mgr.acquire("c", count=1, exclusive=False, memory_mib=4000)


def test_visibility_env_set():
    mgr = AcceleratorLeaseManager(_fleet(n_nvidia=2), default_ttl=100)
    l = mgr.acquire("run", count=1)
    assert "CUDA_VISIBLE_DEVICES" in l.visibility_env


def test_vendor_filter():
    mgr = AcceleratorLeaseManager(_fleet(n_nvidia=1, n_amd=1), default_ttl=100)
    l = mgr.acquire("run", count=1, vendor="amd")
    assert l.vendor == "amd"
    assert "HIP_VISIBLE_DEVICES" in l.visibility_env


def test_expiry_reclaims():
    mgr = AcceleratorLeaseManager(_fleet(n_nvidia=1), default_ttl=0.01)
    l = mgr.acquire("run", count=1)
    import time
    time.sleep(0.05)
    # le périphérique redevient disponible après expiration
    l2 = mgr.acquire("run2", count=1)
    assert l2.device_indices == [0]


def test_release_holder():
    mgr = AcceleratorLeaseManager(_fleet(n_nvidia=3), default_ttl=100)
    mgr.acquire("run", count=2)
    assert mgr.release_holder("run") == 1
    assert mgr.acquire("other", count=3)
