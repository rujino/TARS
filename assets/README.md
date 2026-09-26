# TARS Media & Character Assets Directory

이 디렉터리는 로컬에서 메이드 캐릭터(베라, 미우)의 원본 이미지 에셋을 준비하고, 오브젝트 스토리지(SeaweedFS / S3)로 업로드하기 위한 로컬 작업 공간입니다.

## 📁 디렉터리 구조 및 파일명 규칙

```
assets/
└── characters/
    ├── vera/                # 메이드장 베라
    │   ├── idle.png         # 기본 대기
    │   ├── thinking.png     # 생각/고민
    │   ├── tool_use.png     # 메모보드/클립보드 작성
    │   ├── speaking.png     # 대화/발화
    │   └── interrupted.png  # 말끊김 놀람
    │
    └── miu/                 # 수행 메이드 미우
        ├── idle.png         # 기본 대기
        ├── thinking.png     # 생각/고민
        ├── tool_use.png     # 클립보드 도구 사용
        ├── speaking.png     # 대화/발화
        └── interrupted.png  # 말끊김 놀람
```

## 🚀 오브젝트 스토리지(SeaweedFS S3) 업로드 방법

준비된 이미지를 이 디렉터리에 넣은 후 아래 명령어를 실행하면,
SeaweedFS S3의 `tars-assets` 버킷으로 즉시 동기화 업로드됩니다:

```bash
# 가상환경 활성화
source .venv/bin/activate

# assets 폴더의 파일들을 tars-assets 버킷으로 일괄 업로드
uv run python scripts/upload_assets.py

# 버킷에 업로드된 에셋 목록 확인
uv run python scripts/upload_assets.py --list
```

## 🌐 브라우저 및 프론트엔드 접근 경로

업로드된 이미지는 FastAPI 백엔드 엔드포인트를 통해 투명하게 서빙됩니다:
* `http://localhost:8000/api/v1/assets/characters/vera/idle.png`
* `http://localhost:8000/api/v1/assets/characters/miu/speaking.png`

또는 SeaweedFS Filer 웹 브라우저를 통해 직접 확인:
* `http://localhost:8888/buckets/tars-assets/characters/`
