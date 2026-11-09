# CODEX.md — working agreement for Codex in this repository

Read order: `AGENTS.md` (repository rules, they win) → this file → `CODEX.local.md` if present
(maintainer's local instructions and machine notes; git-ignored).

## Model defaults (`.codex/config.toml`)

- Main agent and every subagent: `gpt-6.1-sol`, reasoning effort `medium`. Quality comes from the
  two-round review below, not from a higher effort.

## How each unit of work is done

1. Take the next item from the maintainer's list.
2. Before a non-trivial feature or fix, look at how similar open-source projects solve it (code,
   issues, maintainer answers) and note the findings in the local record.
3. Failing test first, then the change, then the gate from `AGENTS.md`.
4. Two-round adversarial review: spawn the `critic` agent (`.codex/agents/critic.toml`) on the
   finished piece; keep its thread open; answer each point after fixing; send the fixed version to
   the same critic for a second round; fix again.
5. Commit following `AGENTS.md` (one coherent change, no AI attribution lines, minimal public
   changelog text).

## Parallel work

- Each parallel lane works in its own git worktree and branch; one integrator merges. An open
  critic thread counts toward the subagent thread cap, so keep 2 to 3 subagents per lane.

## Rules on top of `AGENTS.md`

- Never print, log or commit secrets.
- Never use `git stash`, `git reset --hard`, `git checkout .` or `git clean`; make a restore point
  before changing existing data.
- Stop only processes you started, by PID.
- Never delete, weaken or skip a test to get green.
- Tracked files stay free of personal data and machine details; those go to `*.local.md`.
