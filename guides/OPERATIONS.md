# AWS Monitoring Engine — 운영 및 배포 가이드 (OPERATIONS)

이 문서는 시스템의 배포, 패치, 그리고 인프라 설정에 관한 통합 가이드다.

---

## 1. 전체 스택 배포 (CloudFormation)

콘솔(AWS Management Console)을 통해 전체 리소스를 배포하는 표준 절차다.

### 1-1. 코드 패키징 및 S3 업로드
로컬에서 다음 5개 zip 파일을 생성하여 S3 배포 버킷의 특정 버전 경로(예: `s3://bucket/v1.0.0/`)에 업로드한다.

- `common_layer.zip`: `common/` 전체 (Lambda Layer용)
- `daily_monitor.zip`: `daily_monitor/` (Orchestrator + Worker 포함)
- `remediation_handler.zip`: `remediation_handler/`
- `api_handler.zip`: `api_handler/`
- `sqs_worker.zip`: `sqs_worker/` (존재하는 경우)

### 1-2. 스택 생성/업데이트
1. `template.yaml`을 사용하여 CloudFormation 스택을 생성/업데이트한다.
2. **핵심 파라미터**:
   - `DeploymentBucket`: zip 파일이 업로드된 S3 버킷명
   - `CodeVersion`: S3 내 버전 prefix (예: `v1.0.0`)
   - `Environment`: `prod` / `dev` / `staging`

---

## 2. 빠른 패치: API 핸들러 단독 배포

전체 스택 업데이트 없이 `api_handler/` 코드만 수정된 경우 다음 스크립트를 사용하여 빠르게 반영할 수 있다.

```powershell
# API 핸들러 단독 배포 스크립트 실행 (PowerShell)
'{"tool_input":{"file_path":"api_handler/lambda_handler.py"}}' | python .claude\deploy-api-handler.py
```

**스크립트 동작**:
1. 새 `CodeVersion` 생성 및 `api_handler.zip` 빌드/업로드
2. 기존 버전에서 변경되지 않은 아티팩트(`common_layer` 등)를 새 경로로 복사
3. CloudFormation `deploy`를 통해 `CodeVersion` 파라미터만 업데이트

---

## 3. EC2 모니터링 설정 (CloudWatch Agent)

EC2의 Memory/Disk 메트릭을 수집하려면 CloudWatch Agent 설치 및 설정이 필수적이다.

### 3-1. 에이전트 설치 및 설정
- **설정 파일**: `/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json`
- **핵심 설정**: `namespace: "CWAgent"`, `append_dimensions: { "InstanceId": "${aws:InstanceId}" }`
- **적용 명령**:
  ```bash
  sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/path/to/config.json -s
  ```

### 3-2. IAM 권한
인스턴스 역할에 `CloudWatchAgentServerPolicy` 정책이 연결되어 있어야 한다.

---

## 4. 스토리지 관리 (EBS 마운트 및 태깅)

추가 EBS 볼륨을 마운트하고 알람을 자동 생성하는 절차다.

### 4-1. 마운트 절차
1. `lsblk`로 디바이스 확인
2. `sudo mkfs -t xfs /dev/xvdf` (신규 볼륨)
3. `sudo mount /dev/xvdf /data` 및 `/etc/fstab` 등록

### 4-2. 자동 알람 연동 (태깅)
마운트된 경로에 대해 알람을 자동 생성하려면 인스턴스에 태그를 추가한다.
- **규칙**: `Threshold_Disk_{경로명}`
- **예시**: `/data` 마운트 시 `Key=Threshold_Disk_data, Value=90` 태그 추가

---

## 5. 트러블슈팅

| 문제 | 원인 | 해결 |
|------|------|------|
| 메트릭 미발생 | IAM 권한 부족 | `CloudWatchAgentServerPolicy` 확인 |
| 알람 미생성 | 태그 누락 | `Monitoring=on` 및 `Threshold_*` 태그 확인 |
| 배포 실패 | S3 경로 불일치 | `CodeVersion` 파라미터와 S3 prefix 일치 여부 확인 |
| API 404 | Lambda 핸들러 설정 오류 | `api_handler.zip` 루트에 `lambda_handler.py` 위치 확인 |
