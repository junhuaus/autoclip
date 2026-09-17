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
- 单块：默认不超过 90 秒且不超过 24,000,000 bytes
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
- HTTP 200 但 JSON 或时间戳结构无效时，记录 `OPENROUTER_ASR_RESPONSE_INVALID`，由持久化 Stage 做有界重试并复用成功分块；不在 Adapter 内立即重复计费，也绝不切换 Mock。句段时间按与已验证音频区间的交集保存，完全在分块外的句段被丢弃；非空转写若没有任何有效交集才按无效响应处理。可选词级时间继续执行严格的一秒尾部上限，失败时只降级为 `unavailable`。
- 普通 `x-request-id` 不得冒充 generation ID；缺少 `X-Generation-Id` 的 200 响应也按无效 Provider 响应持久化。

## 重试与确定性失败

`429`、`502`、`503`、`524`、`529` 属于可重试范围，遵守有界 `Retry-After`。连接错误与超时也可有限重试。`401`、`402`、`403` 和确定性参数错误不会盲目重试。每次逻辑调用记录请求次数、重试次数、延迟、音频秒数、generation ID 和安全 usage。

## 2026-08-05 实际调用证据

一个仅存于忽略目录的本地 Key 已被 OpenRouter 接受；其值未进入数据库、日志、文档或 Git。仓库只读源 `input/7.28.mp4`（2,190,937,089 bytes，2,780.437 秒）完成了真实调用：

- 33/33 个 90 秒、5 秒重叠的 M4A 分块成功，33 次请求、0 次重试；每次都有通过严格校验的 `X-Generation-Id`。
- 重叠计费音频合计 2,942.016 秒，Provider 返回的实际 cost 合计 USD 0.0735504；代码没有硬编码价格。
- 合并后保存 233 个绝对时间句段，覆盖 0.284–2,780.256 秒。
- 观察到的可选 word 数组是句段镜像或不能可靠对齐，因此 `word_timing_status=unavailable`，数据库保存 0 个伪造词时间；有效 segment 转写被保留。
- 随后的同项目第二代运行按当时的 key-first 身份从 33 个缓存恢复，产生 0 条新的 OpenRouter usage 记录；原调用证据仍属于第一代。运行后对两代 manifest 的 33 组 `chunk_id`、绝对区间、`cache_key` 和音频字节 SHA-256 做了 canonical 比较，全部相同。审查后现行 v2 身份改为同时绑定 `cache_key` 与字节 SHA-256，并以同键不同 SHA 不复用的测试证明；没有为证明新键而重复付费跑长视频。
- 第二代由宿主 Worker 完成 39/39 次 Codex 候选编辑，选出 15 个非降级 EditPlan 并生成 15 个干净审核代理视频。

这些证据验证了当前样本的真实请求/响应/usage/恢复链路。Groq 词汇提示对特定术语的改善、其他上游实现差异、典型 2–4 小时媒体和 Apple M3 性能仍需单独验证。
