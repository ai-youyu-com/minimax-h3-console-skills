---
name: minimax-h3-console-video-generator
description: 通过 minimax-h3-console MCP 生成、提交、检查、重试、取消和跟踪 MiniMax H3 视频任务。当用户希望根据提示词和本地参考图片创建 H3 T2V、I2V，尤其是多参考图 R2V 视频时使用；如果用户只需要编写提示词，而不需要提交到控制台或管理任务，则不要启用。
---

# MiniMax H3 Console 视频生成器

将 `minimax_h3_console` MCP 作为工作区、上传素材、任务提交和任务状态的唯一可信数据源。

## 检查 MCP 可用性

执行任何控制台操作前，确认当前项目中可以使用 `minimax_h3_console` MCP。如果不可用，不要尝试上传、提交、查询状态、重试或取消。提示用户：

1. 打开 [MiniMax H3 Console MCP 设置](https://minimax.beetag.cc/settings/mcp)。
2. 创建 MCP Token。
3. 复制生成的 MCP 链接并粘贴到当前对话，以便为当前项目安装 MCP。

给出上述说明后，暂停控制台工作流，直到用户提供 MCP 链接并完成安装。

## 判断请求类型

- 用户要求生成或提交视频，表示授权在输入校验通过后创建一个符合其意图的视频任务。
- 用户只要求审阅或编写提示词，并不表示授权提交任务。
- 用户要求查询进度时，只能调用 `get_task_details`，除非用户同时要求重试或取消。
- 当视听提示词需要编写或大幅调整时，先使用 `h3-prompt-writing`。保留其时间轴、镜头、对白、声景和音乐结构，仅调整控制台要求的素材引用语法。

上传素材、提交任务、重试或取消前，阅读 [references/console-workflow.md](references/console-workflow.md)。如果只查询状态，可直接调用 `get_task_details`。

## 提交流程

1. 确定目标工作区。优先复用用户或当前项目已明确的工作区 ID；只有在工作区未知或有歧义时才调用 `list_workspaces`。
2. 根据用户请求确定 `mode`、时长、画幅比例、质量和参考素材角色。保留用户明确指定的设置；只有在不会实质改变预期结果时才做保守假设。
3. 对每张本地图片计算 SHA-256、字节大小和内容类型。上传前使用 `scripts/asset_cache.py` 查询素材缓存。
4. 对缓存未命中的图片依次调用 `upload_image(prepare)`、向预签名地址执行 HTTP PUT、再调用 `upload_image(complete)`。相互独立的图片可并行处理。只使用状态为 `ready` 的素材。
5. 调整提示词中的素材引用并组装任务请求。R2V 模式下，每个素材都使用 `reference_image`；每个 `mention_name` 必须唯一且不包含 `@`，提示词中则使用 `@mention_name` 引用。
6. 将组装后的请求临时保存为 JSON，并运行 `scripts/validate_request.py REQUEST.json`。修复全部错误后才能创建任务。
7. 每个新的生成意图都使用新的 UUID。只有在上一次提交结果不确定、且要重试完全相同的 `create_video_task` 请求时，才能复用原 `idempotency_key`。
8. 只调用一次 `create_video_task`。随后立即调用 `get_task_details`，确认实际设置、输入、状态、错误信息和可用的 `video_url`。
9. 返回任务编号、状态、任务链接，以及可用时的视频链接。任务进入 `queued` 即表示提交成功；不要因为任务尚未被执行端领取而重复创建。

## 操作规则

- 不要在面向用户的输出中暴露预签名上传 URL。
- 将稳定的文件身份信息放在上传元数据中，将任务特定的素材语义放在 `reference_description` 中，以支持素材复用并避免哈希与元数据冲突。
- 重试同一请求时，不要更改质量、时长、模式、提示词内容、素材映射或目标机器。
- 任务明确失败后，不要自动创建替代任务。先检查错误；如果修正会实质改变用户请求，应向用户说明或征求意见。
- 只有在任务失败且重试属于用户授权范围时才使用 `retry_task`。只有用户明确要求取消且任务仍可取消时才使用 `cancel_task`。
- 当任务成功、失败或取消时停止监控。成功后，返回 `get_task_details` 提供的最终签名链接或稳定视频链接。
