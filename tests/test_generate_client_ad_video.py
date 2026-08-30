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
        self.assertIn("Mandatory child-agent execution", skill_text)
        self.assertIn("must not inspect attachments", skill_text)
        self.assertIn("Never silently fall back to local production work", skill_text)
        self.assertIn("one independent candidate child for each candidate ID", skill_text)
        self.assertIn("do not spawn a submission child", skill_text)
        self.assertIn("The root conversation is the orchestrator", contract_text)
        self.assertIn("allow one automatic replacement child only for that candidate", contract_text)
        self.assertIn("at most one active child per candidate", contract_text)
        self.assertIn("Gate approvals are single-owner operations", contract_text)
        self.assertIn("Gate 3 authority cannot be delegated early", contract_text)

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
            legacy_state = json.loads(state_path.read_text(encoding="utf-8"))
            legacy_state["schema_version"] = 1
            state_path.write_text(json.dumps(legacy_state), encoding="utf-8")

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
            started = workflow.start_run(project, "run-v2")
            run_dir = Path(started["run_dir"])
            self.assertEqual(2, started["state"]["schema_version"])

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
