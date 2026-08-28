  ### K3s 파일 목록

  • 00-namespace.yaml: tars 네임스페이스 정의
  • 01-config.yaml: 환경 변수 ConfigMap & Secret 템플릿
  • 02-db.yaml: PostgreSQL (Deployment + Service + 10Gi 로컬 영구 볼륨)
  • 03-backend.yaml: TARS 백엔드 (Deployment + 헬스체크 + 스토리지 영구 볼륨 + Service)
  • 04-cluster-issuer.yaml: cert-manager Let's Encrypt 자동 발급자
  • 05-ingress.yaml: 도메인 라우팅, SSL 종료, WebSocket/SSE 지원 Ingress
  • deploy.sh: 빌드/임포트/배포 원클릭 자동화 스크립트
  • DEPLOYMENT.md: 호스트 PC 세팅 및 K3s 배포 가이드로 전면 개편