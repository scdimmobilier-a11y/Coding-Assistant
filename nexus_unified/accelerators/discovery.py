"""nexus_unified.accelerators.discovery — découverte des accélérateurs, tout constructeur.

Point 1 : prise en charge de tout type de constructeur de GPU, y compris des
puces personnalisées. On ne suppose pas NVIDIA : on sonde, par ordre, binaires
vendeur, sysfs, nœuds de périphérique, et surtout le **Container Device
Interface (CDI)** — la voie neutre par laquelle un constructeur de puce
personnalisée déclare ses périphériques à Docker/Podman (fichiers
`/etc/cdi/*.json|yaml`, `/var/run/cdi/*`). Un accélérateur inconnu mais déclaré
en CDI est donc exposé au sandbox sans code spécifique.

Chaque `Accelerator` sait produire les arguments d'exécution conteneur qui
l'exposent (`device_requests` NVIDIA, `devices` pour ROCm/XPU/NPU, chaîne CDI
pour le reste). La découverte dégrade proprement : aucun accélérateur trouvé →
liste vide, jamais d'exception.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Accelerator:
    vendor: str                  # nvidia | amd | intel | habana | ascend | cdi | generic
    index: int
    name: str = ""
    uuid: str = ""
    total_memory_mib: int = 0
    kind: str = "gpu"            # gpu | npu | tpu | accelerator
    cdi_device: str = ""         # ex. "nvidia.com/gpu=0" si exposé via CDI
    device_nodes: List[str] = field(default_factory=list)  # ex. /dev/dri/renderD128
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_run_kwargs(self, *, prefer_cdi: bool = True) -> Dict[str, Any]:
        """Arguments d'exécution conteneur qui exposent CET accélérateur.

        Retourne un dict partiel (`device_requests`, `devices`, ou
        `cdi_devices`) à fusionner avec les kwargs durcis du sandbox.
        """
        if prefer_cdi and self.cdi_device:
            return {"cdi_devices": [self.cdi_device]}
        if self.vendor == "nvidia":
            dr = {"Driver": "nvidia",
                  "DeviceIDs": [self.uuid or str(self.index)],
                  "Capabilities": [["gpu", "utility", "compute"]]}
            return {"device_requests": [dr]}
        if self.vendor in ("amd", "intel", "habana", "ascend", "generic"):
            nodes = list(self.device_nodes)
            # ROCm exige /dev/kfd ; les pilotes DRM exigent /dev/dri
            if self.vendor == "amd" and "/dev/kfd" not in nodes:
                nodes = ["/dev/kfd"] + nodes
            return {"devices": [f"{n}:{n}:rwm" for n in nodes]}
        if self.cdi_device:
            return {"cdi_devices": [self.cdi_device]}
        return {}

    def to_dict(self) -> Dict[str, Any]:
        return {"vendor": self.vendor, "index": self.index, "name": self.name,
                "uuid": self.uuid, "total_memory_mib": self.total_memory_mib,
                "kind": self.kind, "cdi_device": self.cdi_device,
                "device_nodes": self.device_nodes}


def _run(cmd: List[str], timeout: int = 10) -> Optional[str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


# ── NVIDIA ───────────────────────────────────────────────────────────────────
def discover_nvidia() -> List[Accelerator]:
    out: List[Accelerator] = []
    if not shutil.which("nvidia-smi"):
        if not os.path.exists("/proc/driver/nvidia/gpus"):
            return out
    txt = _run(["nvidia-smi", "--query-gpu=index,uuid,name,memory.total",
                "--format=csv,noheader,nounits"])
    if txt:
        for line in txt.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                out.append(Accelerator("nvidia", int(parts[0]), parts[2], parts[1],
                                       int(float(parts[3])), "gpu"))
        return out
    # repli sysfs
    for i, _ in enumerate(sorted(glob.glob("/proc/driver/nvidia/gpus/*"))):
        out.append(Accelerator("nvidia", i, "nvidia-gpu", "", 0, "gpu"))
    return out


# ── AMD ROCm ─────────────────────────────────────────────────────────────────
def discover_amd() -> List[Accelerator]:
    out: List[Accelerator] = []
    if not os.path.exists("/dev/kfd"):
        return out
    render = sorted(glob.glob("/dev/dri/renderD*"))
    names: List[str] = []
    txt = _run(["rocm-smi", "--showproductname", "--csv"]) or ""
    for line in txt.splitlines():
        m = re.search(r"(Navi|Instinct|Radeon|MI\d+|gfx\d+)", line)
        if m:
            names.append(m.group(1))
    for i, node in enumerate(render or ["/dev/dri"]):
        out.append(Accelerator("amd", i, names[i] if i < len(names) else "amd-gpu",
                               "", 0, "gpu", device_nodes=["/dev/kfd", node]))
    return out


# ── Intel (XPU / GPU) ────────────────────────────────────────────────────────
def discover_intel() -> List[Accelerator]:
    out: List[Accelerator] = []
    # xpu-smi si présent, sinon nœuds DRM Intel (i915/xe)
    render = sorted(glob.glob("/dev/dri/renderD*"))
    has_intel = False
    for card in glob.glob("/sys/class/drm/card*/device/vendor"):
        try:
            if open(card).read().strip().lower() == "0x8086":
                has_intel = True
        except OSError:
            pass
    if not (has_intel or shutil.which("xpu-smi")):
        return out
    for i, node in enumerate(render or ["/dev/dri"]):
        out.append(Accelerator("intel", i, "intel-xpu", "", 0, "gpu",
                               device_nodes=[node]))
    return out


# ── Habana Gaudi / Ascend NPU / /dev/accel ──────────────────────────────────
def discover_npu() -> List[Accelerator]:
    out: List[Accelerator] = []
    # Habana : /dev/accel/accelN + /dev/hl_controlDN
    accels = sorted(glob.glob("/dev/accel/accel*"))
    for i, node in enumerate(accels):
        ctrl = f"/dev/hl_controlD{i}"
        nodes = [node] + ([ctrl] if os.path.exists(ctrl) else [])
        out.append(Accelerator("habana", i, "gaudi", "", 0, "npu", device_nodes=nodes))
    # Huawei Ascend : /dev/davinci*
    for i, node in enumerate(sorted(glob.glob("/dev/davinci[0-9]*"))):
        extra = [n for n in ("/dev/davinci_manager", "/dev/devmm_svm", "/dev/hisi_hdc")
                 if os.path.exists(n)]
        out.append(Accelerator("ascend", i, "ascend-npu", "", 0, "npu",
                               device_nodes=[node] + extra))
    return out


# ── CDI — voie neutre pour puces personnalisées ─────────────────────────────
_CDI_DIRS = ("/etc/cdi", "/var/run/cdi", "/run/cdi")


def discover_cdi() -> List[Accelerator]:
    """Lit les specs CDI : tout périphérique qu'un constructeur y déclare est
    exposable au sandbox par sa chaîne `vendor/class=name`, sans code vendeur."""
    out: List[Accelerator] = []
    seen = set()
    for d in _CDI_DIRS:
        for path in glob.glob(os.path.join(d, "*.json")) + \
                    glob.glob(os.path.join(d, "*.yaml")) + glob.glob(os.path.join(d, "*.yml")):
            spec = _load_cdi(path)
            if not spec:
                continue
            kind = spec.get("kind", "")       # ex. "nvidia.com/gpu", "acme.com/npu"
            vendor = kind.split("/")[0] if "/" in kind else "cdi"
            for i, dev in enumerate(spec.get("devices", [])):
                name = dev.get("name", str(i))
                cdi = f"{kind}={name}"
                if cdi in seen:
                    continue
                seen.add(cdi)
                klass = "npu" if "npu" in kind.lower() or "accel" in kind.lower() else "gpu"
                out.append(Accelerator(vendor if vendor != "cdi" else "cdi", i,
                                       kind, "", 0, klass, cdi_device=cdi,
                                       extra={"cdi_kind": kind, "cdi_name": name}))
    return out


def _load_cdi(path: str) -> Optional[Dict[str, Any]]:
    try:
        txt = open(path, encoding="utf-8").read()
    except OSError:
        return None
    if path.endswith(".json"):
        try:
            return json.loads(txt)
        except Exception:
            return None
    try:
        import yaml  # type: ignore
        return yaml.safe_load(txt)
    except Exception:
        return None


def discover_accelerators(*, include_cdi: bool = True) -> List[Accelerator]:
    """Découvre tous les accélérateurs visibles, tout constructeur.

    L'ordre évite les doublons : CDI d'abord (source d'autorité quand présente),
    puis sondes vendeur pour ce que CDI ne couvre pas.
    """
    found: List[Accelerator] = []
    cdi_kinds = set()
    if include_cdi:
        cdi = discover_cdi()
        found.extend(cdi)
        cdi_kinds = {a.vendor for a in cdi}
    for probe, vendor in ((discover_nvidia, "nvidia"), (discover_amd, "amd"),
                          (discover_intel, "intel"), (discover_npu, "npu")):
        if vendor in cdi_kinds:
            continue  # déjà couvert par une spec CDI de ce vendeur
        try:
            found.extend(probe())
        except Exception:
            pass
    # réindexation globale stable
    for gi, a in enumerate(found):
        a.extra["global_index"] = gi
    return found


def discovery_report() -> Dict[str, Any]:
    accs = discover_accelerators()
    by_vendor: Dict[str, int] = {}
    for a in accs:
        by_vendor[a.vendor] = by_vendor.get(a.vendor, 0) + 1
    return {"count": len(accs), "by_vendor": by_vendor,
            "cdi_dirs_present": [d for d in _CDI_DIRS if os.path.isdir(d)],
            "accelerators": [a.to_dict() for a in accs]}
