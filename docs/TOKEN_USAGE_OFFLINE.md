# LiteLLM 토큰 수집·화면 — 2026-10-27

## 범위와 현재 상태

신규 구현: LiteLLM `/spend/logs/v2` → 독립 v2 SQLite 캐시 → 토큰 사용량 페이지와 개요 연결. 화면은 사용자 제공 토큰 화면을 참고하여 기존 v2 테마/기간 선택을 공유합니다. 실제 폐쇄망 LiteLLM 버전/권한/로그 메타데이터를 직접 검증하지는 못했습니다. 실서버 확인 전 호환 완료로 간주하지 않습니다.

- 요청 ID 중복 제거, 지정 키 별칭만 저장, full/quick 수집, 비동기 실행/상태 폴링, 실행 이력/오류, 실패 시 마지막 성공 캐시 유지.
- 전체/입력/출력 토큰, 비용, 요청 수, 식별 사용자 수, 평균 토큰/요청.
- 기간/실/팀/직급/모델 필터, 일별 추이와 사용자 Top10의 표/그래프 전환.
- 사용자별/팀별/모델별 집계, 요청 로그 서버 페이징, 전체 필터 결과 CSV.
- 개요의 토큰·비용·요약 카드에 실제 캐시 집계 연결. 카테고리는 아직 미연결입니다.

## .env 추가 설정

기존 OpenWebUI 설정과 DASHBOARD_CACHE_PATH는 유지합니다. 프로젝트 루트 `.env`에 다음 설정을 추가하고 서버를 재시작합니다. 비밀키는 로컬 파일에만 입력합니다.

```dotenv
TOKEN_CACHE_DB_PATH=data/token_usage_v2.sqlite3
LITELLM_BASE_URL=http://127.0.0.1:4000
LITELLM_API_KEY=발급받은_spend_logs_조회권한_키
LITELLM_REQUIRED_API_KEY_ALIAS=저장할_실제_OpenWebUI_키별칭
LITELLM_SPEND_LOGS_PATH=/spend/logs/v2
LITELLM_LOG_LIMIT=100
LITELLM_SYNC_LOOKBACK_HOURS=24
LITELLM_SYNC_START_DATE=2026-01-01
LITELLM_LOG_TIMEZONE=UTC
LITELLM_MAX_PAGES_PER_WINDOW=10000
MODEL_PRICES_CSV_PATH=
```

주소·별칭·최초 시작일은 현장 실제 값으로 바꿉니다. LiteLLM 주소는 모델 API의 `/v1`을 제외한 관리 API 기본 주소입니다. 수집 키와 저장 대상 키 별칭은 서로 다른 개념입니다. 모델을 호출하는 OpenWebUI 키 자체가 아닌, 해당 로그를 조회할 권한이 있는 키로 인증합니다.

기존 `data/token_usage_cache.db`와 v2는 스키마가 다를 수 있으므로 **기존 파일을 덮어쓰지 말고 새 `data/token_usage_v2.sqlite3`를 사용**합니다. 인식하지 못하는 DB는 자동 변환하지 않고 오류로 보호합니다. OpenWebUI 캐시와 같은 파일을 사용하지 않습니다. 기존 캐시 파일/CSV를 이 ZIP에 포함하지 않습니다.

인증은 Authorization Bearer 헤더로만 전송합니다. 과거 `LITELLM_API_KEY_IN_QUERY` 설정은 복제하지 않았습니다. 공식 spend API의 `api_key` 쿼리는 조회 대상 키 필터로 쓰이므로 인증 키를 자동으로 쿼리에 넣으면 조회 대상이 달라질 수 있습니다. 이 v2는 별칭을 로컬에서 엄격히 확인합니다. 별칭 메타데이터가 없는 로그도 저장하지 않습니다. 조회 건수/별칭 제외 건수/저장 건수를 함께 확인하세요.

## 수집 실행

웹: 토큰 사용량 → 로그 동기화(quick). 최초 성공 이력이 없으면 full로 승격됩니다. `전체 재수집`은 설정한 시작일부터 전체 로그를 다시 모아 성공 시 게시합니다. **화면에서 선택한 조회 기간과 수집 범위는 별개**입니다.

CMD 대안:

```bat
conda activate D:\project\oui-env-v2
cd /d D:\project\oui-dashboard-v2
python -m backend_v2.cli token-sync --kind full
python -m backend_v2.cli token-status
```

이후:

```bat
python -m backend_v2.cli token-sync --kind quick
```

quick은 마지막 성공 실행의 시작 시각에서 LITELLM_SYNC_LOOKBACK_HOURS만큼 이전부터 현재까지 재조회하고 요청 ID로 합칩니다. 저장된 마지막 요청 시각만 기준으로 삼지 않아 빈 구간/지연 로그를 보완합니다. 지나간 로그 삭제나 중복 범위 밖 수정은 full 재대조가 필요합니다. 중복 수집은 409/Busy로 거절합니다.

수집은 하루 단위 창으로 나누어 `YYYY-MM-DD HH:MM:SS` 날짜와 페이지 1부터 100 이하 크기로 조회합니다. 페이지의 data가 빈 배열이 될 때까지 계속하며, 최신 LiteLLM의 total/total_pages 상한으로 조기 종료하지 않습니다. 중복 페이지/상한 도달/날짜나 숫자 계약 오류는 실패시켜 기존 캐시를 보존합니다. 실시간 DB 스냅샷 API가 아니므로 동시에 로그가 바뀌면 주기적인 full 확인이 필요합니다. 최초 수집 기간이 길면 시간 창별 API 호출이 많아질 수 있습니다.

수집 중 서버를 종료하면 작업도 중단됩니다. 10분 lease 만료 후 interrupted로 표시하며, 다음 실행에서 이전 작업을 정리합니다. 서버 재시작만으로 중단 작업을 자동 재개하지 않습니다. 진행 중에는 서버·설정·캐시 파일을 교체하지 마세요.

## 사용자·조직 매핑

OpenWebUI 명부만 사용자 기준으로 사용합니다. 명시적인 openwebui_user_id를 우선하며 없으면 end_user 또는 user_api_key_end_user_id를 ID/고유 이메일로 대조합니다. 명시적 ID가 잘못되었으면 다른 이름으로 임의 연결하지 않습니다. ID가 없을 때 명시적 openwebui_user_email 또는 유일한 openwebui_user_name으로 보완합니다. 삭제 사용자/충돌 이메일/동명이인은 미식별로 남습니다.

LiteLLM의 최상위 user와 metadata.user_api_key_user_id는 키 소유자이므로 직원 ID로 사용하지 않습니다. 원래 로그에 최종 사용자 정보가 없으면 과거 사용량을 직원에게 소급 배분할 수 없습니다. 미식별 로그는 전체 토큰/비용/모델 합계에 포함하지만 조직 필터와 사용자 Top10에는 포함하지 않으며 미식별 요청 수를 표시합니다. 조직 CSV는 다음 조회에서 다시 읽습니다.

## 비용과 가격표

로그 spend가 있으면 0을 포함해 그대로 사용합니다. spend가 없는 요청만 선택적 가격표로 계산합니다. 가격표는 UTF-8/BOM이며 다음 헤더가 필요합니다.

```text
model,input_per_million_usd,output_per_million_usd
example-model,1.0,2.0
```

model은 로그의 model_group(없으면 model)과 일치해야 합니다. 단가는 100만 토큰당 USD입니다. 입력·출력 토큰이 모두 있어야 추정합니다. 로그 비용/CSV 추정/누락을 요청별로 구분합니다. 합계에 비용/토큰 누락이 하나라도 있으면 해당 합계는 대시로 표시하고 누락 건수를 안내합니다. 누락을 실제 0으로 바꾸지 않습니다. 가격표 추정은 세부 캐시 할인/시간 단가 등 모든 청구 조건을 재현하지 않습니다.

## 기존 카테고리 설정과의 관계

기존 CATEGORY_CACHE_DB_PATH, 질문 분류결과 캐시, 카테고리 정의 CSV, CATEGORY_LITELLM_API_KEY, CATEGORY_LITELLM_API_KEY_IN_QUERY, CATEGORY_LLM_MODEL, CATEGORY_LLM_MAX_QUESTIONS는 이전 구현 참고 항목으로 기록합니다. 이번 v2가 이 키를 읽거나 분류를 실행한다고 해석하지 않습니다.

최신 확정 방향은 질문 임베딩 기반 분류입니다. 후속 단계에서 OpenWebUI 원문 수집 경로와 카테고리 설명/예시 임베딩, 모델/분류 버전/신뢰도/내용 해시 캐시를 별도로 연결합니다. 현재 OpenWebUI 캐시는 원문을 저장하지 않으므로 기존 해시로 원문을 복원하지 않습니다. 카테고리 모델 호출이 토큰 집계에 섞이지 않도록 별도 키와 별칭을 사용합니다.

## API 및 현장 검수

- GET `/api/dashboard/v2/tokens/status`: 설정 여부, 실행 이력, 마지막 성공, 건수, 진행 상태.
- POST `/api/dashboard/v2/tokens/sync?kind=quick|full`: 202/runId. 완료는 상태 API로 확인합니다. 202 자체가 수집 성공을 의미하지 않습니다.
- GET `/api/dashboard/v2/tokens`: 날짜/기간/조직/모델/page/pageSize.
- GET `/api/dashboard/v2/tokens/export`: 전체 필터 결과. 인증/CSV 수식 방어 적용.
- CLI와 웹에서 같은 원천·별칭·타임존을 사용합니다. 바뀌면 캐시를 분리합니다.

1. 기존 .env·OpenWebUI DB·조직 CSV와 Conda 환경은 보존하고 backend_v2와 frontend_v2/dist를 함께 교체합니다.
2. 위 설정을 추가하고 Uvicorn을 재시작합니다. 토큰 메뉴를 열어 설정 상태를 확인합니다.
3. 첫 로그 동기화 후 success/저장 건수/제외 건수를 확인하고 LiteLLM 동일 별칭·기간의 토큰·spend와 대조합니다.
4. 사용자 0명이어도 전체 요청/토큰이 있으면 미식별 비율과 end_user 메타데이터를 확인합니다. 직원 정보/원문/키를 외부로 보내지 마세요.
5. 같은 범위 quick 재실행 시 중복 합산되지 않는지, 기간 경계와 모델/팀 필터가 맞는지 확인합니다.
6. CSV가 현재 로그 페이지에 제한되지 않는지, 누락 지표가 0으로 표시되지 않는지 확인합니다.
7. 서버 재시작/키 오류 후 이전 성공 데이터가 유지되는지, 개요 토큰·비용과 토큰 화면을 같은 명시적 기간으로 비교합니다.

실제 LiteLLM 버전에 따라 응답 필드가 다르면 외부 반출 없이 현장에서 키 이름/자료형과 오류 코드만 확인하여 어댑터를 조정합니다. HTTP 오류 원문/URL/헤더/프롬프트/응답은 수집 오류 메시지에 기록하지 않습니다.

조사 기준: 공식 [Spend Tracking](https://docs.litellm.ai/docs/proxy/cost_tracking), 2026-10-27. 로컬 자동 테스트는 합성 데이터 기반이며 실제 폐쇄망/브라우저 검수는 별도입니다.

로컬 검증 완료: 백엔드 55개/프런트 24개 테스트 통과, TypeScript/API 빌드 성공. 실제 폐쇄망 및 브라우저 상호작용은 미검증입니다. 새로운 런타임 의존성은 없습니다.
