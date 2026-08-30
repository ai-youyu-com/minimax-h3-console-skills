# Workflow Contract

## Delegation

The root conversation is an orchestrator only. All filesystem, artifact, image, prompt, validation, submission, and monitoring work belongs to bounded child agents.

| Child | Responsibility | Required return |
|---|---|---|
| Intake/state | inspect and ingest/discover; record feedback; begin revisions; perform state transitions | project/run paths, stage, validation summary |
| Script | record one five-candidate script JSON | artifact version/path and display-ready script table |
| Dimension | record dimension JSON and reference image | status, source disclosure, versions/paths, preview |
| Aggregate keyframe | record one package-level prompt and one image | versions/paths and preview |
| Proposal assembler | validate components and atomically publish VNN | package revision/hash/path and display-ready proposal |
| Lock | record exact client confirmation and authorization | lock ID, proposal revision/hash, candidate ID |
| H3 | write/validate prompt and preview; finalize production package | complete sanitized prompt/settings and package binding |
| Submission/monitor | upload, validate, create one task, and monitor recorded identity | sanitized task status/errors/final links |

Give each child absolute project/run paths, its exact bounded responsibility, current stage, required artifact versions, and relevant Skill/reference paths. Children record artifacts before returning. The root does not read files to rebuild the returned display payload and never fills in a failed child assignment.

## Schema and artifacts

New runs use `schema_version: 3`; schema v1/v2 runs retain their old stages, approvals, and candidate-scoped artifacts without migration.

Record source artifacts with `record`; versions are append-only:

| Kind | Contract |
|---|---|
| `script` | JSON with verified facts and exactly candidates 1–5 |
| `dimension-reference` | JSON with `status: provided|missing`; missing has no measurements, `not_to_scale: true`, and the exact display disclaimer |
| `dimension-reference-image` | visual dimension reference; missing state says `尺寸未提供 / 非按比例` |
| `aggregate-keyframe-prompt` | prompt for the one package-level keyframe |
| `aggregate-keyframe` | one borderless blended image for the whole proposal |
| `client-feedback` | generated only by `record-feedback`; raw reply plus structured impact |
| `proposal-package` | generated only by `finalize-proposal`; immutable package manifest |
| `h3-prompt`, `h3-validation`, `task-preview` | locked-proposal H3 preparation |
| `production-package` | generated only by `finalize-production` |
| `request`, `request-validation`, `task-result` | exact submission evidence and sanitized result |
| `asset-upload` | uploaded asset UUID bound to proposal lock and aggregate-keyframe source SHA-256 |
| `retry-authorization` | generated only by `authorize-retry`; append-only explicit retry audit |

Never store secrets, tokens, presigned URLs, or upload headers.

Each `proposals/VNN/` deliverable contains `proposal.md`, `dimension-reference.json`, its reference image, one aggregate keyframe, and `manifest.json`. The manifest binds parent revision, feedback version, source manifest hash, every component version/path/hash, missing-dimension status, and explicit keyframe reuse reason when applicable. Publishing is atomic; existing package directories and earlier run-level manifests are never overwritten.

## CLI

```text
record-feedback RUN_DIR --proposal-version N --source JSON
begin-revision RUN_DIR --base-revision N --feedback-version V
finalize-proposal RUN_DIR --script-version V --dimension-version V --dimension-image-version V --keyframe-version V [--base-revision N]
lock-proposal RUN_DIR --proposal-version N --candidate-id N --approval-json PATH
finalize-production RUN_DIR
authorize-retry RUN_DIR --approval-json PATH
```

Use `record RUN_DIR --kind KIND --source PATH` for ordinary artifacts, `validate-h3-prompt ... --run-dir RUN_DIR` for prompt validation, `validate-request REQUEST --run-dir RUN_DIR` for final request binding, and compare-and-set `set-stage` for permitted transitions.

`finalize-proposal` is idempotent for the same parent, feedback, and component hashes. A changed package increments the revision. Revision publishing requires bound client feedback. If `affects_visuals: true`, the aggregate keyframe version must change. Pure text feedback may reuse it and records why.

## Proposal lock and production binding

`lock-proposal` requires candidate 1–5 and audit JSON with:

```json
{
  "raw_reply": "确认 V2，选 3，直接生成一个视频",
  "confirmed_at": "2026-08-30T10:05:00+08:00",
  "channel": "chat",
  "client_name": "optional",
  "proposal_revision": 2,
  "candidate_id": "3",
  "create_task_authorized": true
}
```

The immutable lock binds a UUID lock ID, proposal revision/version/SHA-256, selected candidate, and sanitized audit. Locking moves `proposal_review → proposal_locked` and is the only client authority needed for H3 preparation plus one task creation.

The task preview and production package must bind `proposal_lock_id`, `proposal_revision`, `proposal_package_sha256`, `candidate_id`, `h3_prompt_version`, settings, and idempotency UUID. `finalize-production` verifies the H3 validation and moves to `production_ready`. Request validation additionally records `production_package_version` and rejects any prompt, setting, idempotency, or proposal mismatch.

Before validating the request, the submission child records `asset-upload` JSON with `asset_id`, `proposal_lock_id`, and the locked aggregate keyframe's `source_sha256`; request validation requires the `first_frame` asset ID to match this evidence. The child preserves the same request and idempotency key for uncertain retries. After an explicit failure, no child retries automatically. `authorize-retry` requires raw reply, confirmation time, channel, and `retry_authorized: true`; it creates append-only evidence and requires a new preview/production package and new idempotency UUID before one new attempt.

## State transitions

```text
proposal_review -> proposal_locked -> production_ready -> submitted -> monitoring
       ^                  |                |                         |-> succeeded
       +------------------+----------------+                         |-> failed
failed --explicit retry--> proposal_locked
any pre-terminal review/production stage --------------------------> cancelled
```

New feedback after locking or submission starts a new proposal revision and later a new lock. It never edits the earlier lock, production package, request, or task evidence.

## H3 contract

- Use `i2v` with the locked package aggregate keyframe as the only `first_frame`.
- Start with `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`
- Include `integrated_multimodal_description`, `overall_soundscape`, and `non_diegetic_music` in that order.
- Use the selected locked script, strictly increasing cut times, verified claims, and configured duration.
- Validate with the Console validator before task creation.
