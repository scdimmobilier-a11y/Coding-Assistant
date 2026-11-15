"""nexus_unified.security — inspection obligatoire des artefacts et durcissement du sandbox.

Point 9 du cahier des charges : le sandbox est obligatoirement sécurisé, et
tout modèle ou jeu de données téléchargé est obligatoirement inspecté (malware,
commande C2) avant d'être exposé au code de l'agent.

Entrées publiques :
- `ArtifactGate.inspect_and_admit` : porte d'admission (quarantaine → scan → admission).
- `ArtifactScanner.scan` : inspection seule, retourne un `ScanReport`.
- `build_hardened_run_kwargs` / `require_hardened` : profil de sandbox durci.
"""
from .findings import Finding, ScanReport, Severity, Verdict
from .scanner import ArtifactScanner, ScannerConfig, sha256_file
from .gate import ArtifactGate, GatePolicy, AdmissionResult
from .model_scan import scan_model_file
from .pickle_scan import scan_pickle_bytes, classify_global
from .ioc import scan_text
from .archive_scan import inspect_archive, safe_extract
from .sandbox_policy import (
    SandboxHardeningConfig, build_hardened_run_kwargs, validate_run_kwargs,
    require_hardened, process_runtime_refused, SandboxPolicyError,
)

__all__ = [
    "Finding", "ScanReport", "Severity", "Verdict",
    "ArtifactScanner", "ScannerConfig", "sha256_file",
    "ArtifactGate", "GatePolicy", "AdmissionResult",
    "scan_model_file", "scan_pickle_bytes", "classify_global", "scan_text",
    "inspect_archive", "safe_extract",
    "SandboxHardeningConfig", "build_hardened_run_kwargs", "validate_run_kwargs",
    "require_hardened", "process_runtime_refused", "SandboxPolicyError",
]
