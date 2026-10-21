# v2 API 어댑터 계약 (제안, 기존 운영 API와 동일하다는 의미 아님)

기존 `/api/users/usage`, `/api/tokens/usage`의 현재 응답 원본을 확보하지 못했으므로 프런트엔드 내부 계약을 명시합니다. 기존 FastAPI 서비스는 유지하고, 실제 응답 확인 후 `frontend-v2/src/api.ts`에서 변환하거나 별도의 얇은 어댑터 endpoint를 추가합니다.

## GET /api/dashboard/v2/snapshot

`src/domain.ts`의 `Snapshot`이 정규 계약입니다. JSON 최상위 필드:

| 필드 | 형식/규칙 |
| --- | --- |
| schemaVersion | 1 |
| source | api |
| updatedAt | timezone 포함 ISO timestamp |
| coverageStart / coverageEnd | YYYY-MM-DD, 일별 집계 수집 범위 |
| users | 전체 DB 사용자. 기간 사용량과 관계없이 포함, 고유 ID 필수 |
| usage | 비식별 일별 집계 배열 |
| operations | 정규화된 최근 운영 작업 목록 |
| cache | logs / classified / pending 숫자 |

`users[]`: id, name, division, team, position, mapping, source (`openwebui-db` 고정).

`mapping`: 매핑 완료 / 미매핑 / 중복 이름. CSV-only 사용자는 거부합니다. ID 우선 매핑, 중복 이름을 추측하지 않습니다.

`usage[]`: date, userId (미식별 시 null), model, category, questions, chats, attachments, requests, prompt, completion, spend.

- 모든 숫자는 0 이상, spend 단위 USD.
- 사용자와 연결된 행의 userId는 명부에 존재해야 합니다.
- 날짜는 Asia/Seoul 일자. snapshot coverage 안에 있어야 합니다.
- 질문은 role=user 메시지. 질문 데이터와 토큰 로그를 다대다 join해서 수치를 증폭시키면 안 됩니다.
- 질문/채팅/첨부 집계 행에 token 값 0을 넣고, LiteLLM 집계 행에는 questions/chats/attachments를 0으로 넣어 별도 행으로 전송해도 됩니다. 단 같은 요청/메시지를 중복 집계하지 않습니다.
- 고유 채팅방 수는 일별/모델/카테고리 간 단순 합산하면 중복될 수 있습니다. 실제 계약 확장 시 distinct chat 집계 endpoint 또는 비식별 chat key를 도입해야 합니다. 현재 데모의 chats는 합성 가산 지표이며 운영 집계 기준으로 검증되지 않았습니다.
- 모델 필터가 질문에까지 적용될 때는 질문별 모델 귀속 정의가 필요합니다. 복수 응답 모델의 질문 중복 계산을 금지합니다.
- 비용을 0으로 내려주는 것과 비용 정보를 수집하지 못한 것은 구분해야 합니다. 후자는 확장 계약에서 null/coverage 상태가 필요합니다.

**0건 사용자 보존은 프런트만으로 복구할 수 없습니다.** 서버가 기간 내 활동자만 보내면 누락된 DB 사용자를 CSV로 복구하지 않습니다. DB 사용자 전체를 반환하도록 서버 경로를 수정해야 합니다.

## 기존 API와 연결할 때

1. 기존 사용량 API의 `range=all`, 날짜 필터, 페이징 정책과 사용자 명부 전체 제공 여부 확인.
2. `filters`의 팀 목록이 사용자 명부와 같은 원천인지 확인. CSV 필터 옵션이 존재한다고 DB 사용자가 있다는 뜻은 아닙니다.
3. 전체 사용자와 기간 집계 응답을 키로 합치고, 누락 사용량만 0으로 채움.
4. LiteLLM 로그는 요청 ID 기준 dedup 후 별도 합산.
5. 기존 `ok:false`는 HTTP 200이어도 오류로 처리.
6. 수집 범위를 UI에 제공하여 비교 증감률의 유효성을 판단.

## POST 운영 업데이트

제안 경로: 기존 `/api/operations/quick-update`, `/api/operations/full-update`.

현재 decoder는 `{ operation: Operation }` 형식이 필요합니다. `Operation`: id, kind, startedAt, status (success/running/failed), steps 배열. 각 step: name, status (success/running/failed/waiting), detail.

실제 서버가 비동기 job ID를 반환한다면 작업 상태 polling API를 adapter에 연결해야 합니다. 현재 프런트는 API 모드에서 임의의 성공 결과를 생성하지 않습니다. 완료 상태를 검증하지 못하면 결과 확인 안내를 표시합니다.

DB snapshot 실패 후 후속 단계 중단, 토큰/분류 실패 시 이전 정상 데이터 보존은 서버 책임입니다. 공개 프런트에서 Docker 명령/서버 경로를 실행하지 않습니다.

## 배포 환경

같은 origin의 `/api` reverse proxy 권장. 별도 origin이면 정확한 origin과 인증 정책에 맞는 CORS를 설정합니다. 브라우저 빌드 변수에 관리자 토큰/비밀키를 넣지 않습니다. 기존 인증을 사용하는 서비스는 해당 세션/인증 계약에 맞게 `request`를 보완해야 합니다.

전체 기간 데이터가 큰 환경은 현재 snapshot 계약을 그대로 대용량 운영 API로 사용하지 않습니다. 서버 집계·날짜 범위 조회·사용자 서버 페이징으로 확장합니다.
