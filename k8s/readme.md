### K3s 파일 목록

  • 00-namespace.yaml: tars 네임스페이스 정의
  • 01-config.yaml: 환경 변수 ConfigMap & Secret 템플릿
  • 02-db.yaml: PostgreSQL (Deployment + Service + 10Gi 로컬 영구 볼륨)
  • 03-backend.yaml: TARS 백엔드 (Deployment + 헬스체크 + 스토리지 영구 볼륨 + Service)
  • 04-cluster-issuer.yaml: cert-manager Let's Encrypt 자동 발급자
  • 05-ingress.yaml: 도메인 라우팅, SSL 종료, WebSocket/SSE 지원 Ingress
  • deploy.sh: 빌드/임포트/배포 원클릭 자동화 스크립트
  • DEPLOYMENT.md: 호스트 PC 세팅 및 K3s 배포 가이드로 전면 개편

### K3s 설치 및 배포
  1. K3s 및 cert-manager 설치:
    # K3s 설치
    curl -sfL https://get.k3s.io | sh -
    mkdir -p ~/.kube && sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config && sudo chown $(id -u):$(id -g) ~/.kube/config
    export KUBECONFIG=~/.kube/config

    # cert-manager 설치 (SSL 자동 발급기)
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.0/cert-manager.yaml

  2. 프로젝트 클론 및 도메인/비밀번호 설정:
    git clone https://github.com/rujino/TARS.git
    cd TARS

    # k8s/01-config.yaml (DB비밀번호, JWT키, Gemini키)
    # k8s/04-cluster-issuer.yaml (이메일)
    # k8s/05-ingress.yaml (도메인명) 수정

  3. 원클릭 배포:
    bash k8s/deploy.sh