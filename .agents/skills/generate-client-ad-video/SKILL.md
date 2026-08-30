---
name: generate-client-ad-video
description: Orchestrate child agents that turn chat-supplied product information or an existing ad-brief.md project into five ad-script options, five matching aggregate keyframes, and one selected MiniMax H3 video task through three approval gates. Use for low-input client advertising workflows that persist intake and run state locally.
---

# Generate Client Ad Video

Run a dual-input client-ad workflow as an orchestration-only conversation. Accept natural-language product facts and uploaded images for initial intake, or discover an existing file-driven project. Persist chat intake before creative work. Keep script writing, image generation, and video submission in separate turns so one response never performs more than one creative stage.

## Mandatory child-agent execution

The root/current conversation may only coordinate child agents, collect the three user approvals, and present child-produced results. It must not inspect attachments, persist intake, inspect or mutate project/run state, write scripts or prompts, generate images, validate requests, upload assets, submit tasks, or monitor tasks itself.

Delegate every production stage described in [references/workflow-contract.md](references/workflow-contract.md). Give each child the project and run paths, current stage, exact bounded responsibility, applicable approval state, and required Skill/reference paths. Require the child to record its artifacts and return a concise status, artifact paths/versions, and the sanitized display-ready payload the root needs for that gate. Use the recorded files as the production handoff between children; do not ask a later child to reconstruct an earlier artifact from conversation prose, and do not make the root read project files to rebuild a display payload.

Never silently fall back to local production work. If child-agent delegation is unavailable, no execution slot can be obtained, or a required child fails without leaving a valid recorded artifact, stop that stage and explain the delegation blocker. The root may retry or replace only the failed child after capacity returns; it may not complete the child's assignment itself.

## Required dependencies

- The selected-prompt child must use `h3-prompt-writing` to write the final I2VA prompt.
- The submission child must use `minimax-h3-console-video-generator` only after Gate 3 approval.
- Each Gate 2 candidate child must use the built-in image-generation workflow for its aggregate keyframe.
- Prefer fixed-choice controls when available. Otherwise accept the exact text commands documented below. Chat prose remains allowed for initial product intake and factual corrections, not open-ended creative revision.

## Intake

If the current conversation contains product information or attached images, delegate chat intake before project discovery:

1. Spawn an intake child to inspect every accessible attachment and extract explicit user facts and visually verifiable details only.
2. Convert the available information to the canonical JSON fields documented in [references/chat-intake.md](references/chat-intake.md). Derive `project_name` from the named product or service when necessary. Use the neutral defaults `清晰介绍产品或服务` for `objective` and `了解更多` for `cta` only when the user did not specify them.
3. Never invent a selling point. If neither chat nor visible material supports one, ask one concise question for a verifiable selling point; do not present the full form.
4. The intake child runs `scripts/project_workflow.py ingest WORKSPACE_ROOT --brief-json BRIEF_JSON --image ATTACHMENT...`. The command creates a collision-safe project directory, writes `ad-brief.md`, and copies the images beside it.
5. Continue with the returned project directory. Do not ask the user to recreate the same files manually.

If the user supplies factual corrections or additional source images before Gate 3, forward them to an intake/project-state child to save locally and restart from a newly inspected script batch. Before Gate 1 approval, regenerate only the five scripts; do not create or recompute keyframe prompts or images. Do not silently mutate an already approved external task intent.

## Start or resume

1. When chat intake did not create a project, delegate discovery, inspection, resume, and start commands to a project-state child. It runs `scripts/project_workflow.py discover WORKSPACE_ROOT`.
2. If projects exist but none is valid, show their validation errors and offer `编辑后重载` or `取消`. If no `ad-brief.md` exists, offer only `重新扫描` and `取消`.
3. If multiple projects exist, present their relative paths as paginated fixed choices, with no more than three choices per card.
4. Have the project-state child run `scripts/project_workflow.py inspect PROJECT_DIR` for the selected project.
5. If validation fails, show the errors and offer `编辑后重载` or `取消`. Do not infer missing required business facts.
6. Have the project-state child run `scripts/project_workflow.py resume PROJECT_DIR`. Resume the returned non-terminal run when present; otherwise run `scripts/project_workflow.py start PROJECT_DIR`.

Read [references/brief-template.md](references/brief-template.md) when explaining or validating the input form. Read [references/workflow-contract.md](references/workflow-contract.md) before producing Gate 1 output or changing run state.

## Source rules

- Treat the directory containing `ad-brief.md` as the project root.
- Use only supported images directly beside `ad-brief.md`; do not recurse for source images.
- Ignore hidden files, `output/`, generated artifacts, and unsupported formats.
- Treat `approved-keyframe.png`, `.jpg`, `.jpeg`, or `.webp` as a replacement keyframe, never as a source image.
- Analyze every source image visually. Apply optional asset-table roles from the brief as authoritative task semantics, but never let them override visible facts.
- Never invent product capabilities, prices, locations, credentials, measurements, guarantees, or offers.

## Gate 1: approve five scripts

Delegate Gate 1 to one script child. It creates exactly five concise, executable ad candidates for the configured duration and records the script artifact. Its assignment produces scripts only: it must not write keyframe prompts, call image generation, or draft an H3 prompt.

Record one JSON `script` artifact with `verified_facts_summary` and a `candidates` array ordered by stable IDs `1` through `5`. Every candidate must contain non-empty `candidate_id`, `creative_direction`, `hook`, `storyboard`, `voiceover`, `source_mapping`, and `post_production_text`. Give the five candidates materially different creative directions while preserving the same verified facts.

Display the five scripts compactly. Use `确认5个脚本`, `修改事实或重做`, and `取消`. If controls are unavailable, tell the user in the same sentence what each exact reply does. Factual prose such as a corrected price is allowed; after saving it, create a new script batch without doing image work.

On approval, delegate `scripts/project_workflow.py approve RUN_DIR --gate script --version VERSION` to a project-state child. This locks only the script batch and advances to `keyframe_review`; it must not require a keyframe prompt. Do not use `set-stage` to bypass the gate.

## Gate 2: generate five aggregate keyframes and select one pair

After Gate 1 approval, spawn one independent candidate child for each candidate ID `1` through `5`. Each child derives only its candidate's image-generation prompt without re-analyzing the brief or rewriting the approved scripts, records it with `record --kind keyframe-prompt --candidate-id N`, generates only that candidate's image, and records it with `record --kind keyframe --candidate-id N`.

Dispatch candidate children concurrently up to `min(available child-agent slots, 5)`, with at most one active child for a candidate. Keep a stable candidate-to-child assignment and launch remaining candidates in ID order as slots free up. On partial failure, retain every successful recorded candidate and allow at most one automatic replacement child for only the failed or missing candidate; do not rerun successful children. If that replacement also fails, stop Gate 2 and offer only `重做N号` or `取消` for that candidate.

Each candidate child makes exactly one image-generation call for its assigned candidate. Concurrency exists only at the root's child-dispatch layer; no child may generate another candidate. Each image must:

- cover the corresponding script's major storyboard beats in one borderless, naturally blended multi-scene advertising composition;
- avoid a grid, labeled storyboard, split screen, numbered panels, and a composition that represents only the first shot;
- preserve identifiable people, products, logos, colors, and locations only to the degree supported by source material;
- omit generated text unless the brief explicitly requires it, leaving contact details, prices, and exact typography for post-production.

Record every successful image immediately with `record --kind keyframe --candidate-id N`. On interruption or partial failure, inspect the recorded candidate IDs and generate only missing or stale candidates. Never discard successful candidates or restart the whole batch. If a candidate prompt changes, regenerate only that candidate's image.

Present all five script-and-image pairs. The user selects exactly one with `选1` through `选5`; also accept `重做N号`, `返回脚本`, and `取消`. A reserved `approved-keyframe.*` may replace one explicitly named candidate, not the whole batch.

Delegate approval of the selected pair to a project-state child with `approve RUN_DIR --gate keyframe --candidate-id N [--version VERSION]`. Only after this child returns the locked approval, spawn one selected-prompt child. The selected-prompt child consumes but never repeats that approval, uses `h3-prompt-writing` in I2VA mode, records the result with `record --kind h3-prompt --candidate-id N`, validates it, records `task-preview`, and advances to `task_review`. It grounds all output in the selected script and image, preserving the exact opening alignment instruction and the three required fields: `integrated_multimodal_description`, `overall_soundscape`, and `non_diegetic_music`.

The selected-prompt child runs `validate-h3-prompt`, resolves the workspace when omitted, and saves `task-preview` with `candidate_id`, `script_version`, `keyframe_prompt_version`, `keyframe_path`, `keyframe_version`, `h3_prompt_version`, workspace, mode, duration, ratio, quality, backend, and a new idempotency UUID. It advances to `task_review` only after prompt validation and preview recording succeed.

## Gate 3: approve task submission

Show:

- the selected candidate ID, approved script, keyframe path, and thumbnail;
- the complete H3 prompt;
- workspace, mode `i2v`, `first_frame`, duration, aspect ratio, quality, and execution backend;
- an explicit statement that confirmation uploads the keyframe and creates one external task.

Show `确认提交`, `返回修改`, and `取消`. If `返回修改` is chosen, show `返回脚本` and `返回关键帧`.

Forward every back or cancel choice to a project-state child, which performs the matching `set-stage` or cancellation transition and returns the new stage. The root must not change state itself.

Only `确认提交` authorizes upload and task creation. Before that exact approval, do not spawn a submission child and do not approve Gate 3 speculatively. After approval, spawn one submission child and pass the recorded authorization state. That child records it first with `scripts/project_workflow.py approve RUN_DIR --gate task`; this locks the approved keyframe, H3 prompt, and task-preview versions. If a resumed `task_review` already contains `approvals.task`, do not ask again or create a new intent. The child recovers with the locked preview, recorded final request when present, and its existing idempotency key. Then it:

1. Invoke `minimax-h3-console-video-generator` and follow its console workflow.
2. Upload only the approved aggregate keyframe as `first_frame`.
3. Build the final `i2v` request from the locked task preview and uploaded asset ID; preserve the preview's idempotency key exactly.
4. Record the final request JSON, then run `scripts/project_workflow.py validate-request RECORDED_REQUEST --run-dir RUN_DIR`. Do not call `create_video_task` unless this command records a successful validation bound to the current Gate 3 approval.
5. If a prior call has an uncertain result after interruption, resend only the exact recorded request with the same idempotency key; never generate a new key.
6. Calls `get_task_details` immediately and continues monitoring active states until success or explicit failure. Monitoring remains inside this submission child (or a dedicated monitoring child receiving the recorded task identity); the root conversation never polls the task itself.
7. Record sanitized task details with `record --kind task-result`, then advance to `submitted`; save the task ID, status, errors, and final links in run state.

Never expose presigned upload URLs, tokens, or secrets. Do not create a replacement task automatically after explicit failure.

When the user explicitly retries a failed task, return to `task_review`, create a new task-preview with a new idempotency UUID, and request Gate 3 confirmation again. Historical requests and task results remain versioned evidence but cannot satisfy the new approval intent.

## State and artifacts

Use `scripts/project_workflow.py record` for every artifact, `approve` for all three approvals, and `set-stage` for non-approval state changes. New runs use schema v2 and bind candidate-scoped prompts, images, H3 prompts, previews, and requests to the exact selected script. Existing schema v1 runs remain resumable under the legacy single-candidate rules. Never overwrite an earlier version. Keep all run files under `output/<run-id>/`.

Use these stages only:

`script_review`, `keyframe_review`, `task_review`, `submitted`, `monitoring`, `succeeded`, `failed`, `cancelled`.

On interruption, leave the last valid stage unchanged. On the next invocation, resume from it and show the corresponding fixed choices.
