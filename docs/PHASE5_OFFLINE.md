# 5단계: API 사용자 분석 화면 폐쇄망 반입

2026-10-23 신규 구현. 개발 프로젝트는 `D:\project\oui-dashboard-v2`, 이미 반입한 Conda 환경은 `C:\project\oui-env-v2` 기준입니다. 실제 배포 서버 설정은 현장에서 확인합니다.

## 이번 단계 범위

- 사용자 / 팀 / 팀장 조회, 종속 조직 필터, 기간, 검색, 질문 수 정렬, 서버 페이징.
- 사용량 0인 OpenWebUI 등록 사용자와 팀장 전체 순위. CSV-only 사용자는 추가하지 않음.
- 사용자 상세, 라이트/다크, 모션 감소, 차트 툴팁/기간 확대.
- 전체 필터 결과 CSV 내보내기. 페이지와 무관하며 1,000명 이상도 포함.
- 최초 미수집 / 조회 실패 / 마지막 성공 데이터 안내. 토큰·비용·카테고리는 미연결 상태.
- FastAPI 8011에서 화면과 API를 함께 제공. 브라우저에서 OpenWebUI 관리자 키를 사용하지 않음.

## 1. 인터넷 PC 준비

개발 브랜치: `feat/openwebui-api-backend`.

```bat
cd /d C:\project\oui-dashboard
git pull --ff-only origin feat/openwebui-api-backend
node --version
cd frontend-v2
npm ci
npm test
npm run build:api
```

Node 22.12 이상 필요. `npm run build:api`는 API 연결 화면, `npm run build`는 데모입니다. `.env.api`는 비밀키 없이 저장소에 포함됩니다. 기존 VITE_DATA_MODE 환경변수로 덮어쓰지 않았는지 확인합니다.

이미 생성된 5단계 배포 ZIP을 받았다면 위 빌드는 생략할 수 있습니다. 반입 대상은 최신 `backend_v2` 폴더 전체와 API 모드로 생성한 `frontend-v2\dist` 전체입니다. 의존성은 기존 Conda 환경 그대로이며 이번 변경으로 새 Python 패키지는 추가되지 않았습니다. 외부 CDN이나 운영 Node는 필요 없습니다.

## 2. 폐쇄망 파일 배치

실행 중인 새 백엔드가 있다면 종료하고 기존 소스를 백업합니다. 데이터 폴더와 CSV는 보존합니다. 전달 ZIP을 별도 폴더에 풀어 내용을 확인한 뒤 다음 구조로 배치합니다.

| 항목 | 위치 |
| --- | --- |
| 백엔드 | `D:\project\oui-dashboard-v2\backend_v2` |
| 빌드 화면 | `D:\project\oui-dashboard-v2\frontend-v2\dist\index.html` 및 assets 전체 |
| 조직 CSV | `D:\project\oui-dashboard-v2\data\users.csv` (현장 보유 파일) |
| 분석 캐시 | `D:\project\oui-dashboard-v2\data\dashboard-v2.sqlite3` |
| Conda 환경 | `C:\project\oui-env-v2` (압축 해제/경로 보정 완료 경로 유지) |

`dist`의 해시 이름 assets를 골라 복사하지 말고 폴더 전체를 갱신합니다. 이전 assets와 혼합되면 새 index와 맞지 않을 수 있습니다. 기존 운영 대시보드와 별도 프로젝트/포트를 사용합니다.

## 3. 백엔드 테스트 및 설정

Miniconda Prompt (CMD 문법):

```bat
conda activate C:\project\oui-env-v2
cd /d D:\project\oui-dashboard-v2
python -m pip check
python -m unittest discover -s backend_v2\tests -v

set DASHBOARD_CACHE_PATH=D:\project\oui-dashboard-v2\data\dashboard-v2.sqlite3
set DASHBOARD_FRONTEND_DIR=D:\project\oui-dashboard-v2\frontend-v2\dist
```

현재 자동 테스트는 32개입니다. 서버에 있는 30개 테스트 소스가 아닌 최신 backend_v2를 가져왔는지 확인합니다.

OpenWebUI와 동일 PC이고 포트가 8080인 경우만 아래 URL을 그대로 사용합니다. 다른 서버라면 실제 폐쇄망 주소로 변경합니다.

```bat
set OPENWEBUI_URL=http://127.0.0.1:8080
set OPENWEBUI_API_TOKEN=
set /p OPENWEBUI_API_TOKEN=OpenWebUI admin API token:
```

토큰은 로컬 프롬프트에 입력합니다. CMD에서는 입력 글자가 보이므로 화면 공유 중에는 입력하지 않습니다. 채팅/스크린샷/소스/Git에 남기지 않습니다. 이 값은 브라우저용 토큰이 아닙니다. 같은 터미널에서 수집과 서버를 실행해야 설정이 유지됩니다. `.env.example`은 자동 로드하지 않습니다.

조직 CSV를 배치했다면:

```bat
set ORG_USER_CSV_PATH=D:\project\oui-dashboard-v2\data\users.csv
```

CSV가 없으면 해당 변수를 설정하지 않습니다. 사용자 조회는 가능하나 조직은 기타/미매칭이고 팀장 식별도 조직 매핑이 필요합니다.

## 4. 최초 수집 및 화면 실행

```bat
python -m backend_v2.cli sync --kind full
python -m backend_v2.cli status
```

성공 조건: `ok: true`, `ready: true`, 마지막 run `status: success`. 관리자 권한과 OpenWebUI 관리자 analytics API 활성화가 필요합니다. 실패 시 실제 마지막 오류를 확인하며 0명으로 간주하지 않습니다.

```bat
python -m uvicorn backend_v2.app:create_app --factory --host 127.0.0.1 --port 8011
```

같은 PC 브라우저에서 `http://127.0.0.1:8011/`로 접속합니다. `/api/dashboard/v2/health`와 `/api/dashboard/v2/users?range=all`도 같은 포트에서 확인할 수 있습니다. 원격 접근/외부 공개는 이 로컬 검증 이후 인증·프록시를 별도로 설정합니다.

대시보드 자체 인증을 사용할 때는 실행 전에 `DASHBOARD_API_TOKEN`을 별도로 설정하고 화면 우측 상단 설정에 동일 값을 입력합니다. OpenWebUI 관리자 토큰과 다른 키를 사용합니다. 입력한 대시보드 토큰은 메모리에만 유지되어 브라우저 새로고침 시 재입력합니다.

## 5. 현장 검수

1. 전체 기간 전체 사용자 수를 OpenWebUI 관리자 전체 사용자 수와 대조.
2. 특정 팀/직급 필터 후 실제 사용자가 올바르게 매핑되는지 확인. 실 변경 시 팀·직급, 팀 변경 시 직급이 초기화되는지 확인.
3. 팀장 → 전체 순위 → 질문 적은 순: 사용량 0인 등록 팀장이 나타나는지 확인. Top 10은 내림차순 최대 10행.
4. 페이지 이동해도 상단 요약과 일별 추이는 필터 전체 집계를 유지하는지 확인.
5. 전체 CSV의 행 수가 `detail.total`과 일치하는지 확인. 현재 페이지에 제한되지 않음.
6. CSV에만 있는 직원은 사용자/팀장 결과에 추가되지 않는지 확인.
7. 다크 테마, 상세 패널, 검색, 새로 조회, 잘못된 기간 안내 확인.
8. 수집 전 새 캐시에서는 503/미수집 안내, 과거 성공 후 수집 실패 상태에서는 마지막 성공본 안내 확인. 기존 정상 캐시를 삭제해 시험하지 않습니다.

질문 기준은 저장된 전체 role=user 메시지 ID입니다. 수정·분기 메시지도 별도 ID이면 셉니다. 과거 DB 파서와 차이가 있으면 이 기준부터 대조합니다.

## 검증 범위 및 후속

로컬 Python 테스트 32개, 프런트 테스트 16개, TypeScript/API 빌드 검증. 브라우저 계약 QA는 실제 집계 코드로 생성한 합성 응답으로 사용자 목록 및 0건 팀장 상세를 확인했습니다. 프리뷰와 Python 서버의 환경 격리로 실제 HTTP 연결을 브라우저에서 끝까지 검증하지는 못했습니다. Windows/폐쇄망 실제 OpenWebUI 응답·건수 대조가 최종 검증입니다.

현재 실제 화면은 사용자 분석만 제공합니다. 개요, LiteLLM 토큰·비용, 질문 분류, 운영 작업 실행/자동 예약은 후속 단계입니다.
