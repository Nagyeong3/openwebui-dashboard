2026-10-26: .env 자동 로드 지원을 추가했습니다. 설정 방법은 [ENV_SETUP.md](docs/ENV_SETUP.md)를 참고하세요. 추가 Python 패키지는 필요 없습니다.

2026-10-23: React API 사용자 분석 연결 완료. 사용자/팀/팀장 서버 조회 및 FastAPI 정적 화면 서빙은 [5단계 폐쇄망 설치 절차](docs/PHASE5_OFFLINE.md)를 참고하세요. 기존 Conda 환경을 재사용합니다. 토큰/비용/운영 실행은 후속 단계입니다.

# OpenWebUI Analytics Dashboard

2026-10-22: OpenWebUI 0.12.3 공식 API 수집·캐시·0건 포함 사용자 집계를 [`backend_v2/`](backend_v2/README.md)에 신규 구현했습니다. 실제 폐쇄망 호출 검증 전이며 React 데모에 연결하는 작업은 다음 단계입니다. [API 조사 기준](docs/OPENWEBUI_0123_API.md)을 참고하세요.

새 React 대시보드는 [`frontend-v2/`](frontend-v2/README.md)에 있습니다. 라이트/다크, 개요·사용자/팀/팀장·토큰·운영 화면을 제공하며 현재 합성 데모 데이터로 실행됩니다. 실제 폐쇄망 API 연결은 [v2 API 계약](docs/DASHBOARD_V2_API_CONTRACT.md) 확인 후 진행합니다. 기존 Streamlit 원본은 아래에 보존합니다.

OpenWebUI SQLite DB 복사본을 기준으로 사내 LLM 서비스 사용 현황을 분석하는 Streamlit 대시보드입니다.

## 목표

- 운영 DB를 직접 조회하지 않고 분석용 DB 복사본만 사용합니다.
- 사용자, 채팅, 메시지, 모델, 파일 첨부, 피드백 중심의 1차 사용량 지표를 제공합니다.
- 토큰/GPU/vLLM 실시간 지표는 1차 범위에서 제외하고, 이후 별도 수집 구조로 확장합니다.

## 실행 준비

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## DB 배치

분석용 OpenWebUI SQLite DB 복사본을 `data/openwebui.db`에 둡니다.

다른 경로를 사용하려면 환경변수로 지정할 수 있습니다.

```bash
OPENWEBUI_DB_PATH=/path/to/webui.db streamlit run app.py
```

## 프로젝트 구조

```text
app.py                  # 앱 진입점
config/                 # 설정값
data/                   # 분석용 DB 복사본 위치
src/db/                 # SQLite 연결 및 조회
src/services/           # 분석/파싱/분류 로직
src/ui/                 # 공통 화면 컴포넌트
src/pages/              # 대시보드 화면
src/utils/              # 날짜/표시 포맷 유틸
```

## 유지보수 원칙

- 화면 코드는 `src/pages`에 둡니다.
- SQL과 DB 연결은 `src/db`에 둡니다.
- OpenWebUI JSON 파싱과 지표 계산은 `src/services`에 둡니다.
- 공통 카드, 차트, 테이블은 `src/ui`에 둡니다.
- 복잡한 SQL, JSON 구조, 집계 기준에는 짧은 주석을 남깁니다.

API 최초 full 수집, 이후 quick 업데이트, LiteLLM과의 관계 및 향후 운영 화면 구현 기준은 [동기화 사용법](docs/SYNC_USAGE.md)을 참고하세요.
