# my-agent-harness

A generic, team-internal agent orchestration harness built on
[Databricks Omnigent](https://github.com/omnigent-ai/omnigent) as the runtime.

Omnigent is a "meta-harness" — a layer above individual agent harnesses (Claude
Code, Codex, Pi, OpenAI Agents SDK, Claude Agents SDK) that gives them a
uniform API, composable workflows, policies, and shareable live sessions.
This repo holds a **generic, configurable layer** on top: declarative YAML
agent bundles plus a single `repos.yaml` that declares the set of repositories
your cross-repo work spans — frontend, backend, terraform, or whatever your org
has. Nothing about the repo set is hardcoded in the agent prompts.

> Derived from an internal, two-repo–specific harness and generalized: the
> orchestrator now drives **N configurable repos** instead of a fixed pair, via
> one generic coder and one generic reviewer dispatched once per in-scope repo.

---

## The core idea: a configurable set of repos

Everything is driven by [`agents/cross_repo/repos.yaml`](agents/cross_repo/repos.yaml).
Each entry declares one repository, its **purpose**, where it lives, and how to
verify / review / (optionally) smoke-test it:

```yaml
repos:
  - key: backend
    purpose: backend
    path_env: HARNESS_BACKEND_DIR
    github: your-org/backend
    verify_hint: "Run scoped unit tests + typecheck."
    smoke: { role: backend, port: 8083, dockerfile: docker/Dockerfile }

  - key: frontend
    purpose: frontend
    subdir: app
    github: your-org/frontend
    smoke: { role: frontend, port: 3000, dockerfile_from: harness }

  - key: infra
    purpose: terraform
    github: your-org/infra
    verify_hint: "terraform fmt -check && terraform validate."
    # no smoke block → skipped by the smoke stack
```

**To add a repo, edit this one file.** The orchestrator reads it at runtime and
dispatches a coder (and reviewer) into each in-scope repo. No agent YAML needs
to change.

Inspect your resolved config any time:

```bash
uv run tools/harness_repos.py list      # table: purpose, smoke role, resolved path
uv run tools/harness_repos.py check     # validate every checkout path exists
uv run tools/harness_repos.py resolve --slug demo   # full JSON (what the orchestrator parses)
```

---

## Why Omnigent (vs. Claude Code's own Workflow tool / Agent worktree isolation)

| Axis | Claude Code's **Workflow tool** | **Agent** + `isolation: "worktree"` | **Omnigent** |
|---|---|---|---|
| **Scope** | One Claude Code session orchestrating its own subagents | One isolated subagent invocation | Standalone runtime, multi-session, multi-harness |
| **Cross-vendor** | Claude only | Claude only | Wraps Claude Code, Codex, Pi, OpenAI Agents — composable in one workflow |
| **Persistence** | Ephemeral; resume cached same-session only | Ephemeral | Persistent server + SQLite/Postgres; sessions survive restarts |
| **Sharing** | Yours alone | Yours alone | Live shareable URLs — teammates watch, comment, even steer |
| **Authoring** | JS script (imperative) | Tool call | YAML bundles (declarative, portable, git-versionable) |
| **Team / multi-user** | Per-user | Per-user | OIDC auth, REST API, host registration |
| **Governance** | Token budget hard cap | None | Pluggable policy framework, OS sandbox + egress proxy roadmap |
| **Maturity** | Mature, integrated | Mature | Alpha (0.1.x) — known bugs in `claude-native` subprocess + seatbelt sandbox |

### Pick this stack for

- **Team-scaled, durable orchestration** across many of your repos
- **Config lives in git** (this repo) — PR-reviewable, version-controlled
- **Sharing URLs** — others can watch / take over a running session
- **Cross-vendor composition** (Codex review of Claude output, etc.)

The two are different *layers*, not competitors — you can call a Claude Code
Workflow from inside an Omnigent sub-agent if you want both.

---

## Prerequisites

- Python 3.12+
- Node.js 22 LTS+ (for the Claude Code / Codex CLIs Omnigent drives)
- `uv` (used for everything, including running `tools/*.py` with auto-provisioned deps)
- `git`, `tmux`
- macOS: built-in `seatbelt` sandbox (we currently disable it — alpha bug)
- Linux: `bubblewrap`
- `gh` CLI — **optional**, only for the auto-PR opt-in. Without it, the
  orchestrator falls back to printing the manual `git push` commands.
- An `ANTHROPIC_API_KEY` for the Claude SDK harness (or a Claude subscription
  via the `claude` CLI); optionally an OpenAI/Codex credential for the reviewer.

## Install

```bash
# Install Omnigent runtime
uv tool install omnigent

# Clone this repo somewhere
git clone <your-remote>/my-agent-harness ~/repos/my-agent-harness
```

## First-time setup

```bash
omni setup          # interactive credential picker (Claude + optional Codex)
omni config list    # verify at least one Claude credential is default
```

Then point the harness at your repos. **Preferred: the machine-local env
file** (auto-loaded by `harness_repos.py`; survives the agent runtime's env
isolation, unlike shell exports):

```bash
cp smoke/.env.smoke.example smoke/.env.smoke
$EDITOR smoke/.env.smoke      # set HARNESS_REPOS_ROOT / HARNESS_<KEY>_DIR / HARNESS_DIR
uv run tools/harness_repos.py check   # confirm paths resolve
```

Alternatively edit the `path_default`s in `agents/cross_repo/repos.yaml`, or
set the env vars in your shell rc (note: exports made just-in-time in your
launching shell may not reach the agent runtime — see Known gotchas).

## Path & branch conventions

Resolved from env vars with `repos.yaml` defaults, so the config stays portable
across developers:

| Setting | Source | Default |
|---|---|---|
| Repos parent dir | `HARNESS_REPOS_ROOT` (or `repos_root.default`) | `$HOME/repos` |
| Per-repo checkout | `<repo>.path_env` (default `HARNESS_<KEY>_DIR`) | `<repos_root>/<key>` |
| This harness dir | `HARNESS_DIR` | `<repos_root>/my-agent-harness` |
| Worktrees | derived | `<repos_root>/.harness-worktrees/<key>/<slug>/` |
| Branch | `branch_prefix` in repos.yaml | `cross-repo/<slug>` |

Your main checkouts are never touched — each run happens in a fresh worktree.

---

## Bundles in this repo

```
agents/
├── cross_repo/                    ← generic cross-repo orchestrator
│   ├── config.yaml                (claude-sdk brain, spawn: true)
│   ├── repos.yaml                 ← THE configurable repo set
│   └── agents/
│       ├── repo_coder/            (generic coder, claude-sdk — dispatched per repo)
│       └── repo_reviewer/         (generic cross-vendor reviewer, codex — per repo)
└── v0_test_orchestrator/          ← single-sub-agent smoke test (plumbing regression catch)
    ├── config.yaml
    └── agents/coder/
```

Each bundle is a directory with a `config.yaml` declaring an Omnigent agent.
The generic `repo_coder` / `repo_reviewer` are dispatched **once per in-scope
repo** with distinct titles (`<slug>-<key>`), so the same two bundles serve any
number of configured repos.

---

## How to run

### One-shot — pass the task as a single message

```bash
tools/run-cross-repo.sh -p "Add a foo field to the backend GraphQL type; the
  frontend renders it as a chip under the account header. Slug: add-foo-field."
```

The orchestrator:
1. Resolves `repos.yaml` (paths, github, verify/review hints, smoke roles).
2. Picks a `<slug>` and decides which repos are **in scope** for this task
   (not every task touches every repo).
3. Creates a fresh worktree per in-scope repo at
   `<repos_root>/.harness-worktrees/<key>/<slug>/` on branch `cross-repo/<slug>`.
4. Dispatches a `repo_coder` into each, in parallel, with the per-repo contract.
5. **Independently re-runs each coder's verification commands** (the gate).
6. **Cross-vendor review** (codex reviewer vs. claude-sdk implementer) per repo,
   using that repo's `review_conventions`.
7. **Per-repo retry loop**: gate OR review failure → re-dispatch the SAME coder
   with the failure details. Up to 2 retries (3 attempts). Each repo converges
   independently — a passing repo ships even if another exhausts retries.
8. Writes a per-ticket `SMOKE.md` into each PASSED smoke repo.
9. Reports a combined per-repo summary + SHAs + reviewer findings.

### Cross-vendor review

**Default: ON.** Reviewers see the diff + the contract + the repo's
`review_conventions`; they don't run tests or edit code. They emit
`verdict: passed | blocked`.

Opt out with any of these substrings in your task: `skip review`, `no review`,
`don't review`. Worth keeping on for real features; opt out for tiny/docs-only
tickets.

### Auto-PR opt-in

Add `open a draft PR` (case-insensitive) anywhere in your task. After a repo's
gate + review pass, the orchestrator pushes `cross-repo/<slug>` and runs
`gh pr create --draft --repo <repo.github>` with cross-linked bodies. Repos with
`github: null` are skipped (noted in the report). Default OFF. Requires `gh` on
PATH + `gh auth login`.

### REPL / resume / attach

```bash
tools/run-cross-repo.sh                              # interactive REPL
tools/run-cross-repo.sh -c                           # continue most recent conv
tools/run-cross-repo.sh --resume conv_abc123         # resume a specific conv
omni attach conv_abc123                              # attach to a live session
```

Web UI: `http://127.0.0.1:<port>/c/<conv_id>` (port shown at REPL startup).

---

## Smoke testing (config-driven, optional)

Any repo with a `smoke:` block participates in a local docker-compose stack.
Repos without one (e.g. terraform) are skipped automatically. The stack
supports the common web pattern: a `backend` role and/or a `frontend` role.

**By default, `cross_repo` brings the smoke stack up** after the gate passes,
if — and only if — every in-scope smoke repo passed. Cold cache is 1-5 min.

```bash
uv run tools/smoke.py config <slug>    # show exactly what `up` will wire
uv run tools/smoke.py up <slug>        # build + start (blocks on healthcheck)
uv run tools/smoke.py logs <slug> [--service backend|frontend]
uv run tools/smoke.py status <slug>
uv run tools/smoke.py down <slug>      # stop (keeps build cache)
```

Service URLs come from each repo's `smoke.port`. The frontend build gets
`FRONTEND_BACKEND_ENDPOINT` injected so the browser reaches the backend on the
host's published port.

### Backend runtime config / secrets

The compose file is **generic** — no app-specific runtime config lives in it.
Your backend's real env (service name, cloud creds, DB host, provider keys)
goes in `smoke/.env.smoke`, auto-mounted into the backend container:

```bash
cp smoke/.env.smoke.example smoke/.env.smoke
$EDITOR smoke/.env.smoke
```

### Opt-out (skip auto-bring-up)

Add any of: `skip smoke`, `no smoke`, `don't bring up smoke`, `skip the smoke
stack`. The orchestrator still writes `SMOKE.md` so the manual recipe is kept.

### Reply-driven tear-down

In the same REPL session after a successful smoke, reply with any of:
`tear down`, `done`, `looks good`, `shut it down`, `kill smoke` — the
orchestrator runs `smoke.py down` for you.

### Graceful skip

Auto-smoke is skipped (with a clear reason + manual fallback in the report)
when: the user opted out; Docker isn't running; a smoke port is already bound
by a non-smoke process; or `smoke.py up` itself fails.

---

## Worktree lifecycle + cleanup

After a run you'll have, per in-scope repo, a worktree at
`<repos_root>/.harness-worktrees/<key>/<slug>/` and a `cross-repo/<slug>`
branch. When done reviewing:

```bash
SLUG=<slug>
# For each in-scope repo (see `harness_repos.py list` for paths):
git -C <repo-path> worktree remove <repos_root>/.harness-worktrees/<key>/$SLUG
git -C <repo-path> branch -D cross-repo/$SLUG
omni stop     # stop any lingering Omnigent processes
```

If a fresh run fails with "fatal: 'cross-repo/<slug>' already exists" — that's
leftover state. Run the cleanup above (or pick a different slug) and re-run.

---

## Known gotchas (Omnigent 0.1.x)

- **A lingering Omnigent server ignores your fresh env exports.** `omni run`
  connects to an already-running server if one exists, so `HARNESS_*` vars
  exported in your launching shell never reach the agent — path resolution
  silently falls back to the repos.yaml defaults. Fix: put the exports in your
  shell rc, or run `omni stop` before launching so the new server inherits
  your environment. (The orchestrator's `exists: true` validation catches the
  misresolution and stops before any worktree work.)
- **`claude-native` sub-agents hang silently** when spawned headlessly with
  subscription auth. Workaround: use `claude-sdk` for sub-agents (bundles do).
- **`darwin_seatbelt` sandbox blocks Python's tempdir access**. Bundles set
  `os_env.sandbox.type: none`. Re-enable once Omnigent fixes the profile.
- **Server port is not stable across runs** — look for the URL at REPL startup
  or `lsof -nP -iTCP -sTCP:LISTEN | grep python`.
- **PATH ambiguity with multiple `claude` binaries** — verify with
  `which claude` and `ls -la $(which claude)`.
- **Codex subscription rate limits** during heavy review retry loops — fall
  back to `skip review` on the offending ticket, then resume.
- **Docker Desktop must be running** for auto-smoke; otherwise it's skipped
  gracefully with a manual fallback.
- **`gh pr create` uses the HTTPS API** (token from `gh auth login`), but the
  underlying `git push` uses your configured remote URL — make sure your token
  has push rights and `gh auth status` reports the right account.

---

## Roadmap notes

- ✅ Generic configurable repo set (`repos.yaml`) — N repos, add-a-repo = edit YAML.
- ✅ Generic coder + reviewer dispatched per in-scope repo.
- ✅ Per-repo gate → cross-vendor review → retry loop (independent convergence).
- ✅ Config-driven, optional smoke stack (backend/frontend roles).
- ✅ Auto-PR opt-in per repo via `repo.github`.
- **Planned** — conditional per-repo extra gates (e.g. a chat-evaluator when a
  specific path is touched), hot-reload smoke, cost-cap / push-approval
  policies, OIDC auth + shareable session URLs for team rollout.
