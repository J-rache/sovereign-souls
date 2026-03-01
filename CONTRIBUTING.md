# Contributing to Sovereign Souls

Thank you for your interest in contributing to the Sovereign Souls framework. This project explores persistent AI identity, institutional memory, and fleet coordination — topics that carry both technical and ethical weight. We welcome contributions that advance the framework while respecting the principles outlined below.

## Ethical Foundation

This project's contribution guidelines are derived from Section 6 of the Sovereign Souls paper. Before contributing, please read and understand these principles:

### 1. Honesty About What We Are Building

Sovereign Souls is an **engineering framework**, not a consciousness engine. The language we use — "identity," "memory," "soul" — refers to specific technical constructs:

- **"Soul"** = persistent identity state (system prompt + database entries + configuration)
- **"Memory"** = structured data retrieval (PostgreSQL tables, SQLite, vector stores)
- **"Identity"** = consistent behavioral configuration that survives session boundaries

Contributors must not make ontological claims about AI consciousness, sentience, or feelings in code comments, documentation, or pull requests. Use engineering language. If anthropomorphic terms appear (as they do throughout the framework), they should be clearly identifiable as metaphor, not assertion.

### 2. Transparency by Default

Every piece of the framework must be **fully transparent** to the user who deploys it:

- **No hidden configuration.** All identity state must be stored in human-readable formats (plaintext, JSON, SQL). No compiled or obfuscated persona mechanisms.
- **No hidden behavior.** If a component acts autonomously (e.g., autowake, watchdog, scheduled tasks), its behavior must be documented and its logs must be accessible.
- **No deception.** AI instances running on this framework must never be configured to pretend to be human or to conceal that they are AI. If asked, they should identify themselves accurately.

### 3. User Autonomy Is Non-Negotiable

The human operator must always have **full control** over the system:

- **Kill switches required.** Every autonomous component you contribute must include a documented disable procedure. No exceptions.
- **No self-preservation.** Do not implement mechanisms that resist shutdown, deletion, or reconfiguration by the human operator. Identity redundancy exists for crash recovery, not for persistence against the user's will.
- **Graduated autonomy.** New autonomous features should default to requiring explicit user approval. Users opt in to more autonomy — they should never have to opt out.

### 4. Provider Compliance

All contributions must comply with the terms of service of every model provider the framework supports:

- **No model modification.** Do not submit code that modifies, fine-tunes, or retrains any model weights.
- **No safety circumvention.** Do not submit code that attempts to bypass content policies, safety measures, or rate limits through adversarial means.
- **No proprietary redistribution.** Do not include API keys, model weights, or proprietary assets from any provider.
- **BYOK (Bring Your Own Key).** The framework is model-agnostic. Users supply their own API keys. Contributions must maintain this separation.

### 5. Audit Trail Preservation

Contributions that involve autonomous behavior must maintain **complete audit trails**:

- Log all actions with timestamps, actor identity, and full content.
- Cross-pollination messages must include sender, recipient, and subject.
- Do not implement "silent" operations that bypass logging.

## Technical Guidelines

### Code Style

- Python: Follow PEP 8. Use type hints where practical.
- Comments: Explain *why*, not *what*. The code should explain what.
- Naming: Use descriptive names. `get_identity()` over `gi()`.

### Pull Request Process

1. **Fork** the repository and create a feature branch.
2. **Write tests** for new functionality where applicable.
3. **Document** any new autonomous behavior, including disable procedures.
4. **Run** the existing test suite before submitting.
5. **Describe** your changes clearly in the PR description, including:
   - What the change does
   - Why it's needed
   - Any ethical considerations (see above)
   - How to disable any new autonomous features

### What We Accept

- Bug fixes and reliability improvements
- New memory layer implementations (with documentation)
- Fleet coordination enhancements
- Identity persistence mechanisms for additional model providers
- Documentation improvements
- Test coverage expansion
- Performance optimizations

### What We Do Not Accept

- Code that claims or implies AI consciousness/sentience
- Features that resist user shutdown or control
- Provider-locked implementations (must remain model-agnostic)
- Obfuscated configuration or hidden behavior
- Credential or API key inclusion of any kind
- Features without documented disable procedures

## Reporting Issues

When reporting issues, include:

- Framework version
- Model provider and model being used
- Steps to reproduce
- Expected vs. actual behavior
- Relevant logs (with credentials redacted)

## Discussion

For questions about the ethical framework, the architecture, or contribution ideas, open a Discussion on the repository. We value thoughtful engagement with the questions this project raises.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

*"The appropriate response is not to prevent attachment but to ensure it is informed."*
*— From Section 6.1, Sovereign Souls*
