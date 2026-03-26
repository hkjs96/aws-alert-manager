#!/usr/bin/env bash
# lb-tg-alarm-lab 스택 삭제 스크립트
set -euo pipefail

STACK_NAME="lb-tg-alarm-lab"
PROFILE="bjs"
REGION="ap-northeast-2"

echo "스택 삭제 시작: $STACK_NAME (리전: $REGION)"

# 스택 삭제 요청
if ! aws cloudformation delete-stack \
  --profile "$PROFILE" \
  --region "$REGION" \
  --stack-name "$STACK_NAME"; then
  echo ""
  echo "오류: 스택 삭제 요청에 실패했습니다."
  echo "SSO 세션이 만료되었을 수 있습니다. 다음 명령으로 재로그인하세요:"
  echo "  aws sso login --profile $PROFILE"
  exit 1
fi

echo "스택 삭제 대기 중..."

# 삭제 완료 대기
if ! aws cloudformation wait stack-delete-complete \
  --profile "$PROFILE" \
  --region "$REGION" \
  --stack-name "$STACK_NAME"; then
  echo "오류: 스택 삭제 완료 대기에 실패했습니다."
  echo "AWS 콘솔에서 스택 상태를 확인하세요."
  exit 1
fi

echo "스택 삭제 완료: $STACK_NAME"
