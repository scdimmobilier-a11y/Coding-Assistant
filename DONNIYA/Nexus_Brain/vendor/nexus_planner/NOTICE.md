# Third-Party Notice — Nexus Planner

This module is a modified, renamed derivative of **PDDLStream**, created by
Caelan R. Garrett, Tomás Lozano-Pérez, and Leslie P. Kaelbling (MIT).

- Upstream license: **GNU General Public License v3.0 (GPLv3)**
- Upstream repository: github.com/caelan/pddlstream
- Citation: Garrett, Lozano-Pérez, Kaelbling. "PDDLStream: Integrating
  Symbolic Planners and Blackbox Samplers via Optimistic Adaptive
  Planning." ICAPS 2020.

## Required GPLv3 modification notice (License §5a)

GPLv3 requires that modified versions "carry prominent notices stating
that you modified it, and giving a relevant date." This notice serves
that purpose:

> This code was renamed and modified (identifiers, package name, file
> names, internal branding changed from "PDDLStream" to "Nexus Planner")
> starting July 2026. The original `LICENSE` file (GPLv3, unmodified) is
> included in this directory, as required.

The `downward/` directory in the upstream repository was an empty git
submodule placeholder (Fast Downward, the external planner PDDLStream
calls out to) — it was not populated in the source archive this module
was built from, and Fast Downward's own license has not been reviewed
here.

## Why this matters for Nexus Brain specifically

Unlike the other five vendored components (all permissive licenses),
**GPLv3 is copyleft**. If this module's code is directly incorporated
into or statically linked with the rest of Nexus Brain and the combined
work is distributed — or, under some interpretations, offered as a
network service depending on how it's packaged — GPLv3 can require
that the combined work's source be made available under GPLv3 too. This
directly affects any plan to keep Nexus Brain closed-source/proprietary
for investors.

Practical mitigation commonly used for exactly this situation: keep
Nexus Planner running as an isolated subprocess/microservice that the
rest of Nexus Brain calls over a local API/CLI boundary, rather than
importing its code inline into a proprietary codebase. This is not legal
advice — get a real IP/open-source-licensing lawyer to confirm before
this goes anywhere near investors or a distributed product.
