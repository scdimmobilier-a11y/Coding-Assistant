"""nexus_unified.accelerators — découverte (tout constructeur, points 1) et baux (point 2)."""
from .discovery import (
    Accelerator, discover_accelerators, discover_cdi, discover_nvidia,
    discover_amd, discover_intel, discover_npu, discovery_report,
)
from .lease import AcceleratorLeaseManager, Lease, LeaseError

__all__ = [
    "Accelerator", "discover_accelerators", "discover_cdi", "discover_nvidia",
    "discover_amd", "discover_intel", "discover_npu", "discovery_report",
    "AcceleratorLeaseManager", "Lease", "LeaseError",
]
