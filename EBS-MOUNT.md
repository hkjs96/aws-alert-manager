# EBS 볼륨 추가 마운트 가이드

EC2 인스턴스에 EBS 볼륨을 추가하고 특정 경로(예: `/data`)로 마운트하는 절차.

---

## 1. EBS 볼륨 연결 확인

AWS 콘솔 → EC2 → 인스턴스 → 스토리지 탭에서 연결된 디바이스명 확인.

```bash
# 연결된 블록 디바이스 목록 확인
lsblk

# 예시 출력:
# NAME    MAJ:MIN RM SIZE RO TYPE MOUNTPOINT
# xvda    202:0    0   8G  0 disk
# └─xvda1 202:1    0   8G  0 part /
# xvdf    202:80   0  20G  0 disk        ← 새로 추가된 EBS
```

> nvme 기반 인스턴스(t3, m5 등)는 `/dev/nvme1n1` 형태로 표시됨.

---

## 2. 파일시스템 생성 및 마운트

```bash
# 파일시스템 생성 (신규 볼륨에만 실행 - 기존 데이터 있으면 생략)
sudo mkfs -t xfs /dev/xvdf

# 마운트 포인트 생성
sudo mkdir -p /data

# 마운트
sudo mount /dev/xvdf /data

# 재부팅 후에도 유지되도록 /etc/fstab 등록
echo "/dev/xvdf /data xfs defaults,nofail 0 2" | sudo tee -a /etc/fstab

# 마운트 확인
df -h /data
```

---

## 3. 모니터링 엔진 연동

EBS 마운트 후 모니터링 엔진이 `/data` 경로 알람을 자동 생성하려면 EC2 태그 추가 필요.

```bash
aws ec2 create-tags \
  --resources i-xxxxxxxxxxxxxxxxx \
  --tags Key=Threshold_Disk_data,Value=90 \
  --region us-east-1
```

태그 네이밍 규칙: `Threshold_Disk_{경로명}` → 경로 `/data` = 태그 키 `Threshold_Disk_data`

이후 CWAgent가 `/data` 메트릭을 보고하기 시작하면 daily-monitor 실행 시 알람이 자동 생성됨.
즉시 반영하려면 `Monitoring` 태그를 off → on으로 재설정:

```bash
aws ec2 create-tags --resources i-xxxxxxxxxxxxxxxxx --tags Key=Monitoring,Value=off --region us-east-1
aws ec2 create-tags --resources i-xxxxxxxxxxxxxxxxx --tags Key=Monitoring,Value=on --region us-east-1
```

> CWAgent 설정은 `resources: ["*"]`로 되어 있어 마운트만 하면 자동 수집됨. CWAgent 재설정 불필요.

---

## 4. 알람 생성 확인

```bash
aws cloudwatch describe-alarms \
  --alarm-name-prefix "i-xxxxxxxxxxxxxxxxx-Disk-" \
  --query "MetricAlarms[*].{Name:AlarmName,Threshold:Threshold}" \
  --output table \
  --region us-east-1
```

예상 결과:
- `i-xxx-Disk-root-dev`
- `i-xxx-Disk-data-dev`
