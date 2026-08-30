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
        "schema_version": 1,
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


def start_run(project: Path, run_id: str | None = None) -> dict[str, Any]:
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
    state = {
        "schema_version": 1,
        "run_id": run_id,
        "project_dir": inspection["project_dir"],
        "stage": "script_review",
        "created_at": created,
        "updated_at": created,
        "artifacts": {},
        "history": [{"at": created, "event": "run_started", "stage": "script_review"}],
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


def approve_gate(run_dir: Path, gate: str, version: int | None = None) -> dict[str, Any]:
    state_path, state = load_state(run_dir)
    expected_stage = {"script": "script_review", "keyframe": "keyframe_review", "task": "task_review"}[gate]
    if state.get("stage") != expected_stage:
        raise WorkflowError(f"{gate} 确认只能在 {expected_stage} 阶段执行")
    timestamp = now_iso()
    approvals = state.setdefault("approvals", {})

    if gate == "script":
        script = artifact_entry(state, "script", version)
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
        keyframe = artifact_entry(state, "keyframe", version)
        approvals["keyframe"] = {"at": timestamp, "keyframe_version": keyframe["version"]}
        approvals.pop("task", None)
    else:
        if "script" not in approvals or "keyframe" not in approvals:
            raise WorkflowError("确认任务前必须先确认脚本和关键帧")
        h3_prompt = artifact_entry(state, "h3-prompt")
        task_preview = artifact_entry(state, "task-preview")
        validate_task_preview(state, task_preview, h3_prompt)
        approvals["task"] = {
            "at": timestamp,
            "intent_id": str(uuid.uuid4()),
            "h3_prompt_version": h3_prompt["version"],
            "task_preview_version": task_preview["version"],
            "keyframe_version": approvals["keyframe"]["keyframe_version"],
        }

    state["updated_at"] = timestamp
    state.setdefault("history", []).append(
        {"at": timestamp, "event": "gate_approved", "gate": gate, "stage": state["stage"]}
    )
    atomic_json_write(state_path, state)
    return state


def check_transition_preconditions(state: dict[str, Any], current: str, new_stage: str) -> None:
    approvals = state.get("approvals", {})
    if current == "keyframe_review" and new_stage == "task_review":
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
    elif current == "failed" and new_stage == "task_review":
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


def validate_request_for_run(run_dir: Path, path: Path) -> dict[str, Any]:
    _, state = load_state(run_dir)
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
    }


def record_request_validation(run_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("valid"):
        raise WorkflowError("不能记录失败的最终请求校验")
    state_path, state = load_state(run_dir)
    approval = state.get("approvals", {}).get("task", {})
    request = artifact_entry(state, "request")
    verify_artifact_integrity(request, "request")
    if result.get("request_sha256") != request.get("sha256"):
        raise WorkflowError("校验结果与最新 request 不匹配")
    if result.get("intent_id") != approval.get("intent_id"):
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
    for field in ("task_preview_version", "h3_prompt_version", "keyframe_version"):
        if payload.get(field) != approval.get(field):
            raise WorkflowError(f"request 校验记录的 {field} 与审批不一致")
    return {"request": request, "validation": validation, "payload": payload}


def record_artifact(run_dir: Path, kind: str, source: Path) -> dict[str, Any]:
    if kind not in ARTIFACT_KINDS:
        raise WorkflowError(f"未知产物类型: {kind}")
    source = source.resolve()
    if not source.is_file():
        raise WorkflowError(f"产物源文件不存在: {source}")
    state_path, state = load_state(run_dir)
    request_binding: dict[str, Any] | None = None
    if kind == "task-result":
        if "task" not in state.get("approvals", {}):
            raise WorkflowError("记录任务结果前必须完成 Gate 3 确认")
        request_binding = require_bound_request(state)
    entries = state.setdefault("artifacts", {}).setdefault(kind, [])
    version = len(entries) + 1
    suffix = source.suffix.casefold() or ".bin"
    destination = run_dir.resolve() / f"{kind}-v{version:02d}{suffix}"
    if destination.exists():
        raise WorkflowError(f"产物目标已存在: {destination}")

    sanitized_payload: Any = None
    if kind == "task-result":
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError(f"task-result 必须是有效 JSON: {exc}") from exc
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
    if kind == "task-result" and request_binding is not None:
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
        state["task"]["intent_id"] = request_binding["payload"]["intent_id"]
        state["task"]["request_version"] = request_binding["request"]["version"]
    state["updated_at"] = timestamp
    state.setdefault("history", []).append(
        {"at": timestamp, "event": "artifact_recorded", "kind": kind, "version": version}
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
    if not lines or lines[0] != I2VA_OPENING:
        errors.append("I2VA 提示词必须以标准 0 秒首帧对齐语句开头")

    fields = [
        "integrated_multimodal_description:",
        "overall_soundscape:",
        "non_diegetic_music:",
    ]
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

    record_parser = subparsers.add_parser("record", help="Copy an artifact into a versioned run")
    record_parser.add_argument("run_dir", type=Path)
    record_parser.add_argument("--kind", required=True, choices=sorted(ARTIFACT_KINDS))
    record_parser.add_argument("--source", required=True, type=Path)

    prompt_parser = subparsers.add_parser("validate-h3-prompt", help="Validate the final I2VA prompt structure")
    prompt_parser.add_argument("prompt", type=Path)
    prompt_parser.add_argument("--duration", type=float, default=15)
    prompt_parser.add_argument("--run-dir", type=Path)

    request_parser = subparsers.add_parser("validate-request", help="Validate and bind the final Console request")
    request_parser.add_argument("request", type=Path)
    request_parser.add_argument("--run-dir", required=True, type=Path)
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
            result = approve_gate(args.run_dir, args.gate, args.version)
        elif args.command == "record":
            result = record_artifact(args.run_dir, args.kind, args.source)
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
        else:
            raise WorkflowError(f"未知命令: {args.command}")
    except (OSError, WorkflowError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
