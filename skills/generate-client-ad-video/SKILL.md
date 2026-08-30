---
name: generate-client-ad-video
description: Turn either chat-supplied product information with uploaded images or an existing local ad-brief.md project into one recommended ad script, an aggregate keyframe, a MiniMax H3 I2VA prompt, and a console video task through three fixed-choice approval gates. Use for low-input client advertising workflows that persist all intake and run state locally.
---

# Generate Client Ad Video

Run a dual-input client-ad workflow. Accept natural-language product facts and uploaded images for initial intake, or discover an existing file-driven project. Persist chat intake before creative work. Use fixed-choice controls for approvals and creative revisions.

## Required dependencies

- Use `h3-prompt-writing` to write the final I2VA prompt.
- Use `minimax-h3-console-video-generator` only after Gate 3 approval.
- Use the built-in image-generation workflow for the aggregate keyframe.
- Require a host capable of rendering fixed-choice controls for the three approval gates. Chat prose remains allowed for initial product intake and factual corrections, not open-ended creative revision.

## Intake

If the current conversation contains product information or attached images, use chat intake before project discovery:

1. Inspect every accessible attachment. Extract explicit user facts and visually verifiable details only.
2. Convert the available information to the canonical JSON fields documented in [references/chat-intake.md](references/chat-intake.md). Derive `project_name` from the named product or service when necessary. Use the neutral defaults `清晰介绍产品或服务` for `objective` and `了解更多` for `cta` only when the user did not specify them.
3. Never invent a selling point. If neither chat nor visible material supports one, ask one concise question for a verifiable selling point; do not present the full form.
4. Run `scripts/project_workflow.py ingest WORKSPACE_ROOT --brief-json BRIEF_JSON --image ATTACHMENT...`. The command creates a collision-safe project directory, writes `ad-brief.md`, and copies the images beside it.
5. Continue with the returned project directory. Do not ask the user to recreate the same files manually.

If the user supplies factual corrections or additional source images before Gate 3, save them locally and restart from a newly inspected run. Do not silently mutate an already approved external task intent.

## Start or resume

1. When chat intake did not create a project, run `scripts/project_workflow.py discover WORKSPACE_ROOT`.
2. If projects exist but none is valid, show their validation errors and offer `编辑后重载` or `取消`. If no `ad-brief.md` exists, offer only `重新扫描` and `取消`.
3. If multiple projects exist, present their relative paths as paginated fixed choices, with no more than three choices per card.
4. Run `scripts/project_workflow.py inspect PROJECT_DIR` for the selected project.
5. If validation fails, show the errors and offer `编辑后重载` or `取消`. Do not infer missing required business facts.
6. Run `scripts/project_workflow.py resume PROJECT_DIR`. Resume the returned non-terminal run when present; otherwise run `scripts/project_workflow.py start PROJECT_DIR`.

Read [references/brief-template.md](references/brief-template.md) when explaining or validating the input form. Read [references/workflow-contract.md](references/workflow-contract.md) before producing Gate 1 output or changing run state.

## Source rules

- Treat the directory containing `ad-brief.md` as the project root.
- Use only supported images directly beside `ad-brief.md`; do not recurse for source images.
- Ignore hidden files, `output/`, generated artifacts, and unsupported formats.
- Treat `approved-keyframe.png`, `.jpg`, `.jpeg`, or `.webp` as a replacement keyframe, never as a source image.
- Analyze every source image visually. Apply optional asset-table roles from the brief as authoritative task semantics, but never let them override visible facts.
- Never invent product capabilities, prices, locations, credentials, measurements, guarantees, or offers.

## Gate 1: approve the script

Create exactly one recommended 15-second ad package unless the brief overrides duration. Save versioned artifacts before showing the gate.

Include:

- a short verified-facts summary;
- one creative direction and hook;
- a timestamped storyboard covering the full duration;
- spoken dialogue or voiceover in the brief language;
- source-image mapping per shot;
- post-production text recommendations;
- one aggregate-keyframe generation prompt.

Keep generated in-frame text out of the keyframe and H3 video unless the brief explicitly requires it. Prefer post-production overlays for contact details, logos, prices, and exact typography.

Show the primary choices `确认脚本`, `修改或重做`, and `取消`. If `修改或重做` is chosen, show `同配置重做`, `编辑 ad-brief.md 后重载`, and `更换根目录图片后重载`. Never ask for prose revision instructions.

On approval, run `scripts/project_workflow.py approve RUN_DIR --gate script --version VERSION`. This records the exact approved script and keyframe-prompt versions and advances to `keyframe_review`. Do not use `set-stage` to bypass the gate.

## Gate 2: approve the aggregate keyframe

If a reserved `approved-keyframe.*` exists, inspect and use it as the candidate. Otherwise:

1. Inspect all referenced local images before generation.
2. Generate one polished aggregate keyframe using the approved prompt and source images as references.
3. Compose one coherent advertising frame rather than a bordered grid, storyboard sheet, split screen, or labeled collage.
4. Preserve identifiable people, products, logos, colors, and locations only to the degree supported by the source material.
5. Save the candidate inside the active run directory without overwriting earlier versions.

Show `确认关键帧`, `修改或替换`, and `取消`. If `修改或替换` is chosen, show `同配置重新生成`, `加载 approved-keyframe.*`, and `返回脚本`. Do not accept chat prose as the revision mechanism.

After approval, run `scripts/project_workflow.py approve RUN_DIR --gate keyframe --version VERSION`. Then use `h3-prompt-writing` in I2VA mode. Ground the prompt in the approved image and script. Preserve the exact opening alignment instruction and the three required fields: `integrated_multimodal_description`, `overall_soundscape`, and `non_diegetic_music`.

Record the H3 prompt, then run `scripts/project_workflow.py validate-h3-prompt RECORDED_PROMPT --duration SECONDS --run-dir RUN_DIR`. Resolve the workspace with a fixed-choice picker when the brief omits it. Save a `task-preview` JSON containing the approved local keyframe path, H3 prompt version, workspace, mode, duration, ratio, quality, backend, and a new idempotency UUID. Advance from `keyframe_review` to `task_review` only after the prompt validation is recorded and the task preview is saved.

## Gate 3: approve task submission

Show:

- the approved keyframe path and thumbnail;
- the complete H3 prompt;
- workspace, mode `i2v`, `first_frame`, duration, aspect ratio, quality, and execution backend;
- an explicit statement that confirmation uploads the keyframe and creates one external task.

Show `确认提交`, `返回修改`, and `取消`. If `返回修改` is chosen, show `返回脚本` and `返回关键帧`.

Only `确认提交` authorizes upload and task creation. Record it first with `scripts/project_workflow.py approve RUN_DIR --gate task`; this locks the approved keyframe, H3 prompt, and task-preview versions. If a resumed `task_review` already contains `approvals.task`, do not ask again or create a new intent. Recover with the locked preview, recorded final request when present, and its existing idempotency key. Then:

1. Invoke `minimax-h3-console-video-generator` and follow its console workflow.
2. Upload only the approved aggregate keyframe as `first_frame`.
3. Build the final `i2v` request from the locked task preview and uploaded asset ID; preserve the preview's idempotency key exactly.
4. Record the final request JSON, then run `scripts/project_workflow.py validate-request RECORDED_REQUEST --run-dir RUN_DIR`. Do not call `create_video_task` unless this command records a successful validation bound to the current Gate 3 approval.
5. If a prior call has an uncertain result after interruption, resend only the exact recorded request with the same idempotency key; never generate a new key.
6. Call `get_task_details` immediately and continue monitoring active states until success or explicit failure.
7. Record sanitized task details with `record --kind task-result`, then advance to `submitted`; save the task ID, status, errors, and final links in run state.

Never expose presigned upload URLs, tokens, or secrets. Do not create a replacement task automatically after explicit failure.

When the user explicitly retries a failed task, return to `task_review`, create a new task-preview with a new idempotency UUID, and request Gate 3 confirmation again. Historical requests and task results remain versioned evidence but cannot satisfy the new approval intent.

## State and artifacts

Use `scripts/project_workflow.py record` for every approved or candidate artifact, `approve` for all three approvals, and `set-stage` for non-approval state changes. The CLI enforces required artifacts and approval versions before advancing. Never overwrite an earlier version. Keep all run files under `output/<run-id>/`.

Use these stages only:

`script_review`, `keyframe_review`, `task_review`, `submitted`, `monitoring`, `succeeded`, `failed`, `cancelled`.

On interruption, leave the last valid stage unchanged. On the next invocation, resume from it and show the corresponding fixed choices.
