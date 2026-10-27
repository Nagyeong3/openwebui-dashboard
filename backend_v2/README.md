2026-10-27: LiteLLM 토큰 수집·캐시·화면·개요 연동 신규 구현. [설정/폐쇄망 검수 절차](../docs/TOKEN_USAGE_OFFLINE.md)를 참고하세요. 실제 LiteLLM 연동 검수는 현장에서 필요합니다.

2026-10-27: API 개요 화면 및 사용자 메뉴 통합 구현. [개요 업데이트/폐쇄망 반입 절차](../docs/OVERVIEW_OFFLINE.md)를 참고하세요. 토큰·비용·카테고리는 연동 준비 상태입니다.

2026-10-26 설정 변경: 프로젝트 루트 `.env`를 자동 로드합니다. 기존 4d22291에서 최신 backend_v2로 업데이트한 뒤 [ENV_SETUP.md](../docs/ENV_SETUP.md)를 따르세요. 추가 패키지 설치와 프런트 재빌드는 필요 없습니다. 우선순위: 터미널/서비스 환경변수 → .env → 기본값.

# OpenWebUI API 기반 분석 백엔드 v2

상태: **2026-10-23, 계획 1~5단계 구현**. 실제 폐쇄망 서버 검증 전입니다. 기존 Streamlit/운영 FastAPI와 독립된 패키지입니다. Python 3.10 이상 대상, 현재 Python 3.12에서 검증했습니다.

이 단계는 API 수집·분석 캐시·CSV 매핑·사용자/팀/팀장 조회 API까지입니다. React는 API 모드에서 이 백엔드 사용자 조회에 연결되며 기본 모드는 합성 데모입니다. LiteLLM 수집, 질문 분류, 운영 화면의 실행 버튼은 다음 단계입니다. 5단계 설치/검수는 `docs/PHASE5_OFFLINE.md`를 참고하세요.

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

## Conda 26.7.1 설치 및 폐쇄망 배포 (Windows x64)

기본 환경 관리 방식을 Conda로 변경했습니다. Conda 26.7.1은 환경 관리자 버전이며 앱의 Python은 3.12입니다. 기존 venv는 삭제하지 않아도 됩니다. 코드/requirements는 동일합니다.

공식 고정 설치 파일: [Miniconda3-py312_26.7.1-0-Windows-x86_64.exe](https://repo.anaconda.com/miniconda/Miniconda3-py312_26.7.1-0-Windows-x86_64.exe), 129,410,328 bytes.

SHA256: `741c068509955d6fe0171613e3cdb76e12e74c87ed8236672197f01f227cd022`.

설치 EXE는 인터넷 없이 Miniconda base를 설치할 수 있습니다. **EXE만으로 앱 의존성까지 설치되지는 않습니다.** 회사에서 승인한 채널/이용 조건을 적용합니다. 프로젝트 Git에는 바이너리를 넣지 않습니다.

### 1. 인터넷 Windows PC에서 환경 만들기

운영 서버와 같은 Windows x64 PC에서 진행합니다. Mac/Linux에서 만든 환경은 Windows로 옮길 수 없습니다. 공식 EXE를 실행해 Just Me, 기본 경로 `%USERPROFILE%\miniconda3`로 설치하고, Miniconda Prompt에서 `conda --version`이 `26.7.1`인지 확인합니다. 자동으로 최신 버전으로 업데이트하지 않습니다.

저장소 루트에서 PowerShell:

```powershell
Get-FileHash .\Miniconda3-py312_26.7.1-0-Windows-x86_64.exe -Algorithm SHA256
.\backend_v2\scripts\Prepare-CondaBundle.ps1
```

설치 위치가 다르면 `-CondaExe "C:\tools\miniconda3\Scripts\conda.exe"`를 전달합니다. 스크립트는 conda 버전 확인 → Python 3.12 환경 생성 → 고정 의존성/conda-pack 0.9.2 설치 → 테스트 → ZIP 생성을 수행합니다. 기존 빌드 환경/출력 폴더는 덮어쓰지 않습니다. 재빌드 시 새 `-BuildPrefix`, `-OutputDirectory`를 지정합니다. 실행 정책이 막히면 사내 승인 절차를 적용합니다.

출력 `conda-bundle-v2`에는 환경 ZIP, `backend_v2` 소스, 실제 Conda/pip 버전 목록, 체크섬이 들어갑니다. 이 폴더 전체와 Miniconda EXE를 개발/운영 서버로 반입합니다. 토큰/CSV/DB는 포함하지 않습니다.

수동 개발 환경만 만들 때는:

```powershell
conda env create -f backend_v2/environment.yml
conda activate oui-dashboard-v2
python -m pip install -r backend_v2/requirements-test.txt -r backend_v2/requirements-pack.txt
python -m unittest discover -s backend_v2/tests -v
```

`environment.yml`은 재구성 명세이지 오프라인 설치 파일이 아닙니다. 이 명령은 인터넷 또는 별도 패키지 저장소가 필요합니다.

### 이미 oui-dashboard-v2 환경을 만든 경우

환경을 다시 만들지 않고 활성화된 환경을 압축합니다. Miniconda Prompt에서:

```bat
cd /d C:\project\oui-dashboard
git pull --ff-only origin feat/openwebui-api-backend
conda activate oui-dashboard-v2
python -m pip install -r backend_v2\requirements-test.txt -r backend_v2\requirements-pack.txt
python -m unittest discover -s backend_v2\tests -v
powershell -NoProfile -File backend_v2\scripts\Pack-CurrentCondaEnvironment.ps1
```

기본 출력은 `conda-bundle-v2-r1`입니다. 기존 출력이 있으면 새 `-OutputDirectory conda-bundle-v2-r2`를 지정합니다. 환경은 재생성하지 않습니다. 아래 설치 명령의 BundleDirectory도 실제 출력 폴더로 바꿉니다.

Windows 테스트의 `unrelated.sqlite3` 삭제 오류(WinError 32)는 테스트가 `sqlite3.connect` 연결을 명시적으로 닫지 않아 발생했습니다. `contextlib.closing`으로 수정했으며, 테스트를 생략하거나 임시 파일 강제 삭제로 우회하지 않습니다. 앱 캐시의 연결 관리는 별도 context manager로 이미 명시적으로 닫습니다.

### 2. 폐쇄망 개발/운영 서버에 설치

각 서버에서 EXE로 Miniconda를 설치합니다. 동일 버전이 이미 있다면 재설치할 필요 없습니다. 반입 폴더의 상위 폴더에서:

```powershell
.\conda-bundle-v2\backend_v2\scripts\Install-CondaBundle.ps1 -BundleDirectory .\conda-bundle-v2 -EnvironmentPrefix "$env:USERPROFILE\miniconda3\envs\oui-dashboard-v2"
```

이 과정은 네트워크 접속 없이 ZIP 해제 → `conda-unpack` 경로 보정 → 테스트를 수행합니다. 기존 환경을 덮어쓰지 않습니다. 업데이트 시 `oui-dashboard-v2-r2`처럼 새 경로에 설치 후 실행 경로를 전환합니다.

Miniconda Prompt를 열어:

```bat
conda activate "%USERPROFILE%\miniconda3\envs\oui-dashboard-v2"
cd /d C:\path-to\conda-bundle-v2
python --version
python -m pip check
python -m unittest discover -s backend_v2\tests -v
```

이후 PowerShell에서도 환경을 활성화한 상태에서 아래 CLI/API 명령을 실행합니다. PowerShell 활성화를 설정하지 않았다면 Miniconda Prompt에서 `powershell -NoProfile`을 열면 환경 PATH를 상속합니다.

**환경 폴더 자체는 단순 복사하지 않습니다.** 인터넷 PC에서 만든 원본 ZIP을 개발/운영 각각에 풀고 각각 `conda-unpack`합니다. 경로 보정 후 환경은 다시 이동하지 않습니다. 오프라인 개발 서버에서 의존성을 변경했다면 원본 ZIP에 자동 반영되지 않으므로 새 번들을 빌드해야 합니다. 소스만 변경했으면 소스만 별도 배포할 수 있습니다.

공식 근거: https://conda.github.io/conda-pack/ . 사용자는 2026-10-23 Windows 수동 환경 이전 및 테스트 완료를 보고했습니다. PowerShell 자동 스크립트는 실행 정책에 막혔으며 현장 자동 실행은 미검증입니다. Windows용 환경 ZIP은 같은 OS의 인터넷 PC에서 생성합니다.

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

위 SET/PowerShell 설정은 선택 사항입니다. 기본적으로 프로젝트 루트 `.env`를 읽으며, 실제 터미널 환경변수가 더 높은 우선순위를 가집니다. `.env.example`을 루트 `.env`로 복사해 편집할 수 있습니다. 토큰을 프런트엔드 변수나 Git에 넣지 않습니다.

CSV는 실제 조직 CSV 경로를 지정합니다. 아직 없으면 `ORG_USER_CSV_PATH`를 설정하지 않아도 사용자 조회는 가능하며 조직이 기타/미매칭으로 표시됩니다. 잘못된 CSV 경로/헤더는 422로 드러나고, 전부 미매칭인 것처럼 처리하지 않습니다.

지원 헤더: `실` 또는 `본부` / `팀` / `직급` / `이름` 또는 `성명` 또는 `사용자명`. 영문 division/team/position/name 지원. 선택 사용자 ID는 `사용자 ID`, `사용자ID`, `user_id`, `id`입니다. UTF-8(BOM)/CP949 지원.

ID 우선 매핑, 이름은 양쪽에서 유일한 경우에만 매핑. 다른 명시적 ID가 있는 CSV 행을 이름으로 재사용하지 않습니다. CSV 변경은 다음 조회에 재반영되며 API 재동기화가 필요 없습니다.

## 최초 전체 수집

```powershell
python -m backend_v2.cli init
python -m backend_v2.cli sync --kind full
python -m backend_v2.cli status
```

성공 기준: `ok: true`, `users`가 OpenWebUI 관리자 전체 사용자 수와 일치, status의 `ready: true`, 마지막 run의 `status: success`.

초기 전체 수집은 사용자별 전체 메시지를 100건씩 읽으므로 데이터량에 따라 오래 걸립니다. 진행 상황은 다른 PowerShell에서 **같은 DASHBOARD_CACHE_PATH**를 설정한 뒤 `status` 명령으로 확인합니다. `users_done`, `messages_seen`을 제공합니다.

`ENABLE_ADMIN_ANALYTICS`가 활성화되어 있고 관리자 토큰이 이 API 경로를 조회할 권한이 있어야 합니다. 여기서는 기본 설정을 변경하지 않습니다. 401/403은 재시도하지 않으며, 429/일부 5xx/연결 실패는 제한적으로 재시도합니다. 관리자 토큰이나 응답 본문은 오류에 포함하지 않습니다.

## 조회 서버 실행

```powershell
python -m uvicorn backend_v2.app:create_app --factory --host 127.0.0.1 --port 8011
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
python -m backend_v2.cli sync --kind quick
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

로컬 검증: Python 3.12에서 합성 데이터 기반 자동 테스트 32개 통과, 의존성 검사 통과. 실제 OpenWebUI 서버와 Windows 실행은 아직 검증하지 않았습니다. GitHub Actions에는 Windows/Linux 및 Python 3.10/3.12 테스트 작업을 추가했습니다.

1. 8011 API와 실제 OpenWebUI 사용자 수/질문 수 대조.
2. 연결된 React 사용자 분석의 필터/페이징/0건 팀장을 폐쇄망에서 검수. API 모드는 새 users 계약을 사용합니다.
3. 개요/토큰 계약을 분리하고 LiteLLM 데이터 원천/미수집 상태 표현 연결.
4. 실제 질문 분류기 연결(필요한 본문은 분류 시점에만 API로 읽고 캐시 정책 별도 결정).
5. 운영 작업 실행/polling/자동 예약 연결.

## 5단계 화면 연결 (2026-10-23)

- `GET /api/dashboard/v2/users/export`: users와 같은 필터, 전체 CSV. page/pageSize는 적용하지 않으며 같은 대시보드 인증 적용.
- `DASHBOARD_FRONTEND_DIR`에 API 모드로 빌드한 dist 경로를 지정하면 FastAPI가 같은 origin의 루트에서 화면을 제공합니다. `/api` 경로는 그대로 유지합니다.
- 기존 Conda 환경의 의존성 변경은 없습니다. 새 backend_v2 소스와 frontend-v2/dist를 반입하면 됩니다.
- 압축 스크립트의 잘못된 `python -m conda_pack` 호출을 `conda_pack.pack(...)` API 호출로 수정했습니다. PowerShell 정책으로 막히면 기존에 성공한 수동 conda-pack 절차를 사용합니다.

API 최초 full 수집, 이후 quick 업데이트, LiteLLM과의 관계 및 향후 운영 화면 구현 기준은 [동기화 사용법](../docs/SYNC_USAGE.md)을 참고하세요.
