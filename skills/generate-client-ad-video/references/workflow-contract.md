# Workflow Contract

## Artifact names

Record artifacts with `project_workflow.py record`; the command assigns monotonically increasing versions:

| Kind | Typical source | Stored name |
|---|---|---|
| `script` | approved or candidate Markdown package | `script-vNN.md` |
| `keyframe-prompt` | image-generation prompt | `keyframe-prompt-vNN.txt` |
| `keyframe` | generated or replacement image | `keyframe-vNN.<ext>` |
| `h3-prompt` | final I2VA prompt | `h3-prompt-vNN.txt` |
| `h3-validation` | successful validation bound to the prompt SHA-256 | `h3-validation-vNN.json` |
| `task-preview` | pre-upload logical configuration with locked idempotency key | `task-preview-vNN.json` |
| `request` | validated final Console request | `request-vNN.json` |
| `request-validation` | successful Console and approval-binding validation | `request-validation-vNN.json` |
| `task-result` | sanitized task details | `task-result-vNN.json` |

Never place secrets, upload headers, tokens, or presigned URLs in artifacts or state.

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

Record approvals with `approve --gate script|keyframe|task`. Each approval stores the exact selected artifact versions in `state.json`. The state CLI rejects forward transitions when required artifacts or approvals are missing.

Create `task-preview` before Gate 3 with `keyframe_path`, `keyframe_version`, `h3_prompt_version`, `workspace_id`, `mode`, `duration_seconds`, `aspect_ratio`, `quality`, `execution_backend`, and a new `idempotency_key` UUID. After approval and upload, build the final Console `request` with the returned asset ID while preserving every approved setting and the same idempotency key. Run `validate-request` on the recorded request; submission requires a successful validation bound to the current approval intent and exact approved artifact versions.

Returning from `failed` to `task_review` clears the active task identity but preserves versioned history. An explicit retry must create a new task-preview and idempotency key, obtain a new Gate 3 approval, validate a new request, and record a task result bound to that approval before advancing.

Editing `ad-brief.md`, changing source-image bytes, or adding/removing a replacement keyframe invalidates unapproved review-stage resume and starts a new run. A Gate 3-approved `task_review` and already submitted, monitoring, or failed task runs remain resumable so external task identity and the locked idempotency key are not lost.

## Choice controls

Use no more than three options per choice card.

- Gate 1: `确认脚本` / `修改或重做` / `取消`
- Gate 1 submenu: `同配置重做` / `编辑 ad-brief.md 后重载` / `更换根目录图片后重载`
- Gate 2: `确认关键帧` / `修改或替换` / `取消`
- Gate 2 submenu: `同配置重新生成` / `加载 approved-keyframe.*` / `返回脚本`
- Gate 3: `确认提交` / `返回修改` / `取消`
- Gate 3 submenu: `返回脚本` / `返回关键帧`

Do not offer an open-ended revision prompt. If the host automatically exposes an “Other” field, do not rely on it; direct the user to edit `ad-brief.md` or replace local images.

## Final H3 contract

- Use mode `i2v` with exactly one approved keyframe as `first_frame`.
- Start the prompt with: `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`
- Follow with `integrated_multimodal_description`, `overall_soundscape`, and `non_diegetic_music` in that order.
- Cover the complete configured duration with strictly increasing cut times.
- Preserve dialogue language and verified claims from the approved script.
- Validate the request with the console Skill's validator before submission.
