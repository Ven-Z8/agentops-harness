import argparse
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from app.api import create_api
from app.core.showcase import ShowcaseError, import_showcase


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("examples/showcase/governed-migration"),
    )
    parser.add_argument("--storage", type=Path, default=Path(".agentops/showcase.db"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--import-only", action="store_true")
    args = parser.parse_args()

    record = import_showcase(args.fixture, args.storage)
    url = f"http://{args.host}:{args.port}/cockpit?mission=governed-migration"
    print(f"Imported recorded showcase run {record.run_id}")
    if args.import_only:
        return 0
    if not args.no_open:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_api(storage_path=args.storage), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ShowcaseError as exc:
        print(f"showcase validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
