# OpenRouter 本地配置

LiveClip 使用 OpenRouter 的 `openai/whisper-large-v3` 做真实中文 ASR，使用本机已登录的 Codex CLI 做转写后的高光编辑。Codex 不能代替 ASR，也不会收到源视频画面。

## 安全前置条件

`OPENROUTER_SETUP.md` 记录的原 Key 曾在聊天中完整出现，必须视为已泄露。先在 [OpenRouter Keys](https://openrouter.ai/settings/keys) 撤销旧 Key，创建带低消费上限的新 Key。不要在聊天、Git、日志或截图中提供新 Key。

将新 Key 写入本机 `.env.local`；该文件已被 `.gitignore` 忽略：

```dotenv
LIVECLIP_AI_PROVIDER=openrouter-codex
OPENROUTER_API_KEY=<new-local-key>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_ASR_MODEL=openai/whisper-large-v3
LIVECLIP_CODEX_EXECUTABLE=codex
```

然后设置权限并重启服务：

```bash
chmod 600 .env.local
make doctor
make dev
```

`doctor` 只报告 Key 是否存在，不打印 Key，也不把“本地已配置”声称为云端调用成功。

## 真实 Smoke Test

使用允许媒体根目录中的短中文视频：

```bash
make smoke-openrouter INPUT="/absolute/path/to/short.mp4"
```

成功必须同时满足：

- 转写 Provider 为 `openrouter`，模型精确为 `openai/whisper-large-v3`；
- 每个成功 ASR 调用存在 `X-Generation-Id`；
- 编辑 Provider 为 `codex_cli`；
- 每个成功 Codex 调用存在线程 ID 和正数 token usage；
- 入选 EditPlan 不是 `degraded`；
- 全链路没有 Mock Provider。

`ASR_VOCABULARY_PROMPT` 会通过 OpenRouter 官方记录的 JSON
`provider.options.groq.prompt` 发送；LiveClip 不使用 OpenRouter 明确会忽略的
multipart 顶层 `prompt`。只有匹配到 Groq 上游时该 Provider 专属选项会被转发，
因此 smoke 成功只证明请求链；实际术语效果必须用含目标词的样本另行检查转写。

缺少 Key、Codex 登录、允许媒体根或输入文件时，命令明确返回 `not_run`/失败，不自动切到 Mock。

## 数据与隐私边界

- 源视频、画面、数据库、代理视频、成片和交付包留在本机。
- FFmpeg 生成的压缩音频分块会发送到 OpenRouter，并由 OpenRouter 路由给实际承载 Whisper 的上游 Provider。
- Codex 只接收候选转写和少量上下文；它不接收源视频或音频。
- API Key 只从本机环境读取，不进入数据库、前端、命令行参数或持久日志。
- `HTTP-Referer: http://localhost` 和 `X-OpenRouter-Title: LiveClip` 只用于应用归属，不含用户媒体路径。

更多接口证据和未验证项见 [OpenRouter 语音转写核对记录](../research/openrouter-audio.md)。
