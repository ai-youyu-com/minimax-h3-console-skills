---
name: minimax-h3-console-video-generator
description: Generate, submit, inspect, retry, cancel, and follow MiniMax H3 video tasks through the minimax-h3-console MCP. Use when a user wants an H3 T2V, I2V, or especially multi-reference R2V video created from prompts and local reference images; do not activate for prompt writing alone unless console submission or task management is also requested.
---

# MiniMax H3 Console Video Generator

Use the `minimax_h3_console` MCP as the system of record for workspaces, uploaded assets, task submission, and task status.

## MCP availability

Before handling any console operation, confirm that the `minimax_h3_console` MCP is available in the current project. If it is unavailable, do not attempt uploads, submissions, status checks, retries, or cancellations. Tell the user to:

1. Open [MiniMax H3 Console MCP settings](https://minimax.beetag.cc/settings/mcp).
2. Create an MCP token.
3. Copy the generated MCP link and paste it into the current conversation so it can be installed in the current project.

After giving these instructions, stop the console workflow until the user provides the MCP link and the MCP has been installed.

## Route the request

- A request to generate or submit a video authorizes creation of one intended video task after its inputs pass validation.
- A request to review or write a prompt does not authorize task submission.
- A request to check progress authorizes only `get_task_details` unless the user also asks to retry or cancel.
- Use `h3-prompt-writing` first when the audiovisual prompt must be written or materially adapted. Keep its timing, shot, dialogue, soundscape, and music structure, then adapt only the asset-reference syntax required by the console.

Read [references/console-workflow.md](references/console-workflow.md) before uploading assets, submitting a task, retrying, or cancelling. For a status-only lookup, go directly to `get_task_details`.

## Submission workflow

1. Resolve the intended workspace. Reuse a workspace ID already established by the user or current project; call `list_workspaces` only when it is unknown or ambiguous.
2. Determine `mode`, duration, aspect ratio, quality, and reference roles from the user's request. Preserve explicit settings. Make conservative assumptions only when they do not materially change the intended output.
3. For each local image, compute SHA-256, byte size, and content type. Check the asset cache with `scripts/asset_cache.py` before uploading.
4. Upload cache misses through `upload_image(prepare)`, presigned HTTP PUT, and `upload_image(complete)`. Process independent images concurrently. Only use assets whose status is `ready`.
5. Adapt prompt references and assemble the task request. In R2V, every asset uses `reference_image`; each unique `mention_name` excludes `@`, while the prompt refers to it as `@mention_name`.
6. Save the assembled request as JSON temporarily and run `scripts/validate_request.py REQUEST.json`. Fix every reported error before creating the task.
7. Generate a new UUID for each new generation intent. Reuse an idempotency key only when retrying the exact same `create_video_task` request after an uncertain submission outcome.
8. Call `create_video_task` once. Immediately call `get_task_details` to confirm effective settings, inputs, status, errors, and any available `video_url`.
9. Report the task number, status, task URL, and video URL when available. A queued task is successfully submitted; do not create a duplicate merely because it has not yet been leased.

## Operational rules

- Never expose presigned upload URLs in user-facing output.
- Put stable file identity in upload metadata and task-specific semantics in `reference_description`. This enables reuse and prevents hash/metadata conflicts.
- Do not change quality, duration, mode, prompt content, reference mapping, or target machine while retrying an identical request.
- Do not automatically create a replacement task after a definitive failure. Inspect the error and ask or explain when correction would materially alter the request.
- Use `retry_task` only for a failed task when retrying is within the user's request. Use `cancel_task` only when the user asks to cancel and the task is still eligible.
- Stop monitoring when the task succeeds, fails, or is cancelled. On success, return the final signed or stable video link from `get_task_details`.
