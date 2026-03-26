#!/usr/bin/env bash
# nlb-alb-ec2-lab 스택 삭제 스크립트
set -euo pipefail

STACK_NAME="dev-monitoring-lab"
PROFILE="bjs"
REGION="us-east-1"

echo "스택 삭제 시작: $STACK_NAME (리전: $REGION)"

if ! aws cloudformation delete-stack \
  --profile "$PROFILE" \
  --region "$REGION" \
  --stack-name "$STACK_NAME"; then
  echo "오류: 스택 삭제 요청에 실패했습니다."
  echo "SSO 세션 확인: aws sso login --profile $PROFILE"
  exit 1
fi

echo "스택 삭제 대기 중..."

if ! aws cloudformation wait stack-delete-complete \
  --profile "$PROFILE" \
  --region "$REGION" \
  --stack-name "$STACK_NAME"; then
  echo "오류: 스택 삭제 완료 대기에 실패했습니다."
  exit 1
fi

echo "스택 삭제 완료: $STACK_NAME"
