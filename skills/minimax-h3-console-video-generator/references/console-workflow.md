# MiniMax H3 Console MCP Workflow

Read this reference for task creation or other state-changing console operations.

## Available operations

- `list_workspaces`: resolve an active workspace only when its ID is not already known.
- `upload_image`: prepare and complete image uploads.
- `create_video_task`: submit T2V, I2V, or R2V generation to the local backend.
- `get_task_details`: verify submission and obtain events, errors, outputs, and video URLs.
- `retry_task`: retry an eligible failed task.
- `cancel_task`: cancel an eligible queued task.

Discover the live tool schema when necessary; do not assume fields beyond the callable MCP contract.

## Asset cache and deterministic metadata

The cache key is `workspace_id + sha256`. Query it before preparing an upload:

```bash
python3 "<skill-directory>/scripts/asset_cache.py" lookup \
  --workspace-id WORKSPACE_UUID \
  --sha256 IMAGE_SHA256
```

On a cache miss, use metadata that stays the same across tasks:

- filename: `asset-<first-12-sha-chars>.<extension>`
- name: `asset-<first-12-sha-chars>`
- description: omit it
- content type: the file's real MIME type

Do not use ordinal names such as `图片1` as upload metadata. Ordinals belong in the task's `mention_name`; shot-specific meaning belongs in `reference_description`.

For each uncached image:

1. Call `upload_image(action="prepare")` with the deterministic metadata, SHA-256, size, and workspace ID.
2. Upload the exact file bytes to the returned presigned URL with HTTP PUT and every returned header. Do not print the URL.
3. Call `upload_image(action="complete")` with the returned asset ID.
4. Require `status: ready`, then cache the asset:

```bash
python3 "<skill-directory>/scripts/asset_cache.py" put \
  --workspace-id WORKSPACE_UUID \
  --sha256 IMAGE_SHA256 \
  --asset-id ASSET_UUID \
  --content-type image/jpeg \
  --filename asset-0123456789ab.jpg
```

Run independent image pipelines concurrently with a modest limit, normally four to six uploads.

If `prepare` returns `HASH_METADATA_MISMATCH`, first look for a known asset ID in the cache or current conversation. Do not probe different metadata values. If the existing registration cannot be recovered, create a visually lossless temporary PNG from the user-provided image, recompute its hash and size, and upload that new byte representation with deterministic metadata. Keep the source file unchanged.

If task creation rejects a cached asset as missing or unusable, invalidate it and perform a fresh upload:

```bash
python3 "<skill-directory>/scripts/asset_cache.py" invalidate \
  --workspace-id WORKSPACE_UUID \
  --sha256 IMAGE_SHA256
```

## Prompt adaptation

`h3-prompt-writing` uses semantic labels such as `<Picture 1>`. The R2V console instead validates explicit task mentions.

For every referenced image:

1. Assign a unique task-level `mention_name`, such as `图片1`, without `@`.
2. Use the same name in the prompt with an `@` prefix, such as `@图片1`.
3. Replace every semantic `<Picture N>` occurrence according to an explicit asset-to-role mapping, not blindly according to file order.
4. Preserve the referenced image's shot responsibilities and retention requirements.
5. Ensure no `<Picture N>` label remains in an R2V submission.

`<Subject N>` labels are prompt semantics and may remain. They do not replace `@mention_name` references.

## R2V task contract

All R2V images must use `reference_image`, including images that semantically depict an opening or closing frame. Do not send `first_frame` or `last_frame` in R2V.

```json
{
  "workspace_id": "WORKSPACE_UUID",
  "mode": "r2v",
  "assets": [
    {
      "asset_id": "ASSET_UUID_1",
      "role": "reference_image",
      "mention_name": "图片1",
      "reference_description": "Opening rainy windshield viewpoint"
    },
    {
      "asset_id": "ASSET_UUID_2",
      "role": "reference_image",
      "mention_name": "图片2",
      "reference_description": "Brand ambassador and product identity"
    }
  ],
  "prompt": "The opening follows @图片1, then @图片2 enters beside the car.",
  "aspect_ratio": "9:16",
  "duration_seconds": 15,
  "quality": "high",
  "execution_backend": "local_machine",
  "idempotency_key": "NEW_UUID"
}
```

Run the bundled validator before calling `create_video_task`. It rejects duplicate or unresolved mentions, forbidden R2V roles, leftover `<Picture N>` labels, invalid UUIDs, and out-of-range duration.

## Submission and follow-up

After `create_video_task` succeeds, retain both `task_id` and `workspace_id`. Call `get_task_details` with events and signed URLs enabled. Confirm:

- effective mode, aspect ratio, duration, and quality;
- expected input count;
- current status and error fields;
- `video_url` or entries in `videos` after success.

Treat `queued`, `leased`, and `postprocessing` as active states. Do not submit duplicates while active. For progress requests, query the existing task ID. For a definitive failure, report `error_stage`, `error_type`, and `error_message` before deciding whether an authorized retry is appropriate.
