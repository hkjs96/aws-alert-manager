#!/usr/bin/env bash
# deploy.sh - AWS Monitoring Engine 배포 스크립트
# 환경: git bash (Windows) / Linux / macOS
# 사전 조건: aws cli, python3, zip 설치 필요
#
# 사용법:
#   ./deploy.sh <S3_BUCKET> [ENVIRONMENT] [STACK_NAME]
#
# 예시:
#   ./deploy.sh my-deploy-bucket prod aws-monitoring-engine-prod

set -euo pipefail

# ──────────────────────────────────────────────
# 인자 처리
# ──────────────────────────────────────────────
BUCKET="${1:?Usage: ./deploy.sh <S3_BUCKET> [ENVIRONMENT] [STACK_NAME]}"
ENVIRONMENT="${2:-prod}"
STACK_NAME="${3:-aws-monitoring-engine-${ENVIRONMENT}}"

# 배포 버전 (타임스탬프)
VERSION=$(date +%Y%m%d%H%M%S)
S3_PREFIX="${VERSION}"

echo "=== AWS Monitoring Engine 배포 ==="
echo "  Bucket     : ${BUCKET}"
echo "  Environment: ${ENVIRONMENT}"
echo "  Stack      : ${STACK_NAME}"
echo "  Version    : ${VERSION}"
echo ""

# ──────────────────────────────────────────────
# 임시 디렉터리
# ──────────────────────────────────────────────
TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

# ──────────────────────────────────────────────
# 1. common_layer.zip 패키징
#    구조: python/common/... (Lambda Layer 규칙)
# ──────────────────────────────────────────────
echo "[1/4] common_layer.zip 패키징..."
LAYER_DIR="${TMP_DIR}/layer/python"
mkdir -p "${LAYER_DIR}"
cp -r common/. "${LAYER_DIR}/common/"
(cd "${TMP_DIR}/layer" && zip -r "${TMP_DIR}/common_layer.zip" python/ -x "**/__pycache__/*" "**/*.pyc")
echo "      완료: common_layer.zip"

# ──────────────────────────────────────────────
# 2. daily_monitor.zip 패키징
# ──────────────────────────────────────────────
echo "[2/4] daily_monitor.zip 패키징..."
DM_DIR="${TMP_DIR}/daily_monitor"
mkdir -p "${DM_DIR}"
cp daily_monitor/handler.py "${DM_DIR}/handler.py"
(cd "${DM_DIR}" && zip -r "${TMP_DIR}/daily_monitor.zip" . -x "**/__pycache__/*" "**/*.pyc")
echo "      완료: daily_monitor.zip"

# ──────────────────────────────────────────────
# 3. remediation_handler.zip 패키징
# ──────────────────────────────────────────────
echo "[3/4] remediation_handler.zip 패키징..."
RH_DIR="${TMP_DIR}/remediation_handler"
mkdir -p "${RH_DIR}"
cp remediation_handler/handler.py "${RH_DIR}/handler.py"
(cd "${RH_DIR}" && zip -r "${TMP_DIR}/remediation_handler.zip" . -x "**/__pycache__/*" "**/*.pyc")
echo "      완료: remediation_handler.zip"

# ──────────────────────────────────────────────
# 4. S3 업로드
# ──────────────────────────────────────────────
echo "[4/4] S3 업로드 (s3://${BUCKET}/${S3_PREFIX}/)..."
aws s3 cp "${TMP_DIR}/common_layer.zip"        "s3://${BUCKET}/${S3_PREFIX}/common_layer.zip"
aws s3 cp "${TMP_DIR}/daily_monitor.zip"       "s3://${BUCKET}/${S3_PREFIX}/daily_monitor.zip"
aws s3 cp "${TMP_DIR}/remediation_handler.zip" "s3://${BUCKET}/${S3_PREFIX}/remediation_handler.zip"
echo "      완료"

# ──────────────────────────────────────────────
# 5. CloudFormation 배포
# ──────────────────────────────────────────────
echo ""
echo "[5/5] CloudFormation 스택 배포..."
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name "${STACK_NAME}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    DeploymentBucket="${BUCKET}" \
    CodeVersion="${S3_PREFIX}" \
    Environment="${ENVIRONMENT}" \
  --no-fail-on-empty-changeset

echo ""
echo "=== 배포 완료 ==="
echo "스택 출력값 확인:"
aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" \
  --output table
