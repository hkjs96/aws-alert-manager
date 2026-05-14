"""
PostToolUse hook: deploy api_handler-only backend changes through CloudFormation.

The repository keeps backend source under backend/ and the deployable SAM
template under infrastructure/backend/.
"""

import datetime
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


d = json.load(sys.stdin)
fp = d.get("tool_input", {}).get("file_path", "").replace("\\", "/")
if "api_handler" not in fp or not fp.endswith(".py"):
    sys.exit(0)

BUCKET = "bjs-deploy-bucket"
STACK = "aws-monitoring-engine-dev"
PROFILE = "tlsgks678_poc"
REGION = "us-east-1"
OTHER_ZIPS = ["daily_monitor.zip", "remediation_handler.zip", "common_layer.zip", "sqs_worker.zip"]

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
API_HANDLER = BACKEND / "api_handler"
TEMPLATE = ROOT / "infrastructure" / "backend" / "template.yaml"
DIST = ROOT / "dist"

aws = ["aws", "--profile", PROFILE, "--region", REGION]
version = "v" + datetime.datetime.now().strftime("%Y%m%dT%H%M%S")

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

print(f"[auto-deploy] CloudFormation deploy start. version={version}", file=sys.stderr)

r = subprocess.run(
    aws
    + [
        "cloudformation",
        "describe-stacks",
        "--stack-name",
        STACK,
        "--query",
        "Stacks[0].Parameters[?ParameterKey==`CodeVersion`].ParameterValue",
        "--output",
        "text",
    ],
    capture_output=True,
    text=True,
)
old_version = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "v20260504"
print(f"[auto-deploy] previous version={old_version}", file=sys.stderr)

DIST.mkdir(exist_ok=True)
zip_path = DIST / "api_handler.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write(API_HANDLER / "lambda_handler.py", "lambda_handler.py")
    for root, _, files in os.walk(API_HANDLER):
        for f in files:
            if f.endswith(".pyc") or "__pycache__" in root:
                continue
            full = Path(root) / f
            zf.write(full, full.relative_to(BACKEND).as_posix())
print(f"[auto-deploy] packaged {zip_path}", file=sys.stderr)

r = subprocess.run(
    aws + ["s3", "cp", str(zip_path), f"s3://{BUCKET}/{version}/api_handler.zip", "--quiet"],
    capture_output=True,
)
if r.returncode != 0:
    print(f"[auto-deploy] S3 upload failed: {r.stderr.decode(errors='replace')}", file=sys.stderr)
    sys.exit(1)
print(f"[auto-deploy] uploaded s3://{BUCKET}/{version}/api_handler.zip", file=sys.stderr)

for zip_name in OTHER_ZIPS:
    r = subprocess.run(
        aws
        + [
            "s3",
            "cp",
            f"s3://{BUCKET}/{old_version}/{zip_name}",
            f"s3://{BUCKET}/{version}/{zip_name}",
            "--quiet",
        ],
        capture_output=True,
    )
    status = "OK" if r.returncode == 0 else f"FAIL({r.returncode})"
    print(f"[auto-deploy] copy {zip_name}: {status}", file=sys.stderr)

print("[auto-deploy] running cloudformation deploy", file=sys.stderr)
r = subprocess.run(
    aws
    + [
        "cloudformation",
        "deploy",
        "--stack-name",
        STACK,
        "--template-file",
        str(TEMPLATE),
        "--parameter-overrides",
        f"DeploymentBucket={BUCKET}",
        f"CodeVersion={version}",
        "--capabilities",
        "CAPABILITY_IAM",
        "CAPABILITY_NAMED_IAM",
        "--no-fail-on-empty-changeset",
    ],
    capture_output=True,
    env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
)
if r.returncode == 0:
    print(f"[auto-deploy] CloudFormation deploy complete ({version})", file=sys.stderr)
else:
    print(f"[auto-deploy] CloudFormation deploy failed:\n{r.stderr.decode('utf-8', errors='replace')}", file=sys.stderr)
    sys.exit(1)
