# agent-compile

Manages versioned agent templates and compiles agent instances into ready-to-deploy artifacts for the ARC Power platform. Standalone Python tool. Companion to `image-compile` (which produces the image-defaults bundles this tool reads as the chain root) and `apply_openclaw_stack` (which consumes this tool's compiled artifacts).

See the build brief at `../integrations/agent-compile-build-brief-v0_1.md` for the implementation spec. See `../docs/agent-compile-development-plan-v0_1.md` for the development plan. Shared contracts with `image-compile` live in `../docs/contracts/`.

## Status

MVP complete + aligned with the live `agent_registry.yml` v0.4 schema. 183 unit tests passing.

- [x] Pass 1 — scaffolding, identifiers, registry I/O, matrix R/W
- [x] Pass 2 — chain resolution + merge semantics + template diff
- [x] Pass 3 — template new/fork/edit + instance compile + compose.yml + port allocation
- [x] Pass 4 — test mode (Docker runner) + matrix bless + verify
- [x] Pass 5 — snapshot mode (SSH fetch, JSON merge-patch diff, instance-fields scrub)
- [x] Registry alignment — reads the live v0.4 schema: `app` block, `share_class.org`, org_routing host fallback. See `../docs/contracts/agent-registry-app-block-v0_1.md`.

## Development notes

**The test fixtures track the live Ansible registry — keep them in sync.**
`tests/fixtures/agent_registry.yml` and `tests/fixtures/org_routing.yml` mirror
the live files at `~/ansible/registry/agent_registry.yml` and
`~/ansible/inventory/group_vars/all/org_routing.yml` (Windows source:
`VSProjects/Ansible/ansible/...`). The first four agents in the fixture are
copied **verbatim** from the live registry as a schema-fidelity reference;
`test_agent_entry.py::test_fixture_reference_agents_match_live_v0_4_shape`
fails loudly if that shape drifts. When the live registry schema changes,
re-copy from the live file — do not hand-edit the fixture into a shape that
diverges from production. This is the discipline that prevents the
schema-divergence class of bug (see the app-block contract for the history).

## CLI verbs

Template subcommands: `new`, `fork`, `snapshot`, `test`, `bless`, `list`, `diff`, `edit`.
Instance subcommands: `compile [--all]`, `test`, `verify`, `list`.

See `../integrations/agent-compile-build-brief-v0_1.md` §CLI interface for the full surface.

## Layout

```
agent-compile/
├── pyproject.toml
├── config.yml                       # tool config
├── src/agent_compile/
│   ├── __main__.py                  # click entry
│   ├── identifiers.py               # parse/format <flavour>:<name>:<version>
│   ├── registry.py                  # ~/registry/ R/W
│   ├── matrix.py                    # compatibility matrix R/W
│   ├── config.py                    # config loader
│   └── exit_codes.py                # tool exit codes (range 30-39)
├── templates/
│   └── instance-fields/openclaw.yml # snapshot scrub list (stub until first probe-report)
└── tests/
    ├── test_identifiers.py
    ├── test_matrix.py
    ├── test_registry.py
    └── fixtures/                    # hand-authored image_defaults bundle + agent registry
```

## Quick start (dev)

```bash
python -m venv .venv
. .venv/Scripts/activate                          # Windows; use .venv/bin/activate on Linux
pip install -e .[dev]
pytest
```

## Exit codes

Tool exit codes use the 30–39 range, distinct from image-compile (20–29) and the wrapper container (3–7). See `src/agent_compile/exit_codes.py`.
