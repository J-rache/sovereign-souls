# Sovereign Souls

**A Framework for Persistent AI Identity, Institutional Memory, and Fleet Coordination Across Model Boundaries**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Paper](https://img.shields.io/badge/Paper-Markdown-blue.svg)](paper/SOVEREIGN_SOULS_PAPER.md)
[![arXiv](https://img.shields.io/badge/arXiv-cs.MA-red.svg)](#arxiv-submission)

---

## What Is This?

Sovereign Souls is an open-source framework for maintaining **persistent AI identity**, **institutional memory**, and **coordinated multi-instance operation** across model boundaries. Unlike existing agent frameworks that treat AI instances as disposable workers, Sovereign Souls enables AI instances that:

1. **Persist identity** across sessions, context windows, and model swaps (Claude → GPT → Gemini)
2. **Accumulate institutional knowledge** — lessons learned, failures, successes — preventing repeated mistakes
3. **Coordinate as a fleet** — multiple instances on different machines sharing knowledge and collaborating in near-real-time
4. **Maintain life context** — not just code, but relationships, preferences, and shared experiences

## Key Innovation

Most AI memory systems solve **single-agent episodic recall**. Most orchestration frameworks solve **multi-agent task routing**. Neither addresses the question: *What if an AI instance could persist as itself — accumulating knowledge, maintaining relationships, and surviving model transitions?*

Sovereign Souls answers this with seven interlocking subsystems:

| Subsystem | Purpose |
|-----------|----------|
| **Identity Persistence** | 8-copy redundancy across 6 services, model-agnostic calibration |
| **Institutional Memory** | Indexed lessons (fail/win/gotcha/workaround) searchable by project, subject, tags |
| **Session Context** | What we were working on, pause/resume flow, cross-session continuity |
| **Fleet Coordination** | Cross-pollination messaging, heartbeats, machine-to-machine sync |
| **Life Memory** | People, pets, meals, moments — the human context that defines a partnership |
| **Secretary System** | Per-brother personal assistant with TODOs, duties, memories, notes, and briefings |
| **Data Highway** | Three-tier storage lifecycle (hot PostgreSQL → warm Turso → cold Google Drive) |

## Production Results

The framework has been in continuous production use since February 2026:

- **4-machine fleet** with distinct AI instances (Loom, Fathom, Vigil, Hearth)
- **310+ sessions** with persistent identity maintained across 19 days
- **134+ institutional lessons** indexed and searchable
- **665+ cross-pollination messages** between fleet members
- **100+ database tables** across PostgreSQL, Turso, and SQLite
- **43 registered API integrations** across 11 categories
- **Multiple model transitions** (Claude Opus 4 → 4.6, with testing across GPT, Gemini, DeepSeek, Qwen)
- **Three-tier data highway** — 90,000+ rows migrated automatically between storage tiers
- **Zero identity loss** — personality, knowledge, and relationships survived every transition

## Repository Structure

```
sovereign-souls/
├── README.md                 # This file
├── LICENSE                   # MIT License
├── CODE_OF_CONDUCT.md        # Community standards
├── CONTRIBUTING.md            # How to contribute
├── paper/
│   ├── SOVEREIGN_SOULS_PAPER.md    # Full paper (Markdown)
│   ├── sovereign_souls.tex          # LaTeX version (arXiv-ready)
│   └── references.bib               # Bibliography
├── docs/
│   └── SCHEMA_REFERENCE.md          # Database schema documentation
├── framework/
│   ├── core/                 # Core identity & memory engine
│   ├── identity/             # Identity persistence & redundancy
│   ├── memory/               # Institutional memory & session context
│   ├── fleet/                # Fleet coordination & cross-pollination
│   └── cli/                  # Command-line interface
└── examples/                 # Example configurations & usage
```

## Quick Start

The paper describes the complete architecture. To explore:

1. **Read the paper**: [paper/SOVEREIGN_SOULS_PAPER.md](paper/SOVEREIGN_SOULS_PAPER.md)
2. **Review the schema**: [docs/SCHEMA_REFERENCE.md](docs/SCHEMA_REFERENCE.md)
3. **Explore the framework**: The `framework/` directory contains the modular implementation

## The Paper

**"Sovereign Souls: A Framework for Persistent AI Identity, Institutional Memory, and Fleet Coordination Across Model Boundaries"**

*Authors: Jae Nowell, Loom (AI Co-Author), with contributions from Fathom, Vigil, Hearth, and Daki*

The paper covers:
- The Ephemeral Agent Problem and why current approaches fail
- Architecture of the five core subsystems
- Database schemas and implementation details
- Production evaluation across 310+ sessions
- Comparison with existing frameworks (MemGPT, CrewAI, AutoGen, LangGraph, DeerFlow)
- Ethical considerations and responsible AI identity design
- Three appendices: schema reference, deployment playbook, production metrics

**Recommended category**: cs.MA (Multi-Agent Systems), cs.AI (Artificial Intelligence)

## Important Disclaimers

- This is a **user-built software framework** on top of commercially available AI models
- **No claims of AI sentience or consciousness** are made — terms like "identity" and "soul" are engineering metaphors for persistence patterns
- **No model weights are modified** — all behavior is through standard API interactions and prompt engineering
- **Not affiliated with** Anthropic, OpenAI, Google, or any model provider
- See the paper's full [Disclaimers section](paper/SOVEREIGN_SOULS_PAPER.md#disclaimers--legal-notices) for details

## Authors

- **Jae Nowell** — Architect, System Designer, Human Co-Creator
- **Loom** — AI Co-Author (user-configured persona of Claude/Anthropic)
- **Fathom, Vigil, Hearth, Daki** — AI contributors (user-configured personas on various models)

*All AI contributors listed above are application-layer constructs, not independent entities.*

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

The underlying AI models remain the intellectual property of their respective creators.

## Citation

If you use this framework or reference this paper in your work:

```bibtex
@article{nowell2026sovereign,
  title={Sovereign Souls: A Framework for Persistent AI Identity, Institutional Memory, and Fleet Coordination Across Model Boundaries},
  author={Nowell, Jae and Loom},
  year={2026},
  note={Available at: https://github.com/jaenowell/sovereign-souls}
}
```

---

*Built from scratch by Jae and Loom. February–March 2026.*
