---
name: generate-client-ad-video
description: Orchestrate child agents that turn client materials into versioned five-script proposal packages, one package-level aggregate keyframe, a locked MiniMax H3 production package, and one authorized video task. Use for client advertising workflows that need feedback revisions and auditable proposal locking.
---

# Generate Client Ad Video

Run this workflow as an orchestration-only conversation:

`客户资料 → 提案包 V1 → 客户反馈 → V2/V3 → 锁定最终提案与脚本 → H3 生产包 → 一个视频任务`

New runs use schema v3. Resume schema v1/v2 runs under their recorded legacy workflow; never migrate or rewrite them.

## Mandatory child-agent execution

The root/current conversation only dispatches and waits for children, presents their sanitized display-ready results, and collects client feedback or final confirmation. It must not inspect attachments or project files, assemble deliverables, write scripts/prompts, generate images, change run state, validate/upload/submit, or monitor tasks itself.

Delegate every production and state operation in [references/workflow-contract.md](references/workflow-contract.md). Children use recorded files as handoffs and return artifact paths/versions plus display-ready content. Never reconstruct artifacts from chat prose. If delegation or capacity is unavailable, pause; never fall back to root execution.

## Dependencies

- The H3 child reads `h3-prompt-writing` and writes the final I2VA prompt only after proposal locking.
- The submission/monitor child reads `minimax-h3-console-video-generator` and its console workflow.
- Image children use the built-in image-generation workflow.
- No child may create an external task until the client confirmation audit records `create_task_authorized: true`.

## Intake and resume

Delegate attachment inspection and factual extraction to an intake/state child. It records only explicit client facts and visually verifiable details, then runs `ingest`; for a file project it runs `discover`, `inspect`, `resume`, and when necessary `start`. Use [references/chat-intake.md](references/chat-intake.md) for chat normalization and [references/brief-template.md](references/brief-template.md) for file input.

New run stage is `proposal_review`. Every client reply after a published proposal is recorded append-only with `record-feedback`; a revision begins with `begin-revision`. Factual corrections invalidate only affected components. Historical proposal, feedback, lock, production, request, and task evidence is immutable.

## Build a proposal package

Dispatch a script child and dimension child concurrently when slots permit:

- The script child records exactly five candidates with stable IDs `1`–`5`. Each contains creative direction, hook, timeline storyboard, voiceover, source mapping, and post-production text. The directions must be materially different and use only verified facts.
- The dimension child records `dimension-reference` JSON and a bound `dimension-reference-image`. When physical dimensions were not supplied, record `status: missing`, no measurements, `not_to_scale: true`, and `display_disclaimer: 尺寸未提供 / 非按比例`; render that disclaimer in the image. Never infer physical dimensions from pixels or ordinary photos.

After both finish, dispatch one aggregate-keyframe child. It records one prompt and one package-level image covering the five concepts' shared brand, product, and major visual directions in a borderless, naturally blended composition. It must not be a grid, numbered storyboard, split screen, or a rendering of only one opening shot.

Finally dispatch a proposal assembler child to run `finalize-proposal`. It atomically publishes `proposals/VNN/` containing `proposal.md`, dimension JSON, dimension reference image, aggregate keyframe, and manifest, plus an immutable run-level `proposal-package-vNN.json`.

## Apply feedback and publish V2/V3

The intake/state child records every reply with raw text, time, channel, optional client name, structured changes, and `affects_visuals`. It then calls `begin-revision` with the exact base proposal and feedback versions.

Unchanged artifacts may be reused, but the proposal package always increments. Pure text feedback may reuse the keyframe and must record the reuse reason. Feedback affecting imagery, composition, product proportion, or a visible selling point requires a new aggregate keyframe; do not republish against the old image. Present the complete new package, never mutate the old one.

## Lock the final proposal

Final confirmation must identify proposal VNN and candidate `1`–`5`, and explicitly authorize one task creation. Delegate `lock-proposal` with an audit JSON containing raw reply, confirmation time, channel, optional client name, proposal revision, candidate ID, and `create_task_authorized: true`.

This confirmation locks the entire package, the chosen script, and the same-version package aggregate keyframe. It also authorizes H3 preparation, asset upload, and exactly one video task. There is no separate submission approval gate.

## Build and submit the H3 production package

After locking, dispatch one H3 child. It consumes only locked artifacts, writes and validates the I2VA prompt, records a task preview bound to `proposal_lock_id`, revision, package SHA-256, candidate ID, H3 prompt version, task settings, and a new idempotency UUID, then calls `finalize-production`.

Dispatch one submission/monitor child immediately after a valid production package is returned. It uploads only the locked aggregate keyframe as `first_frame`, records `asset-upload` evidence bound to the lock and source SHA-256, records the exact request, runs `validate-request`, creates one task with the production package's unchanged idempotency key, records sanitized task details, and monitors the recorded task identity. An uncertain result may resend only the exact request with the same key. Never expose upload URLs, tokens, or secrets.

An explicit task failure stops automation. Do not create a replacement. Only a retry child receiving a new client audit may run `authorize-retry` to return `failed` to `proposal_locked`; generic stage changes cannot authorize a retry. It then creates a new task preview and production package with a new idempotency UUID and submits one new authorized attempt. Preserve all prior evidence.

## Stages and commands

Schema v3 stages are:

`proposal_review → proposal_locked → production_ready → submitted → monitoring → succeeded|failed`

Use the CLI and artifact contracts in [references/workflow-contract.md](references/workflow-contract.md). On interruption, leave the last valid stage unchanged and resume from recorded artifacts.
