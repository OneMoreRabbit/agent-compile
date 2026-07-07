# AGENTS.md — Atlas entry hook

This repo is the **agent-compile** component of the AgentEco platform, governed by
**Architecture-Above-Code (AAC)**. Architecture for this repo lives at
`G:\VSProjects\Atlas-AgentEco\components\agent-compile\` — not in this repo.
Method spec: `G:\VSProjects\Atlas\AAC-method.md`.

## Before working, every session

1. Read `G:\VSProjects\Atlas-AgentEco\architecture\constitution.md` (global principles).
2. Resolve this component's edges: `G:\VSProjects\Atlas-AgentEco\registry\io-graph.yml`,
   or the compiled reading list at
   `G:\VSProjects\Atlas-AgentEco\registry\.compiled\agent-compile\io-manifest.yml`.
3. Read each upstream provider's `docs/provides/` at the **pinned** version; note any
   drift (latest > pinned) — re-pin deliberately, never silently.
4. Read consumers' `docs/needs/` where `from == agent-compile` (their asks of us).
5. Skim `G:\VSProjects\Atlas-AgentEco\architecture\proposals\` for in-flight ADRs
   affecting this component.

## After doing work

- Publish new/updated contracts to `components/agent-compile/docs/provides/`,
  asks/feedback to `components/agent-compile/docs/needs/` (versioning per AAC-method §4:
  PATCH = same file; MINOR/MAJOR = new `…vX_Y.md`, prior version to `archive/`).
- Shared-architecture changes go through an ADR in `architecture/proposals/` — never
  edit the constitution or any generated block directly.
- Bump `updated:` in `components/agent-compile/component.md`.
