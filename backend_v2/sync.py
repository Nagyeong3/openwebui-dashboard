import hashlib
from datetime import datetime
import json
import math
import sqlite3
import time

from .cache import Cache, now_iso
from .client import ContractError, OpenWebUIClient, UpstreamError
from .settings import Settings


def timestamp(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ContractError("Invalid message timestamp; refusing to invent a date")
    seconds = value / 1000 if value > 10_000_000_000 else value
    if not 1577836800 <= seconds <= time.time() + 86400:
        raise ContractError("Message timestamp is out of supported range")
    return seconds


def normalize_message(message, owner):
    if not isinstance(message, dict):
        raise ContractError("Message must be an object")
    if (
        not all(
            isinstance(message.get(k), str) and message[k]
            for k in ("id", "user_id", "chat_id", "role")
        )
        or message["user_id"] != owner
    ):
        raise ContractError("Invalid message identity or user attribution")
    if message["role"] not in ("user", "assistant", "system", "tool"):
        raise ContractError("Unexpected message role")
    model, parent = message.get("model_id"), message.get("parent_id")
    if (model is not None and not isinstance(model, str)) or (
        parent is not None and not isinstance(parent, str)
    ):
        raise ContractError("Invalid message model/parent")
    files, usage = message.get("files"), message.get("usage")
    if (files is not None and not isinstance(files, list)) or (
        usage is not None and not isinstance(usage, dict)
    ):
        raise ContractError("Invalid message files/usage")
    # Cache no raw content, source text, file paths, prompts or provider keys.
    content_hash = hashlib.sha256(
        json.dumps(message.get("content"), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    # Keep only known numerical token fields. Missing usage remains null, never zero.
    tokens = None
    if usage is not None:
        tokens = {}
        for k in (
            "input_tokens",
            "output_tokens",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        ):
            v = usage.get(k)
            if v is not None:
                if (
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not math.isfinite(v)
                    or v < 0
                ):
                    raise ContractError("Invalid token usage")
                tokens[k] = v
    return (
        message["id"],
        owner,
        message["chat_id"],
        message["role"],
        parent,
        model,
        timestamp(message.get("created_at")),
        timestamp(message.get("updated_at")),
        int(bool(files)),
        content_hash,
        json.dumps(tokens) if tokens is not None else None,
    )


class Synchronizer:
    def __init__(self, settings: Settings, cache: Cache, client=None):
        self.settings, self.cache = settings, cache
        self.client = client or OpenWebUIClient(settings)
        self.source = hashlib.sha256(settings.base_url.rstrip("/").encode()).hexdigest()
        self.lease_seconds = max(600, settings.timeout * (settings.retries + 1) + 120)

    def run(self, kind="quick"):
        if kind not in ("quick", "full"):
            raise ValueError("Sync kind must be quick or full")
        state = self.cache.status()
        if not state["ready"]:
            kind = "full"
        collected_at = now_iso()
        cutoff = (
            (
                min(
                    time.time(),
                    datetime.fromisoformat(state["lastSuccess"]).timestamp(),
                )
                - self.settings.overlap_days * 86400
            )
            if kind == "quick"
            else None
        )
        run_id = self.cache.start(kind, cutoff, self.source, self.lease_seconds)
        count = 0
        try:
            known_users = self.cache.user_ids()
            users = self.client.users()
            self.cache.stage_users(run_id, users)
            for index, user in enumerate(users):
                # A newly discovered user may already have years of messages.
                user_cutoff = cutoff if user["id"] in known_users else None
                seen = set()
                previous_time = float("inf")
                for page in range(self.settings.max_pages_per_user):
                    self.cache.heartbeat(run_id, self.lease_seconds)
                    messages = self.client.messages(
                        user["id"], page * self.settings.page_size
                    )
                    rows = []
                    older = False
                    for message in messages:
                        row = normalize_message(message, user["id"])
                        if row[0] in seen:
                            raise ContractError(
                                "Message pagination shifted or repeated; retry synchronization"
                            )
                        seen.add(row[0])
                        if row[6] > previous_time:
                            raise ContractError(
                                "Messages are not ordered newest first; cannot safely collect"
                            )
                        previous_time = row[6]
                        if user_cutoff is None or row[6] >= user_cutoff:
                            rows.append(row)
                        else:
                            older = True
                    self.cache.stage_messages(run_id, rows)
                    count += len(rows)
                    self.cache.progress(run_id, index, count)
                    if len(messages) < self.settings.page_size or older:
                        break
                else:
                    raise ContractError(
                        "Maximum pages reached; collection is incomplete"
                    )
                self.cache.progress(run_id, index + 1, count)
            self.cache.heartbeat(run_id, self.lease_seconds)
            # No global snapshot/cursor in this upstream API. Catch roster drift explicitly.
            final_users = self.client.users()
            if {u["id"] for u in users} != {u["id"] for u in final_users}:
                raise ContractError(
                    "User roster changed during sync; retry synchronization"
                )
            self.cache.publish(run_id, self.source, collected_at)
            return {
                "ok": True,
                "runId": run_id,
                "kind": kind,
                "users": len(users),
                "messages": count,
            }
        except Exception as error:
            safe = (
                str(error)
                if isinstance(error, UpstreamError)
                else "Synchronization failed; previous successful cache preserved"
            )
            self.cache.fail(run_id, safe)
            if isinstance(error, sqlite3.IntegrityError):
                raise ContractError(
                    "Duplicate staged identity; previous data preserved"
                ) from None
            if not isinstance(error, UpstreamError):
                raise RuntimeError(safe) from None
            raise
