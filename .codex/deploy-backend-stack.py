"""
Codex backend deployment helper.

Builds changed backend Lambda artifacts, uploads a complete CodeVersion prefix
to S3, and deploys the backend CloudFormation stack.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import zipfile
from pathlib import Path


DEFAULT_BUCKET = "bjs-deploy-bucket"
DEFAULT_STACK = "aws-monitoring-engine-dev"
DEFAULT_PROFILE = "tlsgks678_poc"
DEFAULT_REGION = "us-east-1"
DEFAULT_ENVIRONMENT = "development"

ARTIFACTS = (
    "api_handler.zip",
    "common_layer.zip",
    "daily_monitor.zip",
    "remediation_handler.zip",
    "sqs_worker.zip",
)

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TEMPLATE = ROOT / "infrastructure" / "backend" / "template.yaml"
DIST = ROOT / "dist"


class DeployError(RuntimeError):
    """Deployment failed in a recoverable way."""


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise DeployError(message)
    return result


def _aws(profile: str, region: str) -> list[str]:
    return ["aws", "--profile", profile, "--region", region]


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _artifact_targets(paths: list[str], *, all_artifacts: bool) -> set[str]:
    if all_artifacts:
        return set(ARTIFACTS)

    targets: set[str] = set()
    for raw_path in paths:
        path = _normalize(raw_path)
        if not path.endswith(".py"):
            continue
        if path.startswith("backend/tests/"):
            continue
        if path.startswith("backend/common/"):
            targets.add("common_layer.zip")
        elif path.startswith("backend/api_handler/"):
            targets.add("api_handler.zip")
        elif path.startswith("backend/daily_monitor/"):
            targets.add("daily_monitor.zip")
        elif path.startswith("backend/remediation_handler/"):
            targets.add("remediation_handler.zip")
        elif path.startswith("backend/sqs_worker/"):
            targets.add("sqs_worker.zip")
    return targets


def _template_changed(paths: list[str]) -> bool:
    return any(_normalize(path) == "infrastructure/backend/template.yaml" for path in paths)


def _changed_paths_from_git(base_ref: str) -> list[str]:
    result = _run(["git", "diff", "--name-only", base_ref, "HEAD"])
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _current_code_version(profile: str, region: str, stack: str) -> str:
    result = _run(
        _aws(profile, region)
        + [
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            stack,
            "--query",
            "Stacks[0].Parameters[?ParameterKey==`CodeVersion`].ParameterValue",
            "--output",
            "text",
        ]
    )
    version = result.stdout.strip()
    if not version:
        raise DeployError("current stack CodeVersion is empty")
    return version


def _write_zip(zip_name: str) -> Path:
    DIST.mkdir(exist_ok=True)
    zip_path = DIST / zip_name
    if zip_path.exists():
        zip_path.unlink()

    if zip_name == "common_layer.zip":
        root = BACKEND / "common"
        prefix = "python/common"
    else:
        module = zip_name.removesuffix(".zip")
        root = BACKEND / module
        prefix = ""

    if not root.exists():
        raise DeployError(f"artifact source not found: {root}")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix == ".pyc" or "__pycache__" in file_path.parts:
                continue
            rel = file_path.relative_to(root).as_posix()
            arcname = f"{prefix}/{rel}" if prefix else rel
            zf.write(file_path, arcname)
            if zip_name == "api_handler.zip":
                zf.write(file_path, f"api_handler/{rel}")

    return zip_path


def _upload_file(
    profile: str,
    region: str,
    bucket: str,
    version: str,
    zip_name: str,
    local_path: Path,
) -> None:
    _run(
        _aws(profile, region)
        + [
            "s3",
            "cp",
            str(local_path),
            f"s3://{bucket}/{version}/{zip_name}",
            "--quiet",
        ]
    )


def _copy_previous(
    profile: str,
    region: str,
    bucket: str,
    old_version: str,
    new_version: str,
    zip_name: str,
) -> None:
    _run(
        _aws(profile, region)
        + [
            "s3",
            "cp",
            f"s3://{bucket}/{old_version}/{zip_name}",
            f"s3://{bucket}/{new_version}/{zip_name}",
            "--quiet",
        ]
    )


def _deploy(
    profile: str,
    region: str,
    bucket: str,
    stack: str,
    environment: str,
    version: str,
) -> None:
    overrides = [
        f"DeploymentBucket={bucket}",
        f"CodeVersion={version}",
        f"Environment={environment}",
    ]
    # Auth params are passed only when provided via env. Omitted params keep
    # their previous stack value (CFN UsePreviousValue), so auth, once set,
    # persists across code-only deploys.
    for env_name, param_name in (
        ("GOOGLE_CLIENT_ID", "GoogleClientId"),
        ("ALLOWED_EMAILS", "AllowedEmails"),
        ("ALLOWED_EMAIL_DOMAINS", "AllowedEmailDomains"),
        ("ADMIN_EMAILS", "AdminEmails"),
    ):
        value = os.environ.get(env_name)
        if value is not None:
            overrides.append(f"{param_name}={value}")

    _run(
        _aws(profile, region)
        + [
            "cloudformation",
            "deploy",
            "--stack-name",
            stack,
            "--template-file",
            str(TEMPLATE),
            "--s3-bucket",
            bucket,
            "--parameter-overrides",
            *overrides,
            "--capabilities",
            "CAPABILITY_IAM",
            "CAPABILITY_NAMED_IAM",
            "--no-fail-on-empty-changeset",
        ]
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy backend stack from Codex.")
    parser.add_argument(
        "--changed-path",
        action="append",
        default=[],
        help="Changed path to inspect. May be repeated.",
    )
    parser.add_argument(
        "--base-ref",
        default="HEAD~1",
        help="Git base ref used when --changed-path is omitted.",
    )
    parser.add_argument("--all-artifacts", action="store_true")
    parser.add_argument("--bucket", default=os.environ.get("ALARM_MANAGER_DEPLOY_BUCKET", DEFAULT_BUCKET))
    parser.add_argument("--stack", default=os.environ.get("ALARM_MANAGER_STACK", DEFAULT_STACK))
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE", DEFAULT_PROFILE))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    parser.add_argument(
        "--environment",
        default=os.environ.get("ALARM_MANAGER_ENVIRONMENT", DEFAULT_ENVIRONMENT),
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if os.environ.get("ALARM_MANAGER_AUTO_DEPLOY", "1") == "0":
        print("[codex-deploy] skipped: ALARM_MANAGER_AUTO_DEPLOY=0")
        return 0

    paths = args.changed_path or _changed_paths_from_git(args.base_ref)
    targets = _artifact_targets(paths, all_artifacts=args.all_artifacts)
    template_changed = _template_changed(paths)

    if not targets and not template_changed:
        print("[codex-deploy] skipped: no backend deployment targets")
        return 0

    current_version = _current_code_version(args.profile, args.region, args.stack)
    version = current_version
    if targets:
        version = "v" + dt.datetime.now(tz=dt.UTC).strftime("%Y%m%dT%H%M%S")

    print(
        "[codex-deploy] "
        f"stack={args.stack} region={args.region} profile={args.profile} "
        f"current={current_version} target={version} "
        f"artifacts={','.join(sorted(targets)) or '-'} "
        f"template_changed={template_changed}"
    )

    if args.dry_run:
        return 0

    if targets:
        for zip_name in ARTIFACTS:
            if zip_name in targets:
                zip_path = _write_zip(zip_name)
                _upload_file(args.profile, args.region, args.bucket, version, zip_name, zip_path)
                print(f"[codex-deploy] uploaded {zip_name}")
            else:
                _copy_previous(
                    args.profile,
                    args.region,
                    args.bucket,
                    current_version,
                    version,
                    zip_name,
                )
                print(f"[codex-deploy] copied {zip_name}")

    _deploy(args.profile, args.region, args.bucket, args.stack, args.environment, version)
    print(f"[codex-deploy] stack deploy complete CodeVersion={version}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DeployError as exc:
        print(f"[codex-deploy] FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
