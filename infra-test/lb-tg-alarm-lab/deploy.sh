#!/usr/bin/env bash
# lb-tg-alarm-lab 스택 배포 스크립트
set -euo pipefail

STACK_NAME="lb-tg-alarm-lab"
PROFILE="bjs"
REGION="us-east-1"

# 파라미터 파일 경로 확인
if [ -z "${1:-}" ]; then
  echo "사용법: $0 <parameters-file>"
  echo "예시:   $0 parameters.json"
  exit 1
fi

PARAM_FILE="$1"

if [ ! -f "$PARAM_FILE" ]; then
  echo "오류: 파라미터 파일을 찾을 수 없습니다: $PARAM_FILE"
  exit 1
fi

# AmiId가 파라미터 파일에 없으면 SSM에서 AL2023 최신 AMI 자동 조회
if ! grep -q '"AmiId"' "$PARAM_FILE"; then
  echo "AmiId 파라미터 미지정 — SSM에서 AL2023 최신 AMI 조회 중..."
  AMI_ID=$(aws ssm get-parameter \
    --profile "$PROFILE" \
    --region "$REGION" \
    --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
    --query 'Parameter.Value' \
    --output text)
  echo "조회된 AMI ID: $AMI_ID"

  # 임시 파라미터 파일 생성 (AmiId 추가)
  TEMP_PARAM=$(mktemp)
  python3 -c "
import json, sys
with open('$PARAM_FILE') as f:
    params = json.load(f)
params.append({'ParameterKey': 'AmiId', 'ParameterValue': '$AMI_ID'})
json.dump(params, sys.stdout, indent=2)
" > "$TEMP_PARAM"
  PARAM_FILE="$TEMP_PARAM"
  trap 'rm -f "$TEMP_PARAM"' EXIT
fi

echo "스택 배포 시작: $STACK_NAME (리전: $REGION)"

# 스택 존재 여부 확인
STACK_STATUS=$(aws cloudformation describe-stacks \
  --profile "$PROFILE" \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$STACK_STATUS" = "NOT_FOUND" ]; then
  echo "새 스택 생성 중..."
  if ! aws cloudformation create-stack \
    --profile "$PROFILE" \
    --region "$REGION" \
    --stack-name "$STACK_NAME" \
    --template-body "file://template.yaml" \
    --parameters "file://$PARAM_FILE"; then
    echo ""
    echo "오류: 스택 생성에 실패했습니다."
    echo "SSO 세션이 만료되었을 수 있습니다. 다음 명령으로 재로그인하세요:"
    echo "  aws sso login --profile $PROFILE"
    exit 1
  fi
  echo "스택 생성 대기 중... (약 3~5분 소요)"
  aws cloudformation wait stack-create-complete \
    --profile "$PROFILE" \
    --region "$REGION" \
    --stack-name "$STACK_NAME"
else
  echo "기존 스택 업데이트 중... (현재 상태: $STACK_STATUS)"
  if ! aws cloudformation update-stack \
    --profile "$PROFILE" \
    --region "$REGION" \
    --stack-name "$STACK_NAME" \
    --template-body "file://template.yaml" \
    --parameters "file://$PARAM_FILE" 2>&1; then
    echo "참고: 변경 사항이 없으면 'No updates are to be performed' 메시지가 정상입니다."
  fi
  echo "스택 업데이트 대기 중..."
  aws cloudformation wait stack-update-complete \
    --profile "$PROFILE" \
    --region "$REGION" \
    --stack-name "$STACK_NAME" 2>/dev/null || true
fi

echo ""
echo "스택 배포 완료: $STACK_NAME"
echo ""
echo "Outputs:"
aws cloudformation describe-stacks \
  --profile "$PROFILE" \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
  --output table
