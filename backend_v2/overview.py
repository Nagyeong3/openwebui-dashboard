"""Overview built from one published cache snapshot; no upstream calls on page load."""

from datetime import datetime, time, timedelta

from .analytics import SEOUL, user_usage


def overview(cache, settings, *, start=None, end=None, range_value="30d"):
    snapshot = cache.read()
    state = cache.status()

    class Snapshot:
        def read(self):
            return snapshot

        def status(self):
            return state

    payload = user_usage(
        Snapshot(),
        settings,
        start=start,
        end=end,
        range_value=range_value,
        paginate=False,
    )
    records = payload["detail"]["records"]
    leaders = [r for r in records if "팀장" in r["position"]]
    for rank, row in enumerate(leaders, 1):
        # Do not mutate the person rank in the full user result.
        leaders[rank - 1] = {**row, "rank": rank}
    summary = {
        **payload["summary"],
        "averageQuestionsPerChat": (
            round(payload["summary"]["questions"] / payload["summary"]["chats"], 1)
            if payload["summary"]["chats"]
            else None
        ),
        "leaders": len(leaders),
        "activeLeaders": sum(r["questions"] > 0 for r in leaders),
    }
    comparison = {
        "status": "all-time",
        "start": None,
        "end": None,
        "questions": None,
        "changePercent": None,
    }
    a, b = payload["period"]["start"], payload["period"]["end"]
    if a and b:
        current_start = datetime.fromisoformat(a).date()
        current_end = datetime.fromisoformat(b).date()
        span = (current_end - current_start).days + 1
        previous_end = current_start - timedelta(days=1)
        previous_start = current_start - timedelta(days=span)
        lo = datetime.combine(previous_start, time.min, SEOUL).timestamp()
        hi = datetime.combine(current_start, time.min, SEOUL).timestamp()
        ids = {r["id"] for r in records}
        prior = sum(
            m["role"] == "user" and m["user_id"] in ids and lo <= m["created_at"] < hi
            for m in snapshot[1]
        )
        comparison = {
            "status": "available" if prior else "zero-baseline",
            "start": previous_start.isoformat(),
            "end": previous_end.isoformat(),
            "questions": prior,
            "changePercent": (
                round((summary["questions"] - prior) / prior * 100, 1)
                if prior
                else None
            ),
        }
    # Full history has no comparison period. Fill missing dates for the chart/table
    # when the available history fits the same supported custom-range bound.
    daily = payload["daily"]
    if not a and daily:
        first = datetime.fromisoformat(daily[0]["date"]).date()
        last = datetime.fromisoformat(daily[-1]["date"]).date()
        if (last - first).days <= 3659:
            values = {d["date"]: d["questions"] for d in daily}
            daily = [
                {
                    "date": (first + timedelta(days=i)).isoformat(),
                    "questions": values.get((first + timedelta(days=i)).isoformat(), 0),
                }
                for i in range((last - first).days + 1)
            ]
    tokens = {
        "status": "not-connected",
        "source": "litellm",
        "total": None,
        "input": None,
        "output": None,
        "requests": None,
        "averagePerRequest": None,
        "costUsd": None,
    }
    if settings.litellm_url or settings.token_cache_path.exists():
        try:
            from .token_analytics import token_usage

            result = token_usage(
                cache,
                settings,
                start=a,
                end=b,
                range_value="all" if not a else range_value,
            )
            tokens = {
                **result["summary"],
                "status": "ready",
                "source": "litellm",
                "updatedAt": result["updatedAt"],
                "stale": result["dataState"]["stale"],
            }
        except Exception:
            tokens["status"] = "not-synced"
    return {
        "schemaVersion": 1,
        "source": payload["source"],
        "period": payload["period"],
        "updatedAt": payload["updatedAt"],
        "dataState": payload["dataState"],
        "summary": summary,
        "comparison": comparison,
        "daily": daily,
        "leaderTop10": leaders[:10],
        "integrations": {
            "tokens": tokens,
            "categories": {
                "status": "not-connected",
                "source": "embedding-classifier",
                "records": None,
                "classified": None,
            },
        },
    }
