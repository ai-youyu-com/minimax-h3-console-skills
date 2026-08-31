#!/usr/bin/env python3
"""Discover, validate, and version local client-ad workflow projects."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import mimetypes
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BRIEF_NAME = "ad-brief.md"
SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
REPLACEMENT_STEM = "approved-keyframe"
CURRENT_SCHEMA_VERSION = 4
CANDIDATE_IDS = tuple(str(index) for index in range(1, 6))
SCRIPT_CANDIDATE_FIELDS = {
    "candidate_id",
    "creative_direction",
    "hook",
    "storyboard",
    "voiceover",
    "source_mapping",
    "post_production_text",
}
V4_SCRIPT_CANDIDATE_FIELDS = {
    "candidate_id",
    "plan_name",
    "creative_idea",
    "hook",
    "timeline",
    "source_mapping",
}
V4_TIMELINE_FIELDS = {"time", "visual", "voiceover", "subtitle", "cta"}
TERMINAL_STAGES = {"succeeded", "cancelled"}
ALLOWED_STAGES = {
    "script_review",
    "keyframe_review",
    "task_review",
    "submitted",
    "monitoring",
    "succeeded",
    "failed",
    "cancelled",
    "proposal_review",
    "proposal_locked",
    "production_ready",
    "script_locked",
    "storyboard_review",
    "storyboard_locked",
}
TRANSITIONS = {
    "script_review": {"cancelled"},
    "keyframe_review": {"script_review", "task_review", "cancelled"},
    "task_review": {"script_review", "keyframe_review", "submitted", "cancelled"},
    "submitted": {"monitoring", "succeeded", "failed"},
    "monitoring": {"monitoring", "succeeded", "failed"},
    "failed": {"task_review", "cancelled"},
    "succeeded": set(),
    "cancelled": set(),
    "proposal_review": {"proposal_locked", "cancelled"},
    "proposal_locked": {"production_ready", "proposal_review", "cancelled"},
    "production_ready": {"submitted", "proposal_review", "cancelled"},
    "script_locked": {"storyboard_review", "script_review", "cancelled"},
    "storyboard_review": {"storyboard_locked", "script_review", "cancelled"},
    "storyboard_locked": {"production_ready", "storyboard_review", "script_review", "cancelled"},
}
ARTIFACT_KINDS = {
    "script",
    "keyframe-prompt",
    "keyframe",
    "h3-prompt",
    "h3-validation",
    "task-preview",
    "request",
    "request-validation",
    "task-result",
    "client-feedback",
    "dimension-reference",
    "dimension-reference-image",
    "aggregate-keyframe-prompt",
    "aggregate-keyframe",
    "proposal-package",
    "production-package",
    "asset-upload",
    "retry-authorization",
    "script-proposal",
    "script-package",
    "final-script",
    "script-lock",
    "visual-plan",
    "storyboard-package",
    "storyboard-lock",
}
SENSITIVE_KEYS = {
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "presigned_url",
    "upload_url",
    "upload_headers",
}
I2VA_OPENING = (
    "For the target video, at 0.00 seconds into the target video, "
    "<Picture 1> (from [Shot 1]) is fully referenced."
)

FIELD_ALIASES = {
    "project_name": {"项目名称", "project name"},
    "offering": {"产品或服务", "product or service", "offering"},
    "selling_points": {"可核验卖点", "verified selling points", "selling points"},
    "objective": {"广告目标", "advertising goal", "objective"},
    "cta": {"cta", "行动号召", "call to action"},
    "brand": {"品牌", "brand"},
    "audience": {"目标受众", "target audience", "audience"},
    "language": {"语言", "language"},
    "visual_style": {"视觉风格", "visual style"},
    "must_preserve": {"必须保留", "must preserve"},
    "prohibited_claims": {"禁止声明", "prohibited claims"},
    "duration_seconds": {"时长", "duration", "duration seconds"},
    "aspect_ratio": {"画幅比例", "aspect ratio"},
    "quality": {"质量", "quality"},
    "workspace_id": {"目标工作区", "workspace", "workspace id"},
    "asset_roles": {"素材角色", "asset roles"},
}
REQUIRED_FIELDS = {"project_name", "offering", "selling_points", "objective", "cta"}
LIST_FIELDS = {"selling_points", "must_preserve", "prohibited_claims"}
BRIEF_HEADINGS = {
    "project_name": "项目名称",
    "offering": "产品或服务",
    "selling_points": "可核验卖点",
    "objective": "广告目标",
    "cta": "CTA",
    "brand": "品牌",
    "audience": "目标受众",
    "language": "语言",
    "visual_style": "视觉风格",
    "must_preserve": "必须保留",
    "prohibited_claims": "禁止声明",
    "duration_seconds": "时长",
    "aspect_ratio": "画幅比例",
    "quality": "质量",
    "workspace_id": "目标工作区",
    "asset_roles": "素材角色",
}


class WorkflowError(ValueError):
    """Raised for invalid project or state input."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def canonical_field(heading: str) -> str | None:
    normalized = normalize_heading(heading)
    for field, aliases in FIELD_ALIASES.items():
        if normalized in {normalize_heading(alias) for alias in aliases}:
            return field
    return None


def split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    active: str | None = None
    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            active = match.group(1)
            sections.setdefault(active, [])
        elif active is not None:
            sections[active].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def parse_list(value: str) -> list[str]:
    items: list[str] = []
    for line in value.splitlines():
        cleaned = re.sub(r"^\s*[-*+]\s+", "", line).strip()
        if cleaned and not cleaned.startswith("|"):
            items.append(cleaned)
    return items


def parse_scalar(value: str) -> str:
    return " ".join(line.strip() for line in value.splitlines() if line.strip())


def parse_asset_table(value: str) -> list[dict[str, str]]:
    rows = [line.strip() for line in value.splitlines() if line.strip().startswith("|")]
    if not rows:
        return []
    cells = [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]
    if len(cells) < 2:
        return []
    headers = [normalize_heading(cell) for cell in cells[0]]
    if all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells[1]):
        cells = [cells[0], *cells[2:]]
    aliases = {
        "filename": {"文件名", "filename", "file"},
        "role": {"角色", "role"},
        "must_preserve": {"必须保留", "must preserve"},
        "notes": {"说明", "notes", "description"},
    }
    indexes: dict[str, int] = {}
    for key, names in aliases.items():
        normalized_names = {normalize_heading(name) for name in names}
        for index, header in enumerate(headers):
            if header in normalized_names:
                indexes[key] = index
                break
    if "filename" not in indexes:
        raise WorkflowError("素材角色表必须包含“文件名”或“filename”列")
    parsed: list[dict[str, str]] = []
    for row in cells[1:]:
        if not any(row):
            continue
        item = {
            key: row[index].strip() if index < len(row) else ""
            for key, index in indexes.items()
        }
        if item.get("filename"):
            parsed.append(item)
    return parsed


def normalize_ingest_scalar(value: Any, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise WorkflowError(f"聊天简报字段 {field} 必须是文本或数字")
    return " ".join(str(value).split())


def normalize_ingest_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        raise WorkflowError(f"聊天简报字段 {field} 必须是文本或数组")
    normalized = [normalize_ingest_scalar(item, field) for item in values]
    return [item for item in normalized if item]


def safe_project_slug(value: str) -> str:
    slug = re.sub(r"[^\w]+", "-", value.casefold(), flags=re.UNICODE).replace("_", "-")
    slug = re.sub(r"-+", "-", slug).strip("-.")
    return slug[:60].rstrip("-.") or "client-ad"


def safe_asset_filename(name: str) -> str:
    path = Path(name)
    suffix = path.suffix.casefold()
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", path.stem).strip(" .-") or "asset"
    if stem.casefold() == REPLACEMENT_STEM or is_generated_root_image(Path(stem + suffix)):
        stem = "source-" + stem
    return stem[:80].rstrip(" .-") + suffix


def render_chat_brief(payload: dict[str, Any], filename_map: dict[str, str]) -> str:
    unknown = sorted(set(payload) - set(BRIEF_HEADINGS))
    if unknown:
        raise WorkflowError("聊天简报包含未知字段: " + ", ".join(unknown))

    normalized: dict[str, Any] = {}
    for field in BRIEF_HEADINGS:
        value = payload.get(field)
        if field in LIST_FIELDS:
            normalized[field] = normalize_ingest_list(value, field)
        elif field == "asset_roles":
            if value is None:
                normalized[field] = []
            elif not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                raise WorkflowError("聊天简报字段 asset_roles 必须是对象数组")
            else:
                roles: list[dict[str, str]] = []
                for item in value:
                    original = normalize_ingest_scalar(item.get("filename"), "asset_roles.filename")
                    mapped = filename_map.get(original.casefold())
                    if not mapped:
                        raise WorkflowError(f"素材角色引用了未上传图片: {original}")
                    roles.append(
                        {
                            "filename": mapped,
                            "role": normalize_ingest_scalar(item.get("role"), "asset_roles.role"),
                            "must_preserve": normalize_ingest_scalar(
                                item.get("must_preserve"), "asset_roles.must_preserve"
                            ),
                            "notes": normalize_ingest_scalar(item.get("notes"), "asset_roles.notes"),
                        }
                    )
                normalized[field] = roles
        else:
            normalized[field] = normalize_ingest_scalar(value, field)

    normalized["duration_seconds"] = normalized["duration_seconds"] or "15"
    normalized["aspect_ratio"] = normalized["aspect_ratio"] or "9:16"
    normalized["quality"] = normalized["quality"] or "high"
    missing = sorted(field for field in REQUIRED_FIELDS if not normalized.get(field))
    if missing:
        raise WorkflowError("聊天信息缺少必填字段: " + ", ".join(missing))

    sections = ["# Client Ad Brief"]
    for field, heading in BRIEF_HEADINGS.items():
        value = normalized.get(field)
        if value in (None, "", []):
            continue
        sections.extend(["", f"## {heading}"])
        if field in LIST_FIELDS:
            sections.extend(f"- {item}" for item in value)
        elif field == "asset_roles":
            sections.extend(
                [
                    "| 文件名 | 角色 | 必须保留 | 说明 |",
                    "|---|---|---|---|",
                ]
            )
            for item in value:
                cells = [
                    item.get("filename", ""),
                    item.get("role", ""),
                    item.get("must_preserve", ""),
                    item.get("notes", ""),
                ]
                sections.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
        else:
            sections.append(str(value))
    return "\n".join(sections).rstrip() + "\n"


def ingest_chat_project(
    workspace_root: Path, brief_json: Path, images: list[Path], slug: str | None = None
) -> dict[str, Any]:
    workspace_root = workspace_root.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(brief_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取聊天简报 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise WorkflowError("聊天简报 JSON 根节点必须是对象")
    if not images:
        raise WorkflowError("聊天导入至少需要一张 PNG、JPEG 或 WebP 图片")

    planned: list[tuple[Path, str]] = []
    filename_map: dict[str, str] = {}
    used_names: set[str] = set()
    for source in images:
        source = source.resolve()
        if not source.is_file():
            raise WorkflowError(f"上传图片不存在: {source}")
        if source.suffix.casefold() not in SUPPORTED_IMAGES:
            raise WorkflowError(f"不支持的上传图片格式: {source.name}")
        original_key = source.name.casefold()
        if original_key in filename_map:
            raise WorkflowError(f"上传图片文件名重复，无法可靠映射素材角色: {source.name}")
        candidate = safe_asset_filename(source.name)
        stem, suffix = Path(candidate).stem, Path(candidate).suffix
        index = 2
        while candidate.casefold() in used_names:
            candidate = f"{stem}-{index:02d}{suffix}"
            index += 1
        used_names.add(candidate.casefold())
        filename_map[original_key] = candidate
        planned.append((source, candidate))

    brief_text = render_chat_brief(payload, filename_map)
    requested_slug = safe_project_slug(slug or str(payload.get("project_name") or "client-ad"))
    project_dir = workspace_root / requested_slug
    index = 2
    while project_dir.exists():
        project_dir = workspace_root / f"{requested_slug}-{index:02d}"
        index += 1

    staging = workspace_root / f".{project_dir.name}.ingest-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    try:
        (staging / BRIEF_NAME).write_text(brief_text, encoding="utf-8")
        for source, filename in planned:
            shutil.copy2(source, staging / filename)
        inspection = inspect_project(staging)
        if not inspection["valid"]:
            raise WorkflowError("聊天项目校验失败: " + "; ".join(inspection["errors"]))
        staging.replace(project_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    inspection = inspect_project(project_dir)
    return {
        "project_dir": str(project_dir.resolve()),
        "brief_path": inspection["brief_path"],
        "assets": inspection["assets"],
        "valid": inspection["valid"],
        "errors": inspection["errors"],
    }


def parse_brief(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise WorkflowError("ad-brief.md 必须使用 UTF-8 编码") from exc
    sections = split_sections(text)
    values: dict[str, Any] = {}
    errors: list[str] = []
    for heading, body in sections.items():
        field = canonical_field(heading)
        if not field:
            continue
        if field == "asset_roles":
            try:
                values[field] = parse_asset_table(body)
            except WorkflowError as exc:
                errors.append(str(exc))
        elif field in LIST_FIELDS:
            values[field] = parse_list(body)
        else:
            values[field] = parse_scalar(body)

    for field in sorted(REQUIRED_FIELDS):
        if not values.get(field):
            errors.append(f"缺少必填字段: {field}")

    duration_raw = values.get("duration_seconds") or "15"
    try:
        duration = float(duration_raw)
        if not 4 <= duration <= 15:
            raise ValueError
        values["duration_seconds"] = int(duration) if duration.is_integer() else duration
    except (TypeError, ValueError):
        errors.append("时长必须是 4 到 15 秒之间的数字")

    ratio = values.get("aspect_ratio") or "9:16"
    if ratio not in {"16:9", "9:16", "1:1"}:
        errors.append("画幅比例必须是 16:9、9:16 或 1:1")
    values["aspect_ratio"] = ratio

    quality = (values.get("quality") or "high").casefold()
    if quality not in {"high", "standard"}:
        errors.append("质量必须是 high 或 standard")
    values["quality"] = quality
    values["language"] = values.get("language") or "auto"
    values["audience"] = values.get("audience") or "general prospective customers"
    values["asset_roles"] = values.get("asset_roles") or []

    workspace_id = values.get("workspace_id")
    if workspace_id:
        try:
            uuid.UUID(workspace_id)
        except ValueError:
            errors.append("目标工作区必须是有效 UUID")
    return values, errors


def image_metadata(path: Path) -> dict[str, Any]:
    content_type = mimetypes.types_map.get(path.suffix.casefold(), "application/octet-stream")
    if path.suffix.casefold() == ".jpg":
        content_type = "image/jpeg"
    return {
        "filename": path.name,
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "content_type": content_type,
    }


def is_generated_root_image(path: Path) -> bool:
    stem = path.stem.casefold()
    return bool(re.fullmatch(r"(?:aggregate-)?keyframe-v\d+", stem)) or stem == "aggregate-keyframe"


def inspect_project(project: Path) -> dict[str, Any]:
    project = project.resolve()
    brief_path = project if project.is_file() else project / BRIEF_NAME
    if brief_path.name.casefold() != BRIEF_NAME or not brief_path.is_file():
        raise WorkflowError(f"找不到 {BRIEF_NAME}: {brief_path}")
    project_dir = brief_path.parent
    brief, errors = parse_brief(brief_path)

    source_images: list[Path] = []
    replacements: list[Path] = []
    for path in sorted(project_dir.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.casefold() not in SUPPORTED_IMAGES:
            continue
        if path.stem.casefold() == REPLACEMENT_STEM:
            replacements.append(path)
        elif is_generated_root_image(path):
            continue
        else:
            source_images.append(path)

    if not source_images:
        errors.append("项目根目录没有可用的 PNG、JPEG 或 WebP 源图片")
    if len(replacements) > 1:
        errors.append("approved-keyframe.* 只能保留一个格式版本")

    filenames = {path.name.casefold(): path for path in source_images}
    seen_roles: set[str] = set()
    role_map: dict[str, dict[str, str]] = {}
    for row in brief.get("asset_roles", []):
        filename = row["filename"]
        if Path(filename).name != filename:
            errors.append(f"素材角色文件名不能包含目录: {filename}")
            continue
        key = filename.casefold()
        if key in seen_roles:
            errors.append(f"素材角色表重复文件: {filename}")
            continue
        seen_roles.add(key)
        if key not in filenames:
            errors.append(f"素材角色表引用了不存在的根目录图片: {filename}")
            continue
        role_map[key] = row

    assets = []
    for path in source_images:
        metadata = image_metadata(path)
        metadata["declared_role"] = role_map.get(path.name.casefold(), {})
        assets.append(metadata)

    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "valid": not errors,
        "errors": errors,
        "project_dir": str(project_dir),
        "brief_path": str(brief_path),
        "brief_sha256": sha256_file(brief_path),
        "brief": brief,
        "assets": assets,
        "approved_keyframe": image_metadata(replacements[0]) if len(replacements) == 1 else None,
    }


def discover(root: Path) -> list[dict[str, Any]]:
    root = root.resolve()
    projects: list[dict[str, Any]] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if not name.startswith(".") and name.casefold() != "output"]
        matches = [name for name in files if name.casefold() == BRIEF_NAME]
        if not matches:
            continue
        project_dir = Path(current).resolve()
        brief_path = project_dir / next(name for name in matches if name.casefold() == BRIEF_NAME)
        try:
            inspection = inspect_project(project_dir)
        except (OSError, WorkflowError) as exc:
            projects.append(
                {
                    "project_dir": str(project_dir),
                    "brief_path": str(brief_path.resolve()),
                    "valid": False,
                    "errors": [str(exc)],
                    "project_name": None,
                    "asset_count": 0,
                }
            )
            continue
        projects.append(
            {
                "project_dir": inspection["project_dir"],
                "brief_path": inspection["brief_path"],
                "valid": inspection["valid"],
                "errors": inspection["errors"],
                "project_name": inspection["brief"].get("project_name"),
                "asset_count": len(inspection["assets"]),
            }
        )
    return sorted(projects, key=lambda item: item["project_dir"].casefold())


def atomic_json_write(path: Path, data: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def start_run(project: Path, run_id: str | None = None, schema_version_override: int | None = None) -> dict[str, Any]:
    inspection = inspect_project(project)
    if not inspection["valid"]:
        raise WorkflowError("项目校验失败: " + "; ".join(inspection["errors"]))
    if run_id is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", run_id):
        raise WorkflowError("run-id 只能包含字母、数字、点、下划线和连字符")
    run_dir = Path(inspection["project_dir"]) / "output" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    created = now_iso()
    manifest_path = run_dir / "manifest.json"
    state_path = run_dir / "state.json"
    atomic_json_write(manifest_path, inspection)
    run_schema = schema_version_override or CURRENT_SCHEMA_VERSION
    if run_schema not in {1, 2, 3, 4}:
        raise WorkflowError("schema version 必须是 1、2、3 或 4")
    initial_stage = "proposal_review" if run_schema == 3 else "script_review"
    state = {
        "schema_version": run_schema,
        "run_id": run_id,
        "project_dir": inspection["project_dir"],
        "stage": initial_stage,
        "created_at": created,
        "updated_at": created,
        "artifacts": {},
        "history": [{"at": created, "event": "run_started", "stage": initial_stage}],
    }
    atomic_json_write(state_path, state)
    return {"run_dir": str(run_dir.resolve()), "manifest": str(manifest_path), "state": state}


def load_state(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    run_dir = run_dir.resolve()
    state_path = run_dir / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取运行状态: {exc}") from exc
    return state_path, state


def artifact_entry(state: dict[str, Any], kind: str, version: int | None = None) -> dict[str, Any]:
    entries = state.get("artifacts", {}).get(kind, [])
    if not entries:
        raise WorkflowError(f"缺少产物: {kind}")
    if version is None:
        return entries[-1]
    for entry in entries:
        if entry.get("version") == version:
            return entry
    raise WorkflowError(f"找不到产物版本: {kind} v{version}")


def schema_version(state: dict[str, Any]) -> int:
    value = state.get("schema_version", 1)
    return value if isinstance(value, int) else 1


def validate_candidate_id(candidate_id: str | None) -> str:
    value = str(candidate_id or "").strip()
    if value not in CANDIDATE_IDS:
        raise WorkflowError("candidate-id 必须是 1、2、3、4 或 5")
    return value


def validate_script_set(path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"v2 script 必须是有效 JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        raise WorkflowError("v2 script 根节点必须包含 candidates 数组")
    candidates = payload["candidates"]
    if len(candidates) != len(CANDIDATE_IDS):
        raise WorkflowError("v2 script 必须恰好包含 5 个候选")
    ids: list[str] = []
    for item in candidates:
        if not isinstance(item, dict):
            raise WorkflowError("script candidates 的每一项都必须是对象")
        missing = sorted(
            field
            for field in SCRIPT_CANDIDATE_FIELDS
            if field not in item or item[field] in (None, "", [])
        )
        if missing:
            raise WorkflowError("script candidate 缺少字段: " + ", ".join(missing))
        candidate_id = validate_candidate_id(str(item.get("candidate_id")))
        if not isinstance(item.get("storyboard"), list):
            raise WorkflowError(f"候选 {candidate_id} 的 storyboard 必须是非空数组")
        ids.append(candidate_id)
    if tuple(ids) != CANDIDATE_IDS:
        raise WorkflowError("script candidates 必须按 1、2、3、4、5 排列且不得重复")
    return tuple(ids)


def validate_v4_timeline(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise WorkflowError(f"{label}.timeline 必须是非空数组")
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise WorkflowError(f"{label}.timeline[{index}] 必须是对象")
        missing = sorted(field for field in V4_TIMELINE_FIELDS if field not in row)
        if missing:
            raise WorkflowError(f"{label}.timeline[{index}] 缺少字段: " + ", ".join(missing))
        if any(row[field] is None for field in V4_TIMELINE_FIELDS):
            raise WorkflowError(f"{label}.timeline[{index}] 字段不得为 null")
    return value


def validate_script_proposal(path: Path) -> dict[str, Any]:
    payload = read_json_file(path, "script-proposal")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(CANDIDATE_IDS):
        raise WorkflowError("script-proposal 必须恰好包含 5 个候选")
    ids: list[str] = []
    for item in candidates:
        if not isinstance(item, dict):
            raise WorkflowError("script-proposal.candidates 的每一项都必须是对象")
        missing = sorted(
            field for field in V4_SCRIPT_CANDIDATE_FIELDS
            if field not in item or item[field] in (None, "", [])
        )
        if missing:
            raise WorkflowError("script-proposal candidate 缺少字段: " + ", ".join(missing))
        candidate_id = validate_candidate_id(str(item.get("candidate_id")))
        validate_v4_timeline(item.get("timeline"), f"候选 {candidate_id}")
        ids.append(candidate_id)
    if tuple(ids) != CANDIDATE_IDS:
        raise WorkflowError("script-proposal candidates 必须按 1、2、3、4、5 排列且不得重复")
    return payload


def validate_final_script(path: Path) -> dict[str, Any]:
    payload = read_json_file(path, "final-script")
    validate_candidate_id(str(payload.get("source_candidate_id")))
    for field in ("plan_name", "creative_idea", "hook", "source_mapping"):
        if payload.get(field) in (None, "", []):
            raise WorkflowError(f"final-script 缺少字段: {field}")
    validate_v4_timeline(payload.get("timeline"), "final-script")
    return payload


def validate_visual_plan(path: Path) -> dict[str, Any]:
    payload = read_json_file(path, "visual-plan")
    required = ("visual_requirements", "product_reference_decision", "asset_roles", "product_identity_sources", "scale_reference", "storyboard")
    if any(field not in payload or payload.get(field) is None for field in required):
        raise WorkflowError("visual-plan 缺少必需字段: " + ", ".join(field for field in required if field not in payload or payload.get(field) is None))
    decision = payload["product_reference_decision"]
    if not isinstance(decision, dict) or not isinstance(decision.get("required"), bool):
        raise WorkflowError("visual-plan.product_reference_decision.required 必须是布尔值")
    if not isinstance(payload["asset_roles"], list):
        raise WorkflowError("visual-plan.asset_roles 必须是数组")
    allowed_roles = {"Box Master", "Sachet Master", "Bottle Master", "Scale Reference", "Logo/Text Master", "Scene Reference"}
    role_by_filename: dict[str, str] = {}
    for item in payload["asset_roles"]:
        if not isinstance(item, dict) or item.get("role") not in allowed_roles or not item.get("filename"):
            raise WorkflowError("visual-plan.asset_roles 必须包含有效 filename 和素材角色")
        role_by_filename[str(item["filename"])] = str(item["role"])
    identity_sources = payload["product_identity_sources"]
    if not isinstance(identity_sources, list):
        raise WorkflowError("visual-plan.product_identity_sources 必须是数组")
    if decision["required"] and not identity_sources:
        raise WorkflowError("需要产品参考时 product_identity_sources 不能为空")
    for filename in identity_sources:
        if role_by_filename.get(str(filename)) not in {"Box Master", "Sachet Master", "Bottle Master"}:
            raise WorkflowError("产品身份依据只能使用 Box/Sachet/Bottle Master，不能使用 Scene Reference")
    scale = payload["scale_reference"]
    if not isinstance(scale, dict) or scale.get("status") not in {"provided", "missing", "not_required"}:
        raise WorkflowError("visual-plan.scale_reference.status 必须是 provided、missing 或 not_required")
    if scale.get("status") == "missing":
        if scale.get("precise_scale_claimed") is not False:
            raise WorkflowError("缺少 Scale Reference 时 precise_scale_claimed 必须为 false")
        if not scale.get("postproduction_recommendation"):
            raise WorkflowError("缺少 Scale Reference 时必须给出真实素材后期合成建议")
    elif scale.get("status") == "provided":
        if role_by_filename.get(str(scale.get("source_filename"))) != "Scale Reference":
            raise WorkflowError("已提供比例参考时 source_filename 必须指向 Scale Reference")
        if not scale.get("relative_scale_constraints"):
            raise WorkflowError("已提供比例参考时必须记录 relative_scale_constraints")
    storyboard = payload["storyboard"]
    if not isinstance(storyboard, list) or not storyboard:
        raise WorkflowError("visual-plan.storyboard 必须是非空数组")
    for index, panel in enumerate(storyboard):
        if not isinstance(panel, dict) or any(panel.get(field) in (None, "") for field in ("time", "person", "environment", "action", "product", "visual_elements")):
            raise WorkflowError(f"visual-plan.storyboard[{index}] 必须明确人物、环境、动作、产品和重要视觉元素")
    return payload


def read_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"{label} 必须是有效 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise WorkflowError(f"{label} 根节点必须是对象")
    return payload


def validate_dimension_reference(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"dimension-reference 必须是有效 JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("status") not in {"provided", "missing"}:
        raise WorkflowError("dimension-reference.status 必须是 provided 或 missing")
    if payload["status"] == "missing":
        if payload.get("measurements") not in (None, [], {}):
            raise WorkflowError("尺寸缺失时不得包含推测的 measurements")
        if payload.get("not_to_scale") is not True:
            raise WorkflowError("尺寸缺失时必须设置 not_to_scale: true")
        if payload.get("display_disclaimer") != "尺寸未提供 / 非按比例":
            raise WorkflowError("尺寸缺失时必须设置 display_disclaimer: 尺寸未提供 / 非按比例")
    else:
        measurements = payload.get("measurements")
        if not isinstance(measurements, list) or not measurements:
            raise WorkflowError("已提供尺寸时 measurements 必须是非空数组")
        for item in measurements:
            if not isinstance(item, dict) or not all(item.get(key) not in (None, "") for key in ("model", "unit", "source")):
                raise WorkflowError("每条尺寸必须包含 model、unit 和 source")
            if not any(item.get(key) not in (None, "") for key in ("length", "width", "height", "diameter")):
                raise WorkflowError("每条尺寸至少需要长宽高或直径中的一个值")
    return payload


def validate_feedback_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"client-feedback 必须是有效 JSON: {exc}") from exc
    required = ("raw_reply", "received_at", "channel", "change_items")
    if not isinstance(payload, dict) or any(payload.get(field) in (None, "") for field in required):
        raise WorkflowError("client-feedback 必须包含 raw_reply、received_at、channel 和 change_items")
    if not isinstance(payload["change_items"], list):
        raise WorkflowError("client-feedback.change_items 必须是数组")
    if "affects_visuals" not in payload or not isinstance(payload["affects_visuals"], bool):
        raise WorkflowError("client-feedback.affects_visuals 必须是布尔值")
    return payload


def proposal_entry(state: dict[str, Any], revision: int | None = None) -> dict[str, Any]:
    entries = state.get("artifacts", {}).get("proposal-package", [])
    if revision is None:
        if not entries:
            raise WorkflowError("缺少 proposal-package")
        return entries[-1]
    for entry in entries:
        if entry.get("proposal_revision") == revision:
            return entry
    raise WorkflowError(f"找不到提案包 V{revision:02d}")


def component_binding(entry: dict[str, Any]) -> dict[str, Any]:
    verify_artifact_integrity(entry, "proposal component")
    return {"version": entry["version"], "path": entry["path"], "sha256": entry["sha256"]}


def verify_proposal_components(proposal: dict[str, Any]) -> dict[str, Any]:
    payload = read_json_artifact(proposal, "proposal-package")
    components = payload.get("components")
    if not isinstance(components, dict):
        raise WorkflowError("proposal-package 缺少 components")
    for name in ("script", "dimension_reference", "dimension_reference_image", "aggregate_keyframe"):
        binding = components.get(name)
        if not isinstance(binding, dict):
            raise WorkflowError(f"proposal-package 缺少组件绑定: {name}")
        verify_artifact_integrity(binding, f"proposal component {name}")
    feedback = payload.get("client_feedback")
    if feedback is not None:
        verify_artifact_integrity(feedback, "proposal client feedback")
    return payload


def validate_v3_task_preview(payload: dict[str, Any]) -> None:
    errors: list[str] = []
    if payload.get("mode") != "i2v":
        errors.append("mode 必须是 i2v")
    if not is_uuid(payload.get("workspace_id")):
        errors.append("workspace_id 必须是 UUID")
    if not is_uuid(payload.get("idempotency_key")):
        errors.append("idempotency_key 必须是 UUID")
    duration = payload.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 4 <= duration <= 15:
        errors.append("duration_seconds 必须在 4 到 15 秒之间")
    if payload.get("aspect_ratio") not in {"16:9", "9:16", "1:1"}:
        errors.append("aspect_ratio 无效")
    if payload.get("quality") not in {"high", "standard"}:
        errors.append("quality 无效")
    if not isinstance(payload.get("execution_backend"), str) or not payload["execution_backend"].strip():
        errors.append("execution_backend 不能为空")
    if errors:
        raise WorkflowError("task-preview 校验失败: " + "; ".join(errors))


def render_proposal_markdown(
    revision: int,
    scripts: dict[str, Any],
    dimensions: dict[str, Any],
    dimension_image_name: str,
    keyframe_name: str,
) -> str:
    lines = [f"# 客户提案包 V{revision}", "", "## 脚本方案", "", "| ID | 创意方向 | 钩子 | 时间轴分镜 | 口播 | 素材映射 | 后期文字 |", "|---|---|---|---|---|---|---|"]
    for item in scripts["candidates"]:
        def cell(value: Any) -> str:
            if isinstance(value, list):
                value = "<br>".join(str(part) for part in value)
            elif isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False)
            return str(value).replace("|", "\\|").replace("\n", "<br>")
        lines.append("| " + " | ".join(cell(item[field]) for field in ("candidate_id", "creative_direction", "hook", "storyboard", "voiceover", "source_mapping", "post_production_text")) + " |")
    lines.extend(["", "## 产品尺寸参考", ""])
    if dimensions["status"] == "missing":
        lines.extend(["> 尺寸未提供 / 非按比例。不得根据普通照片或像素推算实物尺寸。", ""])
    else:
        lines.extend(["尺寸数据来自客户明确提供的来源；参考图仅按已记录数据表达。", ""])
    lines.extend([f"![产品尺寸参考]({dimension_image_name})", "", "## 总聚合关键帧", "", f"![总聚合关键帧]({keyframe_name})", ""])
    return "\n".join(lines)


def artifact_entry_for_candidate(
    state: dict[str, Any], kind: str, candidate_id: str, version: int | None = None
) -> dict[str, Any]:
    candidate_id = validate_candidate_id(candidate_id)
    entries = state.get("artifacts", {}).get(kind, [])
    script_version = state.get("approvals", {}).get("script", {}).get("script_version")
    matches = [
        entry
        for entry in entries
        if entry.get("candidate_id") == candidate_id
        and entry.get("script_version") == script_version
    ]
    if version is None:
        if matches:
            return matches[-1]
    else:
        for entry in matches:
            if entry.get("version") == version:
                return entry
    suffix = f" v{version}" if version is not None else ""
    raise WorkflowError(f"找不到候选 {candidate_id} 的 {kind}{suffix}")


def require_complete_candidate_batch(state: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    coverage: dict[str, dict[str, dict[str, Any]]] = {}
    missing: list[str] = []
    for candidate_id in CANDIDATE_IDS:
        try:
            prompt = artifact_entry_for_candidate(state, "keyframe-prompt", candidate_id)
            keyframe = artifact_entry_for_candidate(state, "keyframe", candidate_id)
            if keyframe.get("keyframe_prompt_version") != prompt.get("version"):
                raise WorkflowError("图片不是由当前候选的最新提示词生成")
            coverage[candidate_id] = {"prompt": prompt, "keyframe": keyframe}
        except WorkflowError:
            missing.append(candidate_id)
    if missing:
        raise WorkflowError("关键帧批次尚未完成，缺少或需重生成候选: " + ", ".join(missing))
    return coverage


def verify_artifact_integrity(entry: dict[str, Any], label: str) -> Path:
    try:
        path = Path(entry["path"])
        current_sha256 = sha256_file(path)
    except (KeyError, OSError) as exc:
        raise WorkflowError(f"无法读取 {label} 产物") from exc
    if current_sha256 != entry.get("sha256"):
        raise WorkflowError(f"{label} 产物内容已在记录后发生变化")
    return path


def read_json_artifact(entry: dict[str, Any], label: str) -> dict[str, Any]:
    try:
        payload = json.loads(verify_artifact_integrity(entry, label).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取 {label} JSON") from exc
    if not isinstance(payload, dict):
        raise WorkflowError(f"{label} 根节点必须是对象")
    return payload


def is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def validate_task_preview(
    state: dict[str, Any], preview: dict[str, Any], h3_prompt: dict[str, Any]
) -> dict[str, Any]:
    payload = read_json_artifact(preview, "task-preview")
    errors: list[str] = []
    keyframe_version = state.get("approvals", {}).get("keyframe", {}).get("keyframe_version")
    if keyframe_version is None:
        errors.append("task-preview 缺少已确认关键帧上下文")
        keyframe = None
    else:
        keyframe = artifact_entry(state, "keyframe", keyframe_version)
        verify_artifact_integrity(keyframe, "keyframe")
    verify_artifact_integrity(h3_prompt, "h3-prompt")

    expected = {
        "mode": "i2v",
        "h3_prompt_version": h3_prompt.get("version"),
        "keyframe_version": keyframe_version,
    }
    if schema_version(state) >= 2:
        approval = state.get("approvals", {}).get("keyframe", {})
        expected.update(
            {
                "candidate_id": approval.get("candidate_id"),
                "script_version": approval.get("script_version"),
                "keyframe_prompt_version": approval.get("keyframe_prompt_version"),
            }
        )
        for field in ("candidate_id", "script_version", "keyframe_prompt_version", "keyframe_version"):
            if h3_prompt.get(field) != expected.get(field):
                errors.append(f"h3-prompt.{field} 未绑定当前已选候选")
    for field, value in expected.items():
        if payload.get(field) != value:
            errors.append(f"task-preview.{field} 必须等于 {value!r}")

    if keyframe is not None:
        preview_path = payload.get("keyframe_path")
        try:
            same_path = isinstance(preview_path, str) and Path(preview_path).resolve() == Path(keyframe["path"]).resolve()
        except (KeyError, OSError):
            same_path = False
        if not same_path:
            errors.append("task-preview.keyframe_path 必须引用已确认关键帧版本")

    if not is_uuid(payload.get("workspace_id")):
        errors.append("task-preview.workspace_id 必须是 UUID")
    if not is_uuid(payload.get("idempotency_key")):
        errors.append("task-preview.idempotency_key 必须是 UUID")
    duration = payload.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 4 <= duration <= 15:
        errors.append("task-preview.duration_seconds 必须在 4 到 15 秒之间")
    if payload.get("aspect_ratio") not in {"16:9", "9:16", "1:1"}:
        errors.append("task-preview.aspect_ratio 无效")
    if payload.get("quality") not in {"high", "standard"}:
        errors.append("task-preview.quality 无效")
    if not isinstance(payload.get("execution_backend"), str) or not payload["execution_backend"].strip():
        errors.append("task-preview.execution_backend 不能为空")
    if errors:
        raise WorkflowError("task-preview 校验失败: " + "; ".join(errors))
    return payload


def script_package_entry(state: dict[str, Any], revision: int | None = None) -> dict[str, Any]:
    entries = state.get("artifacts", {}).get("script-package", [])
    if revision is None:
        if not entries:
            raise WorkflowError("缺少 script-package")
        return entries[-1]
    for entry in entries:
        if entry.get("script_revision") == revision:
            return entry
    raise WorkflowError(f"找不到脚本提案 V{revision:02d}")


def storyboard_package_entry(state: dict[str, Any], revision: int | None = None) -> dict[str, Any]:
    entries = state.get("artifacts", {}).get("storyboard-package", [])
    if revision is None:
        if not entries:
            raise WorkflowError("缺少 storyboard-package")
        return entries[-1]
    for entry in entries:
        if entry.get("storyboard_revision") == revision:
            return entry
    raise WorkflowError(f"找不到 Storyboard V{revision:02d}")


def render_script_markdown(revision: int, payload: dict[str, Any]) -> str:
    lines = [f"# 五个脚本方案 V{revision}", ""]
    for item in payload["candidates"]:
        lines.extend([
            f"## {item['candidate_id']}. {item['plan_name']}", "",
            item["creative_idea"], "", f"**Hook:** {item['hook']}", "",
            "| 时间 | 画面 | 口播 | 字幕/花字 | CTA |", "|---|---|---|---|---|",
        ])
        for row in item["timeline"]:
            cells = [str(row[field]).replace("|", "\\|").replace("\n", "<br>") for field in ("time", "visual", "voiceover", "subtitle", "cta")]
            lines.append("| " + " | ".join(cells) + " |")
        lines.extend(["", "来源映射：`" + json.dumps(item["source_mapping"], ensure_ascii=False) + "`", ""])
    return "\n".join(lines)


def finalize_script_proposal(run_dir: Path, script_version: int, base_revision: int | None = None) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    if schema_version(state) != 4 or state.get("stage") != "script_review":
        raise WorkflowError("finalize-script-proposal 只能在 schema v4 的 script_review 阶段执行")
    script = artifact_entry(state, "script-proposal", script_version)
    payload = validate_script_proposal(verify_artifact_integrity(script, "script-proposal"))
    active = state.get("active_revision") or {}
    if base_revision is None and active.get("phase") == "script":
        base_revision = active.get("base_revision")
    feedback_version = active.get("feedback_version") if base_revision is not None and active.get("phase") == "script" else None
    if base_revision is not None:
        script_package_entry(state, base_revision)
        if not feedback_version:
            raise WorkflowError("发布脚本修订版前必须绑定 script 阶段客户反馈")
        feedback = artifact_entry(state, "client-feedback", feedback_version)
        if feedback.get("phase") != "script" or feedback.get("base_revision") != base_revision:
            raise WorkflowError("当前反馈不属于指定脚本版本")
    else:
        feedback = None
        if state.get("artifacts", {}).get("script-package"):
            raise WorkflowError("后续脚本版本必须通过 begin-revision 绑定客户反馈")
    revision = len(state.get("artifacts", {}).get("script-package", [])) + 1
    root = run_dir.resolve() / "scripts"
    final_dir = root / f"V{revision:02d}"
    temp_dir = root / f".V{revision:02d}-{uuid.uuid4().hex}.tmp"
    root.mkdir(exist_ok=True)
    if final_dir.exists():
        raise WorkflowError(f"脚本提案目录已存在: {final_dir}")
    temp_dir.mkdir()
    try:
        shutil.copy2(script["path"], temp_dir / "script-proposal.json")
        (temp_dir / "proposal.md").write_text(render_script_markdown(revision, payload), encoding="utf-8")
        package = {
            "schema_version": 4,
            "script_revision": revision,
            "parent_revision": base_revision,
            "feedback_version": feedback_version,
            "client_feedback": component_binding(feedback) if feedback else None,
            "source_manifest_sha256": sha256_file(run_dir.resolve() / "manifest.json"),
            "components": {"script_proposal": component_binding(script)},
            "created_at": now_iso(),
        }
        atomic_json_write(temp_dir / "manifest.json", package)
        temp_dir.replace(final_dir)
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise
    entries = state.setdefault("artifacts", {}).setdefault("script-package", [])
    package_path = final_dir / "manifest.json"
    timestamp = now_iso()
    entry = {"version": len(entries) + 1, "script_revision": revision, "path": str(package_path), "sha256": sha256_file(package_path), "recorded_at": timestamp, "deliverable_dir": str(final_dir)}
    entries.append(entry)
    state.pop("active_revision", None)
    state["updated_at"] = timestamp
    state.setdefault("history", []).append({"at": timestamp, "event": "script_proposal_finalized", "script_revision": revision})
    atomic_json_write(state_path, state)
    return entry


def lock_script(run_dir: Path, script_proposal_version: int, candidate_id: str, final_script_version: int, approval_json: Path) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    if schema_version(state) != 4 or state.get("stage") != "script_review":
        raise WorkflowError("lock-script 只能在 schema v4 的 script_review 阶段执行")
    package = script_package_entry(state, script_proposal_version)
    candidate_id = validate_candidate_id(candidate_id)
    final_script = artifact_entry(state, "final-script", final_script_version)
    final_payload = validate_final_script(verify_artifact_integrity(final_script, "final-script"))
    if final_script.get("script_package_version") != package["version"] or final_script.get("script_package_sha256") != package["sha256"]:
        raise WorkflowError("final-script 未绑定所选 script package 版本")
    if str(final_payload["source_candidate_id"]) != candidate_id:
        raise WorkflowError("final-script.source_candidate_id 与选择的候选不一致")
    proposal_payload = read_json_artifact(package, "script-package")
    proposal = read_json_artifact(proposal_payload["components"]["script_proposal"], "script-proposal")
    if candidate_id not in {str(item["candidate_id"]) for item in proposal["candidates"]}:
        raise WorkflowError("选择的候选不在脚本提案中")
    audit = read_json_file(approval_json, "script approval")
    if any(audit.get(field) in (None, "") for field in ("raw_reply", "confirmed_at", "channel")):
        raise WorkflowError("脚本确认审计必须包含 raw_reply、confirmed_at 和 channel")
    if audit.get("script_revision", script_proposal_version) != script_proposal_version or str(audit.get("candidate_id", candidate_id)) != candidate_id:
        raise WorkflowError("脚本确认审计中的版本或候选 ID 与命令不一致")
    timestamp = now_iso()
    lock_id = str(uuid.uuid4())
    lock_payload = sanitize_json({
        "lock_id": lock_id,
        "script_revision": script_proposal_version,
        "script_package_sha256": package["sha256"],
        "candidate_id": candidate_id,
        "final_script": component_binding(final_script),
        "status": "Script = LOCKED",
        "audit": {**audit, "script_revision": script_proposal_version, "candidate_id": candidate_id},
        "locked_at": timestamp,
    })
    entries = state.setdefault("artifacts", {}).setdefault("script-lock", [])
    version = len(entries) + 1
    destination = run_dir.resolve() / f"script-lock-v{version:02d}.json"
    atomic_json_write(destination, lock_payload)
    entry = {"version": version, "path": str(destination), "sha256": sha256_file(destination), "recorded_at": timestamp, "lock_id": lock_id, "script_revision": script_proposal_version, "candidate_id": candidate_id, "final_script_version": final_script_version}
    entries.append(entry)
    state.setdefault("script_locks", []).append(lock_payload)
    state.setdefault("approvals", {})["script"] = lock_payload
    state["stage"] = "script_locked"
    state["updated_at"] = timestamp
    state.setdefault("history", []).append({"at": timestamp, "event": "script_locked", "lock_id": lock_id, "script_revision": script_proposal_version, "candidate_id": candidate_id})
    atomic_json_write(state_path, state)
    return state


def render_storyboard_markdown(revision: int, visual: dict[str, Any], keyframe_name: str) -> str:
    lines = [f"# 聚合 Storyboard V{revision}", "", "## A. Visual Requirements", "", json.dumps(visual["visual_requirements"], ensure_ascii=False, indent=2), "", "## B. Product Reference Decision", "", json.dumps(visual["product_reference_decision"], ensure_ascii=False, indent=2), "", "## C. Storyboard", ""]
    for index, panel in enumerate(visual["storyboard"], 1):
        lines.append(f"- Panel {index} ({panel['time']}): {panel['person']}；{panel['environment']}；{panel['action']}；{panel['product']}；{panel['visual_elements']}")
    lines.extend(["", "## Aggregate Storyboard", "", f"![Aggregate Storyboard]({keyframe_name})", ""])
    return "\n".join(lines)


def finalize_storyboard(run_dir: Path, visual_plan_version: int, keyframe_prompt_version: int, keyframe_version: int, base_revision: int | None = None) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    if schema_version(state) != 4 or state.get("stage") != "storyboard_review":
        raise WorkflowError("finalize-storyboard 只能在 schema v4 的 storyboard_review 阶段执行")
    script_lock = state.get("approvals", {}).get("script")
    if not script_lock:
        raise WorkflowError("生成 Storyboard 前必须锁定 Final Script")
    visual = artifact_entry(state, "visual-plan", visual_plan_version)
    prompt = artifact_entry(state, "aggregate-keyframe-prompt", keyframe_prompt_version)
    keyframe = artifact_entry(state, "aggregate-keyframe", keyframe_version)
    visual_payload = validate_visual_plan(verify_artifact_integrity(visual, "visual-plan"))
    for entry, label in ((visual, "visual-plan"), (prompt, "aggregate-keyframe-prompt"), (keyframe, "aggregate-keyframe")):
        if entry.get("script_lock_id") != script_lock["lock_id"]:
            raise WorkflowError(f"{label} 未绑定当前 script lock")
    if keyframe.get("keyframe_prompt_version") != prompt["version"]:
        raise WorkflowError("aggregate-keyframe 未绑定所选图片 Prompt")
    if Path(keyframe["path"]).suffix.casefold() not in SUPPORTED_IMAGES:
        raise WorkflowError("aggregate-keyframe 必须是支持的图片格式")
    active = state.get("active_revision") or {}
    if base_revision is None and active.get("phase") == "storyboard":
        base_revision = active.get("base_revision")
    feedback_version = active.get("feedback_version") if base_revision is not None and active.get("phase") == "storyboard" else None
    if base_revision is not None:
        base = storyboard_package_entry(state, base_revision)
        if not feedback_version:
            raise WorkflowError("发布 Storyboard 修订版前必须绑定 storyboard 阶段反馈")
        feedback = artifact_entry(state, "client-feedback", feedback_version)
        if feedback.get("phase") != "storyboard" or feedback.get("base_revision") != base_revision:
            raise WorkflowError("当前反馈不属于指定 Storyboard 版本")
        base_payload = read_json_artifact(base, "storyboard-package")
        if feedback.get("affects_visuals") and base_payload["components"]["aggregate_keyframe"]["sha256"] == keyframe["sha256"]:
            raise WorkflowError("视觉相关反馈必须生成新的聚合 Storyboard")
    else:
        base = None
        feedback = None
        if state.get("artifacts", {}).get("storyboard-package"):
            raise WorkflowError("后续 Storyboard 版本必须通过 begin-revision 绑定客户反馈")
    revision = len(state.get("artifacts", {}).get("storyboard-package", [])) + 1
    components = {"visual_plan": component_binding(visual), "aggregate_keyframe_prompt": component_binding(prompt), "aggregate_keyframe": component_binding(keyframe)}
    root = run_dir.resolve() / "storyboards"
    final_dir = root / f"V{revision:02d}"
    temp_dir = root / f".V{revision:02d}-{uuid.uuid4().hex}.tmp"
    root.mkdir(exist_ok=True)
    if final_dir.exists():
        raise WorkflowError(f"Storyboard 目录已存在: {final_dir}")
    temp_dir.mkdir()
    try:
        keyframe_name = "aggregate-storyboard" + Path(keyframe["path"]).suffix.casefold()
        shutil.copy2(visual["path"], temp_dir / "visual-plan.json")
        shutil.copy2(prompt["path"], temp_dir / "image-prompt.txt")
        shutil.copy2(keyframe["path"], temp_dir / keyframe_name)
        (temp_dir / "storyboard.md").write_text(render_storyboard_markdown(revision, visual_payload, keyframe_name), encoding="utf-8")
        package = {
            "schema_version": 4,
            "storyboard_revision": revision,
            "parent_revision": base_revision,
            "feedback_version": feedback_version,
            "client_feedback": component_binding(feedback) if feedback else None,
            "script_lock_id": script_lock["lock_id"],
            "final_script": script_lock["final_script"],
            "components": components,
            "keyframe_reuse": bool(base and read_json_artifact(base, "storyboard-package")["components"]["aggregate_keyframe"]["sha256"] == keyframe["sha256"]),
            "keyframe_reuse_reason": "非视觉元数据反馈" if base and feedback and not feedback.get("affects_visuals") and read_json_artifact(base, "storyboard-package")["components"]["aggregate_keyframe"]["sha256"] == keyframe["sha256"] else None,
            "created_at": now_iso(),
        }
        atomic_json_write(temp_dir / "manifest.json", package)
        temp_dir.replace(final_dir)
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise
    entries = state.setdefault("artifacts", {}).setdefault("storyboard-package", [])
    package_path = final_dir / "manifest.json"
    timestamp = now_iso()
    entry = {"version": len(entries) + 1, "storyboard_revision": revision, "path": str(package_path), "sha256": sha256_file(package_path), "recorded_at": timestamp, "script_lock_id": script_lock["lock_id"], "deliverable_dir": str(final_dir)}
    entries.append(entry)
    state.pop("active_revision", None)
    state["updated_at"] = timestamp
    state.setdefault("history", []).append({"at": timestamp, "event": "storyboard_finalized", "storyboard_revision": revision})
    atomic_json_write(state_path, state)
    return entry


def lock_storyboard(run_dir: Path, storyboard_version: int, approval_json: Path) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    if schema_version(state) != 4 or state.get("stage") != "storyboard_review":
        raise WorkflowError("lock-storyboard 只能在 schema v4 的 storyboard_review 阶段执行")
    package = storyboard_package_entry(state, storyboard_version)
    payload = read_json_artifact(package, "storyboard-package")
    script_lock = state.get("approvals", {}).get("script")
    if not script_lock or payload.get("script_lock_id") != script_lock.get("lock_id"):
        raise WorkflowError("Storyboard 未绑定当前 Final Script")
    audit = read_json_file(approval_json, "storyboard approval")
    if any(audit.get(field) in (None, "") for field in ("raw_reply", "confirmed_at", "channel")):
        raise WorkflowError("Storyboard 确认审计必须包含 raw_reply、confirmed_at 和 channel")
    if audit.get("create_task_authorized") is not True:
        raise WorkflowError("Storyboard 确认必须明确 create_task_authorized: true")
    if audit.get("storyboard_revision", storyboard_version) != storyboard_version:
        raise WorkflowError("确认审计中的 Storyboard 版本与命令不一致")
    timestamp = now_iso()
    lock_id = str(uuid.uuid4())
    lock_payload = sanitize_json({"lock_id": lock_id, "storyboard_revision": storyboard_version, "storyboard_package_sha256": package["sha256"], "script_lock_id": script_lock["lock_id"], "candidate_id": script_lock["candidate_id"], "audit": {**audit, "storyboard_revision": storyboard_version, "create_task_authorized": True}, "locked_at": timestamp})
    entries = state.setdefault("artifacts", {}).setdefault("storyboard-lock", [])
    version = len(entries) + 1
    destination = run_dir.resolve() / f"storyboard-lock-v{version:02d}.json"
    atomic_json_write(destination, lock_payload)
    entries.append({"version": version, "path": str(destination), "sha256": sha256_file(destination), "recorded_at": timestamp, "lock_id": lock_id, "storyboard_revision": storyboard_version})
    state.setdefault("storyboard_locks", []).append(lock_payload)
    state.setdefault("approvals", {})["storyboard"] = lock_payload
    state["stage"] = "storyboard_locked"
    state["updated_at"] = timestamp
    state.setdefault("history", []).append({"at": timestamp, "event": "storyboard_locked", "lock_id": lock_id, "storyboard_revision": storyboard_version})
    atomic_json_write(state_path, state)
    return state


def record_feedback(run_dir: Path, proposal_version: int, source: Path, phase: str | None = None) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    if schema_version(state) == 4:
        if phase not in {"script", "storyboard"}:
            raise WorkflowError("schema v4 的 record-feedback 必须指定 phase: script 或 storyboard")
        if phase == "script":
            script_package_entry(state, proposal_version)
        else:
            storyboard_package_entry(state, proposal_version)
        payload = validate_feedback_payload(source)
        declared = payload.get("base_revision", proposal_version)
        if declared != proposal_version:
            raise WorkflowError("反馈中的 base_revision 与目标版本不一致")
        payload.update({"phase": phase, "base_revision": proposal_version})
        entries = state.setdefault("artifacts", {}).setdefault("client-feedback", [])
        version = len(entries) + 1
        destination = run_dir.resolve() / f"client-feedback-v{version:02d}.json"
        if destination.exists():
            raise WorkflowError(f"产物目标已存在: {destination}")
        atomic_json_write(destination, payload)
        timestamp = now_iso()
        entry = {"version": version, "path": str(destination), "sha256": sha256_file(destination), "recorded_at": timestamp, "phase": phase, "base_revision": proposal_version, "affects_visuals": payload["affects_visuals"]}
        entries.append(entry)
        state["updated_at"] = timestamp
        state.setdefault("history", []).append({"at": timestamp, "event": "client_feedback_recorded", "version": version, "phase": phase, "base_revision": proposal_version})
        atomic_json_write(state_path, state)
        return entry
    if schema_version(state) != 3:
        raise WorkflowError("record-feedback 仅适用于 schema v3/v4")
    proposal = proposal_entry(state, proposal_version)
    payload = validate_feedback_payload(source)
    declared = payload.get("proposal_revision", proposal_version)
    if declared != proposal_version:
        raise WorkflowError("反馈中的 proposal_revision 与目标提案版本不一致")
    payload["proposal_revision"] = proposal_version
    entries = state.setdefault("artifacts", {}).setdefault("client-feedback", [])
    version = len(entries) + 1
    destination = run_dir.resolve() / f"client-feedback-v{version:02d}.json"
    if destination.exists():
        raise WorkflowError(f"产物目标已存在: {destination}")
    atomic_json_write(destination, payload)
    timestamp = now_iso()
    entry = {"version": version, "path": str(destination), "sha256": sha256_file(destination), "recorded_at": timestamp, "proposal_revision": proposal_version, "affects_visuals": payload["affects_visuals"]}
    entries.append(entry)
    state["updated_at"] = timestamp
    state.setdefault("history", []).append({"at": timestamp, "event": "client_feedback_recorded", "version": version, "proposal_revision": proposal_version})
    atomic_json_write(state_path, state)
    return entry


def begin_revision(run_dir: Path, base_revision: int, feedback_version: int, phase: str | None = None) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    if schema_version(state) == 4:
        if phase not in {"script", "storyboard"}:
            raise WorkflowError("schema v4 的 begin-revision 必须指定 phase: script 或 storyboard")
        if phase == "script":
            script_package_entry(state, base_revision)
        else:
            storyboard_package_entry(state, base_revision)
        feedback = artifact_entry(state, "client-feedback", feedback_version)
        if feedback.get("phase") != phase or feedback.get("base_revision") != base_revision:
            raise WorkflowError("反馈版本不属于指定阶段和基础版本")
        allowed = {"script_review", "storyboard_review", "script_locked", "storyboard_locked", "production_ready", "submitted", "monitoring", "succeeded", "failed"}
        if state.get("stage") not in allowed:
            raise WorkflowError("当前阶段不能开始修订")
        state["active_revision"] = {"phase": phase, "base_revision": base_revision, "feedback_version": feedback_version, "started_at": now_iso()}
        state["stage"] = "script_review" if phase == "script" else "storyboard_review"
        if phase == "script":
            state.get("approvals", {}).pop("storyboard", None)
        state["updated_at"] = now_iso()
        state.setdefault("history", []).append({"at": state["updated_at"], "event": f"{phase}_revision_started", "base_revision": base_revision, "feedback_version": feedback_version})
        atomic_json_write(state_path, state)
        return state
    if schema_version(state) != 3:
        raise WorkflowError("begin-revision 仅适用于 schema v3/v4")
    proposal_entry(state, base_revision)
    feedback = artifact_entry(state, "client-feedback", feedback_version)
    if feedback.get("proposal_revision") != base_revision:
        raise WorkflowError("反馈版本不属于指定的基础提案")
    if state.get("stage") not in {"proposal_review", "proposal_locked", "production_ready", "submitted", "monitoring", "succeeded", "failed"}:
        raise WorkflowError("当前阶段不能开始新提案修订")
    state["active_revision"] = {"base_revision": base_revision, "feedback_version": feedback_version, "started_at": now_iso()}
    state["stage"] = "proposal_review"
    state["updated_at"] = now_iso()
    state.setdefault("history", []).append({"at": state["updated_at"], "event": "proposal_revision_started", "base_revision": base_revision, "feedback_version": feedback_version})
    atomic_json_write(state_path, state)
    return state


def finalize_proposal(
    run_dir: Path,
    script_version: int,
    dimension_version: int,
    dimension_image_version: int,
    keyframe_version: int,
    base_revision: int | None = None,
) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    if schema_version(state) != 3 or state.get("stage") != "proposal_review":
        raise WorkflowError("finalize-proposal 只能在 schema v3 的 proposal_review 阶段执行")
    script = artifact_entry(state, "script", script_version)
    dimension = artifact_entry(state, "dimension-reference", dimension_version)
    dimension_image = artifact_entry(state, "dimension-reference-image", dimension_image_version)
    keyframe = artifact_entry(state, "aggregate-keyframe", keyframe_version)
    scripts_payload = read_json_artifact(script, "script")
    validate_script_set(Path(script["path"]))
    dimensions_payload = validate_dimension_reference(verify_artifact_integrity(dimension, "dimension-reference"))
    if dimension_image.get("dimension_version") != dimension["version"]:
        raise WorkflowError("尺寸参考图未绑定所选 dimension-reference 版本")
    for entry, label in ((dimension_image, "dimension-reference-image"), (keyframe, "aggregate-keyframe")):
        path = verify_artifact_integrity(entry, label)
        if path.suffix.casefold() not in SUPPORTED_IMAGES:
            raise WorkflowError(f"{label} 必须是支持的图片格式")

    active = state.get("active_revision") or {}
    if base_revision is None:
        base_revision = active.get("base_revision")
    feedback_version = active.get("feedback_version") if base_revision is not None else None
    existing_proposals = state.get("artifacts", {}).get("proposal-package", [])
    if base_revision is not None:
        base = proposal_entry(state, base_revision)
        if not feedback_version:
            raise WorkflowError("发布修订版前必须先记录并绑定客户反馈")
        feedback = artifact_entry(state, "client-feedback", feedback_version)
        verify_artifact_integrity(feedback, "client-feedback")
        if feedback.get("proposal_revision") != base_revision:
            raise WorkflowError("当前反馈不属于基础提案")
        base_payload = read_json_artifact(base, "proposal-package")
        if feedback.get("affects_visuals") and base_payload["components"]["aggregate_keyframe"]["version"] == keyframe_version:
            raise WorkflowError("视觉相关反馈必须使用新的总聚合关键帧")
    else:
        base = None
        feedback = None

    components = {
        "script": component_binding(script),
        "dimension_reference": component_binding(dimension),
        "dimension_reference_image": component_binding(dimension_image),
        "aggregate_keyframe": component_binding(keyframe),
    }
    signature = (base_revision, feedback_version, tuple((name, value["sha256"]) for name, value in components.items()))
    for entry in state.get("artifacts", {}).get("proposal-package", []):
        payload = read_json_artifact(entry, "proposal-package")
        existing = (payload.get("parent_revision"), payload.get("feedback_version"), tuple((name, value["sha256"]) for name, value in payload.get("components", {}).items()))
        if existing == signature:
            return entry
    if existing_proposals and base_revision is None:
        raise WorkflowError("V2/V3 必须通过 begin-revision 绑定基础提案和客户反馈")

    revision = len(state.get("artifacts", {}).get("proposal-package", [])) + 1
    if base_revision is not None and base_revision >= revision:
        raise WorkflowError("base-revision 必须指向早于新版本的提案")
    proposals_root = run_dir.resolve() / "proposals"
    final_dir = proposals_root / f"V{revision:02d}"
    temp_dir = proposals_root / f".V{revision:02d}-{uuid.uuid4().hex}.tmp"
    proposals_root.mkdir(exist_ok=True)
    if final_dir.exists():
        raise WorkflowError(f"提案目录已存在: {final_dir}")
    temp_dir.mkdir()
    try:
        dim_json_name = "dimension-reference.json"
        dim_image_name = "dimension-reference" + Path(dimension_image["path"]).suffix.casefold()
        keyframe_name = "aggregate-keyframe" + Path(keyframe["path"]).suffix.casefold()
        shutil.copy2(dimension["path"], temp_dir / dim_json_name)
        shutil.copy2(dimension_image["path"], temp_dir / dim_image_name)
        shutil.copy2(keyframe["path"], temp_dir / keyframe_name)
        (temp_dir / "proposal.md").write_text(render_proposal_markdown(revision, scripts_payload, dimensions_payload, dim_image_name, keyframe_name), encoding="utf-8")
        package = {
            "schema_version": 3,
            "proposal_revision": revision,
            "parent_revision": base_revision,
            "feedback_version": feedback_version,
            "client_feedback": component_binding(feedback) if feedback is not None else None,
            "source_manifest_sha256": sha256_file(run_dir.resolve() / "manifest.json"),
            "components": components,
            "dimension_status": dimensions_payload["status"],
            "keyframe_reuse": bool(base and read_json_artifact(base, "proposal-package")["components"]["aggregate_keyframe"]["sha256"] == keyframe["sha256"]),
            "keyframe_reuse_reason": "纯文字反馈不影响视觉" if base and feedback and not feedback.get("affects_visuals") and read_json_artifact(base, "proposal-package")["components"]["aggregate_keyframe"]["sha256"] == keyframe["sha256"] else None,
            "deliverables": {"proposal_markdown": "proposal.md", "dimension_data": dim_json_name, "dimension_image": dim_image_name, "aggregate_keyframe": keyframe_name},
            "created_at": now_iso(),
        }
        atomic_json_write(temp_dir / "manifest.json", package)
        temp_dir.replace(final_dir)
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise

    entries = state.setdefault("artifacts", {}).setdefault("proposal-package", [])
    version = len(entries) + 1
    manifest_path = final_dir / "manifest.json"
    run_manifest = run_dir.resolve() / f"proposal-package-v{version:02d}.json"
    shutil.copy2(manifest_path, run_manifest)
    timestamp = now_iso()
    entry = {"version": version, "proposal_revision": revision, "path": str(run_manifest), "deliverable_dir": str(final_dir), "sha256": sha256_file(run_manifest), "recorded_at": timestamp}
    entries.append(entry)
    state.pop("active_revision", None)
    state["updated_at"] = timestamp
    state.setdefault("history", []).append({"at": timestamp, "event": "proposal_finalized", "proposal_revision": revision})
    atomic_json_write(state_path, state)
    return entry


def lock_proposal(run_dir: Path, proposal_version: int, candidate_id: str, approval_json: Path) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    if schema_version(state) != 3 or state.get("stage") != "proposal_review":
        raise WorkflowError("lock-proposal 只能在 schema v3 的 proposal_review 阶段执行")
    proposal = proposal_entry(state, proposal_version)
    candidate_id = validate_candidate_id(candidate_id)
    try:
        audit = json.loads(approval_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"approval-json 必须是有效 JSON: {exc}") from exc
    required = ("raw_reply", "confirmed_at", "channel")
    if not isinstance(audit, dict) or any(audit.get(field) in (None, "") for field in required):
        raise WorkflowError("确认审计必须包含 raw_reply、confirmed_at 和 channel")
    if audit.get("create_task_authorized") is not True:
        raise WorkflowError("最终确认必须明确 create_task_authorized: true")
    declared_revision = audit.get("proposal_revision", proposal_version)
    declared_candidate = str(audit.get("candidate_id", candidate_id))
    if declared_revision != proposal_version or declared_candidate != candidate_id:
        raise WorkflowError("确认审计中的提案版本或候选 ID 与命令不一致")
    verify_artifact_integrity(proposal, "proposal-package")
    verify_proposal_components(proposal)
    timestamp = now_iso()
    lock_id = str(uuid.uuid4())
    lock = {"lock_id": lock_id, "at": timestamp, "proposal_revision": proposal_version, "proposal_package_version": proposal["version"], "proposal_package_sha256": proposal["sha256"], "candidate_id": candidate_id, "audit": sanitize_json({**audit, "proposal_revision": proposal_version, "candidate_id": candidate_id, "create_task_authorized": True})}
    state.setdefault("proposal_locks", []).append(lock)
    state.setdefault("approvals", {})["proposal"] = lock
    state["stage"] = "proposal_locked"
    state["updated_at"] = timestamp
    state.setdefault("history", []).append({"at": timestamp, "event": "proposal_locked", "lock_id": lock_id, "proposal_revision": proposal_version, "candidate_id": candidate_id})
    atomic_json_write(state_path, state)
    return state


def validate_v4_task_preview(
    payload: dict[str, Any],
    prompt_text: str,
    aggregate_sha256: str,
    manifest_assets: list[dict[str, Any]],
    visual_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    errors: list[str] = []
    if payload.get("mode") != "r2v":
        errors.append("mode 必须是 r2v")
    if not is_uuid(payload.get("workspace_id")):
        errors.append("workspace_id 必须是 UUID")
    if not is_uuid(payload.get("idempotency_key")):
        errors.append("idempotency_key 必须是 UUID")
    duration = payload.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 4 <= duration <= 15:
        errors.append("duration_seconds 必须在 4 到 15 秒之间")
    if payload.get("aspect_ratio") not in {"16:9", "9:16", "1:1"}:
        errors.append("aspect_ratio 无效")
    if payload.get("quality") not in {"high", "standard"}:
        errors.append("quality 无效")
    if not isinstance(payload.get("execution_backend"), str) or not payload["execution_backend"].strip():
        errors.append("execution_backend 不能为空")
    assets = payload.get("reference_assets")
    if not isinstance(assets, list) or not assets:
        errors.append("reference_assets 必须是非空数组")
        assets = []
    names: list[str] = []
    hashes: list[str] = []
    manifest_by_filename = {str(item.get("filename")): item for item in manifest_assets if item.get("filename")}
    role_by_filename = {str(item["filename"]): str(item["role"]) for item in visual_plan.get("asset_roles", []) if isinstance(item, dict) and item.get("filename") and item.get("role")}
    identity_sources = {str(value) for value in visual_plan.get("product_identity_sources", [])}
    for index, item in enumerate(assets):
        if not isinstance(item, dict):
            errors.append(f"reference_assets[{index}] 必须是对象")
            continue
        name = item.get("mention_name")
        source_hash = item.get("source_sha256")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_\-\u3400-\u4dbf\u4e00-\u9fff]+", name) or name.startswith("@"):
            errors.append(f"reference_assets[{index}].mention_name 无效")
        else:
            names.append(name)
            if f"@{name}" not in prompt_text:
                errors.append(f"H3 prompt 未引用 @{name}")
        source_filename = item.get("source_filename")
        asset_role = item.get("asset_role")
        if source_hash == aggregate_sha256:
            if asset_role != "Aggregate Storyboard" or source_filename != "aggregate-storyboard":
                errors.append(f"reference_assets[{index}] 的聚合图必须标记为 Aggregate Storyboard / aggregate-storyboard")
            hashes.append(source_hash)
        else:
            source_asset = manifest_by_filename.get(str(source_filename))
            expected_role = role_by_filename.get(str(source_filename))
            if not isinstance(source_hash, str) or source_asset is None or source_asset.get("sha256") != source_hash:
                errors.append(f"reference_assets[{index}] 未绑定匹配的客户素材文件和哈希")
            elif expected_role is None or asset_role != expected_role:
                errors.append(f"reference_assets[{index}].asset_role 与 visual-plan 不一致")
            elif asset_role in {"Box Master", "Sachet Master", "Bottle Master"} and str(source_filename) not in identity_sources:
                errors.append(f"reference_assets[{index}] 的产品主素材不在 product_identity_sources 中")
            else:
                hashes.append(source_hash)
        if not item.get("reference_description"):
            errors.append(f"reference_assets[{index}].reference_description 不能为空")
    if len(names) != len(set(names)):
        errors.append("reference_assets.mention_name 不得重复")
    if aggregate_sha256 not in hashes:
        errors.append("reference_assets 必须包含锁定的聚合 Storyboard")
    if "<Picture" in prompt_text:
        errors.append("R2V H3 prompt 不得残留 <Picture N>")
    if errors:
        raise WorkflowError("task-preview 校验失败: " + "; ".join(errors))
    return assets


def finalize_production_v4(run_dir: Path, state_path: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("stage") != "storyboard_locked":
        raise WorkflowError("schema v4 的 finalize-production 只能在 storyboard_locked 阶段执行")
    lock = state.get("approvals", {}).get("storyboard")
    if not lock or lock.get("audit", {}).get("create_task_authorized") is not True:
        raise WorkflowError("缺少授权创建一次视频任务的有效 Storyboard 锁")
    storyboard = storyboard_package_entry(state, lock["storyboard_revision"])
    storyboard_payload = read_json_artifact(storyboard, "storyboard-package")
    if storyboard["sha256"] != lock["storyboard_package_sha256"]:
        raise WorkflowError("锁定 Storyboard 哈希与当前包不一致")
    h3_prompt = artifact_entry(state, "h3-prompt")
    required_lock = {
        "storyboard_lock_id": lock["lock_id"],
        "storyboard_revision": lock["storyboard_revision"],
        "storyboard_package_sha256": lock["storyboard_package_sha256"],
        "script_lock_id": lock["script_lock_id"],
        "candidate_id": lock["candidate_id"],
    }
    for field, expected in required_lock.items():
        if h3_prompt.get(field) != expected:
            raise WorkflowError(f"h3-prompt.{field} 未绑定当前 Storyboard 锁")
    validation = artifact_entry(state, "h3-validation")
    validation_payload = read_json_artifact(validation, "h3-validation")
    if not validation_payload.get("valid") or validation_payload.get("prompt_sha256") != h3_prompt.get("sha256") or validation_payload.get("mode") != "ref2va":
        raise WorkflowError("H3 prompt 缺少匹配的 Ref2VA 成功校验")
    prompt_text = verify_artifact_integrity(h3_prompt, "h3-prompt").read_text(encoding="utf-8-sig").strip()
    preview = artifact_entry(state, "task-preview")
    preview_payload = read_json_artifact(preview, "task-preview")
    manifest = json.loads((run_dir.resolve() / "manifest.json").read_text(encoding="utf-8"))
    aggregate_sha = storyboard_payload["components"]["aggregate_keyframe"]["sha256"]
    visual_plan = read_json_artifact(storyboard_payload["components"]["visual_plan"], "visual-plan")
    reference_assets = validate_v4_task_preview(preview_payload, prompt_text, aggregate_sha, manifest.get("assets", []), visual_plan)
    used_idempotency_keys = {
        read_json_artifact(entry, "production-package").get("idempotency_key")
        for entry in state.get("artifacts", {}).get("production-package", [])
    }
    if preview_payload.get("idempotency_key") in used_idempotency_keys:
        raise WorkflowError("新的生产意图必须使用从未使用过的 idempotency_key")
    retry = state.get("active_retry")
    if retry:
        if preview.get("retry_authorization_version") != retry["authorization_version"]:
            raise WorkflowError("显式重试必须记录新的 task-preview")
        if preview_payload.get("idempotency_key") == retry.get("prior_idempotency_key"):
            raise WorkflowError("显式重试必须使用新的 idempotency_key")
    required_binding = {**required_lock, "h3_prompt_version": h3_prompt["version"]}
    for field, expected in required_binding.items():
        if preview_payload.get(field) != expected:
            raise WorkflowError(f"task-preview.{field} 未绑定锁定 Storyboard")
    entries = state.setdefault("artifacts", {}).setdefault("production-package", [])
    version = len(entries) + 1
    destination = run_dir.resolve() / f"production-package-v{version:02d}.json"
    payload = {"schema_version": 4, "production_package_version": version, **required_binding, "storyboard_package_version": storyboard["version"], "aggregate_keyframe": storyboard_payload["components"]["aggregate_keyframe"], "reference_assets": reference_assets, "h3_prompt": component_binding(h3_prompt), "h3_validation": component_binding(validation), "task_preview": component_binding(preview), "task_parameters": preview_payload, "idempotency_key": preview_payload["idempotency_key"], "created_at": now_iso()}
    atomic_json_write(destination, payload)
    timestamp = now_iso()
    entry = {"version": version, "path": str(destination), "sha256": sha256_file(destination), "recorded_at": timestamp, **required_binding}
    entries.append(entry)
    state["stage"] = "production_ready"
    state.pop("active_retry", None)
    state["updated_at"] = timestamp
    state.setdefault("history", []).append({"at": timestamp, "event": "production_finalized", "version": version, "storyboard_lock_id": lock["lock_id"]})
    atomic_json_write(state_path, state)
    return entry


def finalize_production(run_dir: Path) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    if schema_version(state) == 4:
        return finalize_production_v4(run_dir, state_path, state)
    if schema_version(state) != 3 or state.get("stage") != "proposal_locked":
        raise WorkflowError("finalize-production 只能在 proposal_locked 阶段执行")
    lock = state.get("approvals", {}).get("proposal")
    if not lock or lock.get("audit", {}).get("create_task_authorized") is not True:
        raise WorkflowError("缺少授权创建一次视频任务的有效提案锁")
    proposal = proposal_entry(state, lock["proposal_revision"])
    verify_artifact_integrity(proposal, "proposal-package")
    proposal_payload = verify_proposal_components(proposal)
    if proposal["sha256"] != lock["proposal_package_sha256"]:
        raise WorkflowError("锁定提案哈希与当前提案包不一致")
    h3_prompt = artifact_entry(state, "h3-prompt")
    for field, expected in {
        "proposal_lock_id": lock["lock_id"],
        "proposal_revision": lock["proposal_revision"],
        "proposal_package_sha256": lock["proposal_package_sha256"],
        "candidate_id": lock["candidate_id"],
    }.items():
        if h3_prompt.get(field) != expected:
            raise WorkflowError(f"h3-prompt.{field} 未绑定当前提案锁")
    validation = artifact_entry(state, "h3-validation")
    validation_payload = read_json_artifact(validation, "h3-validation")
    if not validation_payload.get("valid") or validation_payload.get("prompt_sha256") != h3_prompt.get("sha256"):
        raise WorkflowError("H3 prompt 缺少匹配的成功校验")
    preview = artifact_entry(state, "task-preview")
    preview_payload = read_json_artifact(preview, "task-preview")
    validate_v3_task_preview(preview_payload)
    retry = state.get("active_retry")
    if retry:
        if preview.get("retry_authorization_version") != retry["authorization_version"]:
            raise WorkflowError("显式重试必须记录新的 task-preview")
        if preview_payload.get("idempotency_key") == retry.get("prior_idempotency_key"):
            raise WorkflowError("显式重试必须使用新的 idempotency_key")
    required_binding = {"proposal_lock_id": lock["lock_id"], "proposal_revision": lock["proposal_revision"], "proposal_package_sha256": lock["proposal_package_sha256"], "candidate_id": lock["candidate_id"], "h3_prompt_version": h3_prompt["version"]}
    for field, expected in required_binding.items():
        if preview_payload.get(field) != expected:
            raise WorkflowError(f"task-preview.{field} 未绑定锁定提案")
    if not is_uuid(preview_payload.get("idempotency_key")):
        raise WorkflowError("task-preview.idempotency_key 必须是 UUID")
    entries = state.setdefault("artifacts", {}).setdefault("production-package", [])
    version = len(entries) + 1
    destination = run_dir.resolve() / f"production-package-v{version:02d}.json"
    payload = {"schema_version": 3, "production_package_version": version, **required_binding, "proposal_package_version": proposal["version"], "aggregate_keyframe": proposal_payload["components"]["aggregate_keyframe"], "h3_prompt": component_binding(h3_prompt), "h3_validation": component_binding(validation), "task_preview": component_binding(preview), "task_parameters": preview_payload, "idempotency_key": preview_payload["idempotency_key"], "created_at": now_iso()}
    atomic_json_write(destination, payload)
    timestamp = now_iso()
    entry = {"version": version, "path": str(destination), "sha256": sha256_file(destination), "recorded_at": timestamp, **required_binding}
    entries.append(entry)
    state["stage"] = "production_ready"
    state.pop("active_retry", None)
    state["updated_at"] = timestamp
    state.setdefault("history", []).append({"at": timestamp, "event": "production_finalized", "version": version, "proposal_lock_id": lock["lock_id"]})
    atomic_json_write(state_path, state)
    return entry


def authorize_retry(run_dir: Path, approval_json: Path) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    if schema_version(state) == 4:
        if state.get("stage") != "failed":
            raise WorkflowError("authorize-retry 只能用于 schema v4 的 failed 阶段")
        lock = state.get("approvals", {}).get("storyboard")
        if not lock:
            raise WorkflowError("显式重试缺少原 Storyboard 锁")
        audit = read_json_file(approval_json, "retry approval")
        if any(audit.get(field) in (None, "") for field in ("raw_reply", "confirmed_at", "channel")):
            raise WorkflowError("重试审计必须包含 raw_reply、confirmed_at 和 channel")
        if audit.get("retry_authorized") is not True:
            raise WorkflowError("重试审计必须明确 retry_authorized: true")
        entries = state.setdefault("artifacts", {}).setdefault("retry-authorization", [])
        version = len(entries) + 1
        destination = run_dir.resolve() / f"retry-authorization-v{version:02d}.json"
        payload = sanitize_json({**audit, "storyboard_lock_id": lock["lock_id"], "prior_task_id": state.get("task", {}).get("task_id"), "retry_authorized": True})
        atomic_json_write(destination, payload)
        timestamp = now_iso()
        entries.append({"version": version, "path": str(destination), "sha256": sha256_file(destination), "recorded_at": timestamp, "storyboard_lock_id": lock["lock_id"]})
        prior = state.get("artifacts", {}).get("production-package", [])
        prior_idempotency = read_json_artifact(prior[-1], "production-package").get("idempotency_key") if prior else None
        state["active_retry"] = {"authorization_version": version, "prior_idempotency_key": prior_idempotency, "authorized_at": timestamp}
        state["stage"] = "storyboard_locked"
        state.pop("task", None)
        state["updated_at"] = timestamp
        state.setdefault("history", []).append({"at": timestamp, "event": "task_retry_authorized", "version": version, "storyboard_lock_id": lock["lock_id"]})
        atomic_json_write(state_path, state)
        return state
    if schema_version(state) != 3 or state.get("stage") != "failed":
        raise WorkflowError("authorize-retry 只能用于 schema v3 的 failed 阶段")
    lock = state.get("approvals", {}).get("proposal")
    if not lock:
        raise WorkflowError("显式重试缺少原提案锁")
    try:
        audit = json.loads(approval_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"retry approval 必须是有效 JSON: {exc}") from exc
    if not isinstance(audit, dict) or any(audit.get(field) in (None, "") for field in ("raw_reply", "confirmed_at", "channel")):
        raise WorkflowError("重试审计必须包含 raw_reply、confirmed_at 和 channel")
    if audit.get("retry_authorized") is not True:
        raise WorkflowError("重试审计必须明确 retry_authorized: true")
    entries = state.setdefault("artifacts", {}).setdefault("retry-authorization", [])
    version = len(entries) + 1
    destination = run_dir.resolve() / f"retry-authorization-v{version:02d}.json"
    payload = sanitize_json({**audit, "proposal_lock_id": lock["lock_id"], "prior_task_id": state.get("task", {}).get("task_id"), "retry_authorized": True})
    atomic_json_write(destination, payload)
    timestamp = now_iso()
    entries.append({"version": version, "path": str(destination), "sha256": sha256_file(destination), "recorded_at": timestamp, "proposal_lock_id": lock["lock_id"]})
    prior_production = state.get("artifacts", {}).get("production-package", [])
    prior_idempotency = read_json_artifact(prior_production[-1], "production-package").get("idempotency_key") if prior_production else None
    state["active_retry"] = {"authorization_version": version, "prior_idempotency_key": prior_idempotency, "authorized_at": timestamp}
    state["stage"] = "proposal_locked"
    state.pop("task", None)
    state["updated_at"] = timestamp
    state.setdefault("history", []).append({"at": timestamp, "event": "task_retry_authorized", "version": version, "proposal_lock_id": lock["lock_id"]})
    atomic_json_write(state_path, state)
    return state


def approve_gate(
    run_dir: Path,
    gate: str,
    version: int | None = None,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    if schema_version(state) == 4:
        raise WorkflowError("schema v4 使用 lock-script 和 lock-storyboard，不使用旧 Gate 审批")
    if schema_version(state) == 3:
        raise WorkflowError("schema v3 使用 finalize-proposal 和 lock-proposal，不使用旧 Gate 审批")
    expected_stage = {"script": "script_review", "keyframe": "keyframe_review", "task": "task_review"}[gate]
    if state.get("stage") != expected_stage:
        raise WorkflowError(f"{gate} 确认只能在 {expected_stage} 阶段执行")
    timestamp = now_iso()
    approvals = state.setdefault("approvals", {})
    is_v2 = schema_version(state) == 2

    if gate == "script":
        script = artifact_entry(state, "script", version)
        if is_v2:
            candidate_ids = validate_script_set(verify_artifact_integrity(script, "script"))
            approvals["script"] = {
                "at": timestamp,
                "script_version": script["version"],
                "candidate_ids": list(candidate_ids),
            }
        else:
            keyframe_prompt = artifact_entry(state, "keyframe-prompt")
            approvals["script"] = {
                "at": timestamp,
                "script_version": script["version"],
                "keyframe_prompt_version": keyframe_prompt["version"],
            }
        state["stage"] = "keyframe_review"
    elif gate == "keyframe":
        if "script" not in approvals:
            raise WorkflowError("确认关键帧前必须先确认脚本")
        if is_v2:
            selected_id = validate_candidate_id(candidate_id)
            batch = require_complete_candidate_batch(state)
            keyframe = artifact_entry_for_candidate(state, "keyframe", selected_id, version)
            prompt = batch[selected_id]["prompt"]
            if keyframe.get("keyframe_prompt_version") != prompt.get("version"):
                raise WorkflowError("所选关键帧未绑定当前候选的最新提示词")
            approvals["keyframe"] = {
                "at": timestamp,
                "candidate_id": selected_id,
                "script_version": approvals["script"]["script_version"],
                "keyframe_prompt_version": prompt["version"],
                "keyframe_version": keyframe["version"],
            }
        else:
            keyframe = artifact_entry(state, "keyframe", version)
            approvals["keyframe"] = {"at": timestamp, "keyframe_version": keyframe["version"]}
        approvals.pop("task", None)
    else:
        if "script" not in approvals or "keyframe" not in approvals:
            raise WorkflowError("确认任务前必须先确认脚本和关键帧")
        h3_prompt = artifact_entry(state, "h3-prompt")
        task_preview = artifact_entry(state, "task-preview")
        validate_task_preview(state, task_preview, h3_prompt)
        task_binding = {
            "h3_prompt_version": h3_prompt["version"],
            "task_preview_version": task_preview["version"],
            "keyframe_version": approvals["keyframe"]["keyframe_version"],
        }
        if is_v2:
            for field in ("candidate_id", "script_version", "keyframe_prompt_version"):
                task_binding[field] = approvals["keyframe"][field]
        existing_task = approvals.get("task")
        if existing_task is not None:
            if all(existing_task.get(field) == value for field, value in task_binding.items()):
                return state
            raise WorkflowError("当前运行已有不同绑定的 Gate 3 审批；请先返回修改或进入显式重试流程")
        approvals["task"] = {
            "at": timestamp,
            "intent_id": str(uuid.uuid4()),
            **task_binding,
        }

    state["updated_at"] = timestamp
    state.setdefault("history", []).append(
        {"at": timestamp, "event": "gate_approved", "gate": gate, "stage": state["stage"]}
    )
    atomic_json_write(state_path, state)
    return state


def check_transition_preconditions(state: dict[str, Any], current: str, new_stage: str) -> None:
    approvals = state.get("approvals", {})
    if schema_version(state) == 4 and current == "script_locked" and new_stage == "storyboard_review":
        if not approvals.get("script"):
            raise WorkflowError("进入 storyboard_review 前必须存在 Final Script 锁")
    elif schema_version(state) == 4 and current == "production_ready" and new_stage == "submitted":
        lock = approvals.get("storyboard")
        if not lock or lock.get("audit", {}).get("create_task_authorized") is not True:
            raise WorkflowError("提交前必须存在授权创建任务的 Storyboard 锁")
        binding = require_bound_request(state)
        task_result = artifact_entry(state, "task-result")
        verify_artifact_integrity(task_result, "task-result")
        if task_result.get("storyboard_lock_id") != lock.get("lock_id"):
            raise WorkflowError("最新任务结果不属于当前 Storyboard 锁")
        if task_result.get("request_version") != binding["request"]["version"]:
            raise WorkflowError("最新任务结果未绑定当前已校验请求")
        if not state.get("task", {}).get("task_id"):
            raise WorkflowError("进入 submitted 前必须记录当前任务的 task_id")
    elif schema_version(state) == 3 and current == "production_ready" and new_stage == "submitted":
        lock = approvals.get("proposal")
        if not lock or lock.get("audit", {}).get("create_task_authorized") is not True:
            raise WorkflowError("提交前必须存在授权创建任务的提案锁")
        binding = require_bound_request(state)
        task_result = artifact_entry(state, "task-result")
        verify_artifact_integrity(task_result, "task-result")
        if task_result.get("proposal_lock_id") != lock.get("lock_id"):
            raise WorkflowError("最新任务结果不属于当前提案锁")
        if task_result.get("request_version") != binding["request"]["version"]:
            raise WorkflowError("最新任务结果未绑定当前已校验请求")
        if not state.get("task", {}).get("task_id"):
            raise WorkflowError("进入 submitted 前必须记录当前任务的 task_id")
    elif current == "keyframe_review" and new_stage == "task_review":
        if "keyframe" not in approvals:
            raise WorkflowError("进入任务确认前必须确认关键帧")
        h3_prompt = artifact_entry(state, "h3-prompt")
        validation = artifact_entry(state, "h3-validation")
        try:
            validation_payload = read_json_artifact(validation, "h3-validation")
            verify_artifact_integrity(h3_prompt, "h3-prompt")
        except WorkflowError as exc:
            raise WorkflowError("无法读取 H3 提示词校验记录") from exc
        if not validation_payload.get("valid") or validation_payload.get("prompt_sha256") != h3_prompt["sha256"]:
            raise WorkflowError("最新 H3 提示词没有匹配的成功校验记录")
        task_preview = artifact_entry(state, "task-preview")
        validate_task_preview(state, task_preview, h3_prompt)
    elif current == "task_review" and new_stage == "submitted":
        if "task" not in approvals:
            raise WorkflowError("提交前必须完成 Gate 3 确认")
        binding = require_bound_request(state)
        task_result = artifact_entry(state, "task-result")
        verify_artifact_integrity(task_result, "task-result")
        if task_result.get("intent_id") != approvals["task"].get("intent_id"):
            raise WorkflowError("最新任务结果不属于当前 Gate 3 审批意图")
        if task_result.get("request_version") != binding["request"]["version"]:
            raise WorkflowError("最新任务结果未绑定当前已校验请求")
        if not state.get("task", {}).get("task_id"):
            raise WorkflowError("进入 submitted 前必须记录当前任务的 task_id")
    elif current == "submitted" and new_stage in {"monitoring", "succeeded", "failed"}:
        if not state.get("task", {}).get("task_id"):
            raise WorkflowError("提交状态转换前必须记录 task_id")
    elif current == "monitoring" and new_stage in {"succeeded", "failed"}:
        artifact_entry(state, "task-result")


def set_stage(run_dir: Path, expected: str, new_stage: str) -> dict[str, Any]:
    if new_stage not in ALLOWED_STAGES:
        raise WorkflowError(f"未知阶段: {new_stage}")
    state_path, state = load_state(run_dir)
    current = state.get("stage")
    if current != expected:
        raise WorkflowError(f"阶段冲突: 期望 {expected}，实际 {current}")
    if new_stage not in TRANSITIONS.get(current, set()):
        raise WorkflowError(f"不允许的阶段转换: {current} -> {new_stage}")
    check_transition_preconditions(state, current, new_stage)
    timestamp = now_iso()
    approvals = state.setdefault("approvals", {})
    if new_stage == "script_review":
        approvals.clear()
    elif new_stage == "keyframe_review" and current == "task_review":
        approvals.pop("keyframe", None)
        approvals.pop("task", None)
    elif current == "failed" and new_stage in {"task_review", "proposal_locked"}:
        approvals.pop("task", None)
        state.pop("task", None)
    state["stage"] = new_stage
    state["updated_at"] = timestamp
    state.setdefault("history", []).append(
        {"at": timestamp, "event": "stage_changed", "from": current, "to": new_stage}
    )
    atomic_json_write(state_path, state)
    return state


def sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if is_sensitive_key(key) else sanitize_json(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    return value


def is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
    compact = normalized.replace("_", "")
    return (
        normalized in SENSITIVE_KEYS
        or "token" in compact
        or "authorization" in compact
        or "presigned" in compact
        or (compact.startswith("upload") and ("url" in compact or "header" in compact))
    )


def load_console_validator() -> Any:
    path = (
        Path(__file__).resolve().parents[2]
        / "minimax-h3-console-video-generator"
        / "scripts"
        / "validate_request.py"
    )
    if not path.is_file():
        raise WorkflowError(f"找不到 Console 请求校验器: {path}")
    spec = importlib.util.spec_from_file_location("minimax_h3_validate_request", path)
    if spec is None or spec.loader is None:
        raise WorkflowError("无法加载 Console 请求校验器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_v3_request_for_run(state: dict[str, Any], path: Path) -> dict[str, Any]:
    if state.get("stage") != "production_ready":
        raise WorkflowError("schema v3 最终请求只能在 production_ready 阶段校验")
    lock = state.get("approvals", {}).get("proposal")
    if not lock or lock.get("audit", {}).get("create_task_authorized") is not True:
        raise WorkflowError("缺少创建一次视频任务的客户授权")
    request_entry = artifact_entry(state, "request")
    errors: list[str] = []
    if Path(path).resolve() != Path(request_entry["path"]).resolve():
        errors.append("必须校验最新记录的 request 产物")
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "request_sha256": None, "errors": [f"request 必须是有效 JSON: {exc}"]}
    production = artifact_entry(state, "production-package")
    production_payload = read_json_artifact(production, "production-package")
    proposal = proposal_entry(state, lock["proposal_revision"])
    verify_proposal_components(proposal)
    preview_entry = artifact_entry(state, "task-preview", production_payload["task_preview"]["version"])
    preview = read_json_artifact(preview_entry, "task-preview")
    h3_prompt = artifact_entry(state, "h3-prompt", production_payload["h3_prompt"]["version"])
    try:
        errors.extend(load_console_validator().validate(request))
    except (AttributeError, OSError) as exc:
        raise WorkflowError(f"Console 请求校验器执行失败: {exc}") from exc
    for field in ("workspace_id", "mode", "duration_seconds", "aspect_ratio", "quality", "execution_backend", "idempotency_key"):
        if request.get(field) != preview.get(field):
            errors.append(f"request.{field} 与 production package 不一致")
    approved_prompt = verify_artifact_integrity(h3_prompt, "h3-prompt").read_text(encoding="utf-8-sig").strip()
    if not isinstance(request.get("prompt"), str) or request["prompt"].strip() != approved_prompt:
        errors.append("request.prompt 与 production package 中的 H3 prompt 不一致")
    assets = request.get("assets")
    if not isinstance(assets, list) or len(assets) != 1 or not isinstance(assets[0], dict) or assets[0].get("role") != "first_frame":
        errors.append("I2V 请求必须只包含一个 first_frame 素材")
    else:
        try:
            upload = artifact_entry(state, "asset-upload")
            upload_payload = read_json_artifact(upload, "asset-upload")
            if upload_payload.get("proposal_lock_id") != lock["lock_id"]:
                errors.append("asset-upload 未绑定当前提案锁")
            if upload_payload.get("source_sha256") != production_payload["aggregate_keyframe"]["sha256"]:
                errors.append("asset-upload 未绑定锁定总聚合关键帧")
            if assets[0].get("asset_id") != upload_payload.get("asset_id"):
                errors.append("request first_frame asset_id 与已记录上传结果不一致")
        except WorkflowError as exc:
            errors.append(str(exc))
    return {
        "valid": not errors,
        "request_sha256": sha256_file(path),
        "request_version": request_entry["version"],
        "proposal_lock_id": lock["lock_id"],
        "proposal_revision": lock["proposal_revision"],
        "proposal_package_sha256": lock["proposal_package_sha256"],
        "production_package_version": production["version"],
        "candidate_id": lock["candidate_id"],
        "idempotency_key": request.get("idempotency_key"),
        "errors": errors,
    }


def validate_v4_request_for_run(state: dict[str, Any], path: Path) -> dict[str, Any]:
    if state.get("stage") != "production_ready":
        raise WorkflowError("schema v4 最终请求只能在 production_ready 阶段校验")
    lock = state.get("approvals", {}).get("storyboard")
    if not lock or lock.get("audit", {}).get("create_task_authorized") is not True:
        raise WorkflowError("缺少创建一次视频任务的客户授权")
    request_entry = artifact_entry(state, "request")
    errors: list[str] = []
    if Path(path).resolve() != Path(request_entry["path"]).resolve():
        errors.append("必须校验最新记录的 request 产物")
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "request_sha256": None, "errors": [f"request 必须是有效 JSON: {exc}"]}
    production = artifact_entry(state, "production-package")
    production_payload = read_json_artifact(production, "production-package")
    preview_entry = artifact_entry(state, "task-preview", production_payload["task_preview"]["version"])
    preview = read_json_artifact(preview_entry, "task-preview")
    h3_prompt = artifact_entry(state, "h3-prompt", production_payload["h3_prompt"]["version"])
    try:
        errors.extend(load_console_validator().validate(request))
    except (AttributeError, OSError) as exc:
        raise WorkflowError(f"Console 请求校验器执行失败: {exc}") from exc
    for field in ("workspace_id", "mode", "duration_seconds", "aspect_ratio", "quality", "execution_backend", "idempotency_key"):
        if request.get(field) != preview.get(field):
            errors.append(f"request.{field} 与 production package 不一致")
    approved_prompt = verify_artifact_integrity(h3_prompt, "h3-prompt").read_text(encoding="utf-8-sig").strip()
    if not isinstance(request.get("prompt"), str) or request["prompt"].strip() != approved_prompt:
        errors.append("request.prompt 与 production package 中的 H3 prompt 不一致")
    assets = request.get("assets")
    requested_by_name = {
        item.get("mention_name"): item for item in assets
        if isinstance(assets, list) and isinstance(item, dict) and item.get("mention_name")
    }
    expected_assets = production_payload.get("reference_assets", [])
    uploads: dict[str, dict[str, Any]] = {}
    for entry in state.get("artifacts", {}).get("asset-upload", []):
        payload = read_json_artifact(entry, "asset-upload")
        if payload.get("storyboard_lock_id") == lock["lock_id"]:
            uploads[payload.get("mention_name")] = payload
    if not isinstance(assets, list) or len(assets) != len(expected_assets):
        errors.append("R2V 请求素材数量与 production package 不一致")
    for expected in expected_assets:
        name = expected["mention_name"]
        upload = uploads.get(name)
        requested = requested_by_name.get(name)
        if upload is None:
            errors.append(f"缺少 @{name} 的 asset-upload 证据")
            continue
        if upload.get("source_sha256") != expected.get("source_sha256"):
            errors.append(f"@{name} 的上传素材哈希与 production package 不一致")
        if upload.get("source_filename") != expected.get("source_filename") or upload.get("asset_role") != expected.get("asset_role"):
            errors.append(f"@{name} 的上传素材语义与 production package 不一致")
        if requested is None:
            errors.append(f"request 缺少 @{name} 素材")
        elif requested.get("asset_id") != upload.get("asset_id") or requested.get("role") != "reference_image":
            errors.append(f"request @{name} 未绑定已记录的 reference_image 上传结果")
    return {
        "valid": not errors,
        "request_sha256": sha256_file(path),
        "request_version": request_entry["version"],
        "storyboard_lock_id": lock["lock_id"],
        "storyboard_revision": lock["storyboard_revision"],
        "storyboard_package_sha256": lock["storyboard_package_sha256"],
        "production_package_version": production["version"],
        "candidate_id": lock["candidate_id"],
        "idempotency_key": request.get("idempotency_key"),
        "errors": errors,
    }


def validate_request_for_run(run_dir: Path, path: Path) -> dict[str, Any]:
    _, state = load_state(run_dir)
    if schema_version(state) == 4:
        return validate_v4_request_for_run(state, path)
    if schema_version(state) == 3:
        return validate_v3_request_for_run(state, path)
    approval = state.get("approvals", {}).get("task")
    errors: list[str] = []
    if state.get("stage") != "task_review" or not approval:
        raise WorkflowError("最终请求只能在 Gate 3 确认后的 task_review 阶段校验")

    request_entry = artifact_entry(state, "request")
    if Path(path).resolve() != Path(request_entry["path"]).resolve():
        errors.append("必须校验最新记录的 request 产物")
    try:
        request = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "request_sha256": None, "errors": [f"request 必须是有效 JSON: {exc}"]}
    if not isinstance(request, dict):
        return {"valid": False, "request_sha256": sha256_file(path), "errors": ["request 根节点必须是对象"]}

    h3_prompt = artifact_entry(state, "h3-prompt", approval["h3_prompt_version"])
    task_preview = artifact_entry(state, "task-preview", approval["task_preview_version"])
    preview = validate_task_preview(state, task_preview, h3_prompt)
    try:
        errors.extend(load_console_validator().validate(request))
    except (AttributeError, OSError) as exc:
        raise WorkflowError(f"Console 请求校验器执行失败: {exc}") from exc

    for field in (
        "workspace_id",
        "mode",
        "duration_seconds",
        "aspect_ratio",
        "quality",
        "execution_backend",
        "idempotency_key",
    ):
        if request.get(field) != preview.get(field):
            errors.append(f"request.{field} 与已确认 task-preview 不一致")

    try:
        approved_prompt = verify_artifact_integrity(h3_prompt, "h3-prompt").read_text(encoding="utf-8-sig").strip()
    except OSError as exc:
        raise WorkflowError("无法读取已确认 H3 提示词") from exc
    if not isinstance(request.get("prompt"), str) or request["prompt"].strip() != approved_prompt:
        errors.append("request.prompt 与已确认 H3 提示词不一致")
    assets = request.get("assets")
    if not isinstance(assets, list) or len(assets) != 1 or not isinstance(assets[0], dict) or assets[0].get("role") != "first_frame":
        errors.append("I2V 请求必须只包含一个 first_frame 素材")

    return {
        "valid": not errors,
        "request_sha256": sha256_file(path),
        "request_version": request_entry["version"],
        "task_preview_version": task_preview["version"],
        "h3_prompt_version": h3_prompt["version"],
        "keyframe_version": approval["keyframe_version"],
        "intent_id": approval["intent_id"],
        "idempotency_key": request.get("idempotency_key"),
        "errors": errors,
        **(
            {
                "candidate_id": approval.get("candidate_id"),
                "script_version": approval.get("script_version"),
                "keyframe_prompt_version": approval.get("keyframe_prompt_version"),
            }
            if schema_version(state) >= 2
            else {}
        ),
    }


def record_request_validation(run_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("valid"):
        raise WorkflowError("不能记录失败的最终请求校验")
    state_path, state = load_state(run_dir)
    approval_key = "storyboard" if schema_version(state) == 4 else ("proposal" if schema_version(state) == 3 else "task")
    approval = state.get("approvals", {}).get(approval_key, {})
    request = artifact_entry(state, "request")
    verify_artifact_integrity(request, "request")
    if result.get("request_sha256") != request.get("sha256"):
        raise WorkflowError("校验结果与最新 request 不匹配")
    if schema_version(state) == 4:
        if result.get("storyboard_lock_id") != approval.get("lock_id"):
            raise WorkflowError("校验结果不属于当前 Storyboard 锁")
    elif schema_version(state) == 3:
        if result.get("proposal_lock_id") != approval.get("lock_id"):
            raise WorkflowError("校验结果不属于当前提案锁")
    elif result.get("intent_id") != approval.get("intent_id"):
        raise WorkflowError("校验结果不属于当前 Gate 3 审批意图")
    entries = state.setdefault("artifacts", {}).setdefault("request-validation", [])
    version = len(entries) + 1
    destination = run_dir.resolve() / f"request-validation-v{version:02d}.json"
    if destination.exists():
        raise WorkflowError(f"产物目标已存在: {destination}")
    atomic_json_write(destination, result)
    timestamp = now_iso()
    entry = {
        "version": version,
        "path": str(destination),
        "sha256": sha256_file(destination),
        "recorded_at": timestamp,
    }
    entries.append(entry)
    state["updated_at"] = timestamp
    state.setdefault("history", []).append(
        {"at": timestamp, "event": "request_validated", "request_version": request["version"]}
    )
    atomic_json_write(state_path, state)
    return entry


def require_bound_request(state: dict[str, Any]) -> dict[str, Any]:
    if schema_version(state) == 4:
        approval = state.get("approvals", {}).get("storyboard")
        if not approval:
            raise WorkflowError("缺少当前 Storyboard 锁")
        request = artifact_entry(state, "request")
        verify_artifact_integrity(request, "request")
        validation = artifact_entry(state, "request-validation")
        payload = read_json_artifact(validation, "request-validation")
        production = artifact_entry(state, "production-package")
        if not payload.get("valid") or payload.get("request_sha256") != request.get("sha256"):
            raise WorkflowError("最新 request 没有匹配的成功校验记录")
        expected = {
            "storyboard_lock_id": approval["lock_id"],
            "storyboard_revision": approval["storyboard_revision"],
            "storyboard_package_sha256": approval["storyboard_package_sha256"],
            "production_package_version": production["version"],
        }
        for field, value in expected.items():
            if payload.get(field) != value:
                raise WorkflowError(f"request 校验记录的 {field} 与生产包不一致")
        return {"request": request, "validation": validation, "payload": payload}
    if schema_version(state) == 3:
        approval = state.get("approvals", {}).get("proposal")
        if not approval:
            raise WorkflowError("缺少当前提案锁")
        request = artifact_entry(state, "request")
        verify_artifact_integrity(request, "request")
        validation = artifact_entry(state, "request-validation")
        payload = read_json_artifact(validation, "request-validation")
        production = artifact_entry(state, "production-package")
        if not payload.get("valid") or payload.get("request_sha256") != request.get("sha256"):
            raise WorkflowError("最新 request 没有匹配的成功校验记录")
        expected = {
            "proposal_lock_id": approval["lock_id"],
            "proposal_revision": approval["proposal_revision"],
            "proposal_package_sha256": approval["proposal_package_sha256"],
            "production_package_version": production["version"],
        }
        for field, value in expected.items():
            if payload.get(field) != value:
                raise WorkflowError(f"request 校验记录的 {field} 与生产包不一致")
        return {"request": request, "validation": validation, "payload": payload}
    approval = state.get("approvals", {}).get("task")
    if not approval:
        raise WorkflowError("缺少当前 Gate 3 审批")
    request = artifact_entry(state, "request")
    verify_artifact_integrity(request, "request")
    validation = artifact_entry(state, "request-validation")
    payload = read_json_artifact(validation, "request-validation")
    if not payload.get("valid") or payload.get("request_sha256") != request.get("sha256"):
        raise WorkflowError("最新 request 没有匹配的成功校验记录")
    if payload.get("request_version") != request.get("version"):
        raise WorkflowError("request 校验记录版本不匹配")
    if payload.get("intent_id") != approval.get("intent_id"):
        raise WorkflowError("request 校验记录不属于当前 Gate 3 审批意图")
    binding_fields = ["task_preview_version", "h3_prompt_version", "keyframe_version"]
    if schema_version(state) >= 2:
        binding_fields.extend(["candidate_id", "script_version", "keyframe_prompt_version"])
    for field in binding_fields:
        if payload.get(field) != approval.get(field):
            raise WorkflowError(f"request 校验记录的 {field} 与审批不一致")
    return {"request": request, "validation": validation, "payload": payload}


def record_artifact(
    run_dir: Path,
    kind: str,
    source: Path,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    if kind not in ARTIFACT_KINDS:
        raise WorkflowError(f"未知产物类型: {kind}")
    source = source.resolve()
    if not source.is_file():
        raise WorkflowError(f"产物源文件不存在: {source}")
    state_path, state = load_state(run_dir)
    schema = schema_version(state)
    is_v2 = schema == 2
    is_v3 = schema == 3
    is_v4 = schema == 4
    selected_id: str | None = None
    binding: dict[str, Any] = {}
    if is_v4:
        allowed_direct = {"script-proposal", "final-script", "visual-plan", "aggregate-keyframe-prompt", "aggregate-keyframe", "h3-prompt", "task-preview", "request", "asset-upload", "task-result"}
        if kind not in allowed_direct:
            raise WorkflowError(f"schema v4 的 {kind} 必须由专用命令生成")
        if candidate_id is not None:
            raise WorkflowError("schema v4 产物不接受 candidate-id；候选由锁定命令绑定")
        stage = state.get("stage")
        if kind == "script-proposal":
            if stage != "script_review":
                raise WorkflowError("script-proposal 只能在 script_review 阶段记录")
            validate_script_proposal(source)
        elif kind == "final-script":
            if stage != "script_review":
                raise WorkflowError("final-script 只能在 script_review 阶段记录")
            package = script_package_entry(state)
            binding.update({"script_revision": package["script_revision"], "script_package_version": package["version"], "script_package_sha256": package["sha256"]})
            validate_final_script(source)
        elif kind in {"visual-plan", "aggregate-keyframe-prompt", "aggregate-keyframe"}:
            script_lock = state.get("approvals", {}).get("script")
            if stage != "storyboard_review" or not script_lock:
                raise WorkflowError(f"{kind} 只能在 Final Script 锁定后的 storyboard_review 阶段记录")
            binding["script_lock_id"] = script_lock["lock_id"]
            if kind == "visual-plan":
                validate_visual_plan(source)
            elif kind == "aggregate-keyframe":
                if source.suffix.casefold() not in SUPPORTED_IMAGES:
                    raise WorkflowError("aggregate-keyframe 必须是支持的图片格式")
                prompt = artifact_entry(state, "aggregate-keyframe-prompt")
                if prompt.get("script_lock_id") != script_lock["lock_id"]:
                    raise WorkflowError("aggregate-keyframe-prompt 未绑定当前 script lock")
                binding["keyframe_prompt_version"] = prompt["version"]
        elif kind in {"h3-prompt", "task-preview"}:
            lock = state.get("approvals", {}).get("storyboard")
            if stage != "storyboard_locked" or not lock:
                raise WorkflowError(f"{kind} 只能在 Storyboard 锁定后记录")
            binding = {
                "storyboard_lock_id": lock["lock_id"],
                "storyboard_revision": lock["storyboard_revision"],
                "storyboard_package_sha256": lock["storyboard_package_sha256"],
                "script_lock_id": lock["script_lock_id"],
                "candidate_id": lock["candidate_id"],
            }
            if kind == "task-preview":
                payload = read_json_file(source, "task-preview")
                for field, expected in binding.items():
                    if payload.get(field) != expected:
                        raise WorkflowError(f"task-preview.{field} 未绑定锁定 Storyboard")
                h3 = artifact_entry(state, "h3-prompt")
                if payload.get("h3_prompt_version") != h3["version"]:
                    raise WorkflowError("task-preview.h3_prompt_version 未绑定最新 H3 prompt")
                binding["h3_prompt_version"] = h3["version"]
                if state.get("active_retry"):
                    binding["retry_authorization_version"] = state["active_retry"]["authorization_version"]
        elif kind == "request":
            if stage != "production_ready":
                raise WorkflowError("request 只能在 production_ready 阶段记录")
        elif kind == "asset-upload":
            if stage != "production_ready":
                raise WorkflowError("asset-upload 只能在 production_ready 阶段记录")
            upload = read_json_file(source, "asset-upload")
            production = read_json_artifact(artifact_entry(state, "production-package"), "production-package")
            expected_assets = {item["mention_name"]: item for item in production.get("reference_assets", [])}
            name = upload.get("mention_name")
            expected = expected_assets.get(name)
            if expected is None:
                raise WorkflowError("asset-upload.mention_name 不属于 production package")
            if upload.get("storyboard_lock_id") != production["storyboard_lock_id"] or upload.get("source_sha256") != expected.get("source_sha256"):
                raise WorkflowError("asset-upload 未绑定锁定 Storyboard 素材")
            for field in ("source_filename", "asset_role"):
                if upload.get(field) != expected.get(field):
                    raise WorkflowError(f"asset-upload.{field} 与 production package 不一致")
            if not is_uuid(upload.get("asset_id")):
                raise WorkflowError("asset-upload.asset_id 必须是 UUID")
            binding.update({"storyboard_lock_id": production["storyboard_lock_id"], "source_sha256": expected["source_sha256"], "source_filename": expected["source_filename"], "asset_role": expected["asset_role"], "mention_name": name, "asset_id": upload["asset_id"]})
        elif kind == "task-result" and stage not in {"production_ready", "submitted", "monitoring"}:
            raise WorkflowError("task-result 只能在已授权的生产或监控阶段记录")
    elif is_v3:
        allowed_direct = {
            "script",
            "dimension-reference",
            "dimension-reference-image",
            "aggregate-keyframe-prompt",
            "aggregate-keyframe",
            "h3-prompt",
            "task-preview",
            "request",
            "asset-upload",
            "task-result",
        }
        if kind not in allowed_direct:
            raise WorkflowError(f"schema v3 的 {kind} 必须由专用命令生成")
        if candidate_id is not None:
            raise WorkflowError("schema v3 产物不接受 candidate-id；候选由提案锁绑定")
        stage = state.get("stage")
        if kind == "script":
            if stage != "proposal_review":
                raise WorkflowError("script 只能在 proposal_review 阶段记录")
            validate_script_set(source)
        elif kind == "dimension-reference":
            if stage != "proposal_review":
                raise WorkflowError("dimension-reference 只能在 proposal_review 阶段记录")
            validate_dimension_reference(source)
        elif kind in {"dimension-reference-image", "aggregate-keyframe-prompt", "aggregate-keyframe"}:
            if stage != "proposal_review":
                raise WorkflowError(f"{kind} 只能在 proposal_review 阶段记录")
            if kind.endswith("image") or kind == "aggregate-keyframe":
                if source.suffix.casefold() not in SUPPORTED_IMAGES:
                    raise WorkflowError(f"{kind} 必须是支持的图片格式")
            if kind == "dimension-reference-image":
                dimension = artifact_entry(state, "dimension-reference")
                binding["dimension_version"] = dimension["version"]
        elif kind in {"h3-prompt", "task-preview"}:
            lock = state.get("approvals", {}).get("proposal")
            if stage != "proposal_locked" or not lock:
                raise WorkflowError(f"{kind} 只能在提案锁定后记录")
            binding = {
                "proposal_lock_id": lock["lock_id"],
                "proposal_revision": lock["proposal_revision"],
                "proposal_package_sha256": lock["proposal_package_sha256"],
                "candidate_id": lock["candidate_id"],
            }
            if kind == "task-preview":
                payload = json.loads(source.read_text(encoding="utf-8"))
                for field, expected in binding.items():
                    if payload.get(field) != expected:
                        raise WorkflowError(f"task-preview.{field} 未绑定锁定提案")
                h3 = artifact_entry(state, "h3-prompt")
                if payload.get("h3_prompt_version") != h3["version"]:
                    raise WorkflowError("task-preview.h3_prompt_version 未绑定最新 H3 prompt")
                binding["h3_prompt_version"] = h3["version"]
                if state.get("active_retry"):
                    binding["retry_authorization_version"] = state["active_retry"]["authorization_version"]
        elif kind == "request":
            if stage != "production_ready":
                raise WorkflowError("request 只能在 production_ready 阶段记录")
        elif kind == "asset-upload":
            if stage != "production_ready":
                raise WorkflowError("asset-upload 只能在 production_ready 阶段记录")
            try:
                upload = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WorkflowError(f"asset-upload 必须是有效 JSON: {exc}") from exc
            production = read_json_artifact(artifact_entry(state, "production-package"), "production-package")
            expected = {
                "proposal_lock_id": production["proposal_lock_id"],
                "source_sha256": production["aggregate_keyframe"]["sha256"],
            }
            for field, value in expected.items():
                if upload.get(field) != value:
                    raise WorkflowError(f"asset-upload.{field} 未绑定锁定总聚合关键帧")
            if not is_uuid(upload.get("asset_id")):
                raise WorkflowError("asset-upload.asset_id 必须是 UUID")
            binding.update(expected)
            binding["asset_id"] = upload["asset_id"]
        elif kind == "task-result" and stage not in {"production_ready", "submitted", "monitoring"}:
            raise WorkflowError("task-result 只能在已授权的生产或监控阶段记录")
    elif is_v2 and kind == "script":
        if state.get("stage") != "script_review":
            raise WorkflowError("v2 script 只能在 script_review 阶段记录")
        validate_script_set(source)
        if candidate_id is not None:
            raise WorkflowError("script 集合不接受 candidate-id")
    elif is_v2 and kind in {"keyframe-prompt", "keyframe"}:
        if state.get("stage") != "keyframe_review" or "script" not in state.get("approvals", {}):
            raise WorkflowError(f"{kind} 只能在确认 5 个脚本后记录")
        selected_id = validate_candidate_id(candidate_id)
        binding["script_version"] = state["approvals"]["script"]["script_version"]
        if kind == "keyframe":
            prompt = artifact_entry_for_candidate(state, "keyframe-prompt", selected_id)
            binding["keyframe_prompt_version"] = prompt["version"]
    elif is_v2 and kind == "h3-prompt":
        approval = state.get("approvals", {}).get("keyframe")
        if state.get("stage") != "keyframe_review" or not approval:
            raise WorkflowError("h3-prompt 只能在选择一组脚本和关键帧后记录")
        selected_id = validate_candidate_id(candidate_id)
        if selected_id != approval.get("candidate_id"):
            raise WorkflowError("h3-prompt.candidate-id 必须等于已选候选")
        binding = {
            field: approval[field]
            for field in ("script_version", "keyframe_prompt_version", "keyframe_version")
        }
    elif candidate_id is not None:
        if is_v2:
            raise WorkflowError(f"{kind} 不接受 candidate-id")
        raise WorkflowError("schema v1 产物不接受 candidate-id")
    request_binding: dict[str, Any] | None = None
    if kind == "task-result":
        if is_v4:
            if "storyboard" not in state.get("approvals", {}):
                raise WorkflowError("记录任务结果前必须锁定并授权 Storyboard")
        elif is_v3:
            if "proposal" not in state.get("approvals", {}):
                raise WorkflowError("记录任务结果前必须锁定并授权提案")
        elif "task" not in state.get("approvals", {}):
            raise WorkflowError("记录任务结果前必须完成 Gate 3 确认")
        request_binding = require_bound_request(state)
    entries = state.setdefault("artifacts", {}).setdefault(kind, [])
    version = len(entries) + 1
    suffix = source.suffix.casefold() or ".bin"
    candidate_part = f"-{selected_id}" if selected_id is not None else ""
    destination = run_dir.resolve() / f"{kind}{candidate_part}-v{version:02d}{suffix}"
    if destination.exists():
        raise WorkflowError(f"产物目标已存在: {destination}")

    sanitized_payload: Any = None
    if kind in {"task-result", "asset-upload"}:
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError(f"{kind} 必须是有效 JSON: {exc}") from exc
        sanitized_payload = sanitize_json(payload)
        atomic_json_write(destination, sanitized_payload)
    else:
        shutil.copy2(source, destination)

    timestamp = now_iso()
    entry = {
        "version": version,
        "path": str(destination),
        "sha256": sha256_file(destination),
        "recorded_at": timestamp,
    }
    if selected_id is not None:
        entry["candidate_id"] = selected_id
    entry.update(binding)
    if kind == "task-result" and request_binding is not None:
        if is_v4:
            entry["storyboard_lock_id"] = request_binding["payload"]["storyboard_lock_id"]
        elif is_v3:
            entry["proposal_lock_id"] = request_binding["payload"]["proposal_lock_id"]
        else:
            entry["intent_id"] = request_binding["payload"]["intent_id"]
        entry["request_version"] = request_binding["request"]["version"]
    entries.append(entry)
    if kind == "task-result" and isinstance(sanitized_payload, dict):
        allowed_task_keys = {
            "task_id",
            "workspace_id",
            "task_number",
            "status",
            "task_url",
            "video_url",
            "videos",
            "error_stage",
            "error_type",
            "error_message",
        }
        state["task"] = {
            key: sanitized_payload[key] for key in allowed_task_keys if key in sanitized_payload
        }
        if is_v4:
            state["task"]["storyboard_lock_id"] = request_binding["payload"]["storyboard_lock_id"]
        elif is_v3:
            state["task"]["proposal_lock_id"] = request_binding["payload"]["proposal_lock_id"]
        else:
            state["task"]["intent_id"] = request_binding["payload"]["intent_id"]
        state["task"]["request_version"] = request_binding["request"]["version"]
    state["updated_at"] = timestamp
    state.setdefault("history", []).append(
        {
            "at": timestamp,
            "event": "artifact_recorded",
            "kind": kind,
            "version": version,
            **({"candidate_id": selected_id} if selected_id is not None else {}),
        }
    )
    atomic_json_write(state_path, state)
    return entry


def manifest_signature(manifest: dict[str, Any]) -> tuple[Any, ...]:
    assets = tuple(
        sorted((item.get("filename"), item.get("sha256")) for item in manifest.get("assets", []))
    )
    replacement = manifest.get("approved_keyframe") or {}
    return manifest.get("brief_sha256"), assets, replacement.get("sha256")


def resume_run(project: Path) -> dict[str, Any]:
    project = project.resolve()
    if project.is_file():
        project = project.parent
    current = inspect_project(project)
    if not current["valid"]:
        raise WorkflowError("项目校验失败: " + "; ".join(current["errors"]))
    current_signature = manifest_signature(current)
    output = project / "output"
    candidates: list[tuple[int, str, Path, dict[str, Any]]] = []
    if output.is_dir():
        for run_dir in output.iterdir():
            if not run_dir.is_dir() or not (run_dir / "state.json").is_file():
                continue
            try:
                _, state = load_state(run_dir)
            except WorkflowError:
                continue
            stage = state.get("stage")
            if stage in TERMINAL_STAGES:
                continue
            if stage == "task_review" and "task" in state.get("approvals", {}):
                candidates.append((2, state.get("updated_at", ""), run_dir, state))
                continue
            if stage in {"submitted", "monitoring", "failed"}:
                priority = 2 if stage in {"submitted", "monitoring"} else 1
                candidates.append((priority, state.get("updated_at", ""), run_dir, state))
                continue
            try:
                manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest_signature(manifest) == current_signature:
                candidates.append((0, state.get("updated_at", ""), run_dir, state))
    if not candidates:
        return {"found": False}
    _, _, run_dir, state = max(candidates, key=lambda item: (item[0], item[1]))
    return {"found": True, "run_dir": str(run_dir.resolve()), "state": state}


def validate_h3_prompt(path: Path, duration: float) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig").strip()
    errors: list[str] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    mode = "i2va" if lines and lines[0] == I2VA_OPENING else "ref2va"
    if mode == "i2va":
        fields = ["integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:"]
    else:
        fields = ["subject_definitions:", "summary:", "retention_analysis:", "detailed_description:", "overall_soundscape:", "non_diegetic_music:"]
    positions = [text.find(field) for field in fields]
    if any(position < 0 for position in positions):
        errors.append("提示词缺少 H3 必需字段")
    elif positions != sorted(positions):
        errors.append("H3 必需字段顺序错误")

    times: list[float] = []
    for minutes, seconds, millis in re.findall(r"At\s+00:(\d{2}):(\d{2})\.(\d{3})", text):
        times.append(int(minutes) * 60 + int(seconds) + int(millis) / 1000)
    if any(current <= previous for previous, current in zip(times, times[1:])):
        errors.append("镜头切点必须严格递增")
    if any(value <= 0 or value >= duration for value in times):
        errors.append("镜头切点必须大于 0 且小于视频总时长")
    return {
        "valid": not errors,
        "mode": mode,
        "prompt_sha256": sha256_file(path),
        "duration_seconds": duration,
        "cut_times": times,
        "errors": errors,
    }


def record_h3_validation(run_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("valid"):
        raise WorkflowError("不能记录失败的 H3 提示词校验")
    state_path, state = load_state(run_dir)
    prompt = artifact_entry(state, "h3-prompt")
    if result.get("prompt_sha256") != prompt.get("sha256"):
        raise WorkflowError("校验结果与最新 H3 提示词不匹配")
    entries = state.setdefault("artifacts", {}).setdefault("h3-validation", [])
    version = len(entries) + 1
    destination = run_dir.resolve() / f"h3-validation-v{version:02d}.json"
    if destination.exists():
        raise WorkflowError(f"产物目标已存在: {destination}")
    atomic_json_write(destination, result)
    timestamp = now_iso()
    entry = {
        "version": version,
        "path": str(destination),
        "sha256": sha256_file(destination),
        "recorded_at": timestamp,
    }
    entries.append(entry)
    state["updated_at"] = timestamp
    state.setdefault("history", []).append(
        {"at": timestamp, "event": "h3_prompt_validated", "version": prompt["version"]}
    )
    atomic_json_write(state_path, state)
    return entry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover_parser = subparsers.add_parser("discover", help="Find ad-brief.md projects recursively")
    discover_parser.add_argument("root", type=Path)

    ingest_parser = subparsers.add_parser("ingest", help="Create a project from chat brief JSON and uploaded images")
    ingest_parser.add_argument("workspace_root", type=Path)
    ingest_parser.add_argument("--brief-json", required=True, type=Path)
    ingest_parser.add_argument("--image", action="append", required=True, type=Path)
    ingest_parser.add_argument("--slug")

    inspect_parser = subparsers.add_parser("inspect", help="Validate one project")
    inspect_parser.add_argument("project", type=Path)

    start_parser = subparsers.add_parser("start", help="Create a versioned run directory")
    start_parser.add_argument("project", type=Path)
    start_parser.add_argument("--run-id")

    resume_parser = subparsers.add_parser("resume", help="Find the latest non-terminal run")
    resume_parser.add_argument("project", type=Path)

    stage_parser = subparsers.add_parser("set-stage", help="Advance or return workflow state")
    stage_parser.add_argument("run_dir", type=Path)
    stage_parser.add_argument("--expect", required=True, choices=sorted(ALLOWED_STAGES))
    stage_parser.add_argument("--stage", required=True, choices=sorted(ALLOWED_STAGES))

    approve_parser = subparsers.add_parser("approve", help="Record approval of an exact gate artifact version")
    approve_parser.add_argument("run_dir", type=Path)
    approve_parser.add_argument("--gate", required=True, choices=["script", "keyframe", "task"])
    approve_parser.add_argument("--version", type=int)
    approve_parser.add_argument("--candidate-id", choices=CANDIDATE_IDS)

    record_parser = subparsers.add_parser("record", help="Copy an artifact into a versioned run")
    record_parser.add_argument("run_dir", type=Path)
    record_parser.add_argument("--kind", required=True, choices=sorted(ARTIFACT_KINDS))
    record_parser.add_argument("--source", required=True, type=Path)
    record_parser.add_argument("--candidate-id", choices=CANDIDATE_IDS)

    prompt_parser = subparsers.add_parser("validate-h3-prompt", help="Validate the final I2VA or Ref2VA prompt structure")
    prompt_parser.add_argument("prompt", type=Path)
    prompt_parser.add_argument("--duration", type=float, default=15)
    prompt_parser.add_argument("--run-dir", type=Path)

    request_parser = subparsers.add_parser("validate-request", help="Validate and bind the final Console request")
    request_parser.add_argument("request", type=Path)
    request_parser.add_argument("--run-dir", required=True, type=Path)

    feedback_parser = subparsers.add_parser("record-feedback", help="Append client feedback for a revision")
    feedback_parser.add_argument("run_dir", type=Path)
    feedback_parser.add_argument("--proposal-version", type=int, help="Schema v3 proposal revision")
    feedback_parser.add_argument("--base-revision", type=int, help="Schema v4 phase revision")
    feedback_parser.add_argument("--phase", choices=["script", "storyboard"])
    feedback_parser.add_argument("--source", required=True, type=Path)

    script_proposal_parser = subparsers.add_parser("finalize-script-proposal", help="Publish an immutable five-script package")
    script_proposal_parser.add_argument("run_dir", type=Path)
    script_proposal_parser.add_argument("--script-version", required=True, type=int)
    script_proposal_parser.add_argument("--base-revision", type=int)

    script_lock_parser = subparsers.add_parser("lock-script", help="Lock one final script")
    script_lock_parser.add_argument("run_dir", type=Path)
    script_lock_parser.add_argument("--script-proposal-version", required=True, type=int)
    script_lock_parser.add_argument("--candidate-id", required=True, choices=CANDIDATE_IDS)
    script_lock_parser.add_argument("--final-script-version", required=True, type=int)
    script_lock_parser.add_argument("--approval-json", required=True, type=Path)

    storyboard_parser = subparsers.add_parser("finalize-storyboard", help="Publish an immutable aggregate Storyboard package")
    storyboard_parser.add_argument("run_dir", type=Path)
    storyboard_parser.add_argument("--visual-plan-version", required=True, type=int)
    storyboard_parser.add_argument("--keyframe-prompt-version", required=True, type=int)
    storyboard_parser.add_argument("--keyframe-version", required=True, type=int)
    storyboard_parser.add_argument("--base-revision", type=int)

    storyboard_lock_parser = subparsers.add_parser("lock-storyboard", help="Lock Storyboard and authorize one task")
    storyboard_lock_parser.add_argument("run_dir", type=Path)
    storyboard_lock_parser.add_argument("--storyboard-version", required=True, type=int)
    storyboard_lock_parser.add_argument("--approval-json", required=True, type=Path)

    proposal_parser = subparsers.add_parser("finalize-proposal", help="Publish an immutable proposal package")
    proposal_parser.add_argument("run_dir", type=Path)
    proposal_parser.add_argument("--script-version", required=True, type=int)
    proposal_parser.add_argument("--dimension-version", required=True, type=int)
    proposal_parser.add_argument("--dimension-image-version", required=True, type=int)
    proposal_parser.add_argument("--keyframe-version", required=True, type=int)
    proposal_parser.add_argument("--base-revision", type=int)

    lock_parser = subparsers.add_parser("lock-proposal", help="Lock one proposal and selected script candidate")
    lock_parser.add_argument("run_dir", type=Path)
    lock_parser.add_argument("--proposal-version", required=True, type=int)
    lock_parser.add_argument("--candidate-id", required=True, choices=CANDIDATE_IDS)
    lock_parser.add_argument("--approval-json", required=True, type=Path)

    production_parser = subparsers.add_parser("finalize-production", help="Bind the locked proposal into an H3 production package")
    production_parser.add_argument("run_dir", type=Path)

    revision_parser = subparsers.add_parser("begin-revision", help="Start a revision from client feedback")
    revision_parser.add_argument("run_dir", type=Path)
    revision_parser.add_argument("--base-revision", required=True, type=int)
    revision_parser.add_argument("--feedback-version", required=True, type=int)
    revision_parser.add_argument("--phase", choices=["script", "storyboard"])

    retry_parser = subparsers.add_parser("authorize-retry", help="Record explicit client authorization for one failed-task retry")
    retry_parser.add_argument("run_dir", type=Path)
    retry_parser.add_argument("--approval-json", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "discover":
            result: Any = {"projects": discover(args.root)}
        elif args.command == "ingest":
            result = ingest_chat_project(args.workspace_root, args.brief_json, args.image, args.slug)
        elif args.command == "inspect":
            result = inspect_project(args.project)
        elif args.command == "start":
            result = start_run(args.project, args.run_id)
        elif args.command == "resume":
            result = resume_run(args.project)
        elif args.command == "set-stage":
            result = set_stage(args.run_dir, args.expect, args.stage)
        elif args.command == "approve":
            result = approve_gate(args.run_dir, args.gate, args.version, args.candidate_id)
        elif args.command == "record":
            result = record_artifact(args.run_dir, args.kind, args.source, args.candidate_id)
        elif args.command == "validate-h3-prompt":
            result = validate_h3_prompt(args.prompt, args.duration)
            if not result["valid"]:
                print(json.dumps({"ok": False, "result": result}, ensure_ascii=False, indent=2))
                return 1
            if args.run_dir:
                result["recorded_artifact"] = record_h3_validation(args.run_dir, result)
        elif args.command == "validate-request":
            result = validate_request_for_run(args.run_dir, args.request)
            if not result["valid"]:
                print(json.dumps({"ok": False, "result": result}, ensure_ascii=False, indent=2))
                return 1
            result["recorded_artifact"] = record_request_validation(args.run_dir, result)
        elif args.command == "record-feedback":
            revision = args.base_revision if args.base_revision is not None else args.proposal_version
            if revision is None:
                raise WorkflowError("record-feedback 必须提供 --proposal-version 或 --base-revision")
            result = record_feedback(args.run_dir, revision, args.source, args.phase)
        elif args.command == "finalize-script-proposal":
            result = finalize_script_proposal(args.run_dir, args.script_version, args.base_revision)
        elif args.command == "lock-script":
            result = lock_script(args.run_dir, args.script_proposal_version, args.candidate_id, args.final_script_version, args.approval_json)
        elif args.command == "finalize-storyboard":
            result = finalize_storyboard(args.run_dir, args.visual_plan_version, args.keyframe_prompt_version, args.keyframe_version, args.base_revision)
        elif args.command == "lock-storyboard":
            result = lock_storyboard(args.run_dir, args.storyboard_version, args.approval_json)
        elif args.command == "finalize-proposal":
            result = finalize_proposal(args.run_dir, args.script_version, args.dimension_version, args.dimension_image_version, args.keyframe_version, args.base_revision)
        elif args.command == "lock-proposal":
            result = lock_proposal(args.run_dir, args.proposal_version, args.candidate_id, args.approval_json)
        elif args.command == "finalize-production":
            result = finalize_production(args.run_dir)
        elif args.command == "begin-revision":
            result = begin_revision(args.run_dir, args.base_revision, args.feedback_version, args.phase)
        elif args.command == "authorize-retry":
            result = authorize_retry(args.run_dir, args.approval_json)
        else:
            raise WorkflowError(f"未知命令: {args.command}")
    except (OSError, WorkflowError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
