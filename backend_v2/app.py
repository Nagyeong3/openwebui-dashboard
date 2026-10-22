import hmac
import os
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .analytics import user_usage
from .cache import Cache, NotReadyError
from .organization import MappingError
from .settings import Settings


def create_app(settings=None, cache=None):
    settings = settings or Settings.from_env()
    cache = cache or Cache(settings.cache_path)
    app = FastAPI(title="OpenWebUI Analytics Backend v2", version="0.2.0")
    origins = [
        s.strip()
        for s in os.getenv("DASHBOARD_CORS_ORIGINS", "").split(",")
        if s.strip()
    ]
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

    return app
