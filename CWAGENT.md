# CloudWatch Agent 설정 가이드

EC2 인스턴스에서 Memory / Disk 메트릭을 CloudWatch로 수집하기 위한 CWAgent 설정 가이드.

> CPU는 AWS/EC2 네임스페이스에서 기본 제공되므로 CWAgent 불필요.
> Memory / Disk는 CWAgent 설치 및 설정이 필요하다.

---

## 1. CWAgent 설치

```bash
# Amazon Linux 2 / AL2023
sudo yum install -y amazon-cloudwatch-agent

# Ubuntu
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb
```

---

## 2. 설정 파일

경로: `/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json`

```json
{
  "agent": {
    "metrics_collection_interval": 60,
    "run_as_user": "root"
  },
  "metrics": {
    "namespace": "CWAgent",
    "append_dimensions": {
      "InstanceId": "${aws:InstanceId}"
    },
    "metrics_collected": {
      "mem": {
        "measurement": ["mem_used_percent"],
        "metrics_collection_interval": 60
      },
      "disk": {
        "measurement": ["disk_used_percent"],
        "metrics_collection_interval": 60,
        "resources": ["*"],
        "ignore_file_system_types": ["sysfs", "devtmpfs", "tmpfs"]
      }
    }
  }
}
```

### 주요 설정 설명

| 항목 | 값 | 설명 |
|------|-----|------|
| `namespace` | `CWAgent` | CloudWatch 메트릭 네임스페이스 |
| `append_dimensions.InstanceId` | `${aws:InstanceId}` | 인스턴스 ID를 dimension으로 자동 추가 |
| `disk.resources` | `["*"]` | 모든 마운트 파티션 수집 |
| `ignore_file_system_types` | `sysfs, devtmpfs, tmpfs` | 가상 파일시스템 제외 |
| `metrics_collection_interval` | `60` | 수집 주기 (초) |

> `resources: ["*"]`로 설정하면 마운트된 모든 파티션을 자동 수집. 알람 생성은 태그(`Threshold_Disk_*`)로 제어하므로 CWAgent 재설정 없이 EBS 추가 가능.
> EBS 마운트 절차는 [EBS-MOUNT.md](EBS-MOUNT.md) 참고.

---

## 3. 추가 경로 알람 자동 생성 (태그 기반)

모니터링 엔진은 EC2 인스턴스 태그의 `Threshold_Disk_{suffix}` 패턴을 읽어 추가 경로 알람을 자동 생성한다.

### 태그 네이밍 규칙

| 경로 | 태그 키 | 예시 값 |
|------|---------|---------|
| `/` (root) | `Threshold_Disk_root` | `85` |
| `/data` | `Threshold_Disk_data` | `90` |
| `/var/log` | `Threshold_Disk_var_log` | `80` |

EBS 마운트 후 태그만 추가하면 CWAgent가 메트릭을 보고하는 시점에 알람이 자동 생성됨. 자세한 절차는 [EBS-MOUNT.md](EBS-MOUNT.md) 참고.

---

## 4. 설정 적용

### 방법 A: 직접 파일 배포 (단일 인스턴스)

```bash
# 1. 설정 파일 복사
sudo cp amazon-cloudwatch-agent.json \
  /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

# 2. 설정 적용 및 에이전트 시작
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json \
  -s

# 3. 상태 확인
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status
```

### 방법 B: SSM Parameter Store (다수 인스턴스 권장)

**1단계: SSM에 설정 저장 (로컬 PC에서)**

```bash
aws ssm put-parameter \
  --name "/cloudwatch-agent/config" \
  --type "String" \
  --value file://amazon-cloudwatch-agent.json \
  --overwrite \
  --region ap-northeast-2
```

**2단계: 인스턴스에서 SSM 설정 가져와 적용**

```bash
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c ssm:/cloudwatch-agent/config \
  -s
```

**3단계: SSM Run Command로 다수 인스턴스 일괄 적용 (콘솔)**

1. AWS 콘솔 → Systems Manager → Run Command
2. 문서: `AmazonCloudWatch-ManageAgent`
3. Action: `configure`
4. Optional Configuration Source: `ssm`
5. Optional Configuration Location: `/cloudwatch-agent/config`
6. 대상 인스턴스 선택 후 실행

---

## 5. 설정 변경 시

설정 파일 수정 후 반드시 재적용 필요.

```bash
# 파일 직접 수정 후
sudo vi /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

# 재적용
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json \
  -s
```

SSM 방식이면 SSM 파라미터 업데이트 후 Run Command로 일괄 재적용.

---

## 6. 메트릭 확인

적용 후 약 1~2분 뒤 CloudWatch 콘솔에서 확인:

- 네임스페이스: `CWAgent`
- 메트릭: `mem_used_percent`, `disk_used_percent`
- Dimension: `InstanceId`

> 메트릭이 안 보이면 인스턴스 IAM Role에 `CloudWatchAgentServerPolicy` 정책이 붙어있는지 확인.

---

## 7. IAM 권한

인스턴스 IAM Role에 아래 정책 필요:

```
arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy
```

콘솔: EC2 → 인스턴스 → IAM 역할 → 정책 연결
