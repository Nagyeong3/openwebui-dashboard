"""CSV enriches the API roster, never adds users. No pandas/Streamlit dependency."""

from collections import Counter, defaultdict
import csv
import io
from pathlib import Path
import unicodedata


class MappingError(RuntimeError):
    pass


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).casefold()


def load_org(path: Path | None):
    if path is None:
        return [], "not_configured"
    try:
        raw = path.read_bytes()
    except OSError:
        raise MappingError(
            "Organization CSV cannot be read; check ORG_USER_CSV_PATH"
        ) from None
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        raise MappingError("Organization CSV must be UTF-8 or CP949")
    try:
        reader = csv.DictReader(io.StringIO(text), strict=True)
        headers = [s.strip() for s in (reader.fieldnames or [])]
        if len(set(headers)) != len(headers):
            raise MappingError("Organization CSV has duplicate headers")
        reader.fieldnames = headers
        aliases = {
            "division": ("실", "본부", "division"),
            "team": ("팀", "team"),
            "position": ("직급", "position"),
            "name": ("이름", "성명", "사용자명", "name"),
            "id": ("사용자 ID", "사용자ID", "user_id", "id"),
        }
        selected = {
            key: next((a for a in values if a in headers), None)
            for key, values in aliases.items()
        }
        if any(selected[k] is None for k in ("division", "team", "position", "name")):
            raise MappingError(
                "Organization CSV requires division/team/position/name columns"
            )
        records = []
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise MappingError("Organization CSV has malformed rows")
            item = {k: row.get(v, "").strip() if v else "" for k, v in selected.items()}
            if item["name"] or item["id"]:
                records.append(item)
        return records, "loaded"
    except csv.Error:
        raise MappingError("Organization CSV cannot be parsed") from None


def enrich(users, records):
    ids, names = defaultdict(list), defaultdict(list)
    upstream_names = Counter(normalized(u["name"]) for u in users)
    for item in records:
        if item["id"]:
            ids[item["id"]].append(item)
        if normalized(item["name"]):
            names[normalized(item["name"])].append(item)
    result = []
    for user in users:
        match, status = None, "미매칭"
        name = normalized(user["name"])
        if user["id"] in ids:
            if len(ids[user["id"]]) == 1:
                match = ids[user["id"]][0]
            else:
                status = "동명이인 확인 필요"
        elif name and name in names:
            matches = names[name]
            if len(matches) != 1 or upstream_names[name] != 1:
                status = "동명이인 확인 필요"
            elif not matches[0]["id"]:
                match = matches[0]
            # A CSV row with another explicit ID must not be reused by name.
        if match:
            status = "매핑 완료"
        result.append(
            {
                **user,
                "division": (match["division"] if match else "") or "기타",
                "team": (match["team"] if match else "") or "기타",
                "position": (match["position"] if match else "") or "기타",
                "mapping": status,
                "source": "openwebui-api",
            }
        )
    return result
