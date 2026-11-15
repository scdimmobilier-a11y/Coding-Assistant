"""nexus_unified.security.findings — résultat d'inspection commun à tous les analyseurs.

Un analyseur ne décide jamais seul : il produit des `Finding`, et le
`Verdict` se calcule par agrégation. La politique (artifact_gate) décide
ensuite si le verdict autorise la promotion de l'artefact hors quarantaine.
"""
from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional


class Severity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return ["info", "low", "medium", "high", "critical"].index(self.value)


class Verdict(str, enum.Enum):
    CLEAN = "clean"            # aucun constat au-dessus de LOW
    SUSPICIOUS = "suspicious"  # constat MEDIUM ou HIGH : bloqué par défaut
    MALICIOUS = "malicious"    # constat CRITICAL : bloqué, mis en quarantaine
    ERROR = "error"            # l'inspection n'a pas pu aboutir : bloqué

    @property
    def blocks_by_default(self) -> bool:
        return self is not Verdict.CLEAN


@dataclass(frozen=True)
class Finding:
    rule: str                    # identifiant stable, ex. "pickle.dangerous_global"
    severity: Severity
    file: str                    # chemin relatif dans l'artefact
    detail: str                  # phrase lisible
    evidence: str = ""           # extrait court, jamais le contenu complet
    category: str = "malware"    # malware | c2 | integrity | format | policy | dos
    analyzer: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class ScanReport:
    artifact: str
    sha256: Dict[str, str] = field(default_factory=dict)   # fichier -> empreinte
    findings: List[Finding] = field(default_factory=list)
    analyzers_run: List[str] = field(default_factory=list)
    analyzers_unavailable: Dict[str, str] = field(default_factory=dict)
    files_scanned: int = 0
    bytes_scanned: int = 0
    errors: List[str] = field(default_factory=list)

    def add(self, findings: Iterable[Finding]) -> None:
        self.findings.extend(findings)

    @property
    def verdict(self) -> Verdict:
        if self.errors:
            return Verdict.ERROR
        top = max((f.severity.rank for f in self.findings), default=-1)
        if top >= Severity.CRITICAL.rank:
            return Verdict.MALICIOUS
        if top >= Severity.MEDIUM.rank:
            return Verdict.SUSPICIOUS
        return Verdict.CLEAN

    def worst(self, n: int = 10) -> List[Finding]:
        return sorted(self.findings, key=lambda f: -f.severity.rank)[:n]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact": self.artifact,
            "verdict": self.verdict.value,
            "sha256": self.sha256,
            "files_scanned": self.files_scanned,
            "bytes_scanned": self.bytes_scanned,
            "analyzers_run": self.analyzers_run,
            "analyzers_unavailable": self.analyzers_unavailable,
            "errors": self.errors,
            "findings": [f.to_dict() for f in self.findings],
        }


def finding(rule: str, severity: Severity, file: str, detail: str,
            evidence: str = "", category: str = "malware",
            analyzer: str = "") -> Finding:
    ev = evidence if len(evidence) <= 240 else evidence[:237] + "..."
    return Finding(rule, severity, file, detail, ev, category, analyzer)


def max_severity(findings: Iterable[Finding]) -> Optional[Severity]:
    best: Optional[Severity] = None
    for f in findings:
        if best is None or f.severity.rank > best.rank:
            best = f.severity
    return best
