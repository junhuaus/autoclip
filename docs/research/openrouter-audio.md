# OpenRouter 语音转写核对记录

核对日期：2026-08-05。

## 结论

LiveClip 的 OpenRouter ASR 契约固定为：

- API Base URL：`https://openrouter.ai/api/v1`
- 接口：`POST /audio/transcriptions`
- 模型：`openai/whisper-large-v3`
- 语言提示：`zh`
- 响应：`verbose_json`
- 时间戳：`segment` 与 `word`
- 音频：FFmpeg 生成的 M4A/AAC 单声道分块
- 单块：默认不超过 300 秒且不超过 24,000,000 bytes
- 领域词汇：JSON `provider.options.groq.prompt`；不使用会被忽略的 multipart 顶层 `prompt`
- 追踪：成功必须保存精确来自响应头的 `X-Generation-Id`

OpenRouter 的当前 STT 文档列出 WAV、MP3、FLAC、M4A、OGG、WebM 与 AAC 等常见格式；模型页确认 `openai/whisper-large-v3` 支持词级与句段级时间戳。官方教程说明 JSON `input_audio` 与 OpenAI 风格 multipart 都可用，multipart 上限为 25 MB，并且该接口不输出 SRT/VTT。文档还明确指出 multipart 顶层 `prompt` 虽被接受却会被忽略，已记录的词汇提示入口是 JSON `provider.options.groq.prompt`。LiveClip 因此使用 JSON 路径；每次只把一个已校验且最多 24 MB 的分块做 base64 编码，绝不把多小时源文件整体载入内存。24 MB 应用上限也保留了预处理和缓存的保守边界。

官方资料：

- [OpenRouter Speech-to-Text](https://openrouter.ai/docs/guides/overview/multimodal/stt)
- [Transcription on OpenRouter](https://openrouter.ai/blog/tutorials/transcription-on-openrouter/)
- [Whisper Large V3 model/API](https://openrouter.ai/openai/whisper-large-v3/api)
- [App attribution headers](https://openrouter.ai/docs/app-attribution)
- [API errors and Retry-After](https://openrouter.ai/docs/api/reference/errors-and-debugging)

## SDK 与响应处理

项目继续使用官方 OpenAI Python SDK，但仅把客户端 Base URL 指向 OpenRouter。已安装版本为 `openai==2.52.0`：

- SDK 内建 retry 被设为 0，LiveClip 自己执行有上限的指数退避和抖动。
- SDK 的底层 JSON POST 加 raw-response 模式用于在解析正文前读取 `X-Generation-Id`；请求体使用官方 `input_audio` 与 `provider.options.groq.prompt` 结构。
- SDK 响应模型允许额外字段，因此 LiveClip 在应用边界重新校验根字段、文本、有限数值时间、句段和词对齐。
- `usage.seconds`/`usage.cost` 若存在必须是有限非负数；通过校验后才保存，代码不硬编码价格。
- HTTP 200 但 JSON 或时间戳结构无效时，记录 `OPENROUTER_ASR_RESPONSE_INVALID`，不重试、不切换 Mock。
- 普通 `x-request-id` 不得冒充 generation ID；缺少 `X-Generation-Id` 的 200 响应也按无效 Provider 响应持久化。

## 重试与确定性失败

`429`、`502`、`503`、`524`、`529` 属于可重试范围，遵守有界 `Retry-After`。连接错误与超时也可有限重试。`401`、`402`、`403` 和确定性参数错误不会盲目重试。每次逻辑调用记录请求次数、重试次数、延迟、音频秒数、generation ID 和安全 usage。

## 未验证项

仓库没有可安全使用的 OpenRouter Key。用户提供的设置文件明确说明旧 Key 曾在聊天中暴露，因此截至本次核对：

- Adapter 的 JSON/base64、领域词汇 provider options、时间戳、精确 generation ID、usage/cost、重试与异常路径已通过离线 SDK transport 测试。
- 真实 `OpenRouter ASR → Codex` smoke 尚未运行。
- 必须先撤销旧 Key，并将新 Key 只写入被 Git 忽略的 `.env.local`。
