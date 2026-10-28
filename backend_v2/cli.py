import argparse
import json
import sys

from .cache import Cache
from .settings import Settings
from .sync import Synchronizer


def main():
    parser = argparse.ArgumentParser(
        description="OpenWebUI API analytics cache (no DB copy)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("sync")
    p.add_argument("--kind", choices=("full", "quick"), default="quick")
    token = sub.add_parser("token-sync")
    token.add_argument("--kind", choices=("full", "quick"), default="quick")
    category = sub.add_parser("category-classify")
    category.add_argument("--kind", choices=("pending", "retry"), default="pending")
    sub.add_parser("category-status")
    sub.add_parser("token-status")
    sub.add_parser("status")
    sub.add_parser("init")
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        if args.command in ("category-classify", "category-status"):
            from .category_store import CategoryStore
            from .category_sync import prepare, collect
            from .category_analytics import category_usage
            cache = Cache(settings.cache_path)
            store = CategoryStore(settings.category_cache_path)
            result = (collect(settings, cache, store, prepare(settings, cache, store, args.kind))
                      if args.command == "category-classify" else category_usage(cache, settings, range_value="all"))
            # Status CLI reports counts/jobs only, never employee rows.
            if args.command == "category-status":
                result = {k:result[k] for k in ("summary","activeRunId","runs")}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command in ("token-sync", "token-status"):
            from .token_store import TokenStore
            from .token_sync import prepare, collect

            store = TokenStore(settings.token_cache_path)
            result = (
                collect(settings, store, prepare(settings, store, args.kind))
                if args.command == "token-sync"
                else store.status()
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        cache = Cache(settings.cache_path)
        if args.command == "sync":
            result = Synchronizer(settings, cache).run(args.kind)
        else:
            result = cache.status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        # Expected exceptions are deliberately sanitized at the client/sync boundary.
        from .client import UpstreamError
        from .cache import BusyError

        message = (
            str(error)
            if isinstance(error, (ValueError, UpstreamError, BusyError, RuntimeError))
            else "Operation failed; check local configuration and cache permissions"
        )
        print(
            json.dumps({"ok": False, "error": message}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
