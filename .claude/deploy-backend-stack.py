"""
PostToolUse hook: package changed backend Lambda artifacts and deploy the stack.

The backend CloudFormation stack uses one CodeVersion prefix containing:

- api_handler.zip
- common_layer.zip
- daily_monitor.zip
- remediation_handler.zip
- sqs_worker.zip

When a backend Lambda source file changes, this hook builds the affected
artifact(s), copies unchanged artifacts from the current deployed CodeVersion,
uploads everything to a new S3 prefix, and updates CloudFormation.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


BUCKET = os.environ.get("ALARM_MANAGER_DEPLOY_BUCKET", "bjs-deploy-bucket")
STACK = os.environ.get("ALARM_MANAGER_STACK", "aws-monitoring-engine-dev")
PROFILE = os.environ.get("AWS_PROFILE", "tlsgks678_poc")
REGION = os.environ.get("AWS_REGION", "us-east-1")
ENVIRONMENT = os.environ.get("ALARM_MANAGER_ENVIRONMENT", "development")

ARTIFACTS = {
    "api_handler.zip",
    "common_layer.zip",
    "daily_monitor.zip",
    "remediation_handler.zip",
    "sqs_worker.zip",
}

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TEMPLATE = ROOT / "infrastructure" / "backend" / "template.yaml"
DIST = ROOT / "dist"


def _changed_path() -> str:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return ""
    return data.get("tool_input", {}).get("file_path", "").replace("\\", "/")


def _artifact_targets(path: str) -> set[str]:
    if os.environ.get("ALARM_MANAGER_AUTO_DEPLOY", "1") == "0":
        return set()
    if not path.endswith(".py"):
        return set()
    if "/backend/tests/" in path or path.startswith("backend/tests/"):
        return set()
    if "/backend/common/" in path or path.startswith("backend/common/"):
        return {"common_layer.zip"}
    if "/backend/api_handler/" in path or path.startswith("backend/api_handler/"):
        return {"api_handler.zip"}
    if "/backend/daily_monitor/" in path or path.startswith("backend/daily_monitor/"):
        return {"daily_monitor.zip"}
    if "/backend/remediation_handler/" in path or path.startswith("backend/remediation_handler/"):
        return {"remediation_handler.zip"}
    if "/backend/sqs_worker/" in path or path.startswith("backend/sqs_worker/"):
        return {"sqs_worker.zip"}
    return set()


def _run(args: list[str], *, text: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(args, capture_output=True, text=text, env=env)


def _aws() -> list[str]:
    return ["aws", "--profile", PROFILE, "--region", REGION]


def _current_code_version() -> str:
    result = _run(
        _aws()
        + [
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            STACK,
            "--query",
            "Stacks[0].Parameters[?ParameterKey==`CodeVersion`].ParameterValue",
            "--output",
            "text",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "failed to describe current stack")
    version = result.stdout.strip()
    if not version:
        raise RuntimeError("current stack CodeVersion is empty")
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

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(root.rglob("*")):
            if not file.is_file():
                continue
            if file.suffix == ".pyc" or "__pycache__" in file.parts:
                continue
            rel = file.relative_to(root).as_posix()
            arcname = f"{prefix}/{rel}" if prefix else rel
            zf.write(file, arcname)
            if zip_name == "api_handler.zip":
                zf.write(file, f"api_handler/{rel}")

    return zip_path


def _upload_file(local_path: Path, version: str, zip_name: str) -> None:
    result = _run(
        _aws()
        + [
            "s3",
            "cp",
            str(local_path),
            f"s3://{BUCKET}/{version}/{zip_name}",
            "--quiet",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"failed to upload {zip_name}")


def _copy_previous(old_version: str, new_version: str, zip_name: str) -> None:
    result = _run(
        _aws()
        + [
            "s3",
            "cp",
            f"s3://{BUCKET}/{old_version}/{zip_name}",
            f"s3://{BUCKET}/{new_version}/{zip_name}",
            "--quiet",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"failed to copy {zip_name}")


def _deploy(version: str) -> None:
    result = _run(
        _aws()
        + [
            "cloudformation",
            "deploy",
            "--stack-name",
            STACK,
            "--template-file",
            str(TEMPLATE),
            # 템플릿이 51,200 bytes를 넘으면 S3 경유 배포가 필수다.
            "--s3-bucket",
            BUCKET,
            "--s3-prefix",
            "cfn-templates",
            "--parameter-overrides",
            f"DeploymentBucket={BUCKET}",
            f"CodeVersion={version}",
            f"Environment={ENVIRONMENT}",
            "--capabilities",
            "CAPABILITY_IAM",
            "CAPABILITY_NAMED_IAM",
            "--no-fail-on-empty-changeset",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "cloudformation deploy failed")


def main() -> int:
    path = _changed_path()
    targets = _artifact_targets(path)
    if not targets:
        return 0

    version = "v" + _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    print(
        f"[backend-auto-deploy] changed={path} targets={','.join(sorted(targets))} version={version}",
        file=sys.stderr,
    )

    try:
        old_version = _current_code_version()
        print(f"[backend-auto-deploy] current CodeVersion={old_version}", file=sys.stderr)

        for zip_name in sorted(ARTIFACTS):
            if zip_name in targets:
                zip_path = _write_zip(zip_name)
                _upload_file(zip_path, version, zip_name)
                print(f"[backend-auto-deploy] uploaded {zip_name}", file=sys.stderr)
            else:
                _copy_previous(old_version, version, zip_name)
                print(f"[backend-auto-deploy] copied {zip_name}", file=sys.stderr)

        _deploy(version)
        print(f"[backend-auto-deploy] stack deploy complete CodeVersion={version}", file=sys.stderr)
        return 0
    except Exception as exc:  # noqa: BLE001 - hook must report concise failure
        print(f"[backend-auto-deploy] FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
