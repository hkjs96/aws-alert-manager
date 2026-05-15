"""post-commit hook: 변경 파일 기반 조건부 배포 (에이전트 공통).

Backend:  backend/ 또는 infrastructure/backend/ 변경 → zip → S3 → CFN deploy
Frontend: frontend/ 변경 → Amplify start-job 트리거

환경 변수:
  ALARM_MANAGER_AUTO_DEPLOY   "0" 으로 설정 시 배포 전체 스킵 (기본값 "1")
  ALARM_MANAGER_DEPLOY_BUCKET S3 버킷명 (기본값 bjs-deploy-bucket)
  ALARM_MANAGER_STACK         CFN 스택명 (기본값 aws-monitoring-engine-dev)
  AWS_PROFILE                 AWS CLI 프로파일 (기본값 tlsgks678_poc)
  AWS_REGION                  리전 (기본값 us-east-1)
  ALARM_MANAGER_ENVIRONMENT   환경 태그 (기본값 development)
  AMPLIFY_APP_ID              Amplify 앱 ID (미설정 시 프론트 배포 스킵)
  AMPLIFY_BRANCH              Amplify 브랜치 (기본값 main)
"""
from __future__ import annotations

import datetime as _dt
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DIST = ROOT / "dist"
TEMPLATE = ROOT / "infrastructure" / "backend" / "template.yaml"

BUCKET = os.environ.get("ALARM_MANAGER_DEPLOY_BUCKET", "bjs-deploy-bucket")
STACK = os.environ.get("ALARM_MANAGER_STACK", "aws-monitoring-engine-dev")
PROFILE = os.environ.get("AWS_PROFILE", "tlsgks678_poc")
REGION = os.environ.get("AWS_REGION", "us-east-1")
ENVIRONMENT = os.environ.get("ALARM_MANAGER_ENVIRONMENT", "development")
AMPLIFY_APP = os.environ.get("AMPLIFY_APP_ID", "")
AMPLIFY_BRANCH = os.environ.get("AMPLIFY_BRANCH", "main")

# backend 디렉토리 경로 접두사 → 재빌드 대상 아티팩트 매핑
_ARTIFACT_MAP: dict[str, str] = {
    "backend/common/": "common_layer.zip",
    "backend/api_handler/": "api_handler.zip",
    "backend/daily_monitor/": "daily_monitor.zip",
    "backend/remediation_handler/": "remediation_handler.zip",
    "backend/sqs_worker/": "sqs_worker.zip",
}
_ALL_ARTIFACTS: frozenset[str] = frozenset(_ARTIFACT_MAP.values())


def _changed_files() -> list[str]:
    """현재 커밋에서 변경된 파일 목록을 git 에서 읽는다."""
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return result.stdout.splitlines()


def _aws(extra: list[str]) -> subprocess.CompletedProcess:
    """AWS CLI 를 프로파일/리전 옵션과 함께 실행한다."""
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        ["aws", "--profile", PROFILE, "--region", REGION, *extra],
        capture_output=True,
        text=True,
        env=env,
    )


def _artifact_targets(changed: list[str]) -> set[str]:
    """변경 파일 목록에서 재빌드가 필요한 아티팩트 집합을 계산한다."""
    if any(f.startswith("infrastructure/backend/") for f in changed):
        return set(_ALL_ARTIFACTS)

    targets: set[str] = set()
    for path in changed:
        if not path.endswith(".py") or "tests/" in path:
            continue
        for prefix, artifact in _ARTIFACT_MAP.items():
            if path.startswith(prefix):
                targets.add(artifact)
    return targets


def _current_code_version() -> str:
    """현재 CFN 스택에 배포된 CodeVersion 파라미터 값을 읽는다."""
    r = _aws([
        "cloudformation", "describe-stacks",
        "--stack-name", STACK,
        "--query",
        "Stacks[0].Parameters[?ParameterKey==`CodeVersion`].ParameterValue",
        "--output", "text",
    ])
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "describe-stacks failed")
    version = r.stdout.strip()
    if not version:
        raise RuntimeError("current CodeVersion is empty")
    return version


def _build_zip(artifact: str) -> Path:
    """아티팩트 zip 을 dist/ 에 빌드하고 경로를 반환한다."""
    DIST.mkdir(exist_ok=True)
    zip_path = DIST / artifact
    if zip_path.exists():
        zip_path.unlink()

    if artifact == "common_layer.zip":
        src_root, prefix = BACKEND / "common", "python/common"
    else:
        module = artifact.removesuffix(".zip")
        src_root, prefix = BACKEND / module, ""

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(src_root.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix == ".pyc" or "__pycache__" in f.parts:
                continue
            rel = f.relative_to(src_root).as_posix()
            zf.write(f, f"{prefix}/{rel}" if prefix else rel)
    return zip_path


def deploy_backend(changed: list[str]) -> None:
    """변경된 backend 파일 기반으로 zip → S3 → CFN 배포를 수행한다."""
    targets = _artifact_targets(changed)
    if not targets:
        return

    version = "v" + _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    print(f"[backend-deploy] targets={sorted(targets)} version={version}")

    old_version = _current_code_version()

    for artifact in sorted(_ALL_ARTIFACTS):
        if artifact in targets:
            zip_path = _build_zip(artifact)
            r = _aws(["s3", "cp", str(zip_path),
                      f"s3://{BUCKET}/{version}/{artifact}", "--quiet"])
            if r.returncode != 0:
                raise RuntimeError(f"S3 upload failed: {artifact}\n{r.stderr}")
            print(f"[backend-deploy] uploaded {artifact}")
        else:
            r = _aws(["s3", "cp",
                      f"s3://{BUCKET}/{old_version}/{artifact}",
                      f"s3://{BUCKET}/{version}/{artifact}", "--quiet"])
            if r.returncode != 0:
                raise RuntimeError(f"S3 copy failed: {artifact}\n{r.stderr}")

    r = _aws([
        "cloudformation", "deploy",
        "--stack-name", STACK,
        "--template-file", str(TEMPLATE),
        "--parameter-overrides",
        f"DeploymentBucket={BUCKET}",
        f"CodeVersion={version}",
        f"Environment={ENVIRONMENT}",
        "--capabilities", "CAPABILITY_IAM", "CAPABILITY_NAMED_IAM",
        "--no-fail-on-empty-changeset",
    ])
    if r.returncode != 0:
        raise RuntimeError(f"CloudFormation deploy failed\n{r.stderr}")

    print(f"[backend-deploy] complete CodeVersion={version}")


def deploy_frontend(changed: list[str]) -> None:
    """frontend/ 변경 시 Amplify start-job 으로 빌드를 트리거한다."""
    if not any(f.startswith("frontend/") for f in changed):
        return
    if not AMPLIFY_APP:
        print("[frontend-deploy] AMPLIFY_APP_ID 미설정 -- 스킵")
        return

    r = _aws([
        "amplify", "start-job",
        "--app-id", AMPLIFY_APP,
        "--branch-name", AMPLIFY_BRANCH,
        "--job-type", "RELEASE",
    ])
    if r.returncode != 0:
        raise RuntimeError(f"Amplify start-job failed\n{r.stderr}")

    print(
        f"[frontend-deploy] Amplify job started"
        f" (app={AMPLIFY_APP} branch={AMPLIFY_BRANCH})"
    )


def main() -> int:
    """post-commit 배포 메인 진입점."""
    if os.environ.get("ALARM_MANAGER_AUTO_DEPLOY", "1") == "0":
        print("[post-commit] ALARM_MANAGER_AUTO_DEPLOY=0 -- 배포 스킵")
        return 0

    changed = _changed_files()
    if not changed:
        return 0

    failed = False
    for deploy_fn in (deploy_backend, deploy_frontend):
        try:
            deploy_fn(changed)
        except Exception as exc:  # noqa: BLE001 -- hook 은 항상 종료해야 함
            print(f"[post-commit] FAILED: {exc}", file=sys.stderr)
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
