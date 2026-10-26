# .env 설정 (2026-10-26)

이번 수정부터 프로젝트 루트 `.env`를 CLI와 FastAPI가 자동으로 읽습니다. 기존 4d22291 단독 버전에는 자동 로드 기능이 없으므로 최신 backend_v2로 갱신해야 합니다. Python 패키지와 프런트 빌드 변경은 없습니다.

## 토큰 구분

| 설정 | 용도 |
| --- | --- |
| OPENWEBUI_API_TOKEN | OpenWebUI 관리자 계정의 API 키. 전체 사용자와 관리자 analytics 메시지 조회에 사용 |
| DASHBOARD_API_TOKEN | 선택 설정. 대시보드 조회 API에 접속할 때 사용하는 별도 토큰 |
| LiteLLM 키 | 이후 토큰/비용 로그 수집에 사용할 별도 키. 위 설정에 넣지 않음 |

OpenWebUI 관리자 계정으로 로그인 후 설정 → 계정 → API 키에서 발급합니다. API 키 기능이 꺼져 있다면 관리자 설정에서 활성화가 필요합니다. 버전에 따라 메뉴 문구가 다를 수 있습니다. 이 대시보드는 관리자 권한의 `/api/v1/users/all`, `/api/v1/analytics/messages`를 사용하므로 일반 사용자 키로는 부족합니다. API 키의 endpoint 제한을 사용 중이면 해당 경로 접근도 허용되어야 합니다. 브라우저 세션 JWT는 만료될 수 있어 장기 수집에는 API 키를 사용합니다. OpenWebUI의 WEBUI_SECRET_KEY를 복사하는 것이 아닙니다.

## 적용

기존 backend_v2를 백업하고 최신 backend_v2로 갱신합니다. 루트 `.env.example`만 템플릿으로 복사하며 기존 `.env`는 덮어쓰지 않습니다.

Miniconda Prompt (CMD):

```bat
conda activate D:\project\oui-env-v2
cd /d D:\project\oui-dashboard-v2
if not exist .env copy .env.example .env
notepad .env
```

예시:

```dotenv
OPENWEBUI_URL=http://127.0.0.1:8080
OPENWEBUI_API_TOKEN=여기에_관리자_API키
DASHBOARD_CACHE_PATH=data/dashboard-v2.sqlite3
ORG_USER_CSV_PATH=data/users.csv
DASHBOARD_FRONTEND_DIR=frontend_v2/dist
```

URL은 실제 OpenWebUI 서버 주소로 바꿉니다. `DASHBOARD_FRONTEND_DIR`은 실제 빌드 `index.html`과 assets가 들어 있는 폴더로 지정합니다. 폴더명이 `frontend-v2`이면 하이픈으로 바꿉니다. CSV가 없으면 ORG_USER_CSV_PATH를 빈 값으로 둡니다.

`.env` 위치는 `D:\project\oui-dashboard-v2\.env`입니다. backend_v2 안이나 frontend_v2 안이 아닙니다. Windows 메모장에서 `.env.txt`로 저장되지 않았는지 확인합니다.

환경변수 우선순위는 터미널/서비스 환경변수 → .env → 기본값입니다. 이전 SET 값이 남아 있으면 .env 값보다 우선하므로, 기존 터미널을 닫고 새 Miniconda Prompt를 열어 실행합니다. .env를 읽어도 os.environ 전체에 복사하지 않습니다. 상대 경로는 .env가 있는 프로젝트 루트 기준입니다.

```bat
conda activate D:\project\oui-env-v2
cd /d D:\project\oui-dashboard-v2
python -m unittest discover -s backend_v2\tests -v
python -m backend_v2.cli sync --kind full
python -m uvicorn backend_v2.app:create_app --factory --host 127.0.0.1 --port 8011
```

최초 수집이 이미 성공했다면 `sync --kind quick`을 사용할 수 있습니다. 처음 quick은 full로 승격됩니다. .env 수정 후에는 CLI를 다시 실행하거나 Uvicorn을 재시작합니다.

형식은 KEY=VALUE이며 `SET`, `export`, 변수 치환을 사용하지 않습니다. 공백이 있는 값은 따옴표로 감쌀 수 있습니다. 주석은 별도 줄에 씁니다. 인라인 #은 값의 일부로 보존됩니다. UTF-8/BOM을 지원합니다.

실제 .env는 Git에서 제외됩니다. 관리자 키는 백엔드 전용이며 VITE 변수나 프런트엔드 폴더에 넣지 않습니다. .env는 평문 파일이므로 서버 계정의 파일 접근 권한으로 관리합니다. .env와 실제 CSV/DB는 반입 패키지나 공개 저장소에 포함하지 않습니다.

검증: 기존 32개에 .env 우선순위·UTF-8/BOM·경로·CLI/정적 서빙 통합 테스트 3개를 추가했습니다. 실제 폐쇄망 OpenWebUI 권한은 별도 검증입니다.
