# Multi-Account Architecture Design (Draft)

> 이 문서는 향후 멀티 어카운트 확장을 위한 아키텍처 설계 초안입니다.
> 구현 전 팀 리뷰 및 의사결정이 필요합니다.

## 1. 아키텍처 결정: 패턴 A (중앙 집중형)

Lambda와 비즈니스 로직을 중앙 계정에서만 관리하고, 고객 계정에는 이벤트 포워딩 + IAM Role만 배포합니다.

### 선택 근거

- UI 통합: UI → 중앙 API 하나만 호출하면 됨 (패턴 B는 고객 계정별 엔드포인트 관리 필요)
- 코드 관리: Lambda 코드를 중앙에서만 배포/업데이트
- 태그 정책: 중앙 DB에서 태그 정책을 관리하고 모든 계정에 일관 적용
- 비용: 고객 계정에 Lambda/SNS 리소스 불필요

## 2. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                        고객 계정 (경량 스택)                       │
│                                                                 │
│  CloudTrail → EventBridge Rule → 중앙 EventBus (cross-account)  │
│  IAM Role (중앙 계정이 AssumeRole 가능)                           │
│  CloudTrail (이미 활성화 전제)                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                    cross-account event
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        중앙 계정 (풀 스택)                        │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ EventBridge  │───▶│ SQS FIFO     │───▶│ Lambda           │  │
│  │ (수신)       │    │ (버퍼/순서)   │    │ (event_processor)│  │
│  └──────────────┘    └──────┬───────┘    └────────┬─────────┘  │
│                             │                     │             │
│                        ┌────▼────┐          AssumeRole          │
│                        │ SQS DLQ │                │             │
│                        │ (실패)   │          ┌─────▼──────┐     │
│                        └─────────┘          │ 고객 계정    │     │
│                                             │ CW 알람 CRUD│     │
│  ┌──────────────┐    ┌──────────────────┐   └────────────┘     │
│  │ EventBridge  │───▶│ Lambda           │                      │
│  │ Scheduler    │    │ (daily_sync)     │──▶ 각 계정 순회       │
│  └──────────────┘    └──────────────────┘                      │
│                                                                 │
│  ┌──────────────┐    ┌──────────────────┐                      │
│  │ API Gateway  │───▶│ Lambda           │──▶ 알람 CRUD (UI용)  │
│  └──────────────┘    │ (api_handler)    │                      │
│                      └──────────────────┘                      │
│                                                                 │
│  ┌──────────────────────────────────────┐                      │
│  │ DynamoDB                              │                      │
│  │ - 계정 목록 (account_id, role_arn)    │                      │
│  │ - 태그 정책 (기본 임계치, 메트릭 설정) │                      │
│  │ - 알람 상태 (리소스별 알람 현황)       │                      │
│  └──────────────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
```

## 3. 이벤트 처리 안정성: SQS FIFO 도입

### 현재 문제

- EventBridge → Lambda 직접 호출 시 동시 이벤트 누락 가능
- Lambda 동시 실행 제한 (기본 1000)에 도달하면 이벤트 드롭
- Lambda 에러 시 EventBridge 재시도 최대 185회 후 포기
- 멀티 어카운트 확장 시 이벤트 볼륨 급증

### SQS FIFO 도입 효과

| 항목 | 현재 (EventBridge → Lambda) | 개선 (EventBridge → SQS FIFO → Lambda) |
|------|---------------------------|---------------------------------------|
| 이벤트 유실 | Lambda 에러 시 최대 185회 재시도 후 포기 | SQS가 최대 14일 보관, DLQ로 실패 메시지 보존 |
| 동시성 제어 | Lambda 동시 실행 제한에 의존 | MaximumConcurrency 설정으로 제어 |
| 순서 보장 | 보장 안 됨 | FIFO + MessageGroupId(리소스 ID)로 순서 보장 |
| 중복 처리 | 없음 | MessageDeduplicationId로 중복 제거 |
| 배치 처리 | 이벤트당 1회 Lambda 호출 | BatchSize로 묶어서 처리 가능 |
| 모니터링 | Lambda 에러 로그만 | SQS 메트릭 (ApproximateNumberOfMessages 등) |

### SQS FIFO 설계

```
MessageGroupId: "{account_id}:{resource_id}"
  → 같은 리소스에 대한 이벤트가 순서대로 처리됨
  → 다른 리소스의 이벤트는 병렬 처리 가능

MessageDeduplicationId: "{event_id}"
  → EventBridge 이벤트 ID 사용
  → 5분 내 동일 이벤트 중복 제거

VisibilityTimeout: 300초 (Lambda timeout과 동일)
MessageRetentionPeriod: 7일
MaxReceiveCount: 3 (3회 실패 시 DLQ로 이동)
```

### DLQ (Dead Letter Queue) 처리

```
SQS FIFO → Lambda (3회 실패) → DLQ
                                  ↓
                            CloudWatch Alarm (DLQ 메시지 수 > 0)
                                  ↓
                            SNS 알림 → 운영팀
                                  ↓
                            수동 재처리 또는 daily_sync에서 보정
```

## 4. 처리 모드

### 케이스 1: 이벤트 기반만 (실시간)

```
고객 계정 CloudTrail → EventBridge → 중앙 SQS FIFO → Lambda (event_processor)
```

- 태그 변경, 리소스 생성/삭제 시 즉시 알람 동기화
- 지연: 수초 ~ 수십초 (CloudTrail 전달 + SQS + Lambda)
- daily_sync 없음 → 이벤트 누락 시 보정 메커니즘 없음 (DLQ 수동 처리 필요)

### 케이스 2: 이벤트 + 스케줄링 (권장)

```
실시간: 고객 계정 CloudTrail → EventBridge → 중앙 SQS FIFO → Lambda (event_processor)
스케줄: EventBridge Scheduler → Lambda (daily_sync) → 각 계정 순회
```

- 이벤트 기반으로 실시간 반응 + 하루 1회 전체 동기화로 보정
- daily_sync가 이벤트 누락/DLQ 실패를 보정하는 안전망 역할
- 알람 상태 불일치 자동 해소

### 권장: 케이스 2

이벤트 기반 실시간 반응 + daily_sync 보정이 가장 안정적입니다.
이벤트가 누락되더라도 daily_sync에서 전체 리소스를 스캔하여 알람 상태를 보정합니다.

## 5. 고객 계정 경량 스택 (CFN)

고객 계정에 배포할 CloudFormation 템플릿:

```yaml
# 필요한 리소스만:
# 1. EventBridge Rule (이벤트 포워딩)
# 2. IAM Role (중앙 계정 AssumeRole 대상)

Resources:
  # EventBridge Rule: CloudTrail 이벤트를 중앙 계정으로 포워딩
  ForwardToMonitoringHub:
    Type: AWS::Events::Rule
    Properties:
      EventPattern:
        source: [aws.ec2, aws.rds, aws.elasticloadbalancing]
        detail-type: ["AWS API Call via CloudTrail"]
        detail:
          eventName:
            - CreateTags
            - DeleteTags
            - AddTagsToResource
            - RemoveTagsFromResource
            - RunInstances
            - TerminateInstances
            - CreateDBInstance
            - DeleteDBInstance
            - ModifyDBInstance
            - CreateLoadBalancer
            - DeleteLoadBalancer
            - CreateTargetGroup
            - DeleteTargetGroup
      Targets:
        - Id: CentralEventBus
          Arn: !Sub "arn:aws:events:${AWS::Region}:${CentralAccountId}:event-bus/monitoring-hub"
          RoleArn: !GetAtt EventBridgeForwardRole.Arn

  # IAM Role: 중앙 계정이 AssumeRole하여 이 계정의 리소스에 접근
  MonitoringCrossAccountRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: MonitoringEngineRole
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              AWS: !Sub "arn:aws:iam::${CentralAccountId}:root"
            Action: sts:AssumeRole
      Policies:
        - PolicyName: MonitoringAccess
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action:
                  - cloudwatch:PutMetricAlarm
                  - cloudwatch:DeleteAlarms
                  - cloudwatch:DescribeAlarms
                  - cloudwatch:ListMetrics
                  - ec2:DescribeInstances
                  - ec2:DescribeTags
                  - rds:DescribeDBInstances
                  - rds:DescribeDBClusters
                  - rds:ListTagsForResource
                  - rds:DescribeDBInstanceClasses
                  - elasticloadbalancing:DescribeLoadBalancers
                  - elasticloadbalancing:DescribeTags
                  - elasticloadbalancing:DescribeTargetGroups
                Resource: "*"
```

## 6. DI와의 관계

수동 DI 패턴은 이 아키텍처의 핵심 기반입니다:

```python
# event_processor Lambda
def lambda_handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        account_id = body["account"]
        role_arn = f"arn:aws:iam::{account_id}:role/MonitoringEngineRole"
        
        clients = create_clients_for_account(role_arn)
        
        # DI로 고객 계정 클라이언트 주입
        sync_alarms_for_resource(
            resource_id, resource_type, resource_tags,
            cw=clients["cw"],
        )
```

## 7. 마이그레이션 경로

### Phase 1: 현재 (단일 계정)
- 현재 구조 그대로 운영
- DI 패턴 도입 (cw=None 기본값)
- 기존 동작 변경 없음

### Phase 2: SQS FIFO 도입 (단일 계정)
- EventBridge → SQS FIFO → Lambda 구조로 전환
- 이벤트 누락 방지 + DLQ 도입
- 단일 계정에서 안정성 검증

### Phase 3: 멀티 어카운트 확장
- 고객 계정에 경량 스택 배포
- 중앙 EventBus + SQS FIFO로 크로스 어카운트 이벤트 수신
- AssumeRole로 고객 계정 알람 CRUD
- DynamoDB에 계정 목록/태그 정책 관리

### Phase 4: UI + API
- API Gateway + Lambda (api_handler) 추가
- UI에서 알람 CRUD 요청 → 중앙 API → AssumeRole → 고객 계정
- DynamoDB에서 알람 상태 조회/표시

## 8. 미결정 사항

- [ ] CloudTrail이 비활성화된 고객 계정 처리 방안
- [ ] 리전 간 이벤트 포워딩 (고객 계정이 다른 리전인 경우)
- [ ] SQS FIFO 처리량 제한 (300 TPS per MessageGroupId) 대응
- [ ] DynamoDB 스키마 설계 (계정 목록, 태그 정책, 알람 상태)
- [ ] UI 기술 스택 결정
- [ ] 고객 계정 온보딩/오프보딩 자동화 (StackSets 또는 Organizations)
