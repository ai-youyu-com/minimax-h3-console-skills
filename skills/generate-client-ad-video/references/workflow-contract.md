# Workflow Contract

## Delegation contract

The root conversation is the orchestrator, not a production worker. Its only permitted actions are spawning/waiting/messaging child agents, presenting their returned results, and collecting explicit user choices or approvals. It must not run workflow commands, inspect or write project artifacts, invoke image or H3 tools, upload assets, submit requests, or poll external tasks. If delegation is unavailable, stop with a clear blocker; never execute the stage in the root as a fallback.

Use these child assignments and filesystem handoffs:

| Stage | Child responsibility | Required return to root |
|---|---|---|
| Intake/project state | inspect attachments when present; ingest or discover; persist factual corrections/assets; inspect; resume/start; apply every approved back/cancel/gate state transition | project/run paths, validation summary, current stage |
| Gate 1 production | read the brief and visible assets; create and record exactly one five-candidate script batch | script artifact path/version plus a display-ready five-script summary |
| Gate 2 production | one child per candidate ID; create and record only that candidate's keyframe prompt and image | candidate ID, prompt/image paths and versions, display-ready image result |
| Selected H3 preparation | consume the selected pair approval already locked by the project-state child; create/validate/record the H3 prompt and task preview; advance to `task_review` without re-approving Gate 2 | selected binding, prompt/preview paths and versions, complete sanitized H3 prompt and display-ready Gate 3 preview |
| Post-Gate-3 execution | only after the root receives `确认提交`; record Gate 3 approval, upload, validate and submit the locked request, then monitor it | sanitized task ID/status/errors/final links and recorded result version |

Every child receives the absolute project/run paths, current stage, exact candidate ID when applicable, the applicable user approval, and the paths to this Skill plus required dependent Skills/references. Children record artifacts before returning. They also return the sanitized display-ready content required at that gate so the root does not inspect project files. Later children consume recorded artifact paths and locked versions rather than recreated content from chat.

For Gate 2, start one distinct child per candidate in candidate-ID order and run at most `min(available child slots, 5)` concurrently, with at most one active child per candidate. Each child makes exactly one image-generation call for its candidate. When a child fails or leaves no valid artifact, retain all other candidate artifacts and allow one automatic replacement child only for that candidate. If the replacement also fails, stop and offer `重做N号` or `取消`; never retry automatically again or touch successful candidates. The root never fills in missing production output itself.

Gate 3 authority cannot be delegated early: do not spawn the submission child until the user explicitly replies `确认提交`, unless a resumed run already contains a valid locked `approvals.task`. Returning, cancelling, or revising does not authorize upload or task creation. A dedicated monitoring child may replace the submission child after task creation only when it receives the recorded task identity and locked request evidence.

Gate approvals are single-owner operations: a project-state child records Gate 1 and Gate 2 approvals; the post-Gate-3 submission child records Gate 3. Replaying Gate 3 against the same locked versions must reuse the existing approval intent and idempotency key. A different Gate 3 intent is allowed only after the explicit failed-to-`task_review` retry transition clears the old approval.

## Artifact names

Record artifacts with `project_workflow.py record`; the command assigns monotonically increasing versions:

| Kind | Typical source | Stored name |
|---|---|---|
| `script` | JSON package containing exactly candidates 1–5 | `script-vNN.json` |
| `keyframe-prompt` | candidate-scoped image-generation prompt | `keyframe-prompt-N-vNN.txt` |
| `keyframe` | candidate-scoped generated or replacement image | `keyframe-N-vNN.<ext>` |
| `h3-prompt` | final I2VA prompt for the selected candidate | `h3-prompt-N-vNN.txt` |
| `h3-validation` | successful validation bound to the prompt SHA-256 | `h3-validation-vNN.json` |
| `task-preview` | pre-upload logical configuration with locked idempotency key | `task-preview-vNN.json` |
| `request` | validated final Console request | `request-vNN.json` |
| `request-validation` | successful Console and approval-binding validation | `request-validation-vNN.json` |
| `task-result` | sanitized task details | `task-result-vNN.json` |

For schema v2, record `keyframe-prompt`, `keyframe`, and `h3-prompt` with `--candidate-id N`. Every candidate-scoped entry stores its script version; a keyframe also stores the exact prompt version used to generate it. Never place secrets, upload headers, tokens, or presigned URLs in artifacts or state.

The v2 `script` JSON contains `verified_facts_summary` and exactly five ordered candidates with IDs `1` through `5`. Each candidate contains `creative_direction`, `hook`, `storyboard`, `voiceover`, `source_mapping`, and `post_production_text`.

## State transitions

Use compare-and-set transitions:

```text
script_review -> keyframe_review -> task_review -> submitted -> monitoring
       ^                |               |                         |
       +----------------+---------------+                         +-> succeeded
                        +<--------------+                         +-> failed
any review stage -------------------------------------------------> cancelled
failed -> task_review | cancelled
```

Candidate regeneration records a new artifact version without changing the stage. Back actions must call `set-stage` with the current stage in `--expect`.

Record approvals with `approve --gate script|keyframe|task`. Gate 1 locks only the five-script JSON and does not require image prompts. Gate 2 requires complete, current prompt and image coverage for IDs 1–5, accepts `--candidate-id N`, and locks the selected script, prompt, and image versions. Gate 3 propagates the same candidate binding. The CLI rejects forward transitions when required artifacts, candidate coverage, or approvals are missing.

Create `task-preview` before Gate 3 with `candidate_id`, `script_version`, `keyframe_prompt_version`, `keyframe_path`, `keyframe_version`, `h3_prompt_version`, `workspace_id`, `mode`, `duration_seconds`, `aspect_ratio`, `quality`, `execution_backend`, and a new `idempotency_key` UUID. After approval and upload, build the final Console `request` with the returned asset ID while preserving every approved setting and the same idempotency key. Run `validate-request` on the recorded request; submission requires a successful validation bound to the current candidate, approval intent, and exact artifact versions.

Returning from `failed` to `task_review` clears the active task identity but preserves versioned history. An explicit retry must create a new task-preview and idempotency key, obtain a new Gate 3 approval, validate a new request, and record a task result bound to that approval before advancing.

Editing `ad-brief.md`, changing source-image bytes, or adding/removing a replacement keyframe invalidates unapproved review-stage resume and starts a new script batch. Before Gate 1 approval, this must not create keyframe prompts or images. A Gate 3-approved `task_review` and already submitted, monitoring, or failed task runs remain resumable so external task identity and the locked idempotency key are not lost.

New runs use `schema_version: 2`. Existing schema v1 states keep the legacy rule in which Gate 1 locks one script plus one keyframe prompt; do not migrate or rewrite their artifacts while resuming them.

## Choice controls

Prefer no more than three options per choice card. When controls are unavailable, accept the exact text commands directly and explain their effects in one short sentence.

- Gate 1: `确认5个脚本` / `修改事实或重做` / `取消`
- Gate 1 submenu: `同配置重做` / `编辑 ad-brief.md 后重载` / `更换根目录图片后重载`
- Gate 2 selection: `选1` through `选5`; paginate controls when necessary, but accept all five text commands.
- Gate 2 revisions: `重做N号` / `加载 approved-keyframe.* 到 N 号` / `返回脚本` / `取消`
- Gate 3: `确认提交` / `返回修改` / `取消`
- Gate 3 submenu: `返回脚本` / `返回关键帧`

Do not offer an open-ended revision prompt. If the host automatically exposes an “Other” field, do not rely on it; direct the user to edit `ad-brief.md` or replace local images.

## Final H3 contract

- Use mode `i2v` with exactly the selected candidate's approved keyframe as `first_frame`.
- Start the prompt with: `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`
- Follow with `integrated_multimodal_description`, `overall_soundscape`, and `non_diegetic_music` in that order.
- Cover the complete configured duration with strictly increasing cut times.
- Preserve dialogue language and verified claims from the approved script.
- Validate the request with the console Skill's validator before submission.
