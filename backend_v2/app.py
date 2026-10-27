import hmac
import csv
import io
import re
from pathlib import Path
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .analytics import user_usage
from .overview import overview
from .cache import Cache, NotReadyError
from .organization import MappingError
from .settings import Settings


def create_app(settings=None, cache=None):
    settings = settings or Settings.from_env()
    cache = cache or Cache(settings.cache_path)
    app = FastAPI(title="OpenWebUI Analytics Backend v2", version="0.2.0")
    origins = list(settings.cors_origins)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET"],
            allow_headers=["Authorization"],
        )

    def authorized(authorization: str | None = Header(None)):
        if settings.dashboard_token and not hmac.compare_digest(
            authorization or "", "Bearer " + settings.dashboard_token
        ):
            raise HTTPException(401, "Dashboard authentication required")

    @app.get("/api/dashboard/v2/health", dependencies=[Depends(authorized)])
    def health():
        state = cache.status()
        return {
            "ok": True,
            "ready": state["ready"],
            "upstreamConfigured": bool(settings.base_url and settings.api_token),
            "schemaVersion": 1,
        }

    @app.get("/api/dashboard/v2/sync/status", dependencies=[Depends(authorized)])
    def sync_status():
        return cache.status()

    @app.get("/api/dashboard/v2/overview", dependencies=[Depends(authorized)])
    def get_overview(
        start: str | None = None,
        end: str | None = None,
        range: str = "30d",
    ):
        try:
            return overview(cache, settings, start=start, end=end, range_value=range)
        except NotReadyError as error:
            raise HTTPException(503, str(error)) from None
        except (MappingError, ValueError, OverflowError) as error:
            raise HTTPException(422, str(error)) from None

    @app.get("/api/dashboard/v2/users", dependencies=[Depends(authorized)])
    def users(
        start: str | None = None,
        end: str | None = None,
        range: str = "30d",
        division: str = "전체",
        team: str = "전체",
        position: str = "전체",
        matchStatus: str = "전체",
        view: str = "user",
        page: int = Query(1, ge=1),
        pageSize: int = Query(50, ge=1, le=1000),
        order: str = "desc",
        search: str = "",
    ):
        try:
            return user_usage(
                cache,
                settings,
                start=start,
                end=end,
                range_value=range,
                division=division,
                team=team,
                position=position,
                match_status=matchStatus,
                view=view,
                page=page,
                page_size=pageSize,
                order=order,
                search=search,
            )
        except NotReadyError as error:
            raise HTTPException(503, str(error)) from None
        except MappingError as error:
            raise HTTPException(422, str(error)) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get("/api/dashboard/v2/users/export", dependencies=[Depends(authorized)])
    def export_users(
        start: str | None = None,
        end: str | None = None,
        range: str = "30d",
        division: str = "전체",
        team: str = "전체",
        position: str = "전체",
        matchStatus: str = "전체",
        view: str = "user",
        order: str = "desc",
        search: str = "",
    ):
        try:
            payload = user_usage(
                cache,
                settings,
                start=start,
                end=end,
                range_value=range,
                division=division,
                team=team,
                position=position,
                match_status=matchStatus,
                view=view,
                order=order,
                search=search,
                paginate=False,
            )
        except NotReadyError as error:
            raise HTTPException(503, str(error)) from None
        except (MappingError, ValueError) as error:
            raise HTTPException(422, str(error)) from None
        columns = (
            {
                "division": "실 / 본부",
                "team": "팀",
                "users": "등록 사용자",
                "activeUsers": "활성 사용자",
                "questions": "질문 수",
                "chats": "채팅방 수",
                "attachmentQuestions": "첨부 질문",
            }
            if view == "team"
            else {
                "rank": "순서",
                "id": "사용자 ID",
                "name": "사용자명",
                "email": "이메일",
                "division": "실 / 본부",
                "team": "팀",
                "position": "직급",
                "mapping": "조직 매핑",
                "questions": "질문 수",
                "chats": "채팅방 수",
                "attachments": "첨부 질문",
                "lastUsedAt": "마지막 질문 시각",
                "primaryModel": "주 사용 모델",
            }
        )

        def safe(value):
            if value is None:
                return ""
            if isinstance(value, str) and re.match(r"^\s*[=+@-]", value):
                return "'" + value
            return value

        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(columns.values())
        writer.writerows(
            [safe(row.get(k)) for k in columns] for row in payload["detail"]["records"]
        )
        return Response(
            content=output.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="openwebui-{view}.csv"',
                "Cache-Control": "no-store",
            },
        )

    # Optional same-origin static hosting: no Node runtime, proxy or CORS required.
    frontend = settings.frontend_dir
    if frontend:
        directory = Path(frontend).resolve()
        if not (directory / "index.html").is_file():
            raise ValueError("DASHBOARD_FRONTEND_DIR must contain the built index.html")
        app.mount("/", StaticFiles(directory=directory, html=True), name="frontend")
    return app
