from threading import Thread
from fastapi import Depends, HTTPException, Query
from .token_store import TokenStore
from .token_sync import prepare, collect
from .token_analytics import token_usage
from .cache import BusyError, NotReadyError
from .organization import MappingError


def attach(app, settings, cache, authorized):
    def store():
        return TokenStore(settings.token_cache_path)

    @app.get("/api/dashboard/v2/tokens/status", dependencies=[Depends(authorized)])
    def status():
        try:
            return {
                **store().status(),
                "configured": bool(
                    settings.litellm_url
                    and settings.litellm_key
                    and settings.litellm_alias
                    and settings.litellm_start_date
                ),
            }
        except RuntimeError as error:
            raise HTTPException(422, str(error)) from None

    @app.post(
        "/api/dashboard/v2/tokens/sync",
        status_code=202,
        dependencies=[Depends(authorized)],
    )
    def sync(kind: str = "quick"):
        try:
            db = store()
            run = prepare(settings, db, kind)
        except BusyError as error:
            raise HTTPException(409, str(error)) from None
        except (ValueError, RuntimeError) as error:
            raise HTTPException(422, str(error)) from None

        def work():
            try:
                collect(settings, db, run)
            except RuntimeError:
                pass  # safe error persisted, polled by UI

        Thread(target=work, daemon=True, name="token-collector").start()
        return {"ok": True, "runId": run, "status": "running"}

    @app.get("/api/dashboard/v2/tokens", dependencies=[Depends(authorized)])
    def usage(
        start: str | None = None,
        end: str | None = None,
        range: str = "7d",
        division: str = "전체",
        team: str = "전체",
        position: str = "전체",
        model: str = "전체",
        page: int = Query(1, ge=1),
        pageSize: int = Query(50, ge=1, le=1000),
    ):
        try:
            return token_usage(
                cache,
                settings,
                start=start,
                end=end,
                range_value=range,
                division=division,
                team=team,
                position=position,
                model=model,
                page=page,
                page_size=pageSize,
            )
        except NotReadyError as error:
            raise HTTPException(503, str(error)) from None
        except (ValueError, RuntimeError, MappingError) as error:
            raise HTTPException(422, str(error)) from None

    @app.get("/api/dashboard/v2/tokens/export", dependencies=[Depends(authorized)])
    def export(
        start: str | None = None,
        end: str | None = None,
        range: str = "7d",
        division: str = "전체",
        team: str = "전체",
        position: str = "전체",
        model: str = "전체",
    ):
        import csv, io, re
        from fastapi.responses import Response

        try:
            payload = token_usage(
                cache,
                settings,
                start=start,
                end=end,
                range_value=range,
                division=division,
                team=team,
                position=position,
                model=model,
                paginate=False,
            )
        except NotReadyError as error:
            raise HTTPException(503, str(error)) from None
        except (ValueError, RuntimeError, MappingError) as error:
            raise HTTPException(422, str(error)) from None
        columns = {
            "id": "요청 ID",
            "at": "요청 시각(Unix 초)",
            "model": "모델",
            "userName": "사용자명",
            "team": "팀",
            "prompt": "입력 토큰",
            "completion": "출력 토큰",
            "total": "총 토큰",
            "costUsd": "비용 USD",
            "costSource": "비용 기준",
        }
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        writer.writerow(columns.values())

        def safe(v):
            return (
                "'" + v
                if isinstance(v, str) and re.match(r"^\s*[=+@-]", v)
                else "" if v is None else v
            )

        writer.writerows(
            [safe(row[k]) for k in columns] for row in payload["detail"]["records"]
        )
        return Response(
            out.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="token-usage.csv"',
                "Cache-Control": "no-store",
            },
        )
