# MiniMax H3 Skills

这是一个面向 AI Agent 的 Skill 仓库，提供 MiniMax H3 视频提示词编写规范，以及通过 `minimax_h3_console` MCP 上传参考素材、创建视频任务和跟踪生成结果的完整工作流。

## 核心 Skills

仓库以以下两个基础 Skill 为核心，同时包含 3D 动画、品牌宣传、极简产品广告、音乐视频字幕、纸艺科普等场景化视频工作流 Skill。

### `h3-prompt-writing`

用于编写和改写 MiniMax H3 视频生成提示词，支持：

- T2VA：纯文本生成音视频；
- I2VA：以首帧图片开始生成；
- FL2VA：在首帧与尾帧之间生成连续视频；
- L2VA：生成并收束到指定尾帧；
- Ref2VA：使用图片、视频或音频作为完整参考。

Skill 会规范时间轴、镜头、主体、动作、对白、环境声音和非叙事音乐，并保持 `<Picture 1>`、`<Video 1>`、`<Audio 1>` 等素材标签一致。

### `minimax-h3-console-video-generator`

用于通过 `minimax_h3_console` MCP 执行 MiniMax H3 视频任务，包括：

- 查询和选择工作区；
- 上传本地参考图片；
- 创建 T2V、I2V 和多参考图 R2V 任务；
- 查询任务进度和视频链接；
- 重试失败任务或取消可取消的任务。

生成视频时，Agent 会先使用 `h3-prompt-writing` 组织提示词，再将素材引用转换为 Console MCP 接受的格式。特别是在 R2V 模式中，所有图片都使用 `reference_image` 角色，素材名称写作 `mention_name`，提示词通过 `@mention_name` 引用。

## 使用 Console MCP 生成视频

1. 安装本仓库中的两个 Skills。
2. 前往 [MiniMax H3 Console MCP 设置](https://minimax.beetag.cc/settings/mcp) 创建 MCP Token。
3. 复制页面生成的 MCP 链接，将其粘贴到 Agent 对话中，并要求 Agent 为当前项目安装 MCP。
4. 向 Agent 提供视频需求、时长、画幅和参考图片。例如：

   > 使用这些参考图生成一段 9:16、10 秒的 MiniMax H3 视频，先帮我完善提示词，然后提交任务并持续查询到生成完成。

5. Agent 会检查 MCP、上传素材、校验提示词与素材映射、创建任务，并返回任务状态和最终视频链接。

如果当前项目找不到 `minimax_h3_console` MCP，视频任务不会被提交；请先完成上述 MCP 安装步骤。

## 安装 Skills

### 安装到个人环境

将仓库克隆到本地，然后把两个 Skill 目录复制到 Codex 的个人 Skills 目录：

```bash
git clone https://github.com/ai-youyu-com/minimax-h3-jobs.git
cd minimax-h3-jobs
mkdir -p ~/.codex/skills
cp -R .agents/skills/h3-prompt-writing ~/.codex/skills/
cp -R .agents/skills/minimax-h3-console-video-generator ~/.codex/skills/
```

安装后重新打开 Codex，或启动一个新对话，使 Skills 被重新发现。

### 安装到单个项目

如果只希望在某个项目中使用，可将 Skill 目录复制到目标项目的 `.agents/skills/`：

```bash
mkdir -p /path/to/your-project/.agents/skills
cp -R .agents/skills/h3-prompt-writing /path/to/your-project/.agents/skills/
cp -R .agents/skills/minimax-h3-console-video-generator /path/to/your-project/.agents/skills/
```

将 `/path/to/your-project` 替换为目标项目的实际路径。Console MCP 不随 Skill 文件自动安装，仍需在目标项目中单独添加。

## 使用示例

只编写提示词：

> 使用 `$h3-prompt-writing` 把这个创意改写成 15 秒的 H3 Ref2VA 提示词。

直接创建并跟踪视频任务：

> 使用 `$minimax-h3-console-video-generator` 根据这些图片生成一段 10 秒的 R2V 视频，并在完成后返回视频链接。

## 仓库结构

```text
.agents/skills/
├── 3d-animation-short-generator/
├── brand-promo-video-generator/
├── ...其他场景化视频 Skills
├── h3-prompt-writing/
│   ├── SKILL.md
│   └── references/
└── minimax-h3-console-video-generator/
    ├── SKILL.md
    ├── agents/
    ├── references/
    └── scripts/
```
