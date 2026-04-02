#!/bin/bash
# Extended Resources E2E Traffic Test Script
# Generates CloudWatch metrics for SQS, DynamoDB, CloudFront, WAF, S3, SNS.
# ECS/MSK/Route53/EFS/SageMaker auto-emit metrics without traffic.
#
# Usage: ./traffic-test.sh SQS_QUEUE_URL DDB_TABLE_NAME CF_DOMAIN WAF_ALB_DNS S3_BUCKET SNS_TOPIC_ARN

set -euo pipefail

if [ $# -lt 6 ]; then
  echo "Usage: $0 <SQS_QUEUE_URL> <DDB_TABLE_NAME> <CF_DOMAIN> <WAF_ALB_DNS> <S3_BUCKET> <SNS_TOPIC_ARN>"
  echo ""
  echo "Arguments:"
  echo "  SQS_QUEUE_URL   - SQS queue URL from stack output"
  echo "  DDB_TABLE_NAME  - DynamoDB table name from stack output"
  echo "  CF_DOMAIN       - CloudFront domain name from stack output"
  echo "  WAF_ALB_DNS     - WAF ALB DNS name from stack output"
  echo "  S3_BUCKET       - S3 bucket name from stack output"
  echo "  SNS_TOPIC_ARN   - SNS topic ARN from stack output"
  exit 1
fi

SQS_QUEUE_URL="$1"
DDB_TABLE_NAME="$2"
CF_DOMAIN="$3"
WAF_ALB_DNS="$4"
S3_BUCKET="$5"
SNS_TOPIC_ARN="$6"

echo "============================================"
echo "Extended Resources E2E Traffic Test"
echo "============================================"
echo ""

# --------------------------------------------------
# Phase 1: SQS (10 send + 10 receive)
# --------------------------------------------------
echo "[Phase 1] SQS - Sending 10 messages..."
for i in $(seq 1 10); do
  aws sqs send-message \
    --queue-url "$SQS_QUEUE_URL" \
    --message-body "e2e-test-message-$i" \
    --output text --query 'MessageId' 2>&1 || true
done

echo "[Phase 1] SQS - Receiving 10 messages..."
for i in $(seq 1 10); do
  aws sqs receive-message \
    --queue-url "$SQS_QUEUE_URL" \
    --max-number-of-messages 1 \
    --output text --query 'Messages[0].MessageId' 2>&1 || true
done
echo "[Phase 1] SQS - Done"
echo ""

# --------------------------------------------------
# Phase 2: DynamoDB (10 put + 10 get)
# --------------------------------------------------
echo "[Phase 2] DynamoDB - Writing 10 items..."
for i in $(seq 1 10); do
  aws dynamodb put-item \
    --table-name "$DDB_TABLE_NAME" \
    --item "{\"id\":{\"S\":\"e2e-test-$i\"},\"data\":{\"S\":\"traffic-test-payload-$i\"}}" \
    2>&1 || true
done

echo "[Phase 2] DynamoDB - Reading 10 items..."
for i in $(seq 1 10); do
  aws dynamodb get-item \
    --table-name "$DDB_TABLE_NAME" \
    --key "{\"id\":{\"S\":\"e2e-test-$i\"}}" \
    --output text 2>&1 || true
done
echo "[Phase 2] DynamoDB - Done"
echo ""

# --------------------------------------------------
# Phase 3: CloudFront (20 curl requests)
# --------------------------------------------------
echo "[Phase 3] CloudFront - Sending 20 requests to $CF_DOMAIN..."
for i in $(seq 1 20); do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://$CF_DOMAIN/" 2>&1 || echo "000")
  echo "  Request $i: HTTP $HTTP_CODE"
done
echo "[Phase 3] CloudFront - Done"
echo ""

# --------------------------------------------------
# Phase 4: WAF ALB (20 curl requests)
# --------------------------------------------------
echo "[Phase 4] WAF ALB - Sending 20 requests to $WAF_ALB_DNS..."
for i in $(seq 1 20); do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://$WAF_ALB_DNS/" 2>&1 || echo "000")
  echo "  Request $i: HTTP $HTTP_CODE"
done
echo "[Phase 4] WAF ALB - Done"
echo ""

# --------------------------------------------------
# Phase 5: S3 (10 put + 10 get)
# NOTE: S3 Request Metrics take ~15 min to start publishing after activation.
# --------------------------------------------------
echo "[Phase 5] S3 - NOTE: Request Metrics may take ~15 min after stack creation to appear in CloudWatch."
echo "[Phase 5] S3 - Writing 10 objects..."
for i in $(seq 1 10); do
  echo "e2e-test-data-$i" | aws s3api put-object \
    --bucket "$S3_BUCKET" \
    --key "traffic-test/object-$i.txt" \
    --body /dev/stdin \
    --output text 2>&1 || true
done

echo "[Phase 5] S3 - Reading 10 objects..."
for i in $(seq 1 10); do
  aws s3api get-object \
    --bucket "$S3_BUCKET" \
    --key "traffic-test/object-$i.txt" \
    /dev/null \
    --output text 2>&1 || true
done
echo "[Phase 5] S3 - Done"
echo ""

# --------------------------------------------------
# Phase 6: SNS (10 publish)
# --------------------------------------------------
echo "[Phase 6] SNS - Publishing 10 messages..."
for i in $(seq 1 10); do
  aws sns publish \
    --topic-arn "$SNS_TOPIC_ARN" \
    --message "e2e-test-message-$i" \
    --output text --query 'MessageId' 2>&1 || true
done
echo "[Phase 6] SNS - Done"
echo ""

# --------------------------------------------------
# Summary
# --------------------------------------------------
echo "============================================"
echo "Traffic test complete."
echo ""
echo "Resources with auto-emitted metrics (no traffic needed):"
echo "  - ECS Fargate: CPU, Memory, RunningTaskCount"
echo "  - MSK: ActiveControllerCount, UnderReplicatedPartitions, etc."
echo "  - Route53: HealthCheckStatus (us-east-1)"
echo "  - EFS: BurstCreditBalance, PercentIOLimit"
echo "  - SageMaker: CPUUtilization (endpoint must be InService)"
echo ""
echo "Run Daily Monitor to verify alarm auto-creation (~35 alarms expected)."
echo "============================================"
