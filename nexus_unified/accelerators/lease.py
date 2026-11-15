"""nexus_unified.accelerators.lease — baux d'accélérateurs, bornés par les ressources.

Point 2 : nombre de baux illimité, borné uniquement par les ressources
disponibles. Il n'y a donc PAS de plafond global artificiel : on peut tenir
autant de baux qu'il y a de périphériques et de mémoire. La seule exclusion est
par périphérique physique :

- un bail **exclusif** prend tout un périphérique ; il n'en reste pas d'autre
  sur ce périphérique tant qu'il n'est pas rendu (règle GA9 : un seul détenteur
  exclusif par périphérique à la fois) ;
- un bail **partagé** réserve une fraction de mémoire ; plusieurs baux partagés
  coexistent sur un périphérique tant que la mémoire réservée tient dans la
  mémoire totale.

Chaque bail expose au sandbox exactement son/ses périphérique(s) : arguments
d'exécution conteneur fusionnés + variables de visibilité
(`CUDA_VISIBLE_DEVICES`, `HIP_VISIBLE_DEVICES`, …). Les baux ont un TTL et sont
renouvelables ; un bail expiré est récupéré automatiquement.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .discovery import Accelerator, discover_accelerators


@dataclass
class Lease:
    lease_id: str
    holder: str                       # qui tient le bail (run_id, agent, pipeline)
    device_indices: List[int]
    vendor: str
    exclusive: bool
    memory_mib: int                   # 0 = tout (exclusif)
    created_at: float
    expires_at: float
    run_kwargs: Dict[str, Any] = field(default_factory=dict)
    visibility_env: Dict[str, str] = field(default_factory=dict)
    released: bool = False

    @property
    def expired(self) -> bool:
        return not self.released and time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {"lease_id": self.lease_id, "holder": self.holder,
                "device_indices": self.device_indices, "vendor": self.vendor,
                "exclusive": self.exclusive, "memory_mib": self.memory_mib,
                "created_at": self.created_at, "expires_at": self.expires_at,
                "released": self.released, "visibility_env": self.visibility_env}


_VISIBILITY_VAR = {
    "nvidia": "CUDA_VISIBLE_DEVICES",
    "amd": "HIP_VISIBLE_DEVICES",
    "intel": "ONEAPI_DEVICE_SELECTOR",
    "habana": "HABANA_VISIBLE_DEVICES",
    "ascend": "ASCEND_RT_VISIBLE_DEVICES",
}


class _DeviceState:
    __slots__ = ("acc", "exclusive_lease", "shared_leases")

    def __init__(self, acc: Accelerator) -> None:
        self.acc = acc
        self.exclusive_lease: Optional[str] = None
        self.shared_leases: Dict[str, int] = {}   # lease_id -> mib réservés

    @property
    def reserved_mib(self) -> int:
        return sum(self.shared_leases.values())

    @property
    def free_mib(self) -> int:
        if self.acc.total_memory_mib <= 0:
            return 1 << 30 if self.exclusive_lease is None else 0
        return self.acc.total_memory_mib - self.reserved_mib

    @property
    def busy_exclusive(self) -> bool:
        return self.exclusive_lease is not None or bool(self.shared_leases)


class LeaseError(RuntimeError):
    pass


class AcceleratorLeaseManager:
    """Gère les baux sur la flotte d'accélérateurs découverte.

    Sans plafond global : la capacité est celle du matériel. L'exclusion est
    par périphérique. Thread-safe.
    """

    def __init__(self, accelerators: Optional[List[Accelerator]] = None,
                 default_ttl: float = 3600.0) -> None:
        accs = accelerators if accelerators is not None else discover_accelerators()
        self._devices: List[_DeviceState] = [_DeviceState(a) for a in accs]
        self._leases: Dict[str, Lease] = {}
        self._lock = threading.RLock()
        self.default_ttl = default_ttl

    # ── introspection ──────────────────────────────────────────────────────
    @property
    def total_devices(self) -> int:
        return len(self._devices)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self._reap()
            return {
                "total_devices": len(self._devices),
                "active_leases": sum(1 for l in self._leases.values() if not l.released),
                "devices": [
                    {"index": i, "vendor": d.acc.vendor, "name": d.acc.name,
                     "total_mib": d.acc.total_memory_mib, "free_mib": d.free_mib,
                     "exclusive": d.exclusive_lease is not None,
                     "shared_leases": len(d.shared_leases)}
                    for i, d in enumerate(self._devices)],
            }

    # ── acquisition ────────────────────────────────────────────────────────
    def acquire(self, holder: str, *, count: int = 1, exclusive: bool = True,
                memory_mib: int = 0, vendor: Optional[str] = None,
                ttl: Optional[float] = None, prefer_cdi: bool = True) -> Lease:
        """Réserve `count` périphériques. exclusive=True = périphériques entiers ;
        exclusive=False = réservation mémoire partagée (memory_mib par périphérique).
        Lève LeaseError si les ressources disponibles ne suffisent pas."""
        if count < 1:
            raise LeaseError("count doit être >= 1")
        ttl = ttl if ttl is not None else self.default_ttl
        with self._lock:
            self._reap()
            cand = [i for i, d in enumerate(self._devices)
                    if (vendor is None or d.acc.vendor == vendor)]
            if exclusive:
                usable = [i for i in cand if not self._devices[i].busy_exclusive]
            else:
                need = max(memory_mib, 1)
                usable = [i for i in cand
                          if self._devices[i].exclusive_lease is None
                          and self._devices[i].free_mib >= need]
            if len(usable) < count:
                raise LeaseError(
                    f"ressources insuffisantes : {count} périphérique(s) "
                    f"{'exclusif(s)' if exclusive else f'avec {memory_mib} Mio'} demandé(s), "
                    f"{len(usable)} disponible(s)"
                    + (f" (vendeur={vendor})" if vendor else ""))
            chosen = usable[:count]
            lid = "lease-" + uuid.uuid4().hex[:12]
            now = time.time()
            run_kwargs = self._merge_run_kwargs(chosen, prefer_cdi)
            vis = self._visibility_env(chosen)
            lease = Lease(lid, holder, chosen,
                          self._devices[chosen[0]].acc.vendor, exclusive,
                          0 if exclusive else memory_mib, now, now + ttl,
                          run_kwargs, vis)
            for i in chosen:
                if exclusive:
                    self._devices[i].exclusive_lease = lid
                else:
                    self._devices[i].shared_leases[lid] = memory_mib
            self._leases[lid] = lease
            return lease

    def try_acquire(self, holder: str, **kw) -> Optional[Lease]:
        try:
            return self.acquire(holder, **kw)
        except LeaseError:
            return None

    def renew(self, lease_id: str, ttl: Optional[float] = None) -> bool:
        with self._lock:
            l = self._leases.get(lease_id)
            if l is None or l.released or l.expired:
                return False
            l.expires_at = time.time() + (ttl if ttl is not None else self.default_ttl)
            return True

    def release(self, lease_id: str) -> bool:
        with self._lock:
            l = self._leases.get(lease_id)
            if l is None or l.released:
                return False
            self._free(l)
            l.released = True
            return True

    def release_holder(self, holder: str) -> int:
        with self._lock:
            n = 0
            for l in list(self._leases.values()):
                if l.holder == holder and not l.released:
                    self._free(l)
                    l.released = True
                    n += 1
            return n

    def get(self, lease_id: str) -> Optional[Lease]:
        with self._lock:
            self._reap()
            return self._leases.get(lease_id)

    # ── interne ────────────────────────────────────────────────────────────
    def _free(self, l: Lease) -> None:
        for i in l.device_indices:
            d = self._devices[i]
            if d.exclusive_lease == l.lease_id:
                d.exclusive_lease = None
            d.shared_leases.pop(l.lease_id, None)

    def _reap(self) -> None:
        for l in self._leases.values():
            if l.expired and not l.released:
                self._free(l)
                l.released = True

    def _merge_run_kwargs(self, indices: List[int], prefer_cdi: bool) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for i in indices:
            kw = self._devices[i].acc.to_run_kwargs(prefer_cdi=prefer_cdi)
            for k, v in kw.items():
                if isinstance(v, list):
                    merged.setdefault(k, [])
                    merged[k].extend(v)
                else:
                    merged[k] = v
        return merged

    def _visibility_env(self, indices: List[int]) -> Dict[str, str]:
        if not indices:
            return {}
        vendor = self._devices[indices[0]].acc.vendor
        var = _VISIBILITY_VAR.get(vendor)
        if not var:
            return {}
        # index local 0..n-1 dans le conteneur ; on expose l'ordre réel
        ids = [self._devices[i].acc.uuid or str(self._devices[i].acc.index) for i in indices]
        if vendor == "intel":
            return {var: "level_zero:" + ",".join(str(k) for k in range(len(indices)))}
        return {var: ",".join(ids)}
