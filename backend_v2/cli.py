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
    sub.add_parser("status")
    sub.add_parser("init")
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
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
