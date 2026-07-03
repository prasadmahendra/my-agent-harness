#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""harness_repos.py — resolve the configurable repo set from repos.yaml.

This is the single source of truth for "which repos does cross_repo operate
on, and where do they live on this machine". Both the cross_repo orchestrator
(via `resolve`) and tools/smoke.py (via import) use it.

Usage:
    uv run tools/harness_repos.py resolve            # JSON: global + all repos
    uv run tools/harness_repos.py resolve --slug S   # also include worktree paths
    uv run tools/harness_repos.py list               # human-readable table
    uv run tools/harness_repos.py check               # validate all paths exist

Run with `uv run` so pyyaml is provisioned automatically (PEP 723 header).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

HARNESS_DIR = Path(__file__).resolve().parent.parent
REPOS_YAML = HARNESS_DIR / "agents" / "cross_repo" / "repos.yaml"


def _expand(value: str) -> str:
    """Expand $VARS and ~ in a config string against the current environment."""
    return os.path.expanduser(os.path.expandvars(value))


def load_raw() -> dict[str, Any]:
    if not REPOS_YAML.is_file():
        sys.exit(f"error: repos config not found at {REPOS_YAML}")
    with REPOS_YAML.open() as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data.get("repos"), list) or not data["repos"]:
        sys.exit(f"error: {REPOS_YAML} has no `repos:` list")
    return data


def resolve_repos_root(data: dict[str, Any]) -> Path:
    rr = data.get("repos_root") or {}
    env_name = rr.get("env")
    default = rr.get("default", "$HOME/repos")
    raw = os.environ.get(env_name) if env_name else None
    return Path(_expand(raw if raw else default)).resolve()


def resolve(slug: str | None = None) -> dict[str, Any]:
    """Return the fully-resolved config: global settings + per-repo paths."""
    data = load_raw()
    repos_root = resolve_repos_root(data)
    branch_prefix = data.get("branch_prefix", "cross-repo")
    worktrees_root = repos_root / ".harness-worktrees"

    resolved: list[dict[str, Any]] = []
    for entry in data["repos"]:
        key = entry.get("key")
        if not key:
            sys.exit(f"error: a repo entry in {REPOS_YAML} is missing `key`")
        path_env = entry.get("path_env") or f"HARNESS_{key.upper()}_DIR"
        override = os.environ.get(path_env)
        if override:
            path = Path(_expand(override)).resolve()
        else:
            raw_default = entry.get("path_default", key)
            p = Path(_expand(raw_default))
            path = (p if p.is_absolute() else repos_root / p).resolve()

        item: dict[str, Any] = {
            "key": key,
            "purpose": entry.get("purpose", key),
            "description": entry.get("description", ""),
            "path_env": path_env,
            "path": str(path),
            "exists": path.is_dir(),
            "github": entry.get("github"),
            "subdir": entry.get("subdir"),
            "verify_hint": (entry.get("verify_hint") or "").strip(),
            "review_conventions": (entry.get("review_conventions") or "").strip(),
            "smoke": entry.get("smoke"),
        }
        if slug:
            item["worktree"] = str(worktrees_root / key / slug)
        resolved.append(item)

    out: dict[str, Any] = {
        "harness_dir": str(HARNESS_DIR),
        "repos_root": str(repos_root),
        "worktrees_root": str(worktrees_root),
        "branch_prefix": branch_prefix,
        "repos": resolved,
    }
    if slug:
        out["slug"] = slug
        out["branch"] = f"{branch_prefix}/{slug}"
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def cmd_resolve(args: argparse.Namespace) -> int:
    print(json.dumps(resolve(args.slug), indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    cfg = resolve()
    print(f"harness_dir : {cfg['harness_dir']}")
    print(f"repos_root  : {cfg['repos_root']}")
    print(f"branch      : {cfg['branch_prefix']}/<slug>")
    print()
    for r in cfg["repos"]:
        mark = "ok " if r["exists"] else "MISSING"
        smoke = r["smoke"]["role"] if r.get("smoke") else "-"
        print(f"  [{mark}] {r['key']:<12} purpose={r['purpose']:<10} "
              f"smoke={smoke:<9} {r['path']}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    cfg = resolve()
    missing = [r for r in cfg["repos"] if not r["exists"]]
    for r in missing:
        print(
            f"error: repo '{r['key']}' not found at {r['path']}\n"
            f"  set {r['path_env']} or place the checkout there.",
            file=sys.stderr,
        )
    if missing:
        return 1
    print(f"all {len(cfg['repos'])} repos present under {cfg['repos_root']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="harness_repos.py", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_resolve = sub.add_parser("resolve", help="Print resolved config as JSON.")
    p_resolve.add_argument("--slug", help="Include per-repo worktree paths for this slug.")
    p_resolve.set_defaults(func=cmd_resolve)

    p_list = sub.add_parser("list", help="Human-readable repo table.")
    p_list.set_defaults(func=cmd_list)

    p_check = sub.add_parser("check", help="Validate all repo paths exist.")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
