# Audit Mode Workflow Contract

This contract applies only when the user explicitly requests Audit Mode or when resuming an existing schema v1-v4 audit run. New ordinary ad-video requests use the speed-first Fast Mode in `SKILL.md` and do not load or execute this contract.

## Delegation

The root conversation is orchestration-only. Give each child the absolute project/run paths, current stage, exact responsibility, required versions, and relevant Skill paths. Children record artifacts before returning display-ready results.

| Child | Responsibility | Required return |
|---|---|---|
| Intake/state | Inspect, ingest/discover, record feedback, begin revisions, and perform state transitions | Project/run paths, stage, validation summary |
| Script | Follow `5-scripts`; record five candidates and one selected Final Script | Versions/paths and display-ready tables |
| Script lock | Publish and lock the explicitly confirmed script | Script revision, candidate, lock ID |
| Visual | Follow `aggregate-keyframe-generation`; record asset roles, reference decision, scale evidence, panels, and image prompt | Versions/paths and display-ready visual plan |
| Image | Generate exactly one vertical chronological aggregate Storyboard | Image path/version and preview |
| Storyboard assembler/lock | Publish an immutable package and record confirmation | Revision/hash/path and lock ID |
| H3 | Write and validate Ref2VA prompt plus R2V preview | Sanitized prompt/settings and lock binding |
| Submission/monitor | Upload references, validate, create one task, and monitor it | Sanitized status/errors/final links |

## Client-Facing Review Output

After a production child finishes a review-stage deliverable, the root presents the detailed, sanitized tables returned by that child in its next client-facing reply. Artifact paths and concise recommendations are supplementary; they never replace the tables. Do not reduce complete child output to an overview, selected highlights, or a prose summary.

If the required table is missing, truncated, or contains placeholders such as “see artifact,” the root must re-dispatch the responsible child to render it from the recorded artifact. The root does not reconstruct production content itself. Ask for selection, feedback, or confirmation only after the complete tables are visible in chat.

### Script Review

Present all five candidates, in candidate order. For each candidate, include:

1. A metadata table covering candidate ID, plan name, creative idea, hook, and verified source mapping.
2. A timeline table with one row per recorded timeline entry and exactly these content columns: `时间`, `画面`, `旁白`, `字幕`, `CTA`.

Do not merge timeline rows, omit empty-looking but recorded fields, replace content with ellipses, or present only the recommended candidate. After all five detailed candidates, the root may add a short comparison/recommendation and then request an explicit choice or revision.

### Storyboard Review

Present tables for visual requirements, product-reference decision, asset roles, identity/scale evidence, and every chronological Storyboard panel. The panel table includes sequence/time, composition/action, referenced assets or roles, on-screen text, and continuity notes. Show the aggregate Storyboard preview in addition to these tables when available.

### Production Preview and Result

Before authorized submission, present sanitized tables for prompt/settings, every reference asset and `@mention_name` binding, validation status, and the exact non-secret task parameters. Monitoring and terminal-result replies present task identity, status, errors or output links, and relevant recorded versions in a table. Never expose secrets, tokens, upload headers, or presigned URLs.

## Schema v4 Artifacts

All versions are append-only. Do not store secrets, tokens, presigned URLs, or upload headers.

- `script-proposal`: JSON with candidates 1–5. Each has `candidate_id`, `plan_name`, `creative_idea`, `hook`, `source_mapping`, and non-empty `timeline` rows containing `time`, `visual`, `voiceover`, `subtitle`, and `cta`.
- `script-package`: generated only by `finalize-script-proposal`; publishes `scripts/VNN/` atomically.
- `final-script`: one selected/revised script with `source_candidate_id`, `plan_name`, `creative_idea`, `hook`, `source_mapping`, and the same timeline row contract. Recording binds the exact script package version and SHA-256; `lock-script` rejects a Final Script from another proposal revision.
- `script-lock`: generated only by `lock-script`; binds the package, candidate, Final Script hash, confirmation audit, and `Script = LOCKED`.
- `visual-plan`: JSON with `visual_requirements`, `product_reference_decision`, `asset_roles`, `product_identity_sources`, `scale_reference`, and `storyboard`. Asset roles are Box/Sachet/Bottle Master, Scale Reference, Logo/Text Master, or Scene Reference. Product identity sources may reference only Box/Sachet/Bottle Master entries. Missing scale sets `precise_scale_claimed: false` and includes a post-production recommendation.
- `aggregate-keyframe-prompt` and `aggregate-keyframe`: bound to the current script lock; the image binds the prompt version.
- `storyboard-package`: generated only by `finalize-storyboard`; publishes `storyboards/VNN/` atomically and binds the script lock, visual plan, prompt, and image.
- `storyboard-lock`: generated only by `lock-storyboard`; binds the package and sanitized audit with `create_task_authorized: true`.
- `h3-prompt`, `h3-validation`, `task-preview`, `production-package`: bound to the Storyboard lock.
- `asset-upload`: one JSON record per reference with `asset_id`, `storyboard_lock_id`, `source_sha256`, `source_filename`, `asset_role`, `mention_name`, and `reference_description`.
- `request`, `request-validation`, `task-result`, `retry-authorization`: exact submission and retry evidence.

## CLI

```text
record RUN_DIR --kind script-proposal|final-script|visual-plan|aggregate-keyframe-prompt|aggregate-keyframe|h3-prompt|task-preview|asset-upload|request|task-result --source PATH
finalize-script-proposal RUN_DIR --script-version V [--base-revision N]
lock-script RUN_DIR --script-proposal-version N --candidate-id 1..5 --final-script-version V --approval-json PATH
record-feedback RUN_DIR --phase script|storyboard --base-revision N --source JSON
begin-revision RUN_DIR --phase script|storyboard --base-revision N --feedback-version V
finalize-storyboard RUN_DIR --visual-plan-version V --keyframe-prompt-version V --keyframe-version V [--base-revision N]
lock-storyboard RUN_DIR --storyboard-version N --approval-json PATH
validate-h3-prompt PROMPT --duration N --run-dir RUN_DIR
finalize-production RUN_DIR
validate-request REQUEST --run-dir RUN_DIR
authorize-retry RUN_DIR --approval-json PATH
```

Script approval JSON contains `raw_reply`, `confirmed_at`, `channel`, `script_revision`, and `candidate_id`. Storyboard approval contains `raw_reply`, `confirmed_at`, `channel`, `storyboard_revision`, and `create_task_authorized: true`. Retry approval contains the first three audit fields plus `retry_authorized: true`.

## Revisions and Locks

- Script feedback binds the exact base script package. A new script lock supersedes the current downstream working context without changing historical locks or submitted evidence.
- Storyboard feedback binds the exact base Storyboard package. If `affects_visuals: true`, the aggregate image hash must change. Reuse is allowed only for non-visual metadata feedback and records the reason.
- Any new task after changed script or Storyboard content requires a new Storyboard lock and authorization.
- `authorize-retry` is valid only after explicit task failure and returns to `storyboard_locked`; it never changes the approved creative artifacts.

## Ref2VA/R2V Contract

The final H3 prompt uses these sections in order: `subject_definitions`, `summary`, `retention_analysis`, `detailed_description`, `overall_soundscape`, `non_diegetic_music`.

The R2V task preview contains `reference_assets`, each with `source_sha256`, `source_filename`, canonical `asset_role`, unique `mention_name` without `@`, and `reference_description`. The aggregate image uses `source_filename: aggregate-storyboard` and `asset_role: Aggregate Storyboard`. Client assets must match the ingested filename/hash and the role recorded in `visual-plan`; product masters must also appear in `product_identity_sources`. The prompt uses every declared `@mention_name` and contains no `<Picture N>`.

The Console request uses `mode: r2v`; every asset uses `role: reference_image`. Request validation binds every asset ID to matching upload evidence and rejects missing, unused, duplicate, or unresolved references.

Every newly authorized production intent uses an idempotency UUID that has never appeared in an earlier production package. Retrying an uncertain submission reuses the already-recorded exact request directly; it does not finalize another production package.

## Compatibility

New runs use schema v4. Schema v1–v3 runs keep their recorded stages, commands, I2V/proposal contracts, and artifact interpretation. Never rewrite or migrate their state files.
