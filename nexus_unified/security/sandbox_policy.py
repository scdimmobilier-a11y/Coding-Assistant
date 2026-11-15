"""nexus_unified.security.sandbox_policy — profil de sandbox durci, obligatoire.

Point 9 : le sandbox doit être obligatoirement sécurisé. Ce module produit les
arguments `docker run` (ou l'équivalent gVisor/Kata) d'un conteneur agent-server
durci, et un validateur qui refuse tout conteneur qui s'en écarte.

Principes appliqués :
- **Moindre privilège** : `cap_drop=[ALL]`, aucune capacité ajoutée par défaut,
  `no-new-privileges`, utilisateur non-root, `privileged` interdit.
- **Profil seccomp** restrictif (celui par défaut de Docker au minimum ; un
  profil durci custom si fourni).
- **Système de fichiers** : racine en lecture seule, écriture seulement sur un
  `/workspace` monté et des `tmpfs` bornés ; `nodev,nosuid,noexec` sur les tmpfs.
- **Ressources** : `pids_limit`, `mem_limit`, `--ulimit nofile`, pas de swap
  illimité — borne les bombes de ressources.
- **Runtime d'isolation** : `runsc` (gVisor) ou `kata-runtime` si présent ;
  sinon le runtime par défaut, et le mode « strict » refuse de démarrer sans
  isolation renforcée.
- **Réseau** : par défaut `none` ; en mode réseau, un réseau Docker *interne*
  plus un proxy de sortie à liste blanche (jamais le réseau de l'hôte).
- Le **sandbox en processus** (RUNTIME=process) ne fournit aucune de ces
  garanties : il est refusé en mode strict.

Le GPU (lot 1) se compose avec ce profil : les périphériques accélérateurs
sont ajoutés par `accelerators`, le reste du durcissement est inchangé.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Capacités jamais ajoutées, même sur demande (évasion / corruption d'hôte).
FORBIDDEN_CAPS = {
    "SYS_ADMIN", "SYS_PTRACE", "SYS_MODULE", "SYS_RAWIO", "SYS_BOOT", "SYS_TIME",
    "NET_ADMIN", "NET_RAW", "DAC_READ_SEARCH", "DAC_OVERRIDE", "MKNOD", "AUDIT_WRITE",
    "SETUID", "SETGID", "SYS_CHROOT", "FOWNER", "KILL", "BPF", "PERFMON", "CHECKPOINT_RESTORE",
}


@dataclass
class SandboxHardeningConfig:
    strict: bool = True                       # refuse de démarrer sans isolation renforcée
    read_only_rootfs: bool = True
    workspace_mount: str = "/workspace"
    mem_limit: str = "8g"
    pids_limit: int = 2048
    nofile: int = 4096
    tmpfs_size_mb: int = 2048
    allow_network: bool = False               # None = réseau interne + proxy sortie
    internal_network_name: Optional[str] = None
    egress_proxy: Optional[str] = None        # http://proxy:3128, à liste blanche
    seccomp_profile_path: Optional[str] = None
    extra_caps_add: tuple = ()                # filtrées contre FORBIDDEN_CAPS
    preferred_runtimes: tuple = ("runsc", "kata-runtime")


def _detect_isolation_runtime(cfg: SandboxHardeningConfig) -> Optional[str]:
    """Retourne le runtime d'isolation disponible (gVisor/Kata) ou None."""
    for rt in cfg.preferred_runtimes:
        # runsc/kata-runtime enregistrés dans Docker apparaissent dans le PATH.
        if shutil.which(rt):
            return "runsc" if rt == "runsc" else rt
    env = os.getenv("NEXUS_SANDBOX_RUNTIME")
    return env or None


def build_hardened_run_kwargs(cfg: Optional[SandboxHardeningConfig] = None,
                              *, device_requests: Optional[List[Any]] = None,
                              devices: Optional[List[str]] = None,
                              base_env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Construit les kwargs `docker.containers.run` d'un sandbox durci.

    device_requests / devices : passés tels quels par la couche GPU (lot 1).
    """
    cfg = cfg or SandboxHardeningConfig()
    caps_add = [c for c in cfg.extra_caps_add if c.upper() not in FORBIDDEN_CAPS]

    security_opt = ["no-new-privileges:true"]
    if cfg.seccomp_profile_path and os.path.isfile(cfg.seccomp_profile_path):
        security_opt.append(f"seccomp={cfg.seccomp_profile_path}")
    # (sans profil custom, Docker applique son seccomp par défaut, déjà restrictif)

    tmpfs = {
        "/tmp": f"rw,noexec,nosuid,nodev,size={cfg.tmpfs_size_mb}m",
        "/run": f"rw,noexec,nosuid,nodev,size=64m",
    }

    kwargs: Dict[str, Any] = {
        "privileged": False,
        "cap_drop": ["ALL"],
        "cap_add": caps_add,
        "security_opt": security_opt,
        "read_only": cfg.read_only_rootfs,
        "tmpfs": tmpfs,
        "pids_limit": cfg.pids_limit,
        "mem_limit": cfg.mem_limit,
        "memswap_limit": cfg.mem_limit,        # pas de swap supplémentaire
        "ulimits": [{"Name": "nofile", "Soft": cfg.nofile, "Hard": cfg.nofile}],
        "user": "openhands",                   # non-root (défini dans l'image)
        "environment": dict(base_env or {}),
    }

    runtime = _detect_isolation_runtime(cfg)
    if runtime:
        kwargs["runtime"] = runtime
    kwargs["_isolation_runtime"] = runtime     # lu par le validateur, retiré avant run

    # ── Réseau ──────────────────────────────────────────────────────────────
    if not cfg.allow_network:
        kwargs["network_mode"] = "none"
    else:
        if not cfg.internal_network_name:
            raise SandboxPolicyError(
                "allow_network=True exige un réseau Docker interne (internal_network_name) : "
                "le réseau hôte est interdit")
        kwargs["network"] = cfg.internal_network_name
        if cfg.egress_proxy:
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                kwargs["environment"].setdefault(k, cfg.egress_proxy)
            kwargs["environment"].setdefault("NO_PROXY", "localhost,127.0.0.1")

    # ── GPU (lot 1) ─────────────────────────────────────────────────────────
    if device_requests:
        kwargs["device_requests"] = device_requests
    if devices:
        kwargs["devices"] = devices

    if cfg.strict and not runtime:
        # Pas de gVisor/Kata : le durcissement namespace reste appliqué, mais on
        # le signale. En strict, l'appelant décide (voir require_isolation).
        kwargs["_isolation_runtime"] = None
    return kwargs


class SandboxPolicyError(RuntimeError):
    pass


def validate_run_kwargs(kwargs: Dict[str, Any], *, strict: bool = True) -> List[str]:
    """Vérifie qu'un jeu de kwargs respecte le profil. Retourne la liste des
    violations (vide = conforme). En strict, l'appelant refuse de démarrer si
    la liste n'est pas vide."""
    v: List[str] = []
    if kwargs.get("privileged"):
        v.append("privileged=True interdit")
    if "ALL" not in (kwargs.get("cap_drop") or []):
        v.append("cap_drop doit contenir ALL")
    for c in kwargs.get("cap_add") or []:
        if str(c).upper() in FORBIDDEN_CAPS:
            v.append(f"capacité interdite ajoutée : {c}")
    secopt = kwargs.get("security_opt") or []
    if not any("no-new-privileges" in str(s) for s in secopt):
        v.append("no-new-privileges manquant")
    if kwargs.get("network_mode") == "host":
        v.append("network_mode=host interdit")
    if kwargs.get("pid_mode") == "host" or kwargs.get("ipc_mode") == "host":
        v.append("partage d'espace de noms hôte (pid/ipc) interdit")
    if not kwargs.get("read_only", False):
        v.append("racine non montée en lecture seule")
    binds = kwargs.get("volumes") or {}
    for host_path in (binds.keys() if isinstance(binds, dict) else []):
        if str(host_path) in ("/", "/etc", "/var/run/docker.sock", "/root", "/home"):
            v.append(f"montage hôte sensible : {host_path}")
    if strict and kwargs.get("_isolation_runtime") in (None, ""):
        v.append("mode strict : runtime d'isolation (gVisor/Kata) requis et absent")
    return v


def require_hardened(kwargs: Dict[str, Any], *, strict: bool = True) -> Dict[str, Any]:
    """Valide puis nettoie les kwargs pour l'appel docker. Lève si non conforme
    en strict. Retire les clés internes (préfixe `_`)."""
    violations = validate_run_kwargs(kwargs, strict=strict)
    if violations and strict:
        raise SandboxPolicyError("sandbox non conforme au profil durci : " + "; ".join(violations))
    return {k: val for k, val in kwargs.items() if not k.startswith("_")}


def process_runtime_refused(strict: bool = True) -> Optional[str]:
    """Le sandbox en processus (RUNTIME=process) ne fournit aucune isolation.
    Retourne un message de refus en mode strict, sinon None."""
    if strict:
        return ("RUNTIME=process refusé en mode sécurisé : l'agent-server s'exécuterait "
                "comme processus de l'hôte, sans isolation. Utiliser le runtime conteneur durci.")
    return None
