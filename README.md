# AI 导演工作台

面向中文 AI 漫剧的本地优先、多 Agent 导演工作台。

当前版本已经跑通群聊式 MVP 闭环：

1. 左侧管理项目与会话，支持搜索、置顶、重命名和归档；
2. 中间以群聊形式展示九位专业 Agent 的独立发言与总导演结论；
3. 支持 `@Agent`、自主讨论、讨论停止和讨论/提案两种模式；
4. 提案经过“待处理 → 采纳草案 → 确认正式版本”的审批链；
5. 右侧统一管理待办提案、正式版本和参考图片资产；
6. 保留故事大纲、分场剧本、导演执行包、时长上限和 ZIP 导出能力。

单集状态默认持久化到 `data/database.sqlite`。

## 启动网站

首次克隆需要 Python 3.12+、Node.js 20+，先安装依赖并构建：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd web
npm ci
npm run build
cd ..
```

依赖与生产构建已经就绪时，在项目根目录运行：

```powershell
.\start.cmd
```

`start.cmd` 不需要修改 Windows 的全局 PowerShell 执行策略。也可以双击该文件启动。

然后访问 `http://127.0.0.1:3000`。接口文档位于 `http://127.0.0.1:8000/docs`。

## 当前目录

```text
docs/                         领域与工作流设计
server/director_workbench/    FastAPI、状态机、Agent 与持久化
server/tests/                 后端测试
web/                          Next.js 导演工作台
web/e2e-chat.mjs              群聊工作台浏览器端到端验收
```

## 运行验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
cd web
npm run typecheck
npm run build
node e2e-chat.mjs
node e2e-layout.mjs
node e2e-ux-review.mjs
node e2e-settings.mjs
```

`e2e-chat.mjs` 会创建测试项目，请在隔离的数据目录运行。布局检查只读取现有会话，配置页面测试使用模拟写接口，不会覆盖你的密钥。

## 模型配置

默认使用不联网、不消耗 Token 的本地演示团队。打开侧栏的“团队 API 配置”，或访问 `http://127.0.0.1:3000/settings`：

1. 添加兼容接口，填写供应商名称、Base URL（通常以 `/v1` 结尾）和 API Key。
2. 输入供应商支持的精确模型名称，点击“保存并测试连接”（会产生一条少量计费请求）。
3. 为九个 Agent 分别选择供应商并填写模型名称，可混用不同供应商。
4. 点击“保存团队配置”，返回群聊。新一轮讨论立即使用新配置，无需重启。

当前支持 OpenAI 兼容的 `/chat/completions` 接口；不是所有厂商原生 API 都兼容。密钥缺失或调用失败会报错，不会悄悄切换成演示回答。

Windows 上网页输入的密钥使用当前用户的 DPAPI 加密后保存到 `data/model-settings.json`，不回传浏览器、不放入 localStorage 或导出包。留空保留原密钥，清除按钮需保存后生效；修改接口地址会移除旧的网页密钥。移动到其他电脑或 Windows 用户后需要重新填写。高级设置仍支持环境变量，网页密钥优先，非 Windows 系统请使用环境变量。

本工具目前仅供本机个人使用，不带账号权限系统，不要将端口暴露到公网。远程模型地址要求 HTTPS。`data` 内的数据库、日志、配置不对网页公开，只有项目资产目录可访问。Git 排除了本地数据、密钥、依赖与构建产物。

## 当前边界

支持文本讨论、剧本与提示词提案以及参考资产管理，不生成样片。图片目前作为资产及文字描述参与上下文，尚未接入模型视觉识别。自主讨论目前有两轮专家发言与总导演总结，不是无限循环讨论。模型接口的自动化测试使用模拟供应商，真实供应商可用性需用自己的密钥在网页验证。
