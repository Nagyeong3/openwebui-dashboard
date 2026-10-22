from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from .organization import enrich, load_org

SEOUL = ZoneInfo("Asia/Seoul")
ALL = "전체"


def date_value(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Dates must use YYYY-MM-DD")
    return date.fromisoformat(value)


def period(start, end, range_value, latest):
    if bool(start) != bool(end):
        raise ValueError("Provide both start and end")
    if start:
        a, b = date_value(start), date_value(end)
        if a > b:
            raise ValueError("start must not exceed end")
        return a, b
    if range_value == "all":
        return None, None
    if range_value not in ("7d", "30d", "90d"):
        raise ValueError("range must be all, 7d, 30d or 90d")
    b = datetime.fromisoformat(latest).astimezone(SEOUL).date()
    return b - timedelta(days=int(range_value[:-1]) - 1), b


def choices(values):
    return [ALL, *sorted(set(values))]


def user_usage(
    cache,
    settings,
    *,
    start=None,
    end=None,
    range_value="30d",
    division=ALL,
    team=ALL,
    position=ALL,
    match_status=ALL,
    view="user",
    page=1,
    page_size=50,
    order="desc",
    search=""
):
    if view not in ("user", "team", "leader") or order not in ("asc", "desc"):
        raise ValueError("Invalid view or order")
    if not 1 <= page_size <= 1000 or page < 1:
        raise ValueError("Invalid pagination")
    users, messages, meta = cache.read()
    org, org_status = load_org(settings.org_csv)
    users = enrich(users, org)
    a, b = period(start, end, range_value, meta["last_success"])
    start_epoch = (
        datetime.combine(a, time.min, SEOUL).timestamp() if a else float("-inf")
    )
    end_epoch = (
        datetime.combine(b + timedelta(days=1), time.min, SEOUL).timestamp()
        if b
        else float("inf")
    )
    visible_users = [
        u
        for u in users
        if all(
            selected == ALL or u[key] == selected
            for key, selected in (
                ("division", division),
                ("team", team),
                ("position", position),
                ("mapping", match_status),
            )
        )
        and (view != "leader" or "팀장" in u["position"])
        and (
            not search or search.casefold() in (u["name"] + " " + u["team"]).casefold()
        )
    ]
    rows = {
        u["id"]: {
            **u,
            "questions": 0,
            "chats": 0,
            "attachments": 0,
            "lastUsedAt": None,
            "primaryModel": None,
        }
        for u in visible_users
    }
    chats, models, daily, team_chats = (
        defaultdict(set),
        defaultdict(Counter),
        Counter(),
        defaultdict(set),
    )
    all_chats = set()
    for m in messages:
        if m["user_id"] not in rows or not start_epoch <= m["created_at"] < end_epoch:
            continue
        row = rows[m["user_id"]]
        if m["role"] == "assistant" and m["model_id"]:
            models[m["user_id"]][m["model_id"]] += 1
        if m["role"] != "user":
            continue
        row["questions"] += 1
        row["attachments"] += m["has_files"]
        chats[m["user_id"]].add(m["chat_id"])
        all_chats.add(m["chat_id"])
        team_chats[(row["division"], row["team"])].add(m["chat_id"])
        instant = datetime.fromtimestamp(m["created_at"], timezone.utc).astimezone(
            SEOUL
        )
        row["lastUsedAt"] = instant.isoformat()
        daily[instant.date().isoformat()] += 1
    for user_id, row in rows.items():
        row["chats"] = len(chats[user_id])
        if models[user_id]:
            row["primaryModel"] = sorted(
                models[user_id].items(), key=lambda pair: (-pair[1], pair[0])
            )[0][0]
    records = sorted(
        rows.values(),
        key=lambda r: (
            (-r["questions"] if order == "desc" else r["questions"]),
            r["name"],
            r["id"],
        ),
    )
    for index, row in enumerate(records):
        row["rank"] = index + 1
    summary = {
        "users": len(records),
        "activeUsers": sum(r["questions"] > 0 for r in records),
        "zeroUsageUsers": sum(r["questions"] == 0 for r in records),
        "questions": sum(r["questions"] for r in records),
        "chats": len(all_chats),
        "attachmentQuestions": sum(r["attachments"] for r in records),
    }
    if a and b:
        if (b - a).days > 3659:
            raise ValueError("Date range must not exceed 3660 days")
        for days in range((b - a).days + 1):
            daily.setdefault((a + timedelta(days=days)).isoformat(), 0)
    if view == "team":
        grouped = {}
        for row in records:
            key = (row["division"], row["team"])
            r = grouped.setdefault(
                key,
                {
                    "division": key[0],
                    "team": key[1],
                    "users": 0,
                    "activeUsers": 0,
                    "questions": 0,
                    "attachmentQuestions": 0,
                    "chats": len(team_chats[key]),
                },
            )
            r["users"] += 1
            r["activeUsers"] += int(row["questions"] > 0)
            r["questions"] += row["questions"]
            r["attachmentQuestions"] += row["attachments"]
        records = sorted(
            grouped.values(),
            key=lambda r: (
                (-r["questions"] if order == "desc" else r["questions"]),
                r["division"],
                r["team"],
            ),
        )
    state = cache.status()
    stale = bool(state["runs"] and state["runs"][0]["status"] != "success")
    return {
        "schemaVersion": 1,
        "source": "openwebui-api-cache",
        "period": {
            "start": a.isoformat() if a else None,
            "end": b.isoformat() if b else None,
            "timezone": "Asia/Seoul",
            "range": "custom" if a else "all",
        },
        "updatedAt": meta["last_success"],
        "dataState": {
            "ready": True,
            "stale": stale,
            "activeRunId": state["activeRunId"],
            "lastFullReconciliation": meta.get("last_full"),
            "organization": org_status,
            "questionPolicy": "all-stored-user-message-ids",
            "tokens": "not-connected",
            "categories": "not-connected",
            "contentStored": False,
        },
        "filters": {
            "divisions": choices(u["division"] for u in users),
            "teams": choices(
                u["team"] for u in users if division == ALL or u["division"] == division
            ),
            "positions": choices(
                u["position"]
                for u in users
                if (division == ALL or u["division"] == division)
                and (team == ALL or u["team"] == team)
            ),
            "matchStatuses": choices(u["mapping"] for u in users),
        },
        "selected": {
            "division": division,
            "team": team,
            "position": position,
            "matchStatus": match_status,
            "view": view,
        },
        "summary": summary,
        "daily": [{"date": k, "questions": v} for k, v in sorted(daily.items())],
        "detail": {
            "view": view,
            "records": records[(page - 1) * page_size : page * page_size],
            "total": len(records),
            "page": page,
            "pageSize": page_size,
        },
    }
