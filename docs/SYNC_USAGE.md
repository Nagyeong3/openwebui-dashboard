# OpenWebUI API 동기화 사용법

현재 Windows 개발 경로: 프로젝트 `D:\project\oui-dashboard-v2`, Conda 환경 `D:\project\oui-env-v2`.
설정은 프로젝트 최상위 `.env`에 저장합니다. [환경 설정](ENV_SETUP.md)을 먼저 확인하세요.

## 최초 전체 수집

CMD에서 실행합니다.

```bat
conda activate D:\project\oui-env-v2
cd /d D:\project\oui-dashboard-v2
python -m backend_v2.cli sync --kind full
python -m backend_v2.cli status
```

`full`은 OpenWebUI 전체 사용자 명부와 사용자별 전체 메시지를 페이지 단위로 조회하고 대시보드 전용 SQLite 캐시에 저장합니다. 원본 OpenWebUI DB 파일을 복사하거나 원본 데이터를 수정하지 않습니다. 기록이 많으면 최초 수집이 오래 걸릴 수 있습니다. 최초 성공 전 화면의 `no successful API synchronization`은 수집 완료가 필요하다는 뜻입니다. Uvicorn 실행 자체는 수집을 시작하지 않습니다.

## 이후 증분 업데이트

```bat
conda activate D:\project\oui-env-v2
cd /d D:\project\oui-dashboard-v2
python -m backend_v2.cli sync --kind quick
python -m backend_v2.cli status
```

- 사용자 명부는 매번 다시 조회합니다. 명부는 OpenWebUI가 기준이며 CSV는 조직 정보를 보완합니다. CSV에만 있는 사용자를 추가하지 않습니다.
- 기존 사용자는 마지막 성공한 수집의 시작 시각에서 `SYNC_OVERLAP_DAYS`(기본 7일)를 뺀 시점 이후 메시지를 다시 확인합니다. 중단 기간이 길면 그 기간도 포함하며, 항상 현재 시각 기준 최근 7일만 읽는 방식은 아닙니다.
- 최신순 페이지를 읽다가 기준보다 오래된 메시지에 도달하면 중단합니다. 최근 구간은 겹쳐 조회하고 메시지 ID 기준으로 반영합니다. quick도 전체 사용자 조회 및 사용자별 API 호출이 필요하므로 즉시 끝난다는 보장은 없습니다.
- 새로 발견한 사용자는 과거 전체 기록을 수집합니다. 성공한 캐시가 없으면 quick도 full로 전환됩니다.
- 기준 구간 밖의 오래된 수정·삭제는 quick으로 모두 반영할 수 없습니다. 주기적으로 full 재대조가 필요하며, 실행 주기는 실서버 소요시간을 측정한 뒤 정합니다.
- 실패하면 마지막 성공 캐시를 보존합니다. 상태의 `lastSuccess`와 최근 실행 결과를 함께 확인하세요.

## 동기화 중 다른 작업

실행 중인 CMD는 유지하고 새 터미널이나 VS Code에서 다른 작업을 할 수 있습니다. OpenWebUI도 사용할 수 있지만 수집이 서버 자원을 사용합니다. 수집 도중 명부 변동이나 페이지 이동이 감지되면 실패하고 재시도가 필요할 수 있습니다. 동시에 다른 동기화를 실행하지 말고 실행 도중 설정·코드·캐시 파일 변경을 피하세요. 기존 성공 캐시가 있으면 웹 화면은 마지막 성공 데이터를 이용하며, 새 결과는 성공 후 게시됩니다.

## LiteLLM과의 관계

현재 사용자/메시지 수집 경로는 **대시보드 → OpenWebUI API → 대시보드 캐시**입니다. `/api/v1/users/all`과 `/api/v1/analytics/messages`를 조회하며 모델 추론 요청을 보내지 않습니다. 따라서 이 수집이 LiteLLM 추론 로그에 나타나지 않는 것은 정상입니다. OpenWebUI API 키를 사용하며 LiteLLM 모델 연결 키와 다릅니다. 토큰·비용을 위한 LiteLLM 로그 수집은 별도 후속 기능입니다.

## 향후 업데이트 현황 페이지 개발 기준

일반 업데이트 버튼은 기존 `Synchronizer.run(kind="quick")`를 이용하는 백엔드 작업으로 연결합니다(CLI의 `python -m backend_v2.cli sync --kind quick`과 동일한 수집 경로). full은 별도 전체 재대조 동작으로 제공합니다. 최초 quick의 full 전환을 화면에 표시하고, 중복 실행 방지·비동기 실행·진행 상태/성공/실패·마지막 성공 시각·실패 시 기존 데이터 유지·완료 후 화면 갱신을 연결합니다. 긴 수집을 단일 웹 요청이 끝날 때까지 기다리게 구현하지 않습니다. 현재 페이지에서 실행 버튼이 연결되었다는 의미는 아니며, 후속 개발 요구사항입니다. 상태 조회 API는 `/api/dashboard/v2/sync/status`입니다.
