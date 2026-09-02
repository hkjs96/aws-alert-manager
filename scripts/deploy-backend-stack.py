"""
Backend deployment helper (CLI).

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
    "alert_ingestor.zip",
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
        # Windows 기본 코드페이지(cp949)로 템플릿을 읽다 유니코드 주석에서 깨진다.
        # AWS CLI가 file:// 및 --template-file을 읽을 때 쓰는 인코딩을 고정한다.
        "AWS_CLI_FILE_ENCODING": "UTF-8",
    }
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        # 자식(aws)의 출력은 PYTHONIOENCODING=utf-8 — 부모도 같은 인코딩으로 디코딩해야
        # CFN 오류 메시지의 비ASCII 문자에서 UnicodeDecodeError가 나지 않는다.
        encoding="utf-8",
        errors="replace",
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
        elif path.startswith("backend/alert_ingestor/"):
            targets.add("alert_ingestor.zip")
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
    """boto3 changeset 흐름으로 스택을 갱신한다 (aws cloudformation deploy 대체).

    Windows에서 `aws cloudformation deploy --s3-bucket`은 템플릿을 임시 파일에
    로케일 인코딩(cp949)으로 쓰다 유니코드 주석(═, →)에서 깨진다. 템플릿을
    바이트 그대로 S3에 올리고 TemplateURL로 changeset을 만들면 인코딩 경로가 없다.
    """
    import boto3
    from botocore.exceptions import WaiterError

    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3")
    cfn = session.client("cloudformation")

    # 1) 템플릿 업로드 (51,200 bytes 초과 템플릿은 S3 경유 필수)
    key = f"cfn-templates/{version}/template.yaml"
    s3.put_object(Bucket=bucket, Key=key, Body=TEMPLATE.read_bytes())
    template_url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

    # 2) 파라미터: 지정한 것만 덮고 나머지는 이전 값 유지 (deploy의 UsePreviousValue 의미)
    overrides = {
        "DeploymentBucket": bucket,
        "CodeVersion": version,
        "Environment": environment,
    }
    for env_name, param_name in (
        ("GOOGLE_CLIENT_ID", "GoogleClientId"),
        ("ALLOWED_EMAILS", "AllowedEmails"),
        ("ALLOWED_EMAIL_DOMAINS", "AllowedEmailDomains"),
        ("ADMIN_EMAILS", "AdminEmails"),
    ):
        value = os.environ.get(env_name)
        if value is not None:
            overrides[param_name] = value

    existing = cfn.describe_stacks(StackName=stack)["Stacks"][0].get("Parameters", [])
    existing_keys = [p["ParameterKey"] for p in existing]
    parameters = []
    for k in existing_keys:
        if k in overrides:
            parameters.append({"ParameterKey": k, "ParameterValue": overrides[k]})
        else:
            parameters.append({"ParameterKey": k, "UsePreviousValue": True})
    for k, v in overrides.items():
        if k not in existing_keys:
            parameters.append({"ParameterKey": k, "ParameterValue": v})

    # 3) changeset 생성 → 변경 없으면 no-op → 실행 → 완료 대기
    changeset = f"deploy-{version}"
    cfn.create_change_set(
        StackName=stack,
        TemplateURL=template_url,
        Parameters=parameters,
        Capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"],
        ChangeSetName=changeset,
        ChangeSetType="UPDATE",
    )
    try:
        cfn.get_waiter("change_set_create_complete").wait(
            StackName=stack, ChangeSetName=changeset,
            WaiterConfig={"Delay": 5, "MaxAttempts": 60},
        )
    except WaiterError:
        desc = cfn.describe_change_set(StackName=stack, ChangeSetName=changeset)
        reason = desc.get("StatusReason", "")
        if desc.get("Status") == "FAILED" and "didn't contain changes" in reason:
            print("[deploy] no changes in changeset - skipping execute")
            cfn.delete_change_set(StackName=stack, ChangeSetName=changeset)
            return
        raise DeployError(f"changeset failed: {reason}")

    cfn.execute_change_set(StackName=stack, ChangeSetName=changeset)
    try:
        cfn.get_waiter("stack_update_complete").wait(
            StackName=stack, WaiterConfig={"Delay": 10, "MaxAttempts": 120},
        )
    except WaiterError as exc:
        status = cfn.describe_stacks(StackName=stack)["Stacks"][0].get("StackStatus", "?")
        raise DeployError(f"stack update did not complete: {status} ({exc})") from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy backend stack.")
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
        print("[deploy] skipped: ALARM_MANAGER_AUTO_DEPLOY=0")
        return 0

    paths = args.changed_path or _changed_paths_from_git(args.base_ref)
    targets = _artifact_targets(paths, all_artifacts=args.all_artifacts)
    template_changed = _template_changed(paths)

    if not targets and not template_changed:
        print("[deploy] skipped: no backend deployment targets")
        return 0

    current_version = _current_code_version(args.profile, args.region, args.stack)
    version = current_version
    if targets:
        version = "v" + dt.datetime.now(tz=dt.UTC).strftime("%Y%m%dT%H%M%S")

    print(
        "[deploy] "
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
                print(f"[deploy] uploaded {zip_name}")
            else:
                _copy_previous(
                    args.profile,
                    args.region,
                    args.bucket,
                    current_version,
                    version,
                    zip_name,
                )
                print(f"[deploy] copied {zip_name}")

    _deploy(args.profile, args.region, args.bucket, args.stack, args.environment, version)
    print(f"[deploy] stack deploy complete CodeVersion={version}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DeployError as exc:
        print(f"[deploy] FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
