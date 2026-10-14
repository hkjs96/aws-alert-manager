#!/usr/bin/env python3
"""Verified deploy: test and deploy exactly one commit from a clean checkout.

Called by the pre-push hook (.githooks/pre-push). It replaces the old Claude Code PostToolUse
hook that deployed the working tree on every file edit: that hook shipped half-edited code
(2026-10-12 10:26 UTC, `NameError: dataclass` on worker start, one hourly reconcile lost). The dev
stack watches real customer accounts, so only tested commits may reach it.

    python scripts/deploy_verified.py gate   <sha>   # fast tests in a clean checkout of <sha>; exit 1 on failure
    python scripts/deploy_verified.py deploy <sha>   # deploy <sha> from a clean checkout (all artifacts)

Both run in a temporary `git worktree` of the commit, so uncommitted changes in the working tree
can neither make tests pass nor end up in the artifacts. Deploy is skipped (exit 0, with a message)
when ALARM_MANAGER_AUTO_DEPLOY=0 or AWS credentials are unavailable — the push is not blocked by
deploy problems, only by failing tests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STACK = os.environ.get("ALARM_MANAGER_STACK", "aws-monitoring-engine-dev")
PROFILE = os.environ.get("AWS_PROFILE", "tlsgks678_poc")
REGION = os.environ.get("AWS_REGION", "us-east-1")


def _log(msg: str) -> None:
    print(f"[deploy-verified] {msg}", file=sys.stderr, flush=True)


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@contextmanager
def _checkout(sha: str):
    tmp = Path(tempfile.mkdtemp(prefix="verified-"))
    path = tmp / "wt"
    _git("worktree", "add", "--detach", "--quiet", str(path), sha)
    try:
        yield path
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(path)], cwd=ROOT, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def gate(sha: str) -> int:
    with _checkout(sha) as wt:
        _log(f"testing {sha[:7]} in a clean checkout (fast tier, excl. pbt/e2e)")
        r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "--tb=short", "-m", "not pbt and not e2e"],
                           cwd=wt / "backend")
    if r.returncode != 0:
        _log("tests FAILED — push blocked, nothing deployed")
        return 1
    _log("tests passed")
    return 0


def deploy(sha: str) -> int:
    if os.environ.get("ALARM_MANAGER_AUTO_DEPLOY", "1") == "0":
        _log("ALARM_MANAGER_AUTO_DEPLOY=0 — skipping deploy")
        return 0
    probe = subprocess.run(["aws", "sts", "get-caller-identity", "--profile", PROFILE, "--region", REGION],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        _log("AWS credentials unavailable (run `aws sso login --sso-session mzc`) — NOT deployed. "
             f"Deploy later with: python scripts/deploy_verified.py deploy {sha[:7]}")
        return 0
    with _checkout(sha) as wt:
        _log(f"deploying {sha[:7]} to {STACK}")
        r = subprocess.run([sys.executable, str(wt / "scripts" / "deploy-backend-stack.py"), "--all-artifacts",
                            "--stack", STACK, "--profile", PROFILE, "--region", REGION], cwd=wt)
    if r.returncode != 0:
        _log(f"DEPLOY FAILED for {sha[:7]} — the push goes ahead; fix and run "
             f"`python scripts/deploy_verified.py deploy {sha[:7]}`")
        return 0
    _log(f"deployed {sha[:7]}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("gate", "deploy"):
        print(__doc__, file=sys.stderr)
        return 2
    sha = _git("rev-parse", "--verify", argv[2] + "^{commit}")
    return gate(sha) if argv[1] == "gate" else deploy(sha)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
