### K3s 파일 목록

  • 00-namespace.yaml: tars 네임스페이스 정의
  • 01-config.yaml: 환경 변수 ConfigMap (도메인, 환경, DB 및 SLM URL 설정)
  • 01-secret.example.yaml: Secret 템플릿 (01-secret.yaml로 복사하여 사용, gitignore 처리)
  • 02-db.yaml: PostgreSQL 16 (Deployment + Service + 10Gi 로컬 영구 볼륨 PVC)
  • 03-backend.yaml: TARS 백엔드 (Deployment 3 Replicas + 헬스 프로브 + 10Gi/5Gi PVC + Service)
  • 04-cluster-issuer.example.yaml: cert-manager Let's Encrypt 자동 발급자 템플릿 (gitignore 처리)
  • 05-ingress.example.yaml: 도메인 라우팅, SSL 종료 Ingress 템플릿 (gitignore 처리)
  • deploy.sh: 빌드/임포트/배포 원클릭 자동화 스크립트
  • DEPLOYMENT.md: 호스트 PC 세팅 및 K3s 배포 가이드

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

    # 템플릿 복사 및 개인 설정 입력 (모두 gitignore 처리됨):
    cp k8s/01-secret.example.yaml k8s/01-secret.yaml
    cp k8s/04-cluster-issuer.example.yaml k8s/04-cluster-issuer.yaml
    cp k8s/05-ingress.example.yaml k8s/05-ingress.yaml

    # k8s/01-secret.yaml (DB비밀번호, JWT키, Gemini키)
    # k8s/04-cluster-issuer.yaml (이메일)
    # k8s/05-ingress.yaml (도메인명) 수정
    # k8s/01-config.yaml (TARS_LLAMACPP_BASE_URL 필요 시 호스트 SLM 엔드포인트 수정)

  3. (선택) 로컬 SLM (`llama-server`) 실행 및 진단:

    llama-server -m /path/to/model.gguf --port 8080 --host 0.0.0.0 --ctx-size 4096 -ngl 99
    uv run python scripts/test_slm.py

  4. 원클릭 배포:

    bash k8s/deploy.sh