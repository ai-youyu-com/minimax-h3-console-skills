# 项目 Agent 说明

本项目通过 `h3-prompt-writing` 编写 MiniMax H3 提示词，并通过
`minimax-h3-console-video-generator` 提交和管理视频任务。

执行 H3 视频任务前，必须遵循：

- `.agents/skills/h3-prompt-writing/SKILL.md`
- `.agents/skills/minimax-h3-console-video-generator/SKILL.md`
- `.agents/skills/minimax-h3-console-video-generator/references/console-workflow.md`

## R2V 格式转换

`h3-prompt-writing` 中的 `<Picture N>` 是提示词语义标签，不是
`minimax-h3-console` MCP 的实际素材引用格式。提交 R2V 任务时：

- 所有图片素材都使用 `role: "reference_image"`，不能使用
  `first_frame` 或 `last_frame`。
- 为每张图片设置唯一的 `mention_name`，名称本身不包含 `@`。
- 提示词中使用对应的 `@mention_name`，并确保每个引用都能在
  `assets` 中找到完全匹配的定义。
- 提交前不能遗留 `<Picture N>` 引用。

不要向用户输出预签名上传 URL、Token 或其他敏感信息。
