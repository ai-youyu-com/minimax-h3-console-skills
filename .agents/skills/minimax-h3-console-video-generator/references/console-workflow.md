# MiniMax H3 Console MCP 工作流

创建任务或执行其他会改变控制台状态的操作前，阅读本参考文档。

## 可用操作

- `list_workspaces`：仅在工作区 ID 未知时确定可用工作区。
- `upload_image`：准备并完成图片上传。
- `create_video_task`：向本地后端提交 T2V、I2V 或 R2V 生成任务。
- `get_task_details`：验证提交结果，并获取事件、错误、输出和视频链接。
- `retry_task`：重试符合条件的失败任务。
- `cancel_task`：取消符合条件的排队任务。

需要时查询工具的实时 schema；不要假设可调用 MCP 契约之外的字段。

## 素材缓存与确定性元数据

缓存键为 `workspace_id + sha256`。准备上传前先查询缓存：

```bash
python3 "<skill-directory>/scripts/asset_cache.py" lookup \
  --workspace-id WORKSPACE_UUID \
  --sha256 IMAGE_SHA256
```

缓存未命中时，使用在不同任务间保持不变的元数据：

- filename：`asset-<first-12-sha-chars>.<extension>`
- name：`asset-<first-12-sha-chars>`
- description：省略
- content type：文件真实的 MIME 类型

不要使用 `图片1` 之类的序号名称作为上传元数据。序号名称属于任务中的 `mention_name`；特定镜头语义属于 `reference_description`。

对每张未缓存的图片执行以下操作：

1. 使用确定性元数据、SHA-256、文件大小和工作区 ID 调用 `upload_image(action="prepare")`。
2. 使用 HTTP PUT、返回的全部请求头和原始文件字节上传到预签名 URL。不要输出该 URL。
3. 使用返回的素材 ID 调用 `upload_image(action="complete")`。
4. 要求素材达到 `status: ready`，然后写入缓存：

```bash
python3 "<skill-directory>/scripts/asset_cache.py" put \
  --workspace-id WORKSPACE_UUID \
  --sha256 IMAGE_SHA256 \
  --asset-id ASSET_UUID \
  --content-type image/jpeg \
  --filename asset-0123456789ab.jpg
```

相互独立的图片上传流程可以并行执行，并设置适度的并发限制，通常同时处理四至六张图片。

如果 `prepare` 返回 `HASH_METADATA_MISMATCH`，先在缓存或当前对话中查找已知素材 ID。不要尝试不同的元数据值。如果无法找回现有登记记录，则根据用户提供的图片创建视觉无损的临时 PNG，重新计算哈希与大小，并使用确定性元数据上传这个新的字节版本。保持源文件不变。

如果创建任务时发现缓存素材缺失或不可用，则将其缓存记录失效并重新上传：

```bash
python3 "<skill-directory>/scripts/asset_cache.py" invalidate \
  --workspace-id WORKSPACE_UUID \
  --sha256 IMAGE_SHA256
```

## 提示词适配

`h3-prompt-writing` 使用 `<Picture 1>` 等语义标签，而 R2V 控制台会校验明确的任务素材引用。

对每张参考图片执行以下操作：

1. 分配一个任务级唯一 `mention_name`，例如 `图片1`，名称中不包含 `@`。
2. 在提示词中使用带 `@` 前缀的同名引用，例如 `@图片1`。
3. 根据明确的素材与镜头职责映射替换每个 `<Picture N>`，不要仅按照文件顺序盲目替换。
4. 保留参考图片承担的镜头职责和内容保留要求。
5. 确保 R2V 提交内容中不再残留任何 `<Picture N>` 标签。

`<Subject N>` 是提示词语义标签，可以保留，但不能替代 `@mention_name` 素材引用。

## R2V 任务契约

所有 R2V 图片都必须使用 `reference_image`，包括在语义上充当首帧或尾帧的图片。R2V 中不要提交 `first_frame` 或 `last_frame`。

```json
{
  "workspace_id": "WORKSPACE_UUID",
  "mode": "r2v",
  "assets": [
    {
      "asset_id": "ASSET_UUID_1",
      "role": "reference_image",
      "mention_name": "图片1",
      "reference_description": "雨天挡风玻璃视角的开场画面"
    },
    {
      "asset_id": "ASSET_UUID_2",
      "role": "reference_image",
      "mention_name": "图片2",
      "reference_description": "品牌代言人与产品身份"
    }
  ],
  "prompt": "开场沿用 @图片1 的画面，随后 @图片2 中的角色出现在车辆旁边。",
  "aspect_ratio": "9:16",
  "duration_seconds": 15,
  "quality": "high",
  "execution_backend": "local_machine",
  "idempotency_key": "NEW_UUID"
}
```

调用 `create_video_task` 前运行随 Skill 提供的校验脚本。它会拒绝重复或无法解析的素材引用、R2V 禁用角色、残留的 `<Picture N>` 标签、无效 UUID 和超出范围的时长。

## 提交与后续查询

`create_video_task` 成功后，同时保留 `task_id` 和 `workspace_id`。启用事件和签名 URL 后调用 `get_task_details`，并确认：

- 实际使用的模式、画幅比例、时长和质量；
- 输入素材数量符合预期；
- 当前状态与错误字段；
- 成功后返回的 `video_url` 或 `videos` 条目。

将 `queued`、`leased` 和 `postprocessing` 视为活动状态。任务处于活动状态时不要重复提交。用户查询进度时，使用现有任务 ID。任务明确失败时，先报告 `error_stage`、`error_type` 和 `error_message`，再判断是否适合在授权范围内重试。
