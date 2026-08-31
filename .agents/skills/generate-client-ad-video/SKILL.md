---
name: generate-client-ad-video
description: Orchestrate child agents that turn client materials into five versioned script options, one locked Final Script, one chronological aggregate Storyboard, a locked R2V MiniMax H3 production package, and one authorized video task. Use for end-to-end client advertising workflows with auditable feedback and locking.
---

# Generate Client Ad Video

Run this orchestration-only workflow:

`客户资料 → 五案 V1/V2/V3 → Final Script 锁定 → 视觉方案 → 单张聚合 Storyboard → 确认并授权 → R2V H3 生产包 → 一个视频任务`

New runs use schema v4. Resume schema v1–v3 runs under their recorded legacy contract; never migrate or rewrite them.

## Mandatory Child-Agent Execution

The root conversation only dispatches and waits, presents sanitized child results, and records client feedback or confirmation. It must not inspect attachments, assemble deliverables, generate images/prompts, mutate run state, upload assets, submit, or monitor by itself.

Delegate every production and state operation using [references/workflow-contract.md](references/workflow-contract.md). Children exchange recorded artifact paths and versions, never reconstructed chat prose. If delegation is unavailable, pause.

## Dependencies

- The script child must read `5-scripts` and produce exactly five verified candidates plus revisions and a Final Script.
- Only after `Script = LOCKED`, the visual child reads `aggregate-keyframe-generation`; the image child generates its one 9:16 chronological Storyboard.
- The H3 child reads `h3-prompt-writing` and creates a Ref2VA production prompt from locked artifacts.
- The submission child reads `minimax-h3-console-video-generator` and its Console workflow.
- No external video task may be created before the Storyboard confirmation records `create_task_authorized: true`.

## Intake and Script Stage

Delegate attachment inspection and verified fact extraction to an intake/state child. Use [references/chat-intake.md](references/chat-intake.md) for chat input and [references/brief-template.md](references/brief-template.md) for file input.

The script child records `script-proposal` candidates 1–5. Client feedback is append-only and produces a new immutable script package. After selection or revision, record one `final-script` and call `lock-script`; the lock states `Script = LOCKED`. The state child then advances `script_locked → storyboard_review` before visual work begins.

## Storyboard Stage

The visual child consumes only the current script lock and client assets. It records `visual-plan` with asset roles, product-reference decision, scale evidence, and chronological panels, then records one aggregate image prompt. The image child generates one vertical 9:16 multi-panel Storyboard—never a five-concept blend, poster, or set of separate images.

Storyboard feedback creates a new immutable version. Visual changes require a new aggregate image; non-visual metadata changes may reuse it only with a recorded reason. Script changes explicitly return to `script_review` and invalidate downstream bindings.

Final Storyboard confirmation calls `lock-storyboard` with the exact reply, version, time, channel, and `create_task_authorized: true`. This authorizes H3 preparation, necessary uploads, and exactly one video task.

## R2V Production and Submission

The H3 child consumes the locked Storyboard package and Final Script. It writes and validates a Ref2VA prompt, replaces semantic picture labels with exact `@mention_name` references, and records an R2V task preview with a never-before-used idempotency UUID. Every reference binds its source filename, SHA-256, and canonical visual-plan role.

The submission child uploads the aggregate Storyboard and only necessary client master images. Every asset uses `reference_image`; `mention_name` is unique and excludes `@`. Validate that no `first_frame`, `last_frame`, or `<Picture N>` remains, record each upload binding, validate the exact request, create one task, and monitor its recorded identity. Never expose secrets or presigned URLs.

An explicit failure stops automation. A retry requires a new client audit through `authorize-retry`, a new task preview and production package, and a new idempotency UUID.

## Stages

Schema v4 stages are:

`script_review → script_locked → storyboard_review → storyboard_locked → production_ready → submitted → monitoring → succeeded|failed`

Use the CLI and artifact contracts in [references/workflow-contract.md](references/workflow-contract.md). On interruption, resume from the last valid recorded state.
