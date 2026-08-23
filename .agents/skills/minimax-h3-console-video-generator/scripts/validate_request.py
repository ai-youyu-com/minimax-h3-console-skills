#!/usr/bin/env python3
"""Validate a MiniMax H3 console task request before MCP submission."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any


MENTION_RE = re.compile(r"@([A-Za-z0-9_\-\u3400-\u4dbf\u4e00-\u9fff]+)")
PICTURE_RE = re.compile(r"<Picture\s+\d+>", re.IGNORECASE)
ALLOWED_MODES = {"t2v", "i2v", "r2v"}
ALLOWED_RATIOS = {"16:9", "9:16", "1:1"}
ALLOWED_ROLES = {"first_frame", "last_frame", "reference_image"}


def is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def validate(request: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    mode = request.get("mode")
    prompt = request.get("prompt")
    assets = request.get("assets", [])

    if mode not in ALLOWED_MODES:
        errors.append(f"mode must be one of {sorted(ALLOWED_MODES)}")

    if not isinstance(prompt, str) or not prompt.strip():
        errors.append("prompt must be a non-empty string")
        prompt = ""

    if not isinstance(assets, list):
        errors.append("assets must be an array")
        assets = []

    if not is_uuid(request.get("workspace_id")):
        errors.append("workspace_id must be a UUID")

    if not is_uuid(request.get("idempotency_key")):
        errors.append("idempotency_key must be a UUID")

    duration = request.get("duration_seconds")
    if duration is not None and (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not 4 <= duration <= 15
    ):
        errors.append("duration_seconds must be between 4 and 15")

    ratio = request.get("aspect_ratio")
    if ratio is not None and ratio not in ALLOWED_RATIOS:
        errors.append(f"aspect_ratio must be one of {sorted(ALLOWED_RATIOS)}")

    mention_names: list[str] = []
    for index, asset in enumerate(assets):
        label = f"assets[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{label} must be an object")
            continue
        if not is_uuid(asset.get("asset_id")):
            errors.append(f"{label}.asset_id must be a UUID")
        role = asset.get("role")
        if role not in ALLOWED_ROLES:
            errors.append(f"{label}.role must be one of {sorted(ALLOWED_ROLES)}")
        name = asset.get("mention_name")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                errors.append(f"{label}.mention_name must be a non-empty string")
            elif name.startswith("@"):
                errors.append(f"{label}.mention_name must not include @")
            elif not re.fullmatch(r"[A-Za-z0-9_\-\u3400-\u4dbf\u4e00-\u9fff]+", name):
                errors.append(f"{label}.mention_name contains unsupported characters")
            else:
                mention_names.append(name)

    duplicates = sorted({name for name in mention_names if mention_names.count(name) > 1})
    if duplicates:
        errors.append(f"duplicate mention_name values: {', '.join(duplicates)}")

    prompt_mentions = set(MENTION_RE.findall(prompt))
    declared_mentions = set(mention_names)

    unknown = sorted(prompt_mentions - declared_mentions)
    if unknown:
        errors.append(f"prompt contains unresolved mentions: {', '.join('@' + x for x in unknown)}")

    unused = sorted(declared_mentions - prompt_mentions)
    if unused:
        errors.append(f"assets are not referenced in prompt: {', '.join('@' + x for x in unused)}")

    if mode == "r2v":
        if not assets:
            errors.append("r2v requires at least one reference image")
        for index, asset in enumerate(assets):
            if isinstance(asset, dict) and asset.get("role") != "reference_image":
                errors.append(f"assets[{index}].role must be reference_image in r2v")
            if isinstance(asset, dict) and not asset.get("mention_name"):
                errors.append(f"assets[{index}].mention_name is required in r2v")
        leftovers = sorted(set(PICTURE_RE.findall(prompt)))
        if leftovers:
            errors.append(f"r2v prompt contains leftover Picture labels: {', '.join(leftovers)}")

    if mode == "t2v" and assets:
        errors.append("t2v must not include image assets")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, help="JSON file containing create_video_task arguments")
    args = parser.parse_args()

    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False))
        return 2

    if not isinstance(request, dict):
        print(json.dumps({"valid": False, "errors": ["request root must be an object"]}, ensure_ascii=False))
        return 2

    errors = validate(request)
    result = {
        "valid": not errors,
        "mode": request.get("mode"),
        "asset_count": len(request.get("assets", [])) if isinstance(request.get("assets", []), list) else None,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
