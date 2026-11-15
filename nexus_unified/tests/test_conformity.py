"""Vérifie que les 8 phases du pipeline initial et les 9 exigences sont conformes."""
from __future__ import annotations

from nexus_unified.conformity import check_conformity


def test_all_conformity_checks_pass():
    rep = check_conformity()
    failing = {k: v["detail"] for k, v in rep.items() if not v["ok"]}
    assert not failing, f"vérifications non conformes : {failing}"


def test_eight_pipeline_phases_present():
    rep = check_conformity()
    phases = [k for k in rep if k[0].isdigit() and k[1] == "."]
    assert len(phases) >= 8


def test_nine_requirements_present():
    rep = check_conformity()
    reqs = [k for k in rep if any(k.startswith(f"{i}.") for i in range(1, 10))]
    # 8 phases (1..8) + 9 exigences (1..9) partagent des préfixes numériques ;
    # on vérifie la présence des exigences-clés par mot.
    keys = " ".join(rep.keys())
    for term in ["GPU tout constructeur", "LLM global", "Modèle externe",
                 "Orchestrateur maître", "OpenHands fourni", "Magasins open source",
                 "Apprentissage par succès", "Sandbox obligatoire", "Baux illimités"]:
        assert term in keys, f"exigence absente du rapport : {term}"
