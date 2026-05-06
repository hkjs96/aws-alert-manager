"""
PostToolUse hook: api_handler/*.py 수정 시 CloudFormation 스택 업데이트.

흐름:
  1. 타임스탬프 CodeVersion 생성 (v{YYYYMMDDTHHmmSS})
  2. api_handler.zip 패키징
  3. 새 CodeVersion 접두사로 api_handler.zip S3 업로드
  4. 나머지 zip들은 현재 스택 CodeVersion에서 S3 copy
  5. cloudformation deploy
"""

import sys
import json
import subprocess
import os
import zipfile
import datetime

d = json.load(sys.stdin)
fp = d.get("tool_input", {}).get("file_path", "")
if "api_handler" not in fp or not fp.endswith(".py"):
    sys.exit(0)

BUCKET = "bjs-deploy-bucket"
STACK = "aws-monitoring-engine-dev"
PROFILE = "tlsgks678_poc"
REGION = "us-east-1"
OTHER_ZIPS = ["daily_monitor.zip", "remediation_handler.zip", "common_layer.zip", "sqs_worker.zip"]

aws = ["aws", "--profile", PROFILE, "--region", REGION]
version = "v" + datetime.datetime.now().strftime("%Y%m%dT%H%M%S")

# Windows cp949 콘솔에서 AWS CLI UTF-8 출력 오류 방지
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

print(f"[auto-deploy] CFN 배포 시작... 새 버전: {version}", file=sys.stderr)

# 현재 스택의 CodeVersion 조회 (다른 zip 복사 출처)
r = subprocess.run(
    aws + ["cloudformation", "describe-stacks", "--stack-name", STACK,
           "--query", "Stacks[0].Parameters[?ParameterKey==`CodeVersion`].ParameterValue",
           "--output", "text"],
    capture_output=True, text=True
)
old_version = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "v20260504"
print(f"[auto-deploy] 이전 버전: {old_version}", file=sys.stderr)

# api_handler.zip 패키징
os.makedirs("dist", exist_ok=True)
with zipfile.ZipFile("dist/api_handler.zip", "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write("api_handler/lambda_handler.py", "lambda_handler.py")
    for root, dirs, files in os.walk("api_handler"):
        for f in files:
            if f.endswith(".pyc") or "__pycache__" in root:
                continue
            full = os.path.join(root, f)
            zf.write(full, full.replace(os.sep, "/"))
print("[auto-deploy] zip 패키징 완료", file=sys.stderr)

# api_handler.zip 업로드
r = subprocess.run(
    aws + ["s3", "cp", "dist/api_handler.zip",
           f"s3://{BUCKET}/{version}/api_handler.zip", "--quiet"],
    capture_output=True
)
if r.returncode != 0:
    print(f"[auto-deploy] S3 업로드 실패: {r.stderr.decode(errors='replace')}", file=sys.stderr)
    sys.exit(1)
print(f"[auto-deploy] s3://{BUCKET}/{version}/api_handler.zip 업로드 완료", file=sys.stderr)

# 나머지 zip들 S3 copy (old → new version)
for zip_name in OTHER_ZIPS:
    r = subprocess.run(
        aws + ["s3", "cp",
               f"s3://{BUCKET}/{old_version}/{zip_name}",
               f"s3://{BUCKET}/{version}/{zip_name}", "--quiet"],
        capture_output=True
    )
    status = "OK" if r.returncode == 0 else f"FAIL({r.returncode})"
    print(f"[auto-deploy] copy {zip_name}: {status}", file=sys.stderr)

# CloudFormation 스택 배포
print("[auto-deploy] cloudformation deploy 실행 중... (수 분 소요)", file=sys.stderr)
r = subprocess.run(
    aws + ["cloudformation", "deploy",
           "--stack-name", STACK,
           "--template-file", "template.yaml",
           "--parameter-overrides",
           f"DeploymentBucket={BUCKET}",
           f"CodeVersion={version}",
           "--capabilities", "CAPABILITY_IAM", "CAPABILITY_NAMED_IAM",
           "--no-fail-on-empty-changeset"],
    capture_output=True,
    env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
)
if r.returncode == 0:
    print(f"[auto-deploy] CFN 배포 완료 ({version})", file=sys.stderr)
else:
    print(f"[auto-deploy] CFN 배포 실패:\n{r.stderr.decode('utf-8', errors='replace')}", file=sys.stderr)
    sys.exit(1)
