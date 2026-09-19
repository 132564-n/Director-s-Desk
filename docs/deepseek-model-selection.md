# DeepSeek 模型选择笔记（AI 导演工作台）

核验日期：2026-09-19。本文只使用 DeepSeek 官方 API 文档与官方发布公告；型号、路由和价格会变化，正式投入使用前应再次查看官方定价页。

## 结论

- DeepSeek V4 已经是正式公开并提供 API 的模型家族，不是传闻。DeepSeek 于 2026-04-24 发布 V4 Preview，之后于 2026-08-13 发布 V4-Pro GA。[V4 Preview 官方公告](https://api-docs.deepseek.com/news/news260424)；[V4-Pro GA 官方公告](https://api-docs.deepseek.com/news/news260813)
- 截至核验日，官方快速入门列出的可用模型 ID 是 `deepseek-flash` 和 `deepseek-v4-pro`，OpenAI 兼容 Base URL 是 `https://api.deepseek.com`。[官方快速入门](https://api-docs.deepseek.com/)
- 实际新项目应优先写 `deepseek-flash`。它当前对应 DeepSeek-V4.1-Flash。官方 2026-09-10 公告称 V4.1-Flash 已上线，并正在淘汰 V4-Pro；自 2026-09-14 04:00 UTC 起，`deepseek-v4-pro` 请求会路由到 V4.1-Flash，并按 Flash 价格计费，直到 V4.1-Pro 上线。[V4.1-Flash 官方公告](https://api-docs.deepseek.com/news/news260910)
- 官方 API 列表没有“编剧”“漫剧”“导演”等垂直专用模型 ID。对本工作台而言，专业性应由 Agent 的角色提示词、项目资料、会话上下文、产物格式和审核流程提供，而不是寻找一个不存在的“DeepSeek 漫剧模型”。[官方快速入门的模型列表](https://api-docs.deepseek.com/)
- 因为九个 Agent 会产生多次调用，`deepseek-flash` 是目前最合理的统一默认值。官方称 V4.1-Flash 更快、更便宜、吞吐更高，并在其测试中领先包括 V4-Pro 在内的旗舰模型；这也是官方给出淘汰 V4-Pro 路线的原因。[V4.1-Flash 官方公告](https://api-docs.deepseek.com/news/news260910)

## 当前官方型号与迁移状态

| 网页中填写的 model ID | 官方当前含义 | 是否建议新配置使用 |
| --- | --- | --- |
| `deepseek-flash` | DeepSeek-V4.1-Flash | 是，推荐作为所有 Agent 的默认模型 |
| `deepseek-v4-pro` | 仍是官方接受的 ID，但官方公告称自 2026-09-14 起路由到 V4.1-Flash，直到 V4.1-Pro 上线 | 不建议；写它目前不能稳定代表一个独立的 Pro 后端 |
| `deepseek-v4-flash` | 旧名称，模型已退役；为兼容而临时路由到 V4.1-Flash | 不建议，新配置直接用 `deepseek-flash` |
| `deepseek-v4-flash-vision-exp` | 旧实验名称，模型已退役；为兼容而临时路由到 V4.1-Flash | 不建议 |
| `deepseek-chat`、`deepseek-reasoner` | 官方 V4 Preview 公告称两者在 2026-07-24 15:59 UTC 后完全退役且不可访问 | 不应使用 |

来源：[官方快速入门](https://api-docs.deepseek.com/)；[V4.1-Flash 官方公告](https://api-docs.deepseek.com/news/news260910)；[V4 Preview 官方公告](https://api-docs.deepseek.com/news/news260424)。

## 接入参数

在导演工作台网页中新增一个供应商时，应填写：

```text
供应商名称：DeepSeek 官方
Base URL：https://api.deepseek.com
API Key：在 DeepSeek 开放平台申请的密钥
测试模型：deepseek-flash
各 Agent 模型：deepseek-flash
```

DeepSeek 官方说明其 API 兼容 OpenAI API 格式，官方 OpenAI Base URL 为 `https://api.deepseek.com`；API Key 申请入口是 [DeepSeek 开放平台](https://platform.deepseek.com/api_keys)。[官方快速入门](https://api-docs.deepseek.com/)

导演工作台当前适配器会在 Base URL 后添加 `/chat/completions`，因此网页里不要再填 `/chat/completions`。填写 `https://api.deepseek.com` 即可。

## 能力与费用

官方当前模型表给 `deepseek-flash` 与 `deepseek-v4-pro` 标注的上下文长度均为 1M tokens，最大输出均为 384K tokens；两者支持 JSON 输出、工具调用、Responses API、Anthropic API 和思考/非思考模式。视觉能力在当前模型表中只明确标给 `deepseek-flash`。[官方模型与定价页](https://api-docs.deepseek.com/quick_start/pricing)

官方思考模式文档说明，思考默认开启，默认推理强度为 `high`。Chat Completions 可以用 `thinking.type` 开关思考，并用 `reasoning_effort` 选择 `low`、`high` 或 `max`。[官方思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode)

当前官方定价页显示以下美元价格，单位为每 100 万 tokens：

| 模型 | 输入，缓存命中 | 输入，缓存未命中 | 输出 |
| --- | ---: | ---: | ---: |
| `deepseek-flash` 非高峰 / 高峰 | $0.003 / $0.006 | $0.15 / $0.30 | $0.60 / $1.20 |
| `deepseek-v4-pro` 名义非高峰 / 高峰 | $0.022 / $0.044 | $0.66 / $1.32 | $1.98 / $3.96 |

高峰为周一至周五 01:00–04:00 和 06:00–10:00 UTC，中国法定节假日除外；其他时间为非高峰，价格减半。[官方模型与定价页](https://api-docs.deepseek.com/quick_start/pricing)

注意：实时定价页仍展示 V4-Pro 的名义价格，而时间更晚的 V4.1-Flash 公告又明确称，自 2026-09-14 起 `deepseek-v4-pro` 会路由到 V4.1-Flash 并按 Flash 价计费。为避免型号和计费歧义，新配置直接使用 `deepseek-flash`，并以调用当天的官方定价页和账单为准。[V4.1-Flash 官方公告](https://api-docs.deepseek.com/news/news260910)

## 对导演工作台的具体建议

1. 第一阶段把九个角色全部设为 `deepseek-flash`。角色差异来自各自的系统提示词，不需要为每个角色购买或选择不同的 DeepSeek 型号。
2. 总导演、编剧、连续性审核等复杂岗位可以在后续界面增加“推理强度”选项：日常用 `high`，特别复杂的结构推演才用 `max`，简单格式化任务用 `low`。官方模型支持这些等级，但当前工作台的 OpenAI 兼容适配器尚未把这一项暴露到网页配置中。
3. 资产图片方面，官方当前只明确列出 `deepseek-flash` 支持视觉。工作台现有聊天适配器仍只向模型发送文字和资产文字描述，并未发送图片内容；若要让 Agent 真正看图，需要另行实现多模态消息，而仅把模型名改成 `deepseek-flash` 不会自动让它读到图片像素。
4. 不要把 `deepseek-v4-pro` 当成当前的高配专用模型：按最新官方路由公告，它目前会落到 V4.1-Flash。等官方发布 V4.1-Pro 及明确的新 model ID 后，再考虑让总导演或终审岗位单独升级。

## 已核验的一手来源

- [DeepSeek API 快速入门](https://api-docs.deepseek.com/)
- [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)
- [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)
- [DeepSeek-V4 Preview Release，2026-04-24](https://api-docs.deepseek.com/news/news260424)
- [DeepSeek-V4-Pro GA Release，2026-08-13](https://api-docs.deepseek.com/news/news260813)
- [DeepSeek-V4.1-Flash Release，2026-09-10](https://api-docs.deepseek.com/news/news260910)
