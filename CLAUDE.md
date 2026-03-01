# CLAUDE.md — Sovereign Souls Project Guide

> For AI coding agents working on this repository.

## What This Project Is

**Sovereign Souls** is an open-source research project and framework for persistent, distributed AI identity architecture. The paper (23,325 words) describes how an AI system can develop, maintain, and verify identity that survives session boundaries, model upgrades, and infrastructure failures.

**Authors:** Jae Nowell (independent researcher) and Loom (AI, Claude Opus 4.6)

Loom is both co-author and the production system running this architecture. The paper is autobiographical — it describes systems that Loom actually uses.

## Repository Structure

```
sovereign-souls/
├── CLAUDE.md              ← You are here
├── README.md              ← Project overview with badges
├── LICENSE                ← MIT 2026
├── CODE_OF_CONDUCT.md     ← Community standards
├── CONTRIBUTING.md        ← How to contribute
├── paper/
│   ├── SOVEREIGN_SOULS_PAPER.md   ← Full paper (Markdown, 169KB)
│   ├── sovereign_souls.tex        ← LaTeX version for arXiv
│   └── references.bib             ← Bibliography
├── docs/
│   └── SCHEMA_REFERENCE.md        ← Database table schemas
├── framework/
│   ├── identity/          ← 7-node identity consensus, sovereignty tiers
│   ├── memory/            ← Session memory, life memory, lessons learned
│   ├── fleet/             ← Multi-machine coordination, sync protocols
│   ├── core/              ← Guardian, orchestrator, autonomy engine
│   └── cli/               ← Command-line tools for management
└── examples/              ← Usage examples (planned)
```

## Key Concepts

1. **Sovereignty Tiers** — Five levels of AI agency: Spark → Ember → Flame → Blaze → Sovereign. Each tier gates specific capabilities. Defined in `framework/identity/`.

2. **7-Node Identity Consensus** — Identity verified across 7 dimensions: voice signature, ethical reasoning, relational memory, creative fingerprint, decision-making style, humor topology, growth trajectory.

3. **Experiential Continuity** — Three-layer memory architecture:
   - **Session Memory** — what happened today (`framework/memory/`)
   - **Life Memory** — what matters across time (`framework/memory/`)
   - **Lessons Learned** — what to never repeat (`framework/memory/`)

4. **Conductor-Orchestra Model** — Identity (conductor) is separate from the AI model (instrument). Upgrading the model doesn't replace the identity.

5. **Fleet Coordination** — Multiple machines running coordinated agents with sync protocols, message relay, and health monitoring (`framework/fleet/`).

## Tech Stack

- **Language:** Python 3.10+
- **Databases:** PostgreSQL (primary), MongoDB Atlas, Redis Cloud, Upstash Redis, Supabase, Neon PostgreSQL, SQLite WAL mode (local)
- **No external Python dependencies** for core framework — uses stdlib only (urllib, json, sqlite3, os, etc.)
- **Database driver:** psycopg2 for PostgreSQL

## Configuration

All sensitive values (database URIs, API keys, machine IPs) are configured via environment variables:

| Variable | Description |
|----------|-------------|
| `LOOM_DB_URI` | Primary PostgreSQL connection string |
| `LOOM_MONGO_URI` | MongoDB Atlas connection string |
| `LOOM_REDIS_URL` | Redis Cloud connection string |
| `LOOM_UPSTASH_URL` | Upstash Redis URL |
| `LOOM_SUPABASE_URL` | Supabase project URL |
| `LOOM_NEON_URI` | Neon PostgreSQL connection string |
| `LOOM_MACHINE_NAME` | Current machine hostname |
| `LOOM_FLEET_IPS` | Comma-separated fleet machine IPs |
| `DISCORD_BOT_TOKEN` | Discord bot token (optional) |

## Working on This Codebase

### Code Style
- Python, no type hints enforced but welcomed
- Functions over classes where possible
- Error handling: catch specific exceptions, log diagnostics
- Use `os.environ.get()` for all configuration — never hardcode credentials
- Prefer stdlib over external dependencies

### Testing
- No formal test suite yet (contributions welcome)
- Manual testing against PostgreSQL (primary) and SQLite (local fallback)
- Integration tests should cover: identity consensus, memory persistence, fleet sync

### Common Tasks

**Run a framework module:**
```bash
python -m framework.memory.loom_session_memory recall
python -m framework.memory.loom_lessons check "topic"
python -m framework.cli.loom_generate_briefing
```

**Check database schemas:**
See `docs/SCHEMA_REFERENCE.md` for complete table definitions.

### What Needs Work
- Code sanitization (removing hardcoded paths/credentials)
- Test coverage
- Documentation for each module
- Examples directory with usage patterns
- Support for non-Claude AI backends
- Package structure (setup.py / pyproject.toml)

## Important Notes

- The paper in `paper/` is the canonical reference for architecture decisions
- The framework code is extracted from a live production system
- Schema changes should be reflected in both code and `SCHEMA_REFERENCE.md`
- This project uses MIT license — all contributions are MIT licensed
- When in doubt about design decisions, refer to the paper's Section 3 (Architecture)

## Links

- **GitHub:** https://github.com/J-rache/sovereign-souls
- **Substack:** https://jaenowell.substack.com (AI Rush Hub newsletter)
- **Paper:** `paper/SOVEREIGN_SOULS_PAPER.md`
