#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""smoke.py — bring up a config-driven local smoke stack for a cross_repo run.

The set of services is derived from `repos.yaml`: every repo with a `smoke:`
block participates. Repos without one (e.g. a terraform repo) are skipped.
Supports the common web pattern — a `backend` role and/or a `frontend` role.

Usage:
    uv run tools/smoke.py up <slug> [--db sqlite|aurora]
    uv run tools/smoke.py down [<slug>]
    uv run tools/smoke.py logs [<slug>] [--service backend|frontend]
    uv run tools/smoke.py status [<slug>]
    uv run tools/smoke.py config <slug>     # show what `up` would wire

Worktree paths come from repos.yaml via harness_repos.py. The compose file
binds the per-slug worktrees at
    <repos_root>/.harness-worktrees/<repo-key>/<slug>/
which the cross_repo orchestrator creates.

Run with `uv run` so pyyaml is provisioned automatically (PEP 723 header).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import harness_repos

HARNESS_DIR = harness_repos.HARNESS_DIR
COMPOSE_FILE = HARNESS_DIR / "smoke" / "docker-compose.yml"


def smoke_repos(slug: str) -> dict[str, dict]:
    """Return {role: repo_dict} for in-config repos that have a smoke block.

    repo_dict includes the resolved `worktree` for the given slug.
    """
    cfg = harness_repos.resolve(slug=slug)
    by_role: dict[str, dict] = {}
    for repo in cfg["repos"]:
        smoke = repo.get("smoke")
        if not smoke:
            continue
        role = smoke.get("role")
        if role in by_role:
            sys.exit(
                f"error: two repos both claim smoke role '{role}' "
                f"({by_role[role]['key']} and {repo['key']}); roles must be unique."
            )
        by_role[role] = repo
    return by_role


def project_name(slug: str | None) -> str:
    return f"harness-smoke-{slug}" if slug else "harness-smoke"


def base_env(slug: str | None) -> dict[str, str]:
    env = os.environ.copy()
    env["COMPOSE_PROJECT_NAME"] = project_name(slug)
    return env


def compose_run(env: dict[str, str], *args: str) -> int:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), *args]
    return subprocess.run(cmd, env=env).returncode


def _resolve_dockerfile(repo: dict, context: Path) -> str:
    """Absolute path to the Dockerfile for a smoke repo."""
    smoke = repo["smoke"]
    df = smoke.get("dockerfile", "Dockerfile")
    if smoke.get("dockerfile_from") == "harness":
        return str((HARNESS_DIR / df).resolve())
    return str((context / df).resolve())


def build_up_env(slug: str, db_mode: str) -> tuple[dict[str, str], list[str]]:
    """Return (env for compose, list of service names to bring up)."""
    roles = smoke_repos(slug)
    if not roles:
        sys.exit(
            "error: no repo in repos.yaml has a `smoke:` block — nothing to "
            "bring up. Add a smoke role to a repo, or skip smoke for this run."
        )

    env = base_env(slug)
    env["HARNESS_DIR"] = str(HARNESS_DIR)
    env["SMOKE_DB"] = db_mode
    env["DB_LOCAL_ON_DISK"] = "true" if db_mode == "sqlite" else "false"
    services: list[str] = []

    if "backend" in roles:
        repo = roles["backend"]
        wt = Path(repo["worktree"])
        if not wt.is_dir():
            sys.exit(
                f"error: backend worktree not found at {wt}\n"
                f"  create it first with `omni run cross_repo`."
            )
        context = (wt / repo["smoke"].get("context_subdir", ".")).resolve()
        env["BACKEND_CONTEXT"] = str(context)
        env["BACKEND_DOCKERFILE"] = _resolve_dockerfile(repo, context)
        env["BACKEND_PORT"] = str(repo["smoke"].get("port", 8083))
        services.append("backend")

    if "frontend" in roles:
        repo = roles["frontend"]
        wt = Path(repo["worktree"])
        context = (wt / repo["smoke"].get("context_subdir", ".")).resolve()
        if not context.is_dir():
            sys.exit(
                f"error: frontend build context not found at {context}\n"
                f"  create the worktree first with `omni run cross_repo`."
            )
        env["FRONTEND_CONTEXT"] = str(context)
        env["FRONTEND_DOCKERFILE"] = _resolve_dockerfile(repo, context)
        env["FRONTEND_PORT"] = str(repo["smoke"].get("port", 3000))
        env["FRONTEND_BACKEND_ENDPOINT"] = repo["smoke"].get(
            "backend_endpoint", "http://localhost:8083"
        )
        services.append("frontend")

    # Auto-discover smoke/.env.smoke as the backend's env_file. The compose
    # file uses ${BACKEND_ENV_FILE:-/dev/null} so a backend can boot with real
    # creds without exporting env vars on every run. Respect an existing value.
    env_smoke = HARNESS_DIR / "smoke" / ".env.smoke"
    env.setdefault(
        "BACKEND_ENV_FILE",
        str(env_smoke) if env_smoke.exists() else "/dev/null",
    )
    return env, services


def cmd_up(args: argparse.Namespace) -> int:
    env, services = build_up_env(args.slug, args.db)
    rc = compose_run(env, "up", "--build", "-d", "--wait", *services)
    if rc != 0:
        return rc
    lines = [f"\n✓ smoke up — slug={args.slug}, db={args.db}"]
    if "BACKEND_PORT" in env:
        lines.append(f"  Backend:   http://localhost:{env['BACKEND_PORT']}")
    if "FRONTEND_PORT" in env:
        lines.append(f"  Frontend:  http://localhost:{env['FRONTEND_PORT']}")
    lines.append(f"  Tail logs: uv run tools/smoke.py logs {args.slug}")
    lines.append(f"  Tear down: uv run tools/smoke.py down {args.slug}\n")
    print("\n".join(lines))
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    # No -v: keeps build caches between cycles for faster subsequent ups.
    return compose_run(base_env(args.slug), "down")


def cmd_logs(args: argparse.Namespace) -> int:
    base: list[str] = ["logs", "-f"]
    if args.service:
        base.append(args.service)
    return compose_run(base_env(args.slug), *base)


def cmd_status(args: argparse.Namespace) -> int:
    return compose_run(base_env(args.slug), "ps")


def cmd_config(args: argparse.Namespace) -> int:
    env, services = build_up_env(args.slug, args.db)
    print(f"project : {project_name(args.slug)}")
    print(f"services: {', '.join(services)}")
    for k in sorted(env):
        if k.startswith(("BACKEND_", "FRONTEND_", "SMOKE_", "DB_", "HARNESS")):
            print(f"  {k}={env[k]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="smoke.py", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_up = sub.add_parser("up", help="Bring up the smoke stack for a slug.")
    p_up.add_argument("slug")
    p_up.add_argument(
        "--db",
        choices=["sqlite", "aurora"],
        default=os.environ.get("SMOKE_DB", "sqlite"),
        help="DB backend passthrough (default: $SMOKE_DB or sqlite).",
    )
    p_up.set_defaults(func=cmd_up)

    p_down = sub.add_parser("down", help="Tear down the smoke stack for a slug.")
    p_down.add_argument("slug", nargs="?", help="Slug used at `up`.")
    p_down.set_defaults(func=cmd_down)

    p_logs = sub.add_parser("logs", help="Tail container logs.")
    p_logs.add_argument("slug", nargs="?")
    p_logs.add_argument("--service", choices=["backend", "frontend"])
    p_logs.set_defaults(func=cmd_logs)

    p_status = sub.add_parser("status", help="Show container status.")
    p_status.add_argument("slug", nargs="?")
    p_status.set_defaults(func=cmd_status)

    p_config = sub.add_parser("config", help="Show the compose wiring for a slug.")
    p_config.add_argument("slug")
    p_config.add_argument("--db", choices=["sqlite", "aurora"], default="sqlite")
    p_config.set_defaults(func=cmd_config)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
