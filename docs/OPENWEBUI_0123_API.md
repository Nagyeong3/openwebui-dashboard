# OpenWebUI 0.12.3 API 조사 및 구현 기준

확인: 2026-10-22. 공식 태그 v0.12.3, commit `91ea4e3421d1d8069f13d4a463fcb5986d94ea60`를 직접 읽었습니다. 실제 폐쇄망 설정·권한은 미검증입니다.

공식 소스:

- https://github.com/open-webui/open-webui/blob/v0.12.3/backend/open_webui/routers/analytics.py
- https://github.com/open-webui/open-webui/blob/v0.12.3/backend/open_webui/routers/users.py
- https://github.com/open-webui/open-webui/blob/v0.12.3/backend/open_webui/models/chat_messages.py
- https://docs.openwebui.com/features/administration/analytics/

## 확인된 API

| API | 제약/의미 |
| --- | --- |
| GET /api/v1/users/all | 관리자, users/total, 전체 명부 |
| GET /api/v1/users/ | 관리자, page, 한 페이지 30명 |
| GET /api/v1/analytics/users | 관리자, 기본 상위 50명, assistant count 기반. 0건 명부로 사용 금지 |
| GET /api/v1/analytics/messages | 관리자, user_id/model_id/chat_id 필터. 일반 limit 최대100 |
| GET /api/v1/analytics/summary | assistant 기반 메시지/활성 사용자/채팅 집계. 질문 수가 아님 |
| GET /api/v1/analytics/daily | assistant 기반, daily/hourly |
| GET /api/v1/analytics/models | 모델별 assistant 수 및 distinct 사용자/채팅 |
| GET /api/v1/analytics/tokens | 모델별 입력/출력 토큰. usage 기록 누락을 복구하지 않음 |
| GET /api/v1/users/usage | 로그인한 본인 전용. 전체 직원 집계용 아님 |

messages 구현의 주의점:

- 아무 필터도 없으면 빈 배열.
- chat_id → model_id → user_id 순서로 단일 분기. 여러 인자를 함께 줘도 AND 필터가 아님.
- user_id 분기는 start_date/end_date를 전달하지 않음. 로컬 날짜 필터 필요.
- chat_id 분기는 전체 채팅 메시지를 반환하며 skip/limit 적용 안 됨.
- user_id 분기는 created_at 내림차순 + offset 페이징이며 고정 snapshot/cursor가 아님.
- 메시지 ID는 chat_id와 원본 message ID를 합친 composite ID. parent_id는 원본 parent ID일 수 있음.
- 메시지에는 content/files/usage 등의 필드가 있지만 새 캐시에는 원문/파일 경로를 저장하지 않음.

## 신규 개발 방향 (사용자 확정)

기존 대시보드 FastAPI 응답을 복원하는 대신 공식 API에서 새로 수집·집계합니다. 따라서 기존 /api/users/usage JSON이나 폐쇄망 소스 전체를 다시 요청할 필요가 없습니다.

OpenWebUI API → 별도 분석 SQLite 캐시 → CSV 보강/기간 집계 → 신규 FastAPI → React.

1~4단계는 `backend_v2`에 신규 구현했습니다. 조회 계약과 실행 절차는 해당 README가 기준입니다. React의 초기 snapshot 계약은 아직 데모용이며 5단계에서 새 사용자 API로 연결합니다.

질문은 저장된 role=user 메시지 전체 기준으로 정했으며, 현재 분기만 집계하는 과거 파서와 수치 차이를 대조해야 합니다. CSV-only 사용자를 명부에 추가하지 않으며 0건 팀장도 전체 순위에 포함합니다.

LiteLLM 실제 비용/요청수, 카테고리 분류, 운영 업데이트 UI는 이번 단계에서 실데이터 연결하지 않았습니다.
