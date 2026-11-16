# Third-Party Notice — Nexus Harness

This module is a rebranded, modified derivative of **Continual Harness:
Online Adaptation for Self-Improving Foundation Agents**, by Seth Karten,
Joel Zhang, Tersoo Upaa Jr, Ruirong Feng, Wenzhe Li, Chengshuai Shi, Chi
Jin, and Kiran Vodrahalli, and colleagues (see full author lists in
`README.md`'s Citation section).

- Upstream license: MIT
- Upstream copyright: see `LICENSE` (unmodified, kept in this directory)
- Papers: arXiv:2605.09998 (Continual Harness), arXiv:2603.15563 (The
  PokéAgent Challenge — this repo also bundles that benchmark's
  hand-engineered `pokeagent` scaffold)

The Citation section and the "previously published as
sethkarten/pokeagent-speedrun" provenance note in `README.md` were
intentionally left untouched — citation attribution and repo history are
factual/academic matters, not product branding, so they were not
rebranded.

## Heads-up: Pokémon trademark/IP adjacency

This module's evaluation environment (`pokemon_env/`, `PokemonRed-GBC/`,
`Emerald-GBAdvance/`, and emulator save-state fixtures under `tests/`)
benchmarks the harness against Pokémon Red/Emerald/Blue/Yellow/Crystal.
No game ROM files are included in this archive — only emulator save
states, trajectory logs, and interface code. That said, "Pokémon" and the
game titles are Nintendo/Game Freak/Creatures Inc. trademarks; references
to them were left as accurate factual descriptions of the benchmark
environment rather than rebranded (renaming "Pokémon Red" to anything
"Nexus"-branded would be inaccurate, not just risky). If this evaluation
environment is ever exposed in anything customer- or investor-facing
under the Nexus name, it's worth keeping the Pokémon-specific benchmark
clearly labeled as a third-party research benchmark rather than implying
it's Nexus's own content.
