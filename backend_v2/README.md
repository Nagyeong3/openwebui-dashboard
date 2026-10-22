# OpenWebUI API 기반 분석 백엔드 v2

상태: **2026-10-22 신규 구현, 계획 1~4단계**. 실제 폐쇄망 서버 검증 전입니다. 기존 Streamlit/운영 FastAPI와 독립된 패키지입니다. Python 3.10 이상 대상, 현재 Python 3.12에서 검증했습니다.

이 단계는 API 수집·분석 캐시·CSV 매핑·사용자/팀/팀장 조회 API까지입니다. 기존 React 데모는 계속 합성 데이터를 표시합니다. 프런트엔드 연결, LiteLLM 수집, 질문 분류, 운영 화면의 실행 버튼은 다음 단계입니다.

## 데이터 원천과 확정 기준

- 사용자 명부: OpenWebUI `GET /api/v1/users/all`의 전체 사용자. 응답의 `total`과 배열 길이를 대조합니다.
- 활동: `GET /api/v1/analytics/messages?user_id=...&skip=...&limit=...`. 페이지 크기는 최대 100.
- 확인 기준: 공식 `v0.12.3`, commit `91ea4e3421d1d8069f13d4a463fcb5986d94ea60`.
- 이 버전의 user_id 메시지 조회는 날짜 인자를 사용하지 않으므로 수집기가 시간순서와 경계를 검증합니다.
- 질문: 저장된 모든 `role=user` 메시지의 고유 ID. 분기/수정으로 별도 ID가 남으면 각각 셉니다. 현재 대화 경로만 세는 정책은 구현하지 않았습니다. 과거 DB 파서와 대조할 때 이 차이를 확인합니다.
- 채팅방: 기간 내 해당 사용자 질문의 `chat_id` distinct. 모델별/일별 채팅 수를 단순히 합산하지 않습니다.
- 파일 첨부 질문: 사용자 메시지에 비어 있지 않은 `files`가 있는 질문 수. 파일 개수나 전체 파일 저장소 크기가 아닙니다.
- 활성 사용자: 기간 내 질문 1건 이상. 마지막 사용은 기간 내 마지막 사용자 질문 시각.
- 주 사용 모델: 기간 내 assistant 메시지에 나타난 모델 중 가장 많이 나타난 모델. 사용자 질문에 모델을 임의로 귀속하지 않습니다.
- 전체 API 사용자 명부를 왼쪽 집합으로 사용합니다. 0건 사용자/팀장은 기간과 무관하게 남고, CSV-only 사용자는 추가하지 않습니다.
- 기간: Asia/Seoul 시작일 00:00 이상, 종료일 다음날 00:00 미만.
- 토큰·비용·카테고리는 `not-connected`. 이 단계의 응답에서 가짜 0을 만들지 않습니다.

## 설치 (인터넷 개발 PC)

저장소 루트에서 실행합니다. 기존 환경과 충돌하지 않게 전용 가상환경을 만듭니다.

```powershell
python --version
python -m venv .venv-backend-v2
.\.venv-backend-v2\Scripts\python.exe -m pip install -r backend_v2\requirements-test.txt
.\.venv-backend-v2\Scripts\python.exe -m unittest discover -s backend_v2\tests -v
```

Linux에서는 실행 파일 경로만 `.venv-backend-v2/bin/python`으로 바꾸면 됩니다.

## 폐쇄망 반입 준비

운영 테스트 PC와 같은 Windows/Python 버전의 인터넷 PC에서:

```powershell
python -m pip download --only-binary=:all: -r backend_v2\requirements-test.txt -d wheelhouse-v2
```

반입 대상: `backend_v2` 폴더 전체와 `wheelhouse-v2` 폴더. `node_modules`나 OpenWebUI DB는 필요 없습니다. Python ABI가 다른 PC에서 받은 pydantic-core wheel은 재사용하지 마세요. 운영 설치만 할 때도 테스트 의존성을 함께 반입하면 폐쇄망에서 검증할 수 있습니다.

폐쇄망 테스트 폴더 루트에서:

```powershell
python -m venv .venv-backend-v2
.\.venv-backend-v2\Scripts\python.exe -m pip install --no-index --find-links .\wheelhouse-v2 -r .\backend_v2\requirements-test.txt
.\.venv-backend-v2\Scripts\python.exe -m unittest discover -s backend_v2\tests -v
```

## 환경변수 설정 (PowerShell)

아래 URL은 같은 컴퓨터에서 OpenWebUI 포트가 8080일 때의 예시입니다. 다른 서버이면 폐쇄망의 실제 주소로 바꿉니다.

```powershell
$env:OPENWEBUI_URL = "http://127.0.0.1:8080"
$secureToken = Read-Host "OpenWebUI 관리자 API 토큰" -AsSecureString
$env:OPENWEBUI_API_TOKEN = [System.Net.NetworkCredential]::new("", $secureToken).Password
$env:DASHBOARD_CACHE_PATH = ".\data\dashboard-v2.sqlite3"
$env:ORG_USER_CSV_PATH = ".\data\users.csv"
$env:SYNC_OVERLAP_DAYS = "7"
```

토큰은 이 로컬 환경변수에서만 읽습니다. `.env.example`은 설명용이며 CLI가 자동으로 로드하지 않습니다. 토큰을 프런트엔드 변수나 Git에 넣지 않습니다.

CSV는 실제 조직 CSV 경로를 지정합니다. 아직 없으면 `ORG_USER_CSV_PATH`를 설정하지 않아도 사용자 조회는 가능하며 조직이 기타/미매칭으로 표시됩니다. 잘못된 CSV 경로/헤더는 422로 드러나고, 전부 미매칭인 것처럼 처리하지 않습니다.

지원 헤더: `실` 또는 `본부` / `팀` / `직급` / `이름` 또는 `성명` 또는 `사용자명`. 영문 division/team/position/name 지원. 선택 사용자 ID는 `사용자 ID`, `사용자ID`, `user_id`, `id`입니다. UTF-8(BOM)/CP949 지원.

ID 우선 매핑, 이름은 양쪽에서 유일한 경우에만 매핑. 다른 명시적 ID가 있는 CSV 행을 이름으로 재사용하지 않습니다. CSV 변경은 다음 조회에 재반영되며 API 재동기화가 필요 없습니다.

## 최초 전체 수집

```powershell
.\.venv-backend-v2\Scripts\python.exe -m backend_v2.cli init
.\.venv-backend-v2\Scripts\python.exe -m backend_v2.cli sync --kind full
.\.venv-backend-v2\Scripts\python.exe -m backend_v2.cli status
```

성공 기준: `ok: true`, `users`가 OpenWebUI 관리자 전체 사용자 수와 일치, status의 `ready: true`, 마지막 run의 `status: success`.

초기 전체 수집은 사용자별 전체 메시지를 100건씩 읽으므로 데이터량에 따라 오래 걸립니다. 진행 상황은 다른 PowerShell에서 **같은 DASHBOARD_CACHE_PATH**를 설정한 뒤 `status` 명령으로 확인합니다. `users_done`, `messages_seen`을 제공합니다.

`ENABLE_ADMIN_ANALYTICS`가 활성화되어 있고 관리자 토큰이 이 API 경로를 조회할 권한이 있어야 합니다. 여기서는 기본 설정을 변경하지 않습니다. 401/403은 재시도하지 않으며, 429/일부 5xx/연결 실패는 제한적으로 재시도합니다. 관리자 토큰이나 응답 본문은 오류에 포함하지 않습니다.

## 조회 서버 실행

```powershell
.\.venv-backend-v2\Scripts\python.exe -m uvicorn backend_v2.app:create_app --factory --host 127.0.0.1 --port 8011
```

기존 8010 백엔드는 그대로 두고 8011에서 검증합니다. 이 서버는 현재 브라우저 UI를 제공하지 않습니다.

다른 PowerShell에서:

```powershell
Invoke-RestMethod "http://127.0.0.1:8011/api/dashboard/v2/health"
Invoke-RestMethod "http://127.0.0.1:8011/api/dashboard/v2/sync/status"

$result = Invoke-RestMethod "http://127.0.0.1:8011/api/dashboard/v2/users?range=all&pageSize=1000"
$result.summary
$result.detail.records | Select-Object name,team,position,questions,chats

$leaders = Invoke-RestMethod "http://127.0.0.1:8011/api/dashboard/v2/users?range=all&view=leader&order=asc&pageSize=1000"
$leaders.detail.records | Select-Object name,team,position,questions

$teams = Invoke-RestMethod "http://127.0.0.1:8011/api/dashboard/v2/users?range=all&view=team&pageSize=1000"
$teams.detail.records
```

기간 지정 예: `?start=2026-10-01&end=2026-10-21&view=user`. API 날짜는 `YYYY-MM-DD` 형식이며 한국 시간 기준입니다.

처음 수집이 실패했다면 users API는 **503**이며 0건으로 표시하지 않습니다. 과거 성공본이 있고 최신 수집에 실패하면 성공본을 제공하고 `dataState.stale=true`로 알립니다.

`DASHBOARD_API_TOKEN`을 설정한 경우 모든 조회 API에 `Authorization: Bearer ...`가 필요합니다. 원격 접근은 기존 인증/reverse proxy에 연결하는 후속 배포 단계에서 설정합니다. 로컬 검증은 위의 loopback 주소를 사용합니다.

## 빠른 동기화와 정기 재대조

```powershell
.\.venv-backend-v2\Scripts\python.exe -m backend_v2.cli sync --kind quick
```

- 최초 quick은 full로 승격.
- 마지막 성공 시작 시각에서 overlap 일수를 뺀 구간부터 재조회. 장기간 중단되어도 최근 7일만 가져와 누락시키지 않습니다.
- 최근 구간의 삭제/수정 반영 + 전체 사용자 명부 갱신. 삭제된 사용자의 캐시 메시지도 제거.
- 새로 발견한 사용자는 quick에서도 과거 메시지 전체를 수집합니다.
- 더 오래된 수정/삭제는 `full` 재대조 때 반영됩니다. 운영 주기(예: 일별 quick, 주별 full)는 실서버 소요시간을 확인한 후 결정합니다. 자동 예약은 이번 단계에 포함하지 않습니다.
- 매 수집은 임시 테이블에 저장하고 모든 요청이 성공한 뒤 한 번에 공개합니다. 실패 시 마지막 정상본 보존.
- SQLite lease로 동시 수집 방지. 프로세스가 강제 종료되면 기본 약 10분 후 lease가 만료되어 재시도 가능.
- upstream API는 트랜잭션 스냅샷/고정 cursor를 제공하지 않습니다. 수집 도중 메시지가 변경되면 정기 full 재대조가 필요하며, 탐지된 중복 페이지나 사용자 명부 변동은 실패시켜 재시도합니다.
- `MAX_PAGES`에 도달하면 잘린 성공으로 처리하지 않습니다. 기본 한도는 사용자당 10,000페이지.
- 다른 OpenWebUI 인스턴스로 URL을 변경하면 캐시 혼합을 막기 위해 새 캐시 경로가 필요합니다.
- `DASHBOARD_CACHE_PATH`에 기존 OpenWebUI DB를 지정하지 않습니다. 다른 SQLite 파일은 식별자를 검사하여 수정을 거부합니다.

## API 계약

`GET /api/dashboard/v2/users`의 top-level: schemaVersion / source / period / updatedAt / dataState / filters / selected / summary / daily / detail.

- 필터: division, team, position, matchStatus, view=user|team|leader, search.
- 페이징: page 기본 1, pageSize 기본 50/최대1000, detail.total은 필터 후 전체 행 수.
- 정렬: order=desc|asc. 질문 수 → 이름 → ID. 전체 순위 번호를 반환.
- `summary`는 페이지를 자르기 전 전체 선택 사용자에 대한 수치.
- `detail.records`는 사용자일 때 id/name/email/role/division/team/position/mapping/source/questions/chats/attachments/lastUsedAt/primaryModel/rank.
- `view=team`일 때 division/team/users/activeUsers/questions/attachmentQuestions/chats.
- `daily`는 선택 사용자의 질문 수 합계. 날짜 필터 범위 내 빈 날짜는 0으로 채움.
- 개인정보가 들어갈 수 있는 API 응답은 로컬 검증만 하고 공개 저장소에 넣지 않습니다.

## 후속 단계

로컬 검증: Python 3.12에서 합성 데이터 기반 자동 테스트 30개 통과, 의존성 검사 통과. 실제 OpenWebUI 서버와 Windows 실행은 아직 검증하지 않았습니다. GitHub Actions에는 Windows/Linux 및 Python 3.10/3.12 테스트 작업을 추가했습니다.

1. 8011 API와 실제 OpenWebUI 사용자 수/질문 수 대조.
2. React 사용자 분석을 이 API의 서버 페이징에 연결. 현재 snapshot-only decoder는 아직 변경하지 않았습니다.
3. 개요/토큰 계약을 분리하고 LiteLLM 데이터 원천/미수집 상태 표현 연결.
4. 실제 질문 분류기 연결(필요한 본문은 분류 시점에만 API로 읽고 캐시 정책 별도 결정).
5. 운영 작업 실행/polling/자동 예약 연결.
