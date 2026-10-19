#!/usr/bin/env python3
"""Verified deploy: test and deploy exactly one commit from a clean checkout — staging first, then promote.

Called by the pre-push hook (.githooks/pre-push). It replaces the old Claude Code PostToolUse hook that
deployed the working tree on every file edit: that hook shipped half-edited code (2026-10-12 10:26 UTC,
`NameError: dataclass` on worker start, one hourly reconcile lost).

Two stacks share account 949501913924 (docs/specs/stack-split/plan.md):

- LIVE    `aws-monitoring-engine-dev` — watches the customers, serves the frontend. The name says dev; it is
          production in role. Reached only by `promote`.
- STAGING `aws-monitoring-engine-stg` — `Automation=disabled`: no schedules, no CloudTrail/default-bus
          reactions, no post-deploy sync, empty accounts table. Every verified push lands here first.

    python scripts/deploy_verified.py gate    <sha>  # fast tests in a clean checkout of <sha>; exit 1 on failure
    python scripts/deploy_verified.py deploy  <sha>  # deploy <sha> to STAGING (what the pre-push hook runs)
    python scripts/deploy_verified.py promote <sha>  # deploy <sha> to LIVE — only if it is what STAGING runs

All run in a temporary `git worktree` of the commit, so uncommitted changes can neither make tests pass nor
end up in artifacts. The SHA last deployed to staging is recorded in S3 (shared across clones) and promote
refuses any other commit. A staging deploy is skipped (exit 0, with a message) when
ALARM_MANAGER_AUTO_DEPLOY=0 or AWS credentials are unavailable — the push is blocked only by failing tests.
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
LIVE_STACK = os.environ.get("ALARM_MANAGER_STACK", "aws-monitoring-engine-dev")
STAGING_STACK = os.environ.get("ALARM_MANAGER_STAGING_STACK", "aws-monitoring-engine-stg")
PROFILE = os.environ.get("AWS_PROFILE", "tlsgks678_poc")
REGION = os.environ.get("AWS_REGION", "us-east-1")
BUCKET = os.environ.get("ALARM_MANAGER_DEPLOY_BUCKET", "bjs-deploy-bucket")
STAGED_KEY = f"deploy-verified/{STAGING_STACK}/sha"
#: Staging copies these from LIVE on every deploy, so its API is never public (empty GoogleClientId disables auth).
AUTH_PARAMETERS = ("GoogleClientId", "AllowedEmails", "AllowedEmailDomains", "AdminEmails")


def _log(msg: str) -> None:
    print(f"[deploy-verified] {msg}", file=sys.stderr, flush=True)


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _session():
    import boto3
    return boto3.session.Session(profile_name=PROFILE, region_name=REGION)


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


def _credentials_ok() -> bool:
    probe = subprocess.run(["aws", "sts", "get-caller-identity", "--profile", PROFILE, "--region", REGION],
                           capture_output=True, text=True)
    return probe.returncode == 0


def _run_deploy(sha: str, stack: str, environment: str, parameters: dict[str, str]) -> bool:
    with _checkout(sha) as wt:
        _log(f"deploying {sha[:7]} to {stack}")
        cmd = [sys.executable, str(wt / "scripts" / "deploy-backend-stack.py"), "--all-artifacts",
               "--stack", stack, "--profile", PROFILE, "--region", REGION, "--environment", environment]
        for k, v in parameters.items():
            cmd += ["--parameter", f"{k}={v}"]
        return subprocess.run(cmd, cwd=wt).returncode == 0


def _live_auth_parameters() -> dict[str, str]:
    stack = _session().client("cloudformation").describe_stacks(StackName=LIVE_STACK)["Stacks"][0]
    return {p["ParameterKey"]: p.get("ParameterValue", "") for p in stack.get("Parameters", [])
            if p["ParameterKey"] in AUTH_PARAMETERS}


def _staged_sha() -> str:
    from botocore.exceptions import ClientError
    try:
        return _session().client("s3").get_object(Bucket=BUCKET, Key=STAGED_KEY)["Body"].read().decode().strip()
    except ClientError:
        return ""


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
    """STAGING — never acts on its own (Automation=disabled), so a bad commit cannot touch a customer."""
    if os.environ.get("ALARM_MANAGER_AUTO_DEPLOY", "1") == "0":
        _log("ALARM_MANAGER_AUTO_DEPLOY=0 — skipping deploy")
        return 0
    if not _credentials_ok():
        _log("AWS credentials unavailable (run `aws sso login --sso-session mzc`) — NOT deployed. "
             f"Deploy later with: python scripts/deploy_verified.py deploy {sha[:7]}")
        return 0
    params = {**_live_auth_parameters(), "Automation": "disabled"}
    if not _run_deploy(sha, STAGING_STACK, "staging", params):
        _log(f"STAGING DEPLOY FAILED for {sha[:7]} — the push goes ahead; fix and run "
             f"`python scripts/deploy_verified.py deploy {sha[:7]}`")
        return 0
    _session().client("s3").put_object(Bucket=BUCKET, Key=STAGED_KEY, Body=sha.encode())
    _log(f"deployed {sha[:7]} to staging. Check it, then promote to the customer-serving stack with: "
         f"python scripts/deploy_verified.py promote {sha[:7]}")
    return 0


def promote(sha: str) -> int:
    """LIVE — only the exact commit staging runs."""
    if not _credentials_ok():
        _log("AWS credentials unavailable (run `aws sso login --sso-session mzc`)")
        return 1
    staged = _staged_sha()
    if staged != sha:
        _log(f"REFUSED: {sha[:7]} is not what staging runs ({staged[:7] or 'nothing recorded'}). "
             "Push it (staging deploy) first.")
        return 1
    if not _run_deploy(sha, LIVE_STACK, "development", {"Automation": "enabled"}):
        _log(f"PROMOTE FAILED for {sha[:7]}")
        return 1
    _log(f"promoted {sha[:7]} to {LIVE_STACK}")
    return 0


def main(argv: list[str]) -> int:
    commands = {"gate": gate, "deploy": deploy, "promote": promote}
    if len(argv) != 3 or argv[1] not in commands:
        print(__doc__, file=sys.stderr)
        return 2
    sha = _git("rev-parse", "--verify", argv[2] + "^{commit}")
    return commands[argv[1]](sha)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
