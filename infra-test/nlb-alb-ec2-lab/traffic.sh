#!/usr/bin/env bash
# LB 트래픽 생성 스크립트
# NLB → ALB → EC2 체인으로 트래픽 유발
set -euo pipefail

PROFILE="bjs"
REGION="us-east-1"
STACK_NAME="dev-monitoring-lab"

NLB_DNS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --profile "$PROFILE" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='NlbDnsName'].OutputValue" \
  --output text)

ALB_DNS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --profile "$PROFILE" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='AlbDnsName'].OutputValue" \
  --output text)

echo "NLB: $NLB_DNS"
echo "ALB: $ALB_DNS"
echo ""

DURATION=${1:-120}
CONCURRENCY=${2:-5}

echo "트래픽 생성: ${DURATION}초, 동시 ${CONCURRENCY}개"
echo "---"

END=$((SECONDS + DURATION))
COUNT=0
FAIL=0

while [ $SECONDS -lt $END ]; do
  for _ in $(seq 1 "$CONCURRENCY"); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 5 "http://$NLB_DNS/" 2>/dev/null || echo "000")
    COUNT=$((COUNT + 1))
    if [ "$HTTP_CODE" != "200" ]; then
      FAIL=$((FAIL + 1))
    fi
  done
  # 초당 약 CONCURRENCY개 요청
  sleep 0.2
done

echo ""
echo "완료: 총 ${COUNT}건, 실패 ${FAIL}건"
