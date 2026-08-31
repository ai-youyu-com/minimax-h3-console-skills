from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "generate-client-ad-video" / "scripts" / "project_workflow.py"
SPEC = importlib.util.spec_from_file_location("project_workflow", SCRIPT)
assert SPEC and SPEC.loader
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)

VALIDATOR_SCRIPT = ROOT / ".agents" / "skills" / "minimax-h3-console-video-generator" / "scripts" / "validate_request.py"
VALIDATOR_SPEC = importlib.util.spec_from_file_location("validate_request", VALIDATOR_SCRIPT)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
request_validator = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(request_validator)


BRIEF = """# Client Ad Brief

## 项目名称
演示项目

## 产品或服务
一款经过客户确认的产品

## 可核验卖点
- 耐用材质
- 轻巧设计

## 广告目标
让潜在客户了解产品

## CTA
预约体验

## 素材角色
| 文件名 | 角色 | 必须保留 | 说明 |
|---|---|---|---|
| product.jpg | 主产品 | 蓝色外壳 | 主视觉 |
"""


def write_project(path: Path, brief: str = BRIEF, image: bool = True) -> None:
    path.mkdir(parents=True)
    (path / "ad-brief.md").write_text(brief, encoding="utf-8")
    if image:
        (path / "product.jpg").write_bytes(b"fake-jpeg")


def write_script_set(path: Path, candidate_ids: tuple[str, ...] = workflow.CANDIDATE_IDS) -> None:
    payload = {
        "verified_facts_summary": ["耐用材质", "轻巧设计"],
        "candidates": [
            {
                "candidate_id": candidate_id,
                "creative_direction": f"方向 {candidate_id}",
                "hook": f"钩子 {candidate_id}",
                "storyboard": [
                    {"time": "0-5s", "visual": "产品开场"},
                    {"time": "5-15s", "visual": "功能与 CTA"},
                ],
                "voiceover": f"候选 {candidate_id} 口播",
                "source_mapping": [{"shot": "0-15s", "source": "product.jpg"}],
                "post_production_text": ["预约体验"],
            }
            for candidate_id in candidate_ids
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_v4_script_proposal(path: Path) -> None:
    payload = {
        "candidates": [
            {
                "candidate_id": candidate_id,
                "plan_name": f"方案 {candidate_id}",
                "creative_idea": f"创意 {candidate_id}",
                "hook": f"钩子 {candidate_id}",
                "source_mapping": [{"fact": "耐用材质", "source": "ad-brief.md"}],
                "timeline": [
                    {"time": "0-3s", "visual": "人物拿起蓝色产品", "voiceover": "这个真的方便。", "subtitle": "轻巧设计", "cta": ""},
                    {"time": "3-15s", "visual": "展示产品并邀请预约", "voiceover": "现在就来预约体验。", "subtitle": "预约体验", "cta": "预约体验"},
                ],
            }
            for candidate_id in workflow.CANDIDATE_IDS
        ]
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def force_legacy_schema(run_dir: Path, version: int) -> None:
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["schema_version"] = version
    state["stage"] = "script_review"
    state_path.write_text(json.dumps(state), encoding="utf-8")


class ProjectWorkflowTests(unittest.TestCase):
    def test_skill_requires_orchestration_only_child_agent_execution(self) -> None:
        primary = ROOT / ".agents" / "skills" / "generate-client-ad-video"
        mirror = ROOT / "skills" / "generate-client-ad-video"

        for relative in ("SKILL.md", "agents/openai.yaml", "references/workflow-contract.md"):
            self.assertEqual(
                (primary / relative).read_bytes(),
                (mirror / relative).read_bytes(),
                f"published Skill copy differs for {relative}",
            )

        skill_text = (primary / "SKILL.md").read_text(encoding="utf-8")
        contract_text = (primary / "references" / "workflow-contract.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Mandatory Child-Agent Execution", skill_text)
        self.assertIn("must not inspect attachments", skill_text)
        self.assertIn("one vertical 9:16 multi-panel Storyboard", skill_text)
        self.assertIn("create_task_authorized: true", skill_text)
        self.assertIn("The root conversation is orchestration-only", contract_text)
        self.assertIn("record-feedback", contract_text)
        self.assertIn("create_task_authorized", contract_text)
        self.assertIn("returns to `storyboard_locked`", contract_text)

    def test_chat_project_slug_preserves_unicode_names(self) -> None:
        self.assertEqual("咖啡杯新品", workflow.safe_project_slug("咖啡杯新品"))

    def test_ingest_chat_brief_and_uploaded_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            attachments = root / "attachments"
            attachments.mkdir()
            product = attachments / "product.jpg"
            replacement_named_source = attachments / "approved-keyframe.png"
            product.write_bytes(b"product")
            replacement_named_source.write_bytes(b"person")
            brief_json = attachments / "brief.json"
            brief_json.write_text(
                json.dumps(
                    {
                        "project_name": "Demo Product",
                        "offering": "A client-provided product",
                        "selling_points": ["Durable material", "Compact design"],
                        "objective": "Introduce the product",
                        "cta": "Learn more",
                        "language": "English",
                        "asset_roles": [
                            {
                                "filename": "product.jpg",
                                "role": "hero product",
                                "must_preserve": "shape and color",
                                "notes": "main visual",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = workflow.ingest_chat_project(
                root, brief_json, [product, replacement_named_source]
            )
            project = Path(result["project_dir"])

            self.assertEqual("demo-product", project.name)
            self.assertTrue(result["valid"], result["errors"])
            self.assertTrue((project / "ad-brief.md").is_file())
            self.assertTrue((project / "product.jpg").is_file())
            self.assertTrue((project / "source-approved-keyframe.png").is_file())
            inspection = workflow.inspect_project(project)
            self.assertEqual(15, inspection["brief"]["duration_seconds"])
            self.assertEqual("hero product", inspection["assets"][0]["declared_role"]["role"])
            self.assertIsNone(inspection["approved_keyframe"])

            second = workflow.ingest_chat_project(root, brief_json, [product])
            self.assertEqual("demo-product-02", Path(second["project_dir"]).name)

    def test_ingest_chat_rejects_incomplete_brief_without_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "product.webp"
            image.write_bytes(b"product")
            brief_json = root / "brief.json"
            brief_json.write_text(json.dumps({"project_name": "Incomplete"}), encoding="utf-8")

            with self.assertRaises(workflow.WorkflowError):
                workflow.ingest_chat_project(root, brief_json, [image])

            self.assertFalse((root / "incomplete").exists())

    def test_discovery_and_direct_image_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "client-a"
            write_project(project)
            nested = project / "nested"
            nested.mkdir()
            (nested / "ignored.png").write_bytes(b"ignored")
            (project / "aggregate-keyframe.png").write_bytes(b"generated")
            (project / "keyframe-v02.webp").write_bytes(b"generated")
            output_project = project / "output" / "old"
            write_project(output_project)
            hidden_project = root / ".hidden"
            write_project(hidden_project)
            invalid = root / "client-b"
            write_project(invalid, image=False)

            projects = workflow.discover(root)
            self.assertEqual(2, len(projects))
            selected = next(item for item in projects if item["project_name"] == "演示项目" and item["valid"])
            self.assertEqual(1, selected["asset_count"])
            self.assertFalse(next(item for item in projects if not item["valid"])["valid"])

    def test_discovery_isolates_malformed_brief(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = root / "valid"
            write_project(valid)
            malformed = root / "malformed"
            malformed.mkdir()
            (malformed / "ad-brief.md").write_bytes(b"\xff\xfe\x00")
            (malformed / "product.png").write_bytes(b"image")

            projects = workflow.discover(root)

            self.assertEqual(2, len(projects))
            self.assertTrue(next(item for item in projects if item["project_dir"] == str(valid.resolve()))["valid"])
            invalid = next(item for item in projects if item["project_dir"] == str(malformed.resolve()))
            self.assertFalse(invalid["valid"])
            self.assertTrue(any("UTF-8" in error for error in invalid["errors"]))

    def test_defaults_roles_and_replacement_keyframe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "client"
            write_project(project)
            (project / "approved-keyframe.webp").write_bytes(b"replacement")
            result = workflow.inspect_project(project)

            self.assertTrue(result["valid"])
            self.assertEqual(15, result["brief"]["duration_seconds"])
            self.assertEqual("9:16", result["brief"]["aspect_ratio"])
            self.assertEqual("high", result["brief"]["quality"])
            self.assertEqual("主产品", result["assets"][0]["declared_role"]["role"])
            self.assertEqual("approved-keyframe.webp", result["approved_keyframe"]["filename"])
            self.assertEqual(["product.jpg"], [item["filename"] for item in result["assets"]])

    def test_missing_required_field_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "client"
            write_project(project, brief="# Client Ad Brief\n\n## 项目名称\n只有名称\n")
            result = workflow.inspect_project(project)
            self.assertFalse(result["valid"])
            self.assertTrue(any("offering" in error for error in result["errors"]))

    def test_run_versioning_transitions_resume_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "client"
            write_project(project)
            started = workflow.start_run(project, "run-001")
            run_dir = Path(started["run_dir"])
            state_path = run_dir / "state.json"
            force_legacy_schema(run_dir, 1)

            candidate = project / "candidate.md"
            candidate.write_text("script", encoding="utf-8")
            first = workflow.record_artifact(run_dir, "script", candidate)
            second = workflow.record_artifact(run_dir, "script", candidate)
            self.assertEqual(1, first["version"])
            self.assertEqual(2, second["version"])

            with self.assertRaises(workflow.WorkflowError):
                workflow.set_stage(run_dir, "script_review", "keyframe_review")
            keyframe_prompt = project / "keyframe-prompt.txt"
            keyframe_prompt.write_text("prompt", encoding="utf-8")
            workflow.record_artifact(run_dir, "keyframe-prompt", keyframe_prompt)
            state = workflow.approve_gate(run_dir, "script", version=2)
            self.assertEqual("keyframe_review", state["stage"])
            self.assertEqual(2, state["approvals"]["script"]["script_version"])
            resumed = workflow.resume_run(project)
            self.assertTrue(resumed["found"])
            self.assertEqual("keyframe_review", resumed["state"]["stage"])

            (project / "product.jpg").write_bytes(b"changed-image")
            self.assertFalse(workflow.resume_run(project)["found"])

            keyframe = project / "candidate.png"
            keyframe.write_bytes(b"keyframe")
            workflow.record_artifact(run_dir, "keyframe", keyframe)
            workflow.approve_gate(run_dir, "keyframe")
            h3_prompt = project / "h3.txt"
            h3_prompt.write_text(
                workflow.I2VA_OPENING
                + "\n\nintegrated_multimodal_description: [Shot 1] Live-action product ad.\n\n"
                + "overall_soundscape: Quiet room ambience.\n\n"
                + "non_diegetic_music: Light percussion.",
                encoding="utf-8",
            )
            h3_entry = workflow.record_artifact(run_dir, "h3-prompt", h3_prompt)
            keyframe_entry = workflow.artifact_entry(
                json.loads((run_dir / "state.json").read_text(encoding="utf-8")), "keyframe"
            )
            task_preview_payload = {
                "keyframe_path": keyframe_entry["path"],
                "keyframe_version": keyframe_entry["version"],
                "h3_prompt_version": h3_entry["version"],
                "workspace_id": "11111111-1111-4111-8111-111111111111",
                "mode": "i2v",
                "duration_seconds": 15,
                "aspect_ratio": "9:16",
                "quality": "high",
                "execution_backend": "local_machine",
                "idempotency_key": "33333333-3333-4333-8333-333333333333",
            }
            task_preview = project / "task-preview.json"
            task_preview.write_text(json.dumps(task_preview_payload), encoding="utf-8")
            workflow.record_artifact(run_dir, "task-preview", task_preview)
            with self.assertRaises(workflow.WorkflowError):
                workflow.set_stage(run_dir, "keyframe_review", "task_review")
            validation = workflow.validate_h3_prompt(h3_prompt, 15)
            workflow.record_h3_validation(run_dir, validation)
            workflow.set_stage(run_dir, "keyframe_review", "task_review")
            with self.assertRaises(workflow.WorkflowError):
                workflow.set_stage(run_dir, "task_review", "submitted")

            workflow.approve_gate(run_dir, "task")
            approved_resume = workflow.resume_run(project)
            self.assertTrue(approved_resume["found"])
            self.assertIn("task", approved_resume["state"]["approvals"])
            invalid_request = project / "invalid-request.json"
            invalid_request.write_text("{}", encoding="utf-8")
            invalid_entry = workflow.record_artifact(run_dir, "request", invalid_request)
            invalid_validation = workflow.validate_request_for_run(run_dir, Path(invalid_entry["path"]))
            self.assertFalse(invalid_validation["valid"])
            with self.assertRaises(workflow.WorkflowError):
                workflow.record_request_validation(run_dir, invalid_validation)

            request_payload = {
                "workspace_id": task_preview_payload["workspace_id"],
                "mode": "i2v",
                "assets": [
                    {
                        "asset_id": "22222222-2222-4222-8222-222222222222",
                        "role": "first_frame",
                    }
                ],
                "prompt": h3_prompt.read_text(encoding="utf-8"),
                "aspect_ratio": "9:16",
                "duration_seconds": 15,
                "quality": "high",
                "execution_backend": "local_machine",
                "idempotency_key": task_preview_payload["idempotency_key"],
            }
            mismatched_request = project / "mismatched-request.json"
            mismatched_payload = dict(request_payload)
            mismatched_payload["idempotency_key"] = "44444444-4444-4444-8444-444444444444"
            mismatched_request.write_text(json.dumps(mismatched_payload), encoding="utf-8")
            mismatched_entry = workflow.record_artifact(run_dir, "request", mismatched_request)
            mismatched_validation = workflow.validate_request_for_run(
                run_dir, Path(mismatched_entry["path"])
            )
            self.assertFalse(mismatched_validation["valid"])
            self.assertTrue(
                any("idempotency_key" in error for error in mismatched_validation["errors"])
            )

            request = project / "request.json"
            request.write_text(json.dumps(request_payload), encoding="utf-8")
            request_entry = workflow.record_artifact(run_dir, "request", request)
            request_validation = workflow.validate_request_for_run(run_dir, Path(request_entry["path"]))
            self.assertTrue(request_validation["valid"], request_validation["errors"])
            workflow.record_request_validation(run_dir, request_validation)

            task = project / "task.json"
            task.write_text(
                json.dumps(
                    {
                        "task_id": "safe",
                        "video_url": "safe-video",
                        "uploadUrl": "secret",
                        "nested": {"api_token": "x", "presignedUploadUrl": "secret"},
                    }
                ),
                encoding="utf-8",
            )
            recorded = workflow.record_artifact(run_dir, "task-result", task)
            sanitized = json.loads(Path(recorded["path"]).read_text(encoding="utf-8"))
            self.assertEqual("safe", sanitized["task_id"])
            self.assertEqual("safe-video", sanitized["video_url"])
            self.assertEqual("[REDACTED]", sanitized["uploadUrl"])
            self.assertEqual("[REDACTED]", sanitized["nested"]["api_token"])
            self.assertEqual("[REDACTED]", sanitized["nested"]["presignedUploadUrl"])
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("safe", state["task"]["task_id"])

            state = workflow.set_stage(run_dir, "task_review", "submitted")
            self.assertEqual("submitted", state["stage"])
            workflow.set_stage(run_dir, "submitted", "monitoring")
            workflow.set_stage(run_dir, "monitoring", "failed")
            state = workflow.set_stage(run_dir, "failed", "task_review")
            self.assertNotIn("task", state["approvals"])
            self.assertNotIn("task", state)
            state = workflow.approve_gate(run_dir, "task")
            self.assertNotEqual(
                request_validation["intent_id"], state["approvals"]["task"]["intent_id"]
            )
            with self.assertRaises(workflow.WorkflowError):
                workflow.set_stage(run_dir, "task_review", "submitted")

    def test_v2_five_script_batch_candidate_keyframes_and_selected_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "client"
            write_project(project)
            started = workflow.start_run(project, "run-v2", 3)
            run_dir = Path(started["run_dir"])
            self.assertEqual(3, started["state"]["schema_version"])
            force_legacy_schema(run_dir, 2)

            incomplete = project / "incomplete-script.json"
            write_script_set(incomplete, workflow.CANDIDATE_IDS[:-1])
            with self.assertRaises(workflow.WorkflowError):
                workflow.record_artifact(run_dir, "script", incomplete)

            scripts = project / "scripts.json"
            write_script_set(scripts)
            script_entry = workflow.record_artifact(run_dir, "script", scripts)
            prompt = project / "keyframe-prompt.txt"
            prompt.write_text("aggregate prompt", encoding="utf-8")
            with self.assertRaises(workflow.WorkflowError):
                workflow.record_artifact(run_dir, "keyframe-prompt", prompt, "1")

            state = workflow.approve_gate(run_dir, "script", script_entry["version"])
            self.assertEqual("keyframe_review", state["stage"])
            self.assertEqual(list(workflow.CANDIDATE_IDS), state["approvals"]["script"]["candidate_ids"])
            self.assertNotIn("keyframe-prompt", state["artifacts"])
            self.assertNotIn("keyframe", state["artifacts"])

            recorded_keyframes: dict[str, dict[str, object]] = {}
            for candidate_id in workflow.CANDIDATE_IDS[:-1]:
                prompt.write_text(f"aggregate prompt {candidate_id}", encoding="utf-8")
                workflow.record_artifact(run_dir, "keyframe-prompt", prompt, candidate_id)
                image = project / f"candidate-{candidate_id}.png"
                image.write_bytes(f"image-{candidate_id}".encode())
                recorded_keyframes[candidate_id] = workflow.record_artifact(
                    run_dir, "keyframe", image, candidate_id
                )

            with self.assertRaises(workflow.WorkflowError):
                workflow.approve_gate(run_dir, "keyframe", candidate_id="3")
            partial_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(4, len(partial_state["artifacts"]["keyframe"]))

            prompt.write_text("aggregate prompt 5", encoding="utf-8")
            workflow.record_artifact(run_dir, "keyframe-prompt", prompt, "5")
            image = project / "candidate-5.png"
            image.write_bytes(b"image-5")
            recorded_keyframes["5"] = workflow.record_artifact(run_dir, "keyframe", image, "5")

            state = workflow.approve_gate(run_dir, "keyframe", candidate_id="3")
            selected = state["approvals"]["keyframe"]
            self.assertEqual("3", selected["candidate_id"])
            self.assertEqual(script_entry["version"], selected["script_version"])
            self.assertEqual(recorded_keyframes["3"]["version"], selected["keyframe_version"])

            h3_prompt = project / "h3-v2.txt"
            h3_prompt.write_text(
                workflow.I2VA_OPENING
                + "\n\nintegrated_multimodal_description: [Shot 1] Selected candidate.\n\n"
                + "overall_soundscape: Quiet ambience.\n\n"
                + "non_diegetic_music: Light percussion.",
                encoding="utf-8",
            )
            with self.assertRaises(workflow.WorkflowError):
                workflow.record_artifact(run_dir, "h3-prompt", h3_prompt, "2")
            h3_entry = workflow.record_artifact(run_dir, "h3-prompt", h3_prompt, "3")
            self.assertEqual(selected["keyframe_version"], h3_entry["keyframe_version"])

            validation = workflow.validate_h3_prompt(h3_prompt, 15)
            workflow.record_h3_validation(run_dir, validation)
            task_preview_payload = {
                "candidate_id": "3",
                "script_version": selected["script_version"],
                "keyframe_prompt_version": selected["keyframe_prompt_version"],
                "keyframe_path": recorded_keyframes["3"]["path"],
                "keyframe_version": selected["keyframe_version"],
                "h3_prompt_version": h3_entry["version"],
                "workspace_id": "11111111-1111-4111-8111-111111111111",
                "mode": "i2v",
                "duration_seconds": 15,
                "aspect_ratio": "9:16",
                "quality": "high",
                "execution_backend": "local_machine",
                "idempotency_key": "33333333-3333-4333-8333-333333333333",
            }
            task_preview = project / "task-preview-v2.json"
            task_preview.write_text(json.dumps(task_preview_payload), encoding="utf-8")
            workflow.record_artifact(run_dir, "task-preview", task_preview)
            workflow.set_stage(run_dir, "keyframe_review", "task_review")
            state = workflow.approve_gate(run_dir, "task")
            for field in ("candidate_id", "script_version", "keyframe_prompt_version", "keyframe_version"):
                self.assertEqual(selected[field], state["approvals"]["task"][field])
            first_task_approval = dict(state["approvals"]["task"])
            history_count = len(state["history"])
            repeated = workflow.approve_gate(run_dir, "task")
            self.assertEqual(first_task_approval, repeated["approvals"]["task"])
            self.assertEqual(history_count, len(repeated["history"]))

            request_payload = {
                "workspace_id": task_preview_payload["workspace_id"],
                "mode": "i2v",
                "assets": [
                    {
                        "asset_id": "22222222-2222-4222-8222-222222222222",
                        "role": "first_frame",
                    }
                ],
                "prompt": h3_prompt.read_text(encoding="utf-8"),
                "aspect_ratio": "9:16",
                "duration_seconds": 15,
                "quality": "high",
                "execution_backend": "local_machine",
                "idempotency_key": task_preview_payload["idempotency_key"],
            }
            request = project / "request-v2.json"
            request.write_text(json.dumps(request_payload), encoding="utf-8")
            request_entry = workflow.record_artifact(run_dir, "request", request)
            request_validation = workflow.validate_request_for_run(
                run_dir, Path(request_entry["path"])
            )
            self.assertTrue(request_validation["valid"], request_validation["errors"])
            for field in ("candidate_id", "script_version", "keyframe_prompt_version"):
                self.assertEqual(selected[field], request_validation[field])
            workflow.record_request_validation(run_dir, request_validation)
            workflow.require_bound_request(
                json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            )

    def test_v2_new_prompt_invalidates_only_its_candidate_keyframe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "client"
            write_project(project)
            run_dir = Path(workflow.start_run(project, "run-v2-retry")["run_dir"])
            force_legacy_schema(run_dir, 2)
            scripts = project / "scripts.json"
            write_script_set(scripts)
            script_entry = workflow.record_artifact(run_dir, "script", scripts)
            workflow.approve_gate(run_dir, "script", script_entry["version"])

            prompt = project / "prompt.txt"
            for candidate_id in workflow.CANDIDATE_IDS:
                prompt.write_text(f"prompt {candidate_id}", encoding="utf-8")
                workflow.record_artifact(run_dir, "keyframe-prompt", prompt, candidate_id)
                image = project / f"image-{candidate_id}.png"
                image.write_bytes(candidate_id.encode())
                workflow.record_artifact(run_dir, "keyframe", image, candidate_id)

            prompt.write_text("revised prompt 2", encoding="utf-8")
            workflow.record_artifact(run_dir, "keyframe-prompt", prompt, "2")
            with self.assertRaises(workflow.WorkflowError):
                workflow.approve_gate(run_dir, "keyframe", candidate_id="1")

            image = project / "image-2-retry.png"
            image.write_bytes(b"retry-2")
            workflow.record_artifact(run_dir, "keyframe", image, "2")
            state = workflow.approve_gate(run_dir, "keyframe", candidate_id="1")
            self.assertEqual("1", state["approvals"]["keyframe"]["candidate_id"])

    def test_v3_proposal_revision_lock_production_and_request_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "client"
            write_project(project)
            started = workflow.start_run(project, "run-v3", 3)
            run_dir = Path(started["run_dir"])
            self.assertEqual(3, started["state"]["schema_version"])
            self.assertEqual("proposal_review", started["state"]["stage"])

            scripts = project / "scripts.json"
            write_script_set(scripts)
            script = workflow.record_artifact(run_dir, "script", scripts)
            dimensions = project / "dimensions.json"
            dimensions.write_text(
                json.dumps({"status": "missing", "measurements": [], "not_to_scale": True, "display_disclaimer": "尺寸未提供 / 非按比例"}),
                encoding="utf-8",
            )
            dimension = workflow.record_artifact(run_dir, "dimension-reference", dimensions)
            dimension_image_path = project / "dimension.png"
            dimension_image_path.write_bytes(b"dimension-image")
            dimension_image = workflow.record_artifact(
                run_dir, "dimension-reference-image", dimension_image_path
            )
            keyframe_path = project / "aggregate.png"
            keyframe_path.write_bytes(b"aggregate-v1")
            keyframe = workflow.record_artifact(run_dir, "aggregate-keyframe", keyframe_path)

            proposal = workflow.finalize_proposal(
                run_dir,
                script["version"],
                dimension["version"],
                dimension_image["version"],
                keyframe["version"],
            )
            self.assertEqual(1, proposal["proposal_revision"])
            proposal_dir = Path(proposal["deliverable_dir"])
            self.assertTrue((proposal_dir / "proposal.md").is_file())
            self.assertIn("尺寸未提供 / 非按比例", (proposal_dir / "proposal.md").read_text(encoding="utf-8"))
            v1_hash = workflow.sha256_file(Path(proposal["path"]))
            self.assertEqual(
                proposal,
                workflow.finalize_proposal(
                    run_dir,
                    script["version"],
                    dimension["version"],
                    dimension_image["version"],
                    keyframe["version"],
                ),
            )
            changed_keyframe_path = project / "aggregate-unreviewed.png"
            changed_keyframe_path.write_bytes(b"aggregate-unreviewed")
            changed_keyframe = workflow.record_artifact(run_dir, "aggregate-keyframe", changed_keyframe_path)
            with self.assertRaises(workflow.WorkflowError):
                workflow.finalize_proposal(run_dir, script["version"], dimension["version"], dimension_image["version"], changed_keyframe["version"])

            feedback_path = project / "feedback.json"
            feedback_path.write_text(
                json.dumps(
                    {
                        "raw_reply": "价格文字改一下，画面不用改",
                        "received_at": "2026-08-30T10:00:00+08:00",
                        "channel": "chat",
                        "change_items": [{"field": "post_production_text", "action": "replace"}],
                        "affects_visuals": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            feedback = workflow.record_feedback(run_dir, 1, feedback_path)
            workflow.begin_revision(run_dir, 1, feedback["version"])
            proposal_v2 = workflow.finalize_proposal(
                run_dir,
                script["version"],
                dimension["version"],
                dimension_image["version"],
                keyframe["version"],
                1,
            )
            self.assertEqual(2, proposal_v2["proposal_revision"])
            self.assertEqual(v1_hash, workflow.sha256_file(Path(proposal["path"])))
            self.assertTrue(workflow.read_json_artifact(proposal_v2, "proposal")["keyframe_reuse"])
            feedback_binding = workflow.read_json_artifact(proposal_v2, "proposal")["client_feedback"]
            self.assertEqual(feedback["sha256"], feedback_binding["sha256"])

            approval_path = project / "approval.json"
            approval_path.write_text(
                json.dumps(
                    {
                        "raw_reply": "确认 V2，选 3，直接生成一个视频",
                        "confirmed_at": "2026-08-30T10:05:00+08:00",
                        "channel": "chat",
                        "client_name": "客户",
                        "proposal_revision": 2,
                        "candidate_id": "3",
                        "create_task_authorized": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            state = workflow.lock_proposal(run_dir, 2, "3", approval_path)
            lock = state["approvals"]["proposal"]
            self.assertTrue(lock["audit"]["create_task_authorized"])
            self.assertEqual(lock, state["proposal_locks"][0])

            h3_path = project / "h3-v3.txt"
            h3_path.write_text(
                workflow.I2VA_OPENING
                + "\n\nintegrated_multimodal_description: [Shot 1] Product ad.\n\n"
                + "overall_soundscape: Quiet ambience.\n\n"
                + "non_diegetic_music: Light percussion.",
                encoding="utf-8",
            )
            h3 = workflow.record_artifact(run_dir, "h3-prompt", h3_path)
            workflow.record_h3_validation(run_dir, workflow.validate_h3_prompt(h3_path, 15))
            preview_payload = {
                "proposal_lock_id": lock["lock_id"],
                "proposal_revision": 2,
                "proposal_package_sha256": proposal_v2["sha256"],
                "candidate_id": "3",
                "h3_prompt_version": h3["version"],
                "workspace_id": "11111111-1111-4111-8111-111111111111",
                "mode": "i2v",
                "duration_seconds": 15,
                "aspect_ratio": "9:16",
                "quality": "high",
                "execution_backend": "local_machine",
                "idempotency_key": "33333333-3333-4333-8333-333333333333",
            }
            preview_path = project / "preview-v3.json"
            invalid_preview_path = project / "preview-invalid-v3.json"
            invalid_preview_path.write_text(json.dumps({**preview_payload, "mode": "t2v"}), encoding="utf-8")
            workflow.record_artifact(run_dir, "task-preview", invalid_preview_path)
            with self.assertRaises(workflow.WorkflowError):
                workflow.finalize_production(run_dir)
            preview_path.write_text(json.dumps(preview_payload), encoding="utf-8")
            workflow.record_artifact(run_dir, "task-preview", preview_path)
            production = workflow.finalize_production(run_dir)
            self.assertEqual(1, production["version"])

            upload_path = project / "upload.json"
            upload_path.write_text(json.dumps({"asset_id": "22222222-2222-4222-8222-222222222222", "proposal_lock_id": lock["lock_id"], "source_sha256": workflow.read_json_artifact(production, "production")["aggregate_keyframe"]["sha256"]}), encoding="utf-8")
            workflow.record_artifact(run_dir, "asset-upload", upload_path)

            request_payload = {
                "workspace_id": preview_payload["workspace_id"],
                "mode": "i2v",
                "assets": [{"asset_id": "22222222-2222-4222-8222-222222222222", "role": "first_frame"}],
                "prompt": h3_path.read_text(encoding="utf-8"),
                "aspect_ratio": "9:16",
                "duration_seconds": 15,
                "quality": "high",
                "execution_backend": "local_machine",
                "idempotency_key": preview_payload["idempotency_key"],
            }
            request_path = project / "request-v3.json"
            request_path.write_text(json.dumps(request_payload), encoding="utf-8")
            request = workflow.record_artifact(run_dir, "request", request_path)
            validation = workflow.validate_request_for_run(run_dir, Path(request["path"]))
            self.assertTrue(validation["valid"], validation["errors"])
            self.assertEqual(lock["lock_id"], validation["proposal_lock_id"])
            workflow.record_request_validation(run_dir, validation)

            task_path = project / "task-v3.json"
            task_path.write_text(json.dumps({"task_id": "task-v3", "status": "processing"}), encoding="utf-8")
            workflow.record_artifact(run_dir, "task-result", task_path)
            state = workflow.set_stage(run_dir, "production_ready", "submitted")
            self.assertEqual("submitted", state["stage"])
            workflow.set_stage(run_dir, "submitted", "monitoring")
            workflow.set_stage(run_dir, "monitoring", "failed")
            with self.assertRaises(workflow.WorkflowError):
                workflow.set_stage(run_dir, "failed", "proposal_locked")
            retry_path = project / "retry.json"
            retry_path.write_text(json.dumps({"raw_reply": "明确重试一次", "confirmed_at": "2026-08-30T10:10:00+08:00", "channel": "chat", "retry_authorized": True}), encoding="utf-8")
            state = workflow.authorize_retry(run_dir, retry_path)
            self.assertEqual("proposal_locked", state["stage"])
            self.assertEqual(1, len(state["artifacts"]["retry-authorization"]))
            with self.assertRaises(workflow.WorkflowError):
                workflow.finalize_production(run_dir)

    def test_v3_visual_feedback_requires_new_aggregate_keyframe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "client"
            write_project(project)
            run_dir = Path(workflow.start_run(project, "run-v3-visual", 3)["run_dir"])
            scripts = project / "scripts.json"
            write_script_set(scripts)
            script = workflow.record_artifact(run_dir, "script", scripts)
            dimensions = project / "dimensions.json"
            dimensions.write_text(json.dumps({"status": "missing", "measurements": [], "not_to_scale": True, "display_disclaimer": "尺寸未提供 / 非按比例"}), encoding="utf-8")
            dimension = workflow.record_artifact(run_dir, "dimension-reference", dimensions)
            image = project / "reference.png"
            image.write_bytes(b"image")
            dimension_image = workflow.record_artifact(run_dir, "dimension-reference-image", image)
            keyframe = workflow.record_artifact(run_dir, "aggregate-keyframe", image)
            proposal_v1 = workflow.finalize_proposal(run_dir, script["version"], dimension["version"], dimension_image["version"], keyframe["version"])
            approval_v1 = project / "approval-v1.json"
            approval_v1.write_text(json.dumps({"raw_reply": "确认 V1 选 1", "confirmed_at": "2026-08-30T10:00:00+08:00", "channel": "chat", "proposal_revision": 1, "candidate_id": "1", "create_task_authorized": True}), encoding="utf-8")
            state_v1 = workflow.lock_proposal(run_dir, 1, "1", approval_v1)
            old_lock = state_v1["approvals"]["proposal"]
            old_h3_path = project / "old-h3.txt"
            old_h3_path.write_text(workflow.I2VA_OPENING + "\n\nintegrated_multimodal_description: [Shot 1] Old.\n\noverall_soundscape: Quiet.\n\nnon_diegetic_music: Light.", encoding="utf-8")
            old_h3 = workflow.record_artifact(run_dir, "h3-prompt", old_h3_path)
            workflow.record_h3_validation(run_dir, workflow.validate_h3_prompt(old_h3_path, 15))
            feedback_path = project / "feedback.json"
            feedback_path.write_text(json.dumps({"raw_reply": "产品放大", "received_at": "2026-08-30T10:00:00+08:00", "channel": "chat", "change_items": [{"field": "composition"}], "affects_visuals": True}), encoding="utf-8")
            feedback = workflow.record_feedback(run_dir, 1, feedback_path)
            workflow.begin_revision(run_dir, 1, feedback["version"])
            with self.assertRaises(workflow.WorkflowError):
                workflow.finalize_proposal(run_dir, script["version"], dimension["version"], dimension_image["version"], keyframe["version"], 1)
            revised_keyframe_path = project / "reference-v2.png"
            revised_keyframe_path.write_bytes(b"image-v2")
            revised_keyframe = workflow.record_artifact(run_dir, "aggregate-keyframe", revised_keyframe_path)
            proposal_v2 = workflow.finalize_proposal(run_dir, script["version"], dimension["version"], dimension_image["version"], revised_keyframe["version"], 1)
            approval_v2 = project / "approval-v2.json"
            approval_v2.write_text(json.dumps({"raw_reply": "确认 V2 选 2", "confirmed_at": "2026-08-30T10:05:00+08:00", "channel": "chat", "proposal_revision": 2, "candidate_id": "2", "create_task_authorized": True}), encoding="utf-8")
            state_v2 = workflow.lock_proposal(run_dir, 2, "2", approval_v2)
            new_lock = state_v2["approvals"]["proposal"]
            stale_preview_path = project / "stale-preview.json"
            stale_preview_path.write_text(json.dumps({"proposal_lock_id": new_lock["lock_id"], "proposal_revision": 2, "proposal_package_sha256": proposal_v2["sha256"], "candidate_id": "2", "h3_prompt_version": old_h3["version"], "workspace_id": "11111111-1111-4111-8111-111111111111", "mode": "i2v", "duration_seconds": 15, "aspect_ratio": "9:16", "quality": "high", "execution_backend": "local_machine", "idempotency_key": "55555555-5555-4555-8555-555555555555"}), encoding="utf-8")
            workflow.record_artifact(run_dir, "task-preview", stale_preview_path)
            with self.assertRaises(workflow.WorkflowError):
                workflow.finalize_production(run_dir)
            self.assertNotEqual(old_lock["lock_id"], new_lock["lock_id"])

    def test_v4_locked_script_storyboard_and_r2v_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "client"
            write_project(project)
            started = workflow.start_run(project, "run-v4")
            run_dir = Path(started["run_dir"])
            self.assertEqual(4, started["state"]["schema_version"])
            self.assertEqual("script_review", started["state"]["stage"])

            visual_path = project / "visual.json"
            visual_payload = {
                "visual_requirements": {"product": "保持蓝色外壳"},
                "product_reference_decision": {"required": True, "reason": "需要手持与近景"},
                "asset_roles": [
                    {"filename": "product.jpg", "role": "Box Master"},
                    {"filename": "scene.jpg", "role": "Scene Reference"},
                ],
                "product_identity_sources": ["product.jpg"],
                "scale_reference": {"status": "missing", "precise_scale_claimed": False, "postproduction_recommendation": "使用真实产品素材后期合成"},
                "storyboard": [
                    {"time": "0-3s", "person": "年轻女性", "environment": "明亮厨房", "action": "拿起产品", "product": "蓝色盒装产品", "visual_elements": "中近景"},
                    {"time": "3-15s", "person": "同一女性", "environment": "同一厨房", "action": "展示产品并指向 CTA", "product": "同一蓝色盒装产品", "visual_elements": "结尾预留文字区"},
                ],
            }
            visual_path.write_text(json.dumps(visual_payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(workflow.WorkflowError):
                workflow.record_artifact(run_dir, "visual-plan", visual_path)

            proposal_path = project / "script-proposal.json"
            write_v4_script_proposal(proposal_path)
            proposal_artifact = workflow.record_artifact(run_dir, "script-proposal", proposal_path)
            package = workflow.finalize_script_proposal(run_dir, proposal_artifact["version"])

            final_path = project / "final-script.json"
            candidates = json.loads(proposal_path.read_text(encoding="utf-8"))["candidates"]
            final_path.write_text(json.dumps({"source_candidate_id": "2", **{key: value for key, value in candidates[1].items() if key != "candidate_id"}}, ensure_ascii=False), encoding="utf-8")
            final_artifact = workflow.record_artifact(run_dir, "final-script", final_path)
            script_approval = project / "script-approval.json"
            script_approval.write_text(json.dumps({"raw_reply": "确认 V1，选 2，脚本锁定", "confirmed_at": "2026-08-31T10:00:00+08:00", "channel": "chat", "script_revision": 1, "candidate_id": "2"}, ensure_ascii=False), encoding="utf-8")
            state = workflow.lock_script(run_dir, package["script_revision"], "2", final_artifact["version"], script_approval)
            self.assertEqual("script_locked", state["stage"])
            self.assertEqual("Script = LOCKED", state["approvals"]["script"]["status"])
            workflow.set_stage(run_dir, "script_locked", "storyboard_review")

            invalid_visual = project / "invalid-visual.json"
            invalid_payload = {**visual_payload, "product_identity_sources": ["scene.jpg"]}
            invalid_visual.write_text(json.dumps(invalid_payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(workflow.WorkflowError):
                workflow.record_artifact(run_dir, "visual-plan", invalid_visual)

            visual = workflow.record_artifact(run_dir, "visual-plan", visual_path)
            prompt_path = project / "aggregate-prompt.txt"
            prompt_path.write_text("Generate ONE SINGLE vertical 9:16 aggregate storyboard sheet containing 2 chronological cinematic panels.", encoding="utf-8")
            prompt = workflow.record_artifact(run_dir, "aggregate-keyframe-prompt", prompt_path)
            image_path = project / "aggregate.png"
            image_path.write_bytes(b"aggregate-storyboard-v1")
            keyframe = workflow.record_artifact(run_dir, "aggregate-keyframe", image_path)
            storyboard = workflow.finalize_storyboard(run_dir, visual["version"], prompt["version"], keyframe["version"])

            storyboard_approval = project / "storyboard-approval.json"
            storyboard_approval.write_text(json.dumps({"raw_reply": "确认 Storyboard V1，直接生成一次", "confirmed_at": "2026-08-31T10:05:00+08:00", "channel": "chat", "storyboard_revision": 1, "create_task_authorized": True}, ensure_ascii=False), encoding="utf-8")
            state = workflow.lock_storyboard(run_dir, storyboard["storyboard_revision"], storyboard_approval)
            lock = state["approvals"]["storyboard"]
            self.assertEqual("storyboard_locked", state["stage"])

            h3_path = project / "h3-ref2va.txt"
            h3_path.write_text(
                "subject_definitions: @产品主图 is the exact blue product identity.\n\n"
                "summary: Create the locked 15-second ad using @分镜图 and @产品主图.\n\n"
                "retention_analysis: Retain product shape, color, and chronological panel intent.\n\n"
                "detailed_description: Follow @分镜图 chronologically while preserving @产品主图.\n\n"
                "overall_soundscape: Natural kitchen ambience and clear Malaysian Chinese dialogue.\n\n"
                "non_diegetic_music: Light upbeat percussion.",
                encoding="utf-8",
            )
            h3 = workflow.record_artifact(run_dir, "h3-prompt", h3_path)
            validation = workflow.validate_h3_prompt(h3_path, 15)
            self.assertEqual("ref2va", validation["mode"])
            workflow.record_h3_validation(run_dir, validation)

            storyboard_payload = workflow.read_json_artifact(storyboard, "storyboard-package")
            aggregate_sha = storyboard_payload["components"]["aggregate_keyframe"]["sha256"]
            manifest = json.loads(Path(started["manifest"]).read_text(encoding="utf-8"))
            product_sha = next(item["sha256"] for item in manifest["assets"] if item["filename"] == "product.jpg")
            preview_payload = {
                "storyboard_lock_id": lock["lock_id"],
                "storyboard_revision": 1,
                "storyboard_package_sha256": storyboard["sha256"],
                "script_lock_id": lock["script_lock_id"],
                "candidate_id": "2",
                "h3_prompt_version": h3["version"],
                "workspace_id": "11111111-1111-4111-8111-111111111111",
                "mode": "r2v",
                "duration_seconds": 15,
                "aspect_ratio": "9:16",
                "quality": "high",
                "execution_backend": "local_machine",
                "idempotency_key": "33333333-3333-4333-8333-333333333333",
                "reference_assets": [
                    {"source_sha256": aggregate_sha, "source_filename": "aggregate-storyboard", "asset_role": "Aggregate Storyboard", "mention_name": "分镜图", "reference_description": "锁定的聚合 Storyboard"},
                    {"source_sha256": product_sha, "source_filename": "product.jpg", "asset_role": "Box Master", "mention_name": "产品主图", "reference_description": "蓝色盒装产品身份"},
                ],
            }
            invalid_preview_path = project / "preview-invalid-semantics.json"
            invalid_preview = {**preview_payload, "reference_assets": [
                {**preview_payload["reference_assets"][0], "source_filename": "product.jpg", "asset_role": "Box Master"},
                {**preview_payload["reference_assets"][1], "source_filename": "aggregate-storyboard", "asset_role": "Aggregate Storyboard"},
            ]}
            invalid_preview_path.write_text(json.dumps(invalid_preview, ensure_ascii=False), encoding="utf-8")
            workflow.record_artifact(run_dir, "task-preview", invalid_preview_path)
            with self.assertRaises(workflow.WorkflowError):
                workflow.finalize_production(run_dir)
            preview_path = project / "preview-v4.json"
            preview_path.write_text(json.dumps(preview_payload, ensure_ascii=False), encoding="utf-8")
            workflow.record_artifact(run_dir, "task-preview", preview_path)
            production = workflow.finalize_production(run_dir)
            self.assertEqual("r2v", workflow.read_json_artifact(production, "production-package")["task_parameters"]["mode"])

            upload_data = [
                ("分镜图", aggregate_sha, "aggregate-storyboard", "Aggregate Storyboard", "22222222-2222-4222-8222-222222222222"),
                ("产品主图", product_sha, "product.jpg", "Box Master", "44444444-4444-4444-8444-444444444444"),
            ]
            for index, (name, source_sha, source_filename, asset_role, asset_id) in enumerate(upload_data, 1):
                upload_path = project / f"upload-{index}.json"
                upload_path.write_text(json.dumps({"asset_id": asset_id, "storyboard_lock_id": lock["lock_id"], "source_sha256": source_sha, "source_filename": source_filename, "asset_role": asset_role, "mention_name": name, "reference_description": name}, ensure_ascii=False), encoding="utf-8")
                workflow.record_artifact(run_dir, "asset-upload", upload_path)

            request_payload = {
                "workspace_id": preview_payload["workspace_id"],
                "mode": "r2v",
                "assets": [
                    {"asset_id": asset_id, "role": "reference_image", "mention_name": name, "reference_description": name}
                    for name, _, _, _, asset_id in upload_data
                ],
                "prompt": h3_path.read_text(encoding="utf-8"),
                "aspect_ratio": "9:16",
                "duration_seconds": 15,
                "quality": "high",
                "execution_backend": "local_machine",
                "idempotency_key": preview_payload["idempotency_key"],
            }
            request_path = project / "request-v4.json"
            request_path.write_text(json.dumps(request_payload, ensure_ascii=False), encoding="utf-8")
            request = workflow.record_artifact(run_dir, "request", request_path)
            result = workflow.validate_request_for_run(run_dir, Path(request["path"]))
            self.assertTrue(result["valid"], result["errors"])
            workflow.record_request_validation(run_dir, result)
            task_path = project / "task-v4.json"
            task_path.write_text(json.dumps({"task_id": "task-v4", "status": "queued"}), encoding="utf-8")
            workflow.record_artifact(run_dir, "task-result", task_path)
            state = workflow.set_stage(run_dir, "production_ready", "submitted")
            self.assertEqual("submitted", state["stage"])

            metadata_feedback_path = project / "metadata-feedback.json"
            metadata_feedback_path.write_text(json.dumps({"raw_reply": "只改内部备注", "received_at": "2026-08-31T10:10:00+08:00", "channel": "chat", "change_items": [{"field": "metadata"}], "affects_visuals": False}, ensure_ascii=False), encoding="utf-8")
            metadata_feedback = workflow.record_feedback(run_dir, 1, metadata_feedback_path, "storyboard")
            workflow.begin_revision(run_dir, 1, metadata_feedback["version"], "storyboard")
            storyboard_v2 = workflow.finalize_storyboard(run_dir, visual["version"], prompt["version"], keyframe["version"], 1)
            storyboard_approval_v2 = project / "storyboard-approval-v2.json"
            storyboard_approval_v2.write_text(json.dumps({"raw_reply": "确认 Storyboard V2，再生成一次", "confirmed_at": "2026-08-31T10:11:00+08:00", "channel": "chat", "storyboard_revision": 2, "create_task_authorized": True}, ensure_ascii=False), encoding="utf-8")
            state = workflow.lock_storyboard(run_dir, storyboard_v2["storyboard_revision"], storyboard_approval_v2)
            lock_v2 = state["approvals"]["storyboard"]
            h3_v2 = workflow.record_artifact(run_dir, "h3-prompt", h3_path)
            workflow.record_h3_validation(run_dir, workflow.validate_h3_prompt(h3_path, 15))
            preview_v2 = {**preview_payload, "storyboard_lock_id": lock_v2["lock_id"], "storyboard_revision": 2, "storyboard_package_sha256": storyboard_v2["sha256"], "h3_prompt_version": h3_v2["version"]}
            preview_v2_path = project / "preview-v4-reused-idempotency.json"
            preview_v2_path.write_text(json.dumps(preview_v2, ensure_ascii=False), encoding="utf-8")
            workflow.record_artifact(run_dir, "task-preview", preview_v2_path)
            with self.assertRaises(workflow.WorkflowError):
                workflow.finalize_production(run_dir)

    def test_v4_final_script_must_match_script_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "client"
            write_project(project)
            run_dir = Path(workflow.start_run(project, "run-v4-script-binding")["run_dir"])
            proposal_path = project / "proposal-v1.json"
            write_v4_script_proposal(proposal_path)
            proposal_v1 = workflow.record_artifact(run_dir, "script-proposal", proposal_path)
            package_v1 = workflow.finalize_script_proposal(run_dir, proposal_v1["version"])
            selected = json.loads(proposal_path.read_text(encoding="utf-8"))["candidates"][0]
            final_path = project / "final-v1.json"
            final_path.write_text(json.dumps({"source_candidate_id": "1", **{key: value for key, value in selected.items() if key != "candidate_id"}}, ensure_ascii=False), encoding="utf-8")
            stale_final = workflow.record_artifact(run_dir, "final-script", final_path)
            self.assertEqual(package_v1["sha256"], stale_final["script_package_sha256"])

            feedback_path = project / "script-feedback.json"
            feedback_path.write_text(json.dumps({"raw_reply": "更新脚本措辞", "received_at": "2026-08-31T10:05:00+08:00", "channel": "chat", "change_items": [{"field": "voiceover"}], "affects_visuals": False}, ensure_ascii=False), encoding="utf-8")
            feedback = workflow.record_feedback(run_dir, 1, feedback_path, "script")
            workflow.begin_revision(run_dir, 1, feedback["version"], "script")
            proposal_v2_path = project / "proposal-v2.json"
            write_v4_script_proposal(proposal_v2_path)
            proposal_v2 = workflow.record_artifact(run_dir, "script-proposal", proposal_v2_path)
            package_v2 = workflow.finalize_script_proposal(run_dir, proposal_v2["version"], 1)
            approval_path = project / "script-approval-v2.json"
            approval_path.write_text(json.dumps({"raw_reply": "确认 V2，选 1", "confirmed_at": "2026-08-31T10:06:00+08:00", "channel": "chat", "script_revision": 2, "candidate_id": "1"}, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(workflow.WorkflowError):
                workflow.lock_script(run_dir, package_v2["script_revision"], "1", stale_final["version"], approval_path)

    def test_v4_visual_feedback_requires_new_storyboard_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "client"
            write_project(project)
            run_dir = Path(workflow.start_run(project, "run-v4-feedback")["run_dir"])
            proposal_path = project / "proposal.json"
            write_v4_script_proposal(proposal_path)
            proposal = workflow.record_artifact(run_dir, "script-proposal", proposal_path)
            package = workflow.finalize_script_proposal(run_dir, proposal["version"])
            selected = json.loads(proposal_path.read_text(encoding="utf-8"))["candidates"][0]
            final_path = project / "final.json"
            final_path.write_text(json.dumps({"source_candidate_id": "1", **{key: value for key, value in selected.items() if key != "candidate_id"}}, ensure_ascii=False), encoding="utf-8")
            final = workflow.record_artifact(run_dir, "final-script", final_path)
            approval = project / "approval.json"
            approval.write_text(json.dumps({"raw_reply": "选 1", "confirmed_at": "2026-08-31T10:00:00+08:00", "channel": "chat"}), encoding="utf-8")
            workflow.lock_script(run_dir, package["script_revision"], "1", final["version"], approval)
            workflow.set_stage(run_dir, "script_locked", "storyboard_review")
            visual_path = project / "visual.json"
            visual_path.write_text(json.dumps({"visual_requirements": {"product": "蓝色"}, "product_reference_decision": {"required": True}, "asset_roles": [{"filename": "product.jpg", "role": "Box Master"}], "product_identity_sources": ["product.jpg"], "scale_reference": {"status": "missing", "precise_scale_claimed": False, "postproduction_recommendation": "后期合成"}, "storyboard": [{"time": "0-15s", "person": "人物", "environment": "室内", "action": "展示", "product": "产品", "visual_elements": "预留 CTA"}]}, ensure_ascii=False), encoding="utf-8")
            visual = workflow.record_artifact(run_dir, "visual-plan", visual_path)
            prompt_path = project / "prompt.txt"
            prompt_path.write_text("ONE SINGLE vertical 9:16 aggregate storyboard", encoding="utf-8")
            prompt = workflow.record_artifact(run_dir, "aggregate-keyframe-prompt", prompt_path)
            image_path = project / "image.png"
            image_path.write_bytes(b"v1")
            image = workflow.record_artifact(run_dir, "aggregate-keyframe", image_path)
            workflow.finalize_storyboard(run_dir, visual["version"], prompt["version"], image["version"])
            feedback_path = project / "feedback.json"
            feedback_path.write_text(json.dumps({"raw_reply": "产品放大", "received_at": "2026-08-31T10:05:00+08:00", "channel": "chat", "change_items": [{"field": "composition"}], "affects_visuals": True}, ensure_ascii=False), encoding="utf-8")
            feedback = workflow.record_feedback(run_dir, 1, feedback_path, "storyboard")
            workflow.begin_revision(run_dir, 1, feedback["version"], "storyboard")
            with self.assertRaises(workflow.WorkflowError):
                workflow.finalize_storyboard(run_dir, visual["version"], prompt["version"], image["version"], 1)

    def test_h3_prompt_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            prompt = Path(temp) / "prompt.txt"
            prompt.write_text(
                workflow.I2VA_OPENING
                + "\n\nintegrated_multimodal_description: [Shot 1] Live-action. "
                + "[Shot 2] At 00:00:03.000, the camera cuts to the product.\n\n"
                + "overall_soundscape: Quiet room ambience.\n\n"
                + "non_diegetic_music: Light percussion.",
                encoding="utf-8",
            )
            result = workflow.validate_h3_prompt(prompt, 15)
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual([3.0], result["cut_times"])

    def test_final_i2v_request_matches_console_contract(self) -> None:
        request = {
            "workspace_id": "11111111-1111-4111-8111-111111111111",
            "mode": "i2v",
            "assets": [
                {
                    "asset_id": "22222222-2222-4222-8222-222222222222",
                    "role": "first_frame",
                }
            ],
            "prompt": workflow.I2VA_OPENING + "\n\nintegrated_multimodal_description: [Shot 1] Product ad.\n\noverall_soundscape: Quiet ambience.\n\nnon_diegetic_music: Light percussion.",
            "aspect_ratio": "9:16",
            "duration_seconds": 15,
            "quality": "high",
            "execution_backend": "local_machine",
            "idempotency_key": "33333333-3333-4333-8333-333333333333",
        }
        self.assertEqual([], request_validator.validate(request))


if __name__ == "__main__":
    unittest.main()
