#!/bin/bash
# E2E Traffic Test - ALB/NLB endpoint로 요청 발생
# Usage: ./traffic-test.sh <ALB_DNS> <NLB_DNS> [count]
#
# SSM Session Manager로 bastion에 접속 후 실행하거나,
# 로컬에서 직접 실행 가능 (internet-facing LB)

ALB_DNS=${1:?"Usage: $0 <ALB_DNS> <NLB_DNS> [count]"}
NLB_DNS=${2:?"Usage: $0 <ALB_DNS> <NLB_DNS> [count]"}
COUNT=${3:-20}

echo "=== ALB instance TG (default route) ==="
for i in $(seq 1 $COUNT); do
  curl -s -o /dev/null -w "%{http_code} " "http://${ALB_DNS}/"
done
echo ""

echo "=== ALB ip TG (/ip/ route) ==="
for i in $(seq 1 $COUNT); do
  curl -s -o /dev/null -w "%{http_code} " "http://${ALB_DNS}/ip/"
done
echo ""

echo "=== NLB (TCP:80) ==="
for i in $(seq 1 $COUNT); do
  curl -s -o /dev/null -w "%{http_code} " --max-time 3 "http://${NLB_DNS}/" 2>/dev/null
done
echo ""

echo "Done. Wait 5 min for CloudWatch metrics to appear."
