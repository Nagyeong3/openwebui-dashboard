2026-10-28 후속: 일시 중단/계속하기/중단·단계 선택·실패 항목 재시도·분류 직접 수정·인증 화면 변경은 [CONTROLS_AND_REVIEW_OFFLINE.md](CONTROLS_AND_REVIEW_OFFLINE.md)를 우선 참고하세요.

# 운영 업데이트 페이지 — 반입과 사용법

2026-10-28 신규 구현. 기존 이미지 시안만 있던 dd13a0a와 달리 이번 릴리스에는 운영 메뉴/실제 페이지와 통합 실행 API가 포함됩니다. 실제 폐쇄망 모델·브라우저 동작은 반입 후 검수 필요합니다.

## 반입

1. 실행 중인 수집/분류가 끝난 뒤 Uvicorn을 Ctrl+C로 종료합니다.
2. 기존 `backend_v2`와 `frontend_v2/dist`를 백업하고 ZIP의 폴더 전체로 교체합니다. 프런트만 바꾸면 새 API가 없어 실패합니다. 기존 dist/assets와 새 assets를 혼합하지 않습니다.
3. `.env`, `data`, DB, users.csv, question_categories.csv, 기타 실제 CSV와 Conda 환경은 보존합니다. `.env.example`로 실제 `.env`를 덮어쓰지 않습니다.
4. 새 패키지 설치나 기존 full 재수집은 필요하지 않습니다. 기존 source 설정을 사용합니다.

CMD:

```bat
conda activate D:\project\oui-env-v2
cd /d D:\project\oui-dashboard-v2
python -m uvicorn backend_v2.app:create_app --factory --host 127.0.0.1 --port 8011
```

브라우저 `http://localhost:8011/?screen=operations`를 열고 **Ctrl+F5**. 사이드바 운영 업데이트 메뉴가 활성화되어 있어야 합니다. 여전히 준비 중이면 이전 dist를 보고 있는 것이므로 프런트 교체 위치와 DASHBOARD_FRONTEND_DIR을 확인하세요. 조회/실행 API가 404면 백엔드도 새 폴더로 교체하고 해당 경로에서 재시작했는지 확인합니다.

## 평소에는 최근 변경분 업데이트

한 번 클릭하면 서버에서 순서대로 진행합니다.

1. **OpenWebUI quick**: 마지막 성공한 수집 시작 시각에서 SYNC_OVERLAP_DAYS(기본7일)를 뺀 시점 이후 구간. 명부 전체는 매번 API로 확인하며, 기존 사용자의 메시지는 최신 페이지부터 읽어 경계에서 중단합니다. 새 사용자는 이전 이력도 최초 수집합니다.
2. **LiteLLM quick**: 독립적인 마지막 토큰 수집 성공 시작 시각에서 LITELLM_SYNC_LOOKBACK_HOURS(기본24시간)를 뺀 시점부터 현재까지. 키 별칭 필터와 ID upsert를 그대로 사용합니다.
3. **카테고리 pending**: 현재 snapshot에서 결과 없는 질문을 끝까지 자동 분류합니다. 200개는 내부 구간, 모델 요청은 기본 5개 배치입니다. 이미 유효한 결과는 재호출하지 않습니다. CSV/모델/분류 버전 변경 시 처리 대상이 늘 수 있습니다.

**월 1회 실행도 한 달 전체 변경분을 조회**합니다. 24시간은 최근 하루만 수집한다는 뜻이 아니라 중복 여유분입니다. 예: 마지막 성공 9월28일 → 다음 실행 10월28일이면, 기본 토큰 조회는 9월27일~10월28일입니다. 지연 로그를 더 넓게 재확인하려면 `.env`에서 LITELLM_SYNC_LOOKBACK_HOURS=168로 조정 후 재시작할 수 있습니다. 이 경우 마지막 성공 시점보다 7일 전부터 조회합니다. 자동 월간 예약은 구현하지 않았습니다.

최초 수집이 없는 원천의 quick은 기존 수집기 규칙대로 full로 승격됩니다. LiteLLM 최초 시작일/별칭/조회 키는 기존 설정이 필요합니다. 카테고리에는 별도의 추론 키/모델/활성 기타 정의가 필요합니다.

## 진행 상태와 실패

- OpenWebUI: 처리 사용자/전체 사용자, 조회 메시지 수. 완료 후 신규·수정·삭제 질문 수를 비교해 표시합니다.
- 토큰: 조회 수, 별칭 일치 저장 수, 제외 수. 중복 조회 구간을 포함하므로 저장 수를 신규 로그 수라고 표시하지 않습니다.
- 분류: 처리/대상 수, 모델 요청 배치 수. 총량을 아는 분류만 실제 퍼센트 진행률, 전체 조회량을 모르는 수집 단계는 활동 표시.
- 최근 실행 내역과 단계 결과는 별도 SQLite에 저장합니다. 브라우저 새로고침 후에도 확인할 수 있습니다.
- OpenWebUI 실패: 뒤 두 단계를 건너뛰고 실패로 종료. 이전 정상 snapshot 보존.
- 토큰 실패: 마지막 정상 토큰 캐시와 토큰 기준 시각 보존. 분류는 계속하고 전체 결과는 일부 미완료.
- 분류 실패/원본 조회 불가: 완료 배치는 유지, 일부 미완료로 표시. 원본 해시가 달라진 경우 OWUI quick 후 재실행.
- **일시 중단/중단**은 모든 단계에 제공하며 안전한 요청 경계에서 적용합니다. 세부 재개 방식은 후속 사용법 문서를 참고하세요.
- 브라우저 종료만으로 서버 작업이 중지되지 않습니다. 서버 프로세스 종료 후에는 자동 재실행하지 않으며 약 10분 잠금 만료 후 재시도합니다.
- 운영 작업은 한 번에 하나만 시작할 수 있습니다. 별도 수집/분류 작업이 진행 중이면 시작을 거부합니다. 실행 중 다른 탭/CLI에서 별도 작업을 시작하지 마세요. 경합 시 원천별 기존 잠금이 겹친 수집을 거부하며 실패 단계로 기록됩니다.

## 고급 작업

- **전체 재대조**: OWUI full → LiteLLM full → pending 분류. 중복 여유 범위보다 오래된 수정/삭제를 확인할 때 사용합니다. 많은 시간이 걸릴 수 있습니다.
- **전체 미처리 분류**: 수집 단계를 건너뛰고 현재 분석 snapshot의 미처리 질문만 분류합니다. 이미 완료한 질문의 강제 재분류 버튼이 아닙니다.

선택 CLI (웹 버튼과 동시에 실행하지 않음):

```bat
python -m backend_v2.cli operation-status
python -m backend_v2.cli operation-update --kind quick
python -m backend_v2.cli operation-update --kind full
python -m backend_v2.cli operation-update --kind classify
```

CLI 통합 실행은 동기식이며 완료 상태가 success 이외면 종료코드 1입니다. 결과에 원문/키/직원 상세를 출력하지 않습니다.

## 작업 이력 파일

기본 `DASHBOARD_CACHE_PATH`와 같은 폴더의 `operations_v2.sqlite3`에 생성합니다. 기존 cache/CSV 경로와 달라야 합니다. 새 `.env` 설정은 필수가 아닙니다. 필요할 때만 `OPERATIONS_CACHE_DB_PATH=data/operations_v2.sqlite3`를 지정합니다. 기존 source DB를 이 경로로 지정하지 않습니다. 이 파일도 다음 배포 때 보존해야 실행 이력이 유지됩니다. 화면에는 최근20개가 보이며 DB 이력은 자동 삭제하지 않습니다.

## 분류 요청이 LiteLLM에 보이지 않을 때

분류는 OWUI에 모델 호출을 위임하지 않고 대시보드 백엔드가 직접 호출합니다.

- CATEGORY_LITELLM_BASE_URL이 있으면 그 주소, 공란이면 LITELLM_BASE_URL.
- 엔드포인트 `/v1/chat/completions`, 모델 CATEGORY_LLM_MODEL, Bearer 키 CATEGORY_LITELLM_API_KEY.
- 분류 화면에 모델명/분류 전용 주소 사용 여부와 모델 요청 배치 수를 표시합니다. 요청 수는 HTTP 요청 직전에 저장하며 실패한 요청도 포함합니다. 내부 재시도별 실제 HTTP 요청 수와 논리적 배치 수는 다를 수 있습니다.
- 요청 0이면 본문 재조회/대상 확인 중이거나 유효한 캐시만 있어서 호출할 대상이 없을 수 있습니다. 1이상인데 LiteLLM에서 안 보이면 별도 분류 주소 사용 여부, LiteLLM 로그 화면의 키/모델 필터, 요청 오류를 확인합니다. 검증 실패 요청이 LiteLLM spend 로그로 저장된다고 보장하지 않습니다.
- 대시보드 토큰 통계는 OpenWebUI용 별칭만 수집하므로 별도 분류 키 요청이 제외되는 것이 정상일 수 있습니다. 관리자 LiteLLM 전체 요청 로그와 혼동하지 않습니다.
- 실제 키/질문 원문을 인터넷에 반출할 필요는 없습니다. 오류 문구와 숫자만 확인합니다.

## API와 확인

대시보드 인증 설정이 있으면 기존 Bearer 토큰 필요:

- GET `/api/dashboard/v2/operations/status`
- POST `/api/dashboard/v2/operations/update?kind=quick|full|classify` → 202/runId. 접수이지 완료가 아닙니다.
- GET `/api/dashboard/v2/operations/runs/{runId}`
- POST `/api/dashboard/v2/operations/stop-classification`

검수: 운영 메뉴가 열림 → 최근 변경분 실행 → 세 단계 완료 → 새로고침 후 내역 유지 → 다시 quick 실행했을 때 질문/로그 중복 증가 없고 기존 질문 재분류 없음. 실제 서버의 월간 소요시간은 데이터량/프록시/모델에 따라 다릅니다. 수집 중 원천 API 데이터가 바뀌는 제약과 정기 full 재대조 필요성은 기존 문서를 따릅니다.

로컬 검증: 백엔드93 / 프런트28 테스트 통과, TypeScript/API 빌드 성공. 운영 메뉴 활성 상태와 기간 선택 숨김은 실제 LiveApp의 서버 렌더 테스트로 검증했습니다. 합성 데이터 기준이며 실제 LiteLLM/OWUI 및 Windows 브라우저 상호작용은 현장 검수 필요.
