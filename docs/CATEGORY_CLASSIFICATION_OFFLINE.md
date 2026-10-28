# 질문 카테고리 분류 — 폐쇄망 설정과 검수

2026-10-28 신규 구현. 사용자 보고로 LiteLLM 토큰 수집 정상은 확인했습니다. **분류 모델의 실제 서버 호출과 정확도, 현장 화면 검수는 별도로 필요합니다.** 운영 소스의 복원본이 아닌 v2 기능입니다.

## 방법과 범위

기존 `category, description, keywords, examples, active` CSV를 유지하고, LiteLLM의 OpenAI 호환 Chat Completions로 질문 의도를 분류합니다. 단순 키워드 포함만으로 정답을 결정하지 않습니다. 기본 다섯 질문을 한 요청에 묶고, 같은 질문 해시와 첨부 여부의 결과를 재사용합니다. 모든 질문은 활성 카테고리 하나 또는 미분류 중 하나에 속합니다. 키워드/예시는 `|`로 구분할 수 있으며 쉼표가 들어간 셀은 CSV 규칙에 따라 큰따옴표로 감쌉니다. `active`는 true/false 또는 1/0이며, 비활성 행은 모델에 전달하지 않습니다.

문서/RAG, 번역, 요약 등 비슷한 카테고리의 경계는 CSV 설명에 구체적으로 적습니다. 첨부가 있다는 이유만으로 문서/RAG로 강제하지 않습니다. 분류는 질문 본문과 첨부 유무에 대한 **의도 분류**이며, 실제 검색 실행 여부/RAG 성공 여부를 증명하는 지표가 아닙니다. 원문 대화 맥락이나 첨부파일 내용은 모델에 전달하지 않습니다.

임베딩 최근접 분류는 향후 대안입니다. 대표 질문과 정답 검수 세트 없이 유사도 임계값을 고정해 더 정확하다고 단정하지 않습니다. 우선 기존 CSV를 LLM이 읽는 방법으로 소량 검수 후 확대합니다.

## 1. 업데이트

1. 실행 중인 수집/분류가 끝난 뒤 Uvicorn을 Ctrl+C로 종료합니다.
2. 기존 `backend_v2`와 `frontend_v2/dist`를 백업 후 새 릴리스의 폴더 전체로 교체합니다. 새 dist의 assets와 이전 파일을 혼합하지 않습니다.
3. `.env`, `data`, 기존 DB/CSV, Conda 환경은 보존합니다. 기존 OpenWebUI full 재수집, 토큰 full 재수집, 의존성 설치는 필요하지 않습니다.
4. 기존 `.env`에 아래 항목을 추가합니다. `.env.example`로 실제 `.env`를 덮어쓰지 않습니다.

```dotenv
CATEGORY_CACHE_DB_PATH=data/category_v2.sqlite3
CATEGORY_DEFINITIONS_CSV_PATH=data/question_categories.csv
CATEGORY_LITELLM_BASE_URL=
CATEGORY_LITELLM_API_KEY=실제_분류모델_호출권한_키
CATEGORY_LLM_MODEL=LiteLLM에_등록된_실제_모델별칭
CATEGORY_LLM_MAX_QUESTIONS=20
CATEGORY_BATCH_SIZE=5
CATEGORY_MAX_QUESTION_CHARS=6000
CATEGORY_MIN_CONFIDENCE=0.65
CATEGORY_JSON_MODE=true
CATEGORY_CLASSIFIER_REVISION=1
```

- CATEGORY_DEFINITIONS_CSV_PATH는 **현재 사용 중인 실제 정의 CSV** 경로로 맞춥니다. 이 릴리스에는 실제 CSV나 직원 데이터가 없습니다. Excel에서 UTF-8 CSV로 저장하는 것을 권장하며 CP949도 지원합니다. 이름이 비어 있거나 중복되면 오류로 알립니다. `미분류`, `전체`는 예약 이름입니다.
- CATEGORY_LITELLM_BASE_URL 공란이면 LITELLM_BASE_URL을 사용합니다. 분류 URL은 기본 주소와 `/v1` 접미사 모두 허용합니다.
- **분류 키는 모델 추론 권한이 필요합니다.** spend 로그 조회 키와 역할이 다르므로 별도로 설정합니다. OWUI 관리자 키와 DASHBOARD_API_TOKEN도 다릅니다. 키는 Bearer 헤더로만 전달하며 과거 API_KEY_IN_QUERY 옵션은 사용하지 않습니다.
- 가능하면 분류 전용 LiteLLM 키/별칭을 사용하고, 토큰 수집의 REQUIRED_API_KEY_ALIAS는 OpenWebUI 서비스 키로 유지합니다. 분류 요청 비용이 사용자 서비스 사용량에 섞이지 않게 운영합니다. 같은 키를 사용하면 분류 호출도 사용자 토큰 통계에 포함될 수 있습니다.
- **CATEGORY_CACHE_DB_PATH는 새로운 v2 파일**을 사용합니다. 기존 `category_cache.db`는 보존하며 자동 이관하지 않습니다. DB 식별자가 다르면 실행을 거부합니다. OpenWebUI/토큰/카테고리 캐시 경로는 모두 달라야 합니다.
- 점수는 모델의 자기 평가이며 통계적으로 보정된 확률이 아닙니다. 기본 0.65 미만이나 null 분류는 `검토 필요`로 저장합니다.
- JSON 모드 지원은 모델마다 다릅니다. `response_format` 미지원 400/422라면 현장 모델 지원을 확인하고 CATEGORY_JSON_MODE=false로 설정 후 재시작할 수 있습니다. 이때도 결과 ID/카테고리/점수/누락 검증은 유지하며 잘못된 응답을 성공 처리하지 않습니다. `temperature=0`, `max_tokens=2048`, 일반 non-stream chat completion을 지원하는 모델이 대상입니다.

## 2. 서버 실행과 첫 20개 검수 (CMD)

```bat
conda activate D:\project\oui-env-v2
cd /d D:\project\oui-dashboard-v2
python -m uvicorn backend_v2.app:create_app --factory --host 127.0.0.1 --port 8011
```

브라우저 `http://localhost:8011/?screen=categories`에서 Ctrl+F5 후 **미처리 질문 분류**를 누릅니다. 인증을 설정했다면 상단 대시보드 인증 설정을 입력합니다. HTTP 202는 접수이며 완료가 아닙니다. 진행 표시가 완료로 바뀌는지 확인합니다.

별도 CMD로 실행하려면 웹 버튼과 동시에 실행하지 말고:

```bat
conda activate D:\project\oui-env-v2
cd /d D:\project\oui-dashboard-v2
python -m backend_v2.cli category-classify --kind pending
python -m backend_v2.cli category-status
```

분류 작업은 **전체 기간 미처리 질문 중 최근순**, 한 번에 설정한 최대 질문 수만 처리합니다. 화면의 기간/조직 필터는 조회만 바꾸며 분류 실행 범위를 바꾸지 않습니다. 기본 배포값은 200이지만 첫 검수는 20으로 권장합니다. 정상 확인 후 `.env`의 한도를 200으로 바꾸고 서버를 재시작하면 됩니다. 버튼 또는 CLI를 반복하면 남은 미처리 질문을 이어 처리합니다. 대량 전체를 한 번에 무제한 자동 처리하지 않습니다.

검토 필요 결과를 다시 시도하려면:

```bat
python -m backend_v2.cli category-classify --kind retry
```

또는 **검토 필요 재시도** 버튼을 사용합니다. 같은 정의와 모델에서 판정이 달라지지 않을 수 있으므로 CSV의 경계를 개선하고 검수합니다.

## 3. 데이터 처리와 캐시 유효성

기존 분석 DB에는 원문 대신 content_hash만 있습니다. 새 분류기는 **대상 사용자의 메시지 API를 페이지 조회**하여 대상 질문의 본문을 메모리에서만 읽습니다. OpenWebUI/분석 DB에는 쓰지 않습니다. 오래된 질문은 사용자 메시지 목록의 뒤쪽까지 조회해야 하므로 모델 호출 외 API 재조회 시간도 필요합니다. 캐시가 유효한 질문만 남은 사용자는 재조회하지 않습니다.

- 로컬 DB에는 버전/해시, 카테고리, 판단 점수, 처리 상태/시각만 저장합니다. 원문·파일명·파일내용·모델 응답 전문·판정 이유는 저장하거나 응답에 포함하지 않습니다.
- 모델 요청에는 임시 Q0/Q1 ID와 질문 텍스트/첨부 유무만 넣습니다. 사용자명·이메일·OWUI ID·파일 경로를 추가하지 않습니다. **질문 본문 자체에 포함된 정보는 모델 서버로 전달됩니다.** 기존과 동일하게 사내 승인된 LiteLLM 경로와 모델을 사용하며 LiteLLM 측 프롬프트 로그 보존 정책도 별도로 적용됩니다.
- 질문 안의 지시는 실행하지 않도록 시스템 프롬프트에서 분리하고, 모델 응답은 허용된 카테고리 코드와 입력 ID만 인정합니다. 도구 호출/스트리밍/임의 후속 동작은 없습니다.
- 성공한 배치 단위로 저장합니다. 다음 배치가 실패해도 앞선 결과는 유지하고 해당 실패 배치는 성공 처리하지 않습니다. 서버를 강제 종료하면 약 10분 후 작업 잠금이 만료됩니다. 이후 pending 재실행으로 이어갑니다. 진행 중인 작업은 웹 새로고침 시 상태를 다시 읽습니다.
- 질문 수정/삭제/사용자 삭제는 다음 OWUI quick/full 동기화 결과가 기준입니다. 분류 전 API 원문 해시와 현재 분석 snapshot 해시가 다르면 원본 확인 필요로 건너뜁니다. OWUI quick 동기화 후 분류를 다시 실행합니다. 삭제된 질문/사용자의 과거 분류 캐시는 현재 통계에 포함하지 않습니다.
- 활성 정의/설명/키워드/예시, 모델, URL, 임계값, 길이, JSON 모드, revision 변경은 새로운 분류 버전으로 처리합니다. 이전 버전 결과를 삭제하지 않으며 현재 통계에 섞지 않습니다. **미처리로 돌아온 뒤 pending을 다시 실행**합니다. 같은 모델 별칭의 실제 모델을 교체했다면 CATEGORY_CLASSIFIER_REVISION을 올립니다.
- 질문 텍스트가 없거나 이미지/파일만 있으면 텍스트 없음. 모델에 보내지 않으며 미분류에 포함합니다. 멀티모달 content는 text/input_text 부분만 사용합니다.
- 긴 질문은 기본 첫 6000자만 사용하며 일부 텍스트 사용 표시를 남깁니다. 실제 전체 질문을 이해했다고 설명하지 않습니다.

## 4. 확인할 항목

1. 총 질문 수 = 분류 완료 + 미처리 + 검토 필요 + 텍스트 없음.
2. 카테고리 분포 합계 = 같은 기간·조직의 총 질문 수. 미분류가 포함되며 0과 미수집을 혼동하지 않습니다.
3. 개요의 카테고리 합계가 같은 기간의 총 질문 수와 일치. 부분 분류 시 나머지는 미분류.
4. 같은 설정으로 pending을 다시 실행하면 완료 질문을 다시 모델 호출하지 않음.
5. CSV active=false 행이 분류 기준에서 빠짐. CSV 수정 후 이전 결과는 현재 분류율에서 빠짐.
6. 사내 OpenWebUI에서 직접 확인 가능한 소량 정답과 비교. 예: 실제 문서 검색 의도/일반 번역 의도/애매한 혼합 질문. 이때 질문 내용을 인터넷으로 반출할 필요는 없음.
7. 실패 시 status 오류와 숫자만 전달. 키/실제 질문/직원 데이터는 공유하지 않음.

## API

대시보드 인증 동일:

- GET `/api/dashboard/v2/categories/status`: 설정 여부, 작업, 한도. 원문/키 없음.
- POST `/api/dashboard/v2/categories/classify?kind=pending|retry`: 202 비동기 접수, 중복 409.
- GET `/api/dashboard/v2/categories?range=all&page=1&pageSize=50`: 기간/조직 분포, 정의, 질문별 메타데이터. division/team/position/category 지원. pageSize 최대1000. 카테고리 선택은 상세표/일별에 적용, 상단 총질문/분포는 선택 기간·조직 전체 유지.
- 기존 `/overview`에 동일 snapshot과 기간의 분류 분포 연결. 조회는 모델을 호출하지 않음.

공식 근거: https://docs.litellm.ai/docs/completion/json_mode — `/v1/chat/completions`, Bearer 인증과 response_format 지원은 모델별 확인 필요. 새 런타임 패키지는 없습니다. 아직 운영 업데이트 전체 워크플로/자동 예약/사람의 분류 수정 기능은 구현하지 않았습니다.

로컬 검증: 백엔드 75개 / 프런트 26개 테스트, TypeScript/API 빌드 통과. 실제 모델 판정 정확도는 자동 계약 테스트로 보장하지 않습니다.
