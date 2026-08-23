# 项目 Agent 说明

## minimax-h3-console：R2V 多参考图任务

使用项目中的 `h3-prompt-writing` Skill 编写提示词时，需要区分 Skill 的语义格式与 `minimax-h3-console` MCP 实际接受的素材引用格式。

### 已知问题

- `r2v` 模式不接受 `first_frame` 或 `last_frame` 素材角色；所有参考图片都必须使用 `reference_image`。
- 不要在提交给 `minimax-h3-console` 的 R2V 提示词中直接使用 `<Picture 1>`、`<Picture 2>` 等 Skill 文档标签来引用 MCP 素材。这会触发 `Unknown mentions` 校验错误。
- `mention_name` 是素材名称本身，不要包含 `@`。例如设置为 `图片1`，并在提示词正文中使用 `@图片1`。
- 多张参考图必须拥有互不重复的 `mention_name`，而且提示词中的每个 `@名称` 必须与对应素材的 `mention_name` 完全一致。

### 正确示例

```json
{
  "mode": "r2v",
  "assets": [
    {
      "asset_id": "...",
      "role": "reference_image",
      "mention_name": "图片1"
    },
    {
      "asset_id": "...",
      "role": "reference_image",
      "mention_name": "图片2"
    }
  ],
  "prompt": "镜头从 @图片1 的室外入口向内推进，然后切换到 @图片2 展示工人工作。"
}
```

### 错误示例

```json
{
  "mode": "r2v",
  "assets": [
    {
      "asset_id": "...",
      "role": "first_frame",
      "mention_name": "Picture 1"
    }
  ],
  "prompt": "从 <Picture 1> 推进，并展示 <Picture 2>。"
}
```

### 提交前检查

1. 先通过 `upload_image(prepare)` 获取预签名地址，再用 HTTP PUT 上传，最后调用 `upload_image(complete)`；只有状态为 `ready` 的素材才能提交。
2. 确认任务模式为 `r2v`，每张图片的角色均为 `reference_image`。
3. 确认所有提示词素材引用均使用 `@mention_name`，没有遗留 `<Picture N>` 标签。
4. 确认每个 `@mention_name` 都能在 `assets` 中找到完全匹配的定义。
5. 每个新的生成意图使用新的 UUID 作为 `idempotency_key`；只有重试完全相同的请求时才复用原键。
6. `create_video_task` 成功后，用 `get_task_details` 检查状态、错误信息和最终 `video_url`。

### Skill 适配原则

继续遵循 `h3-prompt-writing` Skill 对时间轴、镜头、声音和旁白的结构要求；仅在提交 MCP 时，把 Skill 中的 `<Picture N>` 语义引用转换成控制台支持的 `@mention_name` 格式，不要丢失各参考图的镜头职责和保留要求。
