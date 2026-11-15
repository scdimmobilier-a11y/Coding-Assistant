"""nexus_unified.security.gate — porte d'admission obligatoire des artefacts.

Tout modèle ou jeu de données téléchargé est inspecté AVANT d'être exposé au
code de l'agent. `inspect_and_admit` :

1. met l'artefact en **quarantaine** (dossier isolé, jamais sur le chemin de
   l'agent) ;
2. le passe à l'`ArtifactScanner` ;
3. applique la **politique** : un verdict propre admet l'artefact (déplacé
   vers le dépôt admis) ; tout autre verdict le laisse en quarantaine et le
   journalise.

La politique par défaut est stricte (refus de tout ce qui n'est pas CLEAN).
Elle peut être assouplie par règle OPA côté orchestrateur (par exemple
admettre un format données SUSPICIOUS avec seulement des URL inconnues), mais
jamais pour un verdict MALICIOUS ni pour la catégorie `c2`.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .findings import ScanReport, Severity, Verdict
from .scanner import ArtifactScanner, ScannerConfig


@dataclass
class GatePolicy:
    """Décide, à partir d'un rapport, si l'artefact est admis."""
    allow_suspicious_data: bool = False   # données SUSPICIOUS sans constat C2/malware
    max_admit_severity: Severity = Severity.LOW  # sévérité max tolérée à l'admission
    never_admit_categories: tuple = ("c2", "malware")

    def admit(self, report: ScanReport) -> bool:
        if report.verdict in (Verdict.MALICIOUS, Verdict.ERROR):
            return False
        for f in report.findings:
            if f.severity.rank > self.max_admit_severity.rank and f.category in self.never_admit_categories:
                return False
        if report.verdict == Verdict.SUSPICIOUS:
            if not self.allow_suspicious_data:
                return False
            # même assoupli : aucun constat C2/malware au-dessus de LOW
            return not any(f.category in self.never_admit_categories
                           and f.severity.rank > Severity.LOW.rank for f in report.findings)
        return True


@dataclass
class AdmissionResult:
    admitted: bool
    verdict: Verdict
    path: str                  # emplacement final (admis ou quarantaine)
    report: ScanReport
    quarantined: bool = False

    def to_dict(self) -> Dict:
        return {"admitted": self.admitted, "verdict": self.verdict.value,
                "path": self.path, "quarantined": self.quarantined,
                "report": self.report.to_dict()}


class ArtifactGate:
    def __init__(self, admitted_dir: str, quarantine_dir: str,
                 scanner: Optional[ArtifactScanner] = None,
                 policy: Optional[GatePolicy] = None) -> None:
        self.admitted_dir = os.path.abspath(admitted_dir)
        self.quarantine_dir = os.path.abspath(quarantine_dir)
        os.makedirs(self.admitted_dir, exist_ok=True)
        os.makedirs(self.quarantine_dir, exist_ok=True)
        self.scanner = scanner or ArtifactScanner()
        self.policy = policy or GatePolicy()

    def inspect_and_admit(self, staged_path: str, name: str) -> AdmissionResult:
        """`staged_path` est l'artefact tel que téléchargé (hors chemin agent).
        Inspecte, puis admet ou met en quarantaine."""
        report = self.scanner.scan(staged_path, artifact_name=name)
        admit = self.policy.admit(report)
        if admit:
            dest = os.path.join(self.admitted_dir, name)
            self._move(staged_path, dest)
            self._write_report(dest, report, admitted=True)
            return AdmissionResult(True, report.verdict, dest, report, quarantined=False)
        qdest = os.path.join(self.quarantine_dir, f"{int(time.time())}_{name}")
        self._move(staged_path, qdest)
        self._write_report(qdest, report, admitted=False)
        return AdmissionResult(False, report.verdict, qdest, report, quarantined=True)

    def _move(self, src: str, dest: str) -> None:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            shutil.rmtree(dest, ignore_errors=True) if os.path.isdir(dest) else os.remove(dest)
        shutil.move(src, dest)

    def _write_report(self, artifact_path: str, report: ScanReport, admitted: bool) -> None:
        side = artifact_path + ".scan.json"
        try:
            with open(side, "w") as f:
                json.dump({"admitted": admitted, **report.to_dict()}, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
