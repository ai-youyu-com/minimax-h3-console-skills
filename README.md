# MiniMax H3 Console Video Generator

这是一个 Agent Skill 仓库，主要提供 `minimax-h3-console-video-generator`：让 Codex、Claude Code、Cursor 等兼容 Agent Skills 的工具通过 `minimax_h3_console` MCP 上传参考图片、提交 MiniMax H3 视频任务，并查询最终生成结果。

MiniMax H3 的提示词规范和创作类 Skills 来源于 [MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills)。本仓库的 Console Skill 会配合其中的 `h3-prompt-writing` 使用，但不替代 MiniMax 官方 Skill。

## 功能

`minimax-h3-console-video-generator` 支持：

- 查询和选择 MiniMax H3 Console 工作区；
- 上传本地参考图片并复用已上传素材；
- 创建 T2V、I2V 和多参考图 R2V 视频任务；
- 校验提示词中的素材引用关系；
- 查询任务进度和最终视频链接；
- 重试失败任务或取消可取消的任务。

仓库还提供 `generate-client-ad-video`：用户既可以在项目目录中放置 `ad-brief.md` 和同级图片，也可以直接在对话中描述产品并上传图片。Skill 会把聊天信息和附件保存成标准本地项目，再通过三次固定选项确认完成广告脚本、聚合关键帧和 H3 视频任务。

生成视频时，建议先由官方 `h3-prompt-writing` Skill 按照 H3 规范组织时间轴、镜头、对白、环境声音和音乐，再由 Console Skill 将提示词与素材转换成 MCP 接受的任务格式。

在 R2V 模式中，所有图片都使用 `reference_image` 角色；每张图片拥有唯一的 `mention_name`，提示词通过 `@mention_name` 引用对应素材。

## 安装

### 1. 安装 Console 视频生成 Skill

在目标项目目录中执行：

```bash
npx skills add ai-youyu-com/minimax-h3-console-skills --skill minimax-h3-console-video-generator
```

`npx skills` 会检测当前环境中的 Agent，并询问安装目标。若要直接安装给 Codex：

```bash
npx skills add ai-youyu-com/minimax-h3-console-skills --skill minimax-h3-console-video-generator --agent codex
```

如果希望全局安装，使所有项目都能使用，可增加 `--global`：

```bash
npx skills add ai-youyu-com/minimax-h3-console-skills --skill minimax-h3-console-video-generator --agent codex --global
```

### 2. 安装 MiniMax 官方完整 Skill 集

推荐同时安装 MiniMax 官方仓库中的全部 Skills。它们不仅提供 `h3-prompt-writing` 提示词规范，还覆盖多种可直接辅助视频生成的创意策划、分镜设计和成片工作流：

- `h3-prompt-writing`：H3 提示词结构与多模态引用规范；
- `3d-animation-short-generator`：3D 动画短片；
- `brand-promo-video-generator`：品牌宣传视频；
- `co-op-game-intro-generator`：双人合作游戏开场；
- `handdrawn-live-video-generator`：手绘动画与实拍融合视频；
- `minimalist-product-ad-generator`：极简产品广告；
- `music-video-subtitle-generator`：音乐视频与歌词字幕；
- `paper-collage-explainer-generator`：纸张拼贴科普视频；
- `papercraft-stop-motion-explainer`：纸艺定格科普视频。

安装完整 Skill 集：

```bash
npx skills add MiniMax-AI/MiniMax-H3 --skill '*'
```

若要明确安装到 Codex：

```bash
npx skills add MiniMax-AI/MiniMax-H3 --skill '*' --agent codex
```

如果只需要 Console Skill 的核心提示词依赖，也可以仅安装 `h3-prompt-writing`：

```bash
npx skills add MiniMax-AI/MiniMax-H3 --skill h3-prompt-writing
```

若要安装文件驱动的客户广告工作流：

```bash
npx skills add ai-youyu-com/minimax-h3-console-skills --skill generate-client-ad-video
```

在任意项目子目录中放置以下文件后，调用 `$generate-client-ad-video`：

```text
client-project/
├── ad-brief.md
├── product.jpg
├── spokesperson.png
└── scene.webp
```

`ad-brief.md` 的字段模板位于该 Skill 的 `references/brief-template.md`。图片必须与描述文件同级；运行产物自动保存到项目的 `output/<run-id>/`。

也可以直接调用 `$generate-client-ad-video`，在同一条消息中描述产品、卖点和广告用途并上传图片。Skill 会自动创建不覆盖旧数据的项目子目录，将产品信息写入 `ad-brief.md`，将上传图片复制到同级目录，然后继续相同的确认流程。

可以通过以下命令查看官方仓库当前提供的完整列表，具体说明请参阅 [MiniMax H3 官方 Skills](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills)：

```bash
npx skills add MiniMax-AI/MiniMax-H3 --list
```

### 3. 安装 MiniMax H3 Console MCP

Skill 只提供 Agent 工作流，视频提交能力由 `minimax_h3_console` MCP 提供：

1. 打开 [MiniMax H3 Console MCP 设置](https://minimax.beetag.cc/settings/mcp)。
2. 创建 MCP Token。
3. 复制页面生成的 MCP 链接。
4. 将链接粘贴到 Agent 对话中，并要求 Agent 为当前项目安装 MCP。

如果当前项目找不到 `minimax_h3_console` MCP，Console Skill 会暂停视频任务，并提示先完成 MCP 安装。

## 生成视频

安装 Skill 与 MCP 后，向 Agent 提供视频需求、时长、画幅和参考图片。例如：

> 使用 `$minimax-h3-console-video-generator` 和这些参考图生成一段 9:16、10 秒的 R2V 视频。先用 `$h3-prompt-writing` 完善提示词，然后提交任务并在完成后返回视频链接。

典型流程如下：

1. 使用 `h3-prompt-writing` 编写符合 MiniMax H3 规范的提示词。
2. 检查 `minimax_h3_console` MCP 和目标工作区。
3. 上传参考图片，等待素材状态变为 `ready`。
4. 将提示词中的 `<Picture N>` 语义标签转换为 Console 的 `@mention_name` 引用。
5. 校验并创建视频任务。
6. 查询任务状态，成功后返回视频链接。

## 仓库结构

```text
skills/
├── generate-client-ad-video/
│   ├── SKILL.md
│   ├── agents/
│   ├── references/
│   └── scripts/
└── minimax-h3-console-video-generator/
    ├── SKILL.md
    ├── agents/
    ├── references/
    └── scripts/
```

根目录 `skills/` 是供 `npx skills` 发现和安装的发布目录。仓库中的 `.agents/skills/` 用于当前项目的开发与本地验证。
