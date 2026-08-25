#!/usr/bin/env python3
"""Maintain a small local cache of ready MiniMax console image asset IDs."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CACHE = Path.home() / ".cache" / "minimax-h3-console" / "assets.json"


def load_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "assets": {}}
    if not isinstance(data, dict) or not isinstance(data.get("assets"), dict):
        raise SystemExit(f"Invalid cache format: {path}")
    return data


def save_cache(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def cache_key(workspace_id: str, sha256: str) -> str:
    return f"{workspace_id}:{sha256.lower()}"


@contextmanager
def cache_lock(path: Path, exclusive: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lock_file.fileno(), operation)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    lookup = subparsers.add_parser("lookup")
    lookup.add_argument("--workspace-id", required=True)
    lookup.add_argument("--sha256", required=True)

    put = subparsers.add_parser("put")
    put.add_argument("--workspace-id", required=True)
    put.add_argument("--sha256", required=True)
    put.add_argument("--asset-id", required=True)
    put.add_argument("--content-type")
    put.add_argument("--filename")

    invalidate = subparsers.add_parser("invalidate")
    invalidate.add_argument("--workspace-id", required=True)
    invalidate.add_argument("--sha256", required=True)

    args = parser.parse_args()
    with cache_lock(args.cache, exclusive=args.command != "lookup"):
        data = load_cache(args.cache)
        key = cache_key(args.workspace_id, args.sha256)

        if args.command == "lookup":
            item = data["assets"].get(key)
            print(json.dumps({"hit": item is not None, "asset": item}, ensure_ascii=False, indent=2))
            return 0

        if args.command == "put":
            item = {
                "workspace_id": args.workspace_id,
                "sha256": args.sha256.lower(),
                "asset_id": args.asset_id,
                "status": "ready",
                "content_type": args.content_type,
                "filename": args.filename,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            data["assets"][key] = item
            save_cache(args.cache, data)
            print(json.dumps({"stored": True, "asset": item}, ensure_ascii=False, indent=2))
            return 0

        removed = data["assets"].pop(key, None)
        save_cache(args.cache, data)
        print(json.dumps({"invalidated": removed is not None}, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
