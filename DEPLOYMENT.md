# TARS K3s Production Deployment Guide (DEPLOYMENT.md)

이 문서는 TARS AI Companion 백엔드 시스템을 자체 호스트 PC(홈 서버, 미니 PC, Linux 머신 등)에 **K3s (경량 쿠버네티스)**, **PostgreSQL 16**, **Traefik Ingress**, 그리고 **cert-manager (Let's Encrypt 자동 SSL/TLS)** 기반으로 안전하게 프로덕션 배포하는 종합 가이드입니다.

---

## 1. 사전 요구사항 (Host Prerequisites)

### 1.1 하드웨어 권장 사양
- **CPU**: 2 Core 이상 (4 Core 이상 권장)
- **RAM**: 최소 4GB (8GB 이상 권장)
- **스토리지**: SSD 20GB 이상의 여유 공간

### 1.2 소프트웨어 요구사항
- **OS**: Ubuntu 22.04 / 24.04 LTS (또는 Debian 계열)
- **Docker**: v24.0 이상 (로컬 컨테이너 이미지 빌드용)
- **K3s**: 경량 쿠버네티스 배포판
- **curl, git**: 소스코드 클론 및 도구 설치용

---

## 2. 네트워크 및 도메인 / DDNS 설정

### 2.1 공유기 포트 포워딩 (Router Port Forwarding)
공유기 관리자 페이지(192.168.0.1 또는 192.168.1.1)에 접속하여 다음 포트를 호스트 PC의 내부 IP로 전달합니다:
- **외부 80 (TCP)** ➡️ **호스트 PC IP : 80 (Traefik HTTP / Let's Encrypt 챌린지)**
- **외부 443 (TCP)** ➡️ **호스트 PC IP : 443 (Traefik HTTPS / WSS)**

### 2.2 도메인 연결 (DDNS & CNAME)
1. **공유기 DDNS 생성**: 공유기 관리자 페이지에서 무료 DDNS를 설정합니다. (예: `myhome.iptime.org`)
2. **도메인 DNS 등록**: 보유하신 도메인 관리 콘솔(가비아, Namecheap 등)에서 CNAME 레코드를 추가합니다:
   - **Type**: `CNAME`
   - **Host**: `@` (루트) 또는 `tars`
   - **Value**: `myhome.iptime.org.`

---

## 3. 호스트 PC 세팅 (Step-by-Step)

### Step 1: K3s 설치 및 기본 권한 설정
호스트 PC 터미널에서 K3s를 단 한 줄로 설치합니다:
```bash
# 1. K3s 설치 (Traefik 및 로컬 스토리지 클래스 기본 내장)
curl -sfL https://get.k3s.io | sh -

# 2. 일반 유저 권한으로 kubectl 사용 설정
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
export KUBECONFIG=~/.kube/config
echo "export KUBECONFIG=~/.kube/config" >> ~/.bashrc

# 3. K3s 정상 구동 확인
kubectl get nodes
```

---

### Step 2: cert-manager 설치 (SSL 인증서 자동 발급기)
```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.0/cert-manager.yaml

# 파드들이 모두 Running 상태가 될 때까지 대기
kubectl get pods -n cert-manager --watch
```

---

### Step 3: TARS 레포지토리 클론
```bash
cd ~
git clone https://github.com/rujino/TARS.git
cd TARS
```

---

### Step 4: 설정 파일(YAML) 수정

개인 정보(도메인, 이메일, 키값)가 들어가는 파일들은 모두 템플릿(`.example.yaml`)으로 제공되며, `.gitignore`에 등록되어 안전하게 관리됩니다.

```bash
# 템플릿 복사
cp k8s/01-secret.example.yaml k8s/01-secret.yaml
cp k8s/04-cluster-issuer.example.yaml k8s/04-cluster-issuer.yaml
cp k8s/05-ingress.example.yaml k8s/05-ingress.yaml
```

1. **`k8s/01-secret.yaml`**:
   - `TARS_JWT_SECRET_KEY`: `openssl rand -hex 32` 명령어로 생성한 안전한 32바이트 이상 키 입력.
   - `POSTGRES_PASSWORD`: 안전한 DB 비밀번호 설정.
   - `TARS_GEMINI_API_KEY`: Google Gemini API 키 입력.

2. **`k8s/04-cluster-issuer.yaml`**:
   - `email`: 본인의 실제 이메일 주소 입력 (인증서 만료 사전 알림용).

3. **`k8s/05-ingress.yaml`**:
   - `tars.example.com`을 실제 사용하시는 도메인으로 변경.

4. **`k8s/01-config.yaml`**:
   - `TARS_DOMAIN`: 사용하실 도메인 입력 (예: `tars.yourdomain.com`).

---

### Step 5: 원클릭 빌드 및 배포

배포 스크립트를 실행하여 로컬 이미지 빌드, K3s 임포트 및 매니페스트 적용을 일괄 처리합니다:
```bash
chmod +x k8s/deploy.sh
bash k8s/deploy.sh
```

---

## 4. 배포 상태 및 로그 확인

```bash
# 1. 전체 파드 및 서비스 상태 확인
kubectl get pods,svc,pvc,ingress -n tars

# 2. 백엔드 실시간 로그 모니터링
kubectl logs -f deployment/tars-backend -n tars

# 3. SSL 인증서 발급 상태 확인
kubectl get certificate -n tars
kubectl describe certificate tars-tls-secret -n tars
```

---

## 5. 트러블슈팅 (Troubleshooting)

| 현상 | 원인 | 해결 방법 |
| :--- | :--- | :--- |
| **인증서 발급 대기 (Pending/False)** | 공유기 80 포트 미개방 또는 도메인 DNS 전파 지연 | `kubectl describe challenge -n tars`로 원인 확인 및 80 포트포워딩 재확인 |
| **CrashLoopBackOff (DB 연결 에러)** | DB 컨테이너가 준비되기 전 백엔드가 기동됨 | K3s가 자동으로 재시도하여 곧 정상 기동됩니다. `kubectl logs deployment/tars-backend -n tars` 확인 |
| **ImagePullBackOff** | 로컬 이미지가 K3s containerd에 임포트되지 않음 | `docker save tars-backend:latest \| sudo k3s ctr images import -` 다시 실행 |
