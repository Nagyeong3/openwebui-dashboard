from collections import defaultdict
import csv
from datetime import datetime, time, timedelta, timezone
from .analytics import ALL, SEOUL, choices, period
from .organization import enrich, load_org, normalized
from .token_store import TokenStore


def prices(path):
    if not path:
        return {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            result = {}
            for row in csv.DictReader(f):
                model = row["model"].strip()
                if not model or model in result:
                    raise ValueError()
                from .token_sync import numeric

                result[model] = (
                    numeric(row["input_per_million_usd"]),
                    numeric(row["output_per_million_usd"]),
                )
                if None in result[model]:
                    raise ValueError()
            return result
    except (OSError, KeyError, ValueError):
        raise ValueError(
            "Model prices CSV requires unique model,input_per_million_usd,output_per_million_usd columns"
        ) from None


def aggregate(rows):
    def complete(key):
        return (
            sum(r[key] for r in rows) if all(r[key] is not None for r in rows) else None
        )

    total = complete("total")
    cost = complete("costUsd")
    return {
        "total": total,
        "input": complete("prompt"),
        "output": complete("completion"),
        "costUsd": cost,
        "requests": len(rows),
        "averagePerRequest": (
            round(total / len(rows), 1) if rows and total is not None else None
        ),
        "knownCostUsd": sum(r["costUsd"] or 0 for r in rows),
        "missingCostRequests": sum(r["costUsd"] is None for r in rows),
        "missingTokenRequests": sum(r["total"] is None for r in rows),
        "estimatedCostRequests": sum(r["costSource"] == "csv-estimate" for r in rows),
    }


def token_usage(
    cache,
    settings,
    *,
    start=None,
    end=None,
    range_value="7d",
    division=ALL,
    team=ALL,
    position=ALL,
    model=ALL,
    page=1,
    page_size=50,
    paginate=True
):
    if page < 1 or not 1 <= page_size <= 1000:
        raise ValueError("Invalid token pagination")
    store = TokenStore(settings.token_cache_path)
    logs, meta = store.read(settings)
    users, _, _ = cache.read()
    org, org_status = load_org(settings.org_csv)
    users = enrich(users, org)
    by_id = {u["id"]: u for u in users}
    by_email = defaultdict(list)
    by_name = defaultdict(list)
    for u in users:
        if normalized(u["email"]):
            by_email[normalized(u["email"])].append(u)
        if normalized(u["name"]):
            by_name[normalized(u["name"])].append(u)
    a, b = period(start, end, range_value, meta["last_success"])
    lo = datetime.combine(a, time.min, SEOUL).timestamp() if a else float("-inf")
    hi = (
        datetime.combine(b + timedelta(days=1), time.min, SEOUL).timestamp()
        if b
        else float("inf")
    )
    if a and b and (b - a).days > 3659:
        raise ValueError("Date range must not exceed 3660 days")
    price = prices(settings.model_prices_csv)
    filtered = []
    for log in logs:
        if not lo <= log["at"] < hi or model != ALL and log["model"] != model:
            continue
        ident = log["identity_id"]
        user = by_id.get(ident)
        if not user and ident and "@" in ident:
            found = by_email[normalized(ident)]
            user = found[0] if len(found) == 1 else None
        if not ident:
            found = by_email[normalized(log["identity_email"])]
            if len(found) == 1:
                user = found[0]
            elif not log["identity_email"]:
                found = by_name[normalized(log["identity_name"])]
                user = found[0] if len(found) == 1 else None
        if any(s != ALL for s in (division, team, position)) and (
            not user
            or any(
                s != ALL and user[k] != s
                for k, s in [
                    ("division", division),
                    ("team", team),
                    ("position", position),
                ]
            )
        ):
            continue
        cost = log["spend"]
        source = "logged" if cost is not None else "missing"
        if (
            cost is None
            and log["model"] in price
            and log["prompt"] is not None
            and log["completion"] is not None
        ):
            rates = price[log["model"]]
            cost = (log["prompt"] * rates[0] + log["completion"] * rates[1]) / 1000000
            source = "csv-estimate"
        filtered.append(
            {
                **log,
                "userId": user["id"] if user else None,
                "userName": user["name"] if user else None,
                "team": user["team"] if user else None,
                "costUsd": cost,
                "costSource": source,
            }
        )
    daily = defaultdict(list)
    per_user = defaultdict(list)
    per_model = defaultdict(list)
    for row in filtered:
        daily[
            datetime.fromtimestamp(row["at"], timezone.utc)
            .astimezone(SEOUL)
            .date()
            .isoformat()
        ].append(row)
        if row["userId"]:
            per_user[row["userId"]].append(row)
        per_model[row["model"]].append(row)
    if a and b:
        for i in range((b - a).days + 1):
            daily.setdefault((a + timedelta(days=i)).isoformat(), [])
    ranking = sorted(
        [
            {
                "id": uid,
                "name": by_id[uid]["name"],
                "team": by_id[uid]["team"],
                **aggregate(rows),
            }
            for uid, rows in per_user.items()
        ],
        key=lambda r: (-(r["total"] or 0), r["name"], r["id"]),
    )
    team_groups = defaultdict(list)
    for row in filtered:
        if row["userId"]:
            u = by_id[row["userId"]]
            team_groups[(u["division"], u["team"])].append(row)
    teams = [
        {"division": key[0], "team": key[1], **aggregate(rows)}
        for key, rows in sorted(team_groups.items())
    ]
    summary = aggregate(filtered)
    summary.update(
        {
            "users": len(per_user),
            "unidentifiedRequests": sum(r["userId"] is None for r in filtered),
        }
    )
    state = store.status()
    return {
        "schemaVersion": 1,
        "source": "litellm-api-cache",
        "period": {
            "start": a.isoformat() if a else None,
            "end": b.isoformat() if b else None,
            "timezone": "Asia/Seoul",
        },
        "updatedAt": meta["last_success"],
        "summary": summary,
        "daily": [{"date": d, **aggregate(rows)} for d, rows in sorted(daily.items())],
        "topUsers": ranking[:10],
        "users": ranking,
        "teams": teams,
        "models": [
            {"model": m, **aggregate(rows)} for m, rows in sorted(per_model.items())
        ],
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
            "models": choices(r["model"] for r in logs),
        },
        "selected": {
            "division": division,
            "team": team,
            "position": position,
            "model": model,
        },
        "dataState": {
            "stale": bool(state["runs"] and state["runs"][0]["status"] != "success"),
            "organization": org_status,
            "coverageStart": state["coverageStart"],
        },
        "detail": {
            "records": [
                {
                    k: r[k]
                    for k in (
                        "id",
                        "at",
                        "model",
                        "prompt",
                        "completion",
                        "total",
                        "userName",
                        "team",
                        "costUsd",
                        "costSource",
                    )
                }
                for r in (
                    sorted(filtered, key=lambda r: (-r["at"], r["id"]))[
                        (page - 1) * page_size : page * page_size
                    ]
                    if paginate
                    else sorted(filtered, key=lambda r: (-r["at"], r["id"]))
                )
            ],
            "total": len(filtered),
            "page": page,
            "pageSize": page_size,
        },
    }
