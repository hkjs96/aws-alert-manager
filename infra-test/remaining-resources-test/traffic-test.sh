#!/bin/bash
# E2E Traffic Test - Remaining Resources (APIGW REST/HTTP/WebSocket + CLB)
# Usage: ./traffic-test.sh <REST_API_URL> <HTTP_API_URL> <WS_API_URL> <CLB_DNS> [BACKUP_VAULT] [BACKUP_ROLE_ARN] [DDB_TABLE_ARN]
#
# VPN, ACM, MQ, OpenSearch은 AWS가 자동으로 메트릭을 발행하므로 트래픽 불필요.
# Backup은 수동 백업 트리거로 메트릭 발생 (선택적 - 인자 제공 시).

REST_API_URL=${1:?"Usage: $0 <REST_API_URL> <HTTP_API_URL> <WS_API_URL> <CLB_DNS> [BACKUP_VAULT] [BACKUP_ROLE_ARN] [DDB_TABLE_ARN]"}
HTTP_API_URL=${2:?"Usage: $0 <REST_API_URL> <HTTP_API_URL> <WS_API_URL> <CLB_DNS>"}
WS_API_URL=${3:?"Usage: $0 <REST_API_URL> <HTTP_API_URL> <WS_API_URL> <CLB_DNS>"}
CLB_DNS=${4:?"Usage: $0 <REST_API_URL> <HTTP_API_URL> <WS_API_URL> <CLB_DNS>"}
BACKUP_VAULT=${5:-""}
BACKUP_ROLE_ARN=${6:-""}
DDB_TABLE_ARN=${7:-""}

echo "=== Phase 1: APIGW REST - Sequential (20 requests) ==="
for i in $(seq 1 20); do
  curl -s -o /dev/null -w "%{http_code} " "${REST_API_URL}/"
done
echo ""

echo "=== Phase 2: APIGW REST - Concurrent (20 requests, 10 parallel) ==="
seq 1 20 | xargs -I{} -P 10 curl -s -o /dev/null -w "%{http_code} " "${REST_API_URL}/"
echo ""

echo "=== Phase 3: APIGW HTTP - Sequential (20 requests) ==="
for i in $(seq 1 20); do
  curl -s -o /dev/null -w "%{http_code} " "${HTTP_API_URL}/"
done
echo ""

echo "=== Phase 4: APIGW WebSocket - Connect/Disconnect (5 cycles) ==="
# wss:// → https:// for curl fallback
WS_URL_HTTP=$(echo "$WS_API_URL" | sed 's|^wss://|https://|')
for i in $(seq 1 5); do
  if command -v wscat &>/dev/null; then
    wscat -c "$WS_API_URL" -x '{"action":"test"}' --wait 1 2>/dev/null && echo "101 " || echo "fail "
  else
    curl -s -o /dev/null -w "%{http_code} " \
      -H "Connection: Upgrade" -H "Upgrade: websocket" \
      -H "Sec-WebSocket-Version: 13" \
      -H "Sec-WebSocket-Key: $(openssl rand -base64 16)" \
      "$WS_URL_HTTP" 2>/dev/null
  fi
done
echo ""

echo "=== Phase 5: CLB - Sequential (20 requests) ==="
for i in $(seq 1 20); do
  curl -s -o /dev/null -w "%{http_code} " --max-time 3 "http://${CLB_DNS}/" 2>/dev/null
done
echo ""

echo "=== Summary ==="
echo "Traffic generation complete."
echo "  - VPN, ACM, MQ, OpenSearch: no traffic needed (auto-published metrics)"

# Phase 6: Backup - manual backup trigger (optional)
if [ -n "$BACKUP_VAULT" ] && [ -n "$BACKUP_ROLE_ARN" ] && [ -n "$DDB_TABLE_ARN" ]; then
  echo ""
  echo "=== Phase 6: AWS Backup - Manual backup trigger ==="
  aws backup start-backup-job \
    --backup-vault-name "$BACKUP_VAULT" \
    --resource-arn "$DDB_TABLE_ARN" \
    --iam-role-arn "$BACKUP_ROLE_ARN" 2>&1 | head -5
  echo "Backup job started (check AWS Backup console for status)"
else
  echo "  - Backup: skipped (provide BACKUP_VAULT, BACKUP_ROLE_ARN, DDB_TABLE_ARN args to trigger)"
fi

echo ""
echo "Done. Wait 5 min for CloudWatch metrics to appear."
