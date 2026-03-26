# AgentChatBot

基于 LangChain / LangGraph 的多模式智能对话系统，支持聊天、智能体、知识库问答和多智能体协作四种工作模式，提供 Web UI、飞书机器人和命令行三种接入方式。

## 项目背景

毕业设计项目。目标是构建一个可切换多种 LLM 后端（Qwen API、本地 Ollama、Moonshot/Kimi）的对话机器人，并通过工具调用（联网搜索、代码生成）和 RAG 知识库检索扩展模型能力。

## 核心功能

- **聊天模式 (chat)**：基础多轮对话，支持流式输出，自动根据配置选择模型后端
- **智能体模式 (agent)**：基于 LangGraph ReAct Agent，支持工具调用（联网搜索、代码生成），流式返回思考过程和结果
- **知识库模式 (rag)**：上传文档 → 向量化索引 → 检索增强问答，支持 PDF / TXT / Markdown
- **协作体模式 (swarm)**：基于 OpenAI Swarm 的多智能体协作，分诊智能体自动路由到代码 / 搜索 / 问答专家
- **多模型切换**：前端可实时切换 Qwen / Ollama / Moonshot，无需重启
- **文件处理**：支持图片（Vision 模型分析）、文档上传与内容提取
- **会话管理**：基于 Redis 的会话历史持久化，支持多会话

## 技术栈

### 运行时与框架

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| Web 框架 | Flask |
| 智能体框架 | LangGraph (ReAct Agent) |
| 多智能体协作 | OpenAI Swarm |
| LLM 客户端 | LangChain OpenAI / 自定义 AsyncClient |
| 向量化 | 自研轻量 VectorStore + Embedding Model |
| 会话存储 | Redis |
| 前端 | 单文件 HTML (`web_page.html`) |

### 主要依赖

| 包 | 用途 |
|---|------|
| `langchain` / `langchain-openai` | LLM 调用、消息格式 |
| `langgraph` / `langgraph-prebuilt` | ReAct 智能体构建 |
| `flask` / `flask-cors` | Web 服务与 SSE 流式推送 |
| `redis` | 会话历史存储 |
| `openai` | OpenAI 兼容 API 客户端 |
| `requests` | 搜索工具 HTTP 调用 |
| `PyPDF2` / `python-docx` | 文档解析 |
| `pillow` | 图片处理 |

完整依赖见 `requirements.txt`。

## 环境要求

| 依赖 | 说明 |
|------|------|
| Python | 3.10 及以上 |
| Redis | 用于会话历史存储，未连接时服务仍可运行但无历史记录 |
| Ollama（可选） | 本地模型推理，需提前拉取模型（如 `ollama pull qwen3:14b`） |

### 环境变量

在项目根目录创建 `.env` 文件，配置以下变量：

| 变量 | 必填 | 说明 |
|------|------|------|
| `QWEN_API_KEY` | 是（使用 Qwen 时） | 阿里云 DashScope API Key |
| `TAVILY_API_KEY` | 是（使用联网搜索时） | Tavily 搜索 API Key，注册地址：https://tavily.com/ |
| `FEISHU_APP_ID` | 否 | 飞书机器人应用 ID |
| `FEISHU_APP_SECRET` | 否 | 飞书机器人应用 Secret |
| `FEISHU_ENCRYPT_KEY` | 否 | 飞书事件加密 Key |
| `FEISHU_VERIFICATION_TOKEN` | 否 | 飞书事件验证 Token |

`.env` 示例：

```bash
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxx
TAVILY_API_KEY=tvly-dev-xxxxxxxxxxxxxxxx
```

## 安装与运行

```bash
# 克隆项目
git clone <repo-url>
cd agent_chat

# 创建 Conda 环境（推荐）
conda create --name agent_chat python=3.10
conda activate agent_chat

# 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/

# 配置环境变量
# 复制 .env.example 或手动创建 .env，填入 API Key

# 启动 Redis（会话存储需要）
redis-server
```

### 常用命令

```bash
# Web 版（浏览器访问 http://127.0.0.1:5000）
python web_bot.py

# 命令行版
python cli_bot.py

# 飞书机器人版
cd playground/feishu
python main.py
```

### 重启服务（PowerShell）

```powershell
Stop-Process -Name python -Force -ErrorAction SilentlyContinue; Start-Sleep 2; python web_bot.py
```

## 配置项说明

所有配置集中在 `config/config.py`，通过 `python-dotenv` 加载 `.env` 中的敏感信息。

### LLM 模型配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `QWEN_DATA['use']` | `True` | 启用 Qwen API |
| `QWEN_DATA['model']` | `qwen-plus` | Qwen 模型名称 |
| `QWEN_DATA['url']` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | API 地址 |
| `QWEN_DATA['temperature']` | `0.7` | 生成温度 |
| `QWEN_DATA['vision_model']` | `qwen-vl-plus` | 图片分析模型 |
| `QWEN_DATA['embedding_model']` | `text-embedding-v3` | 嵌入模型 |
| `OLLAMA_DATA['use']` | `True` | 启用本地 Ollama |
| `OLLAMA_DATA['model']` | `qwen3:14b` | Ollama 模型名称 |
| `OLLAMA_DATA['api_url']` | `http://localhost:11434/v1/` | Ollama OpenAI 兼容地址 |
| `MOONSHOT_DATA['use']` | `True` | 启用 Moonshot/Kimi |
| `MOONSHOT_DATA['model']` | `kimi-k2.5` | Moonshot 模型名称 |

### 模型选择逻辑

- **聊天模式**：Ollama 优先，Qwen 兜底
- **智能体 / RAG 模式**：Qwen 优先，Ollama 兜底
- **前端指定 `model_provider`**：强制使用指定模型，不走优先级

### 搜索工具配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SEARCH_TOOL_CONFIG['priority']` | `['tavily', 'duckduckgo']` | 搜索引擎优先级 |
| `tavily.api_key` | 环境变量 `TAVILY_API_KEY` | Tavily API Key |
| `tavily.max_results` | `3` | 最大搜索结果数 |
| `duckduckgo.use` | `True` | DuckDuckGo 作为兜底方案 |

### RAG 知识库配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `RAG_CONFIG['knowledge_base_path']` | `data/knowledge_bases` | 知识库存储路径 |
| `RAG_CONFIG['max_token_len']` | `600` | 文档分块最大 token 数 |
| `RAG_CONFIG['default_k']` | `3` | 检索 top-k 数量 |
| `RAG_CONFIG['allowed_extensions']` | `{'pdf', 'md', 'txt'}` | 支持的文档类型 |

### 其他配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `REDIS_DATA` | `localhost:6379/0` | Redis 连接信息 |
| `UPLOAD_FOLDER` | `uploads` | Web 端上传文件存储路径 |
| `FILE_CONFIG['max_size']` | `50MB` | 文件上传大小限制 |

## 目录结构

```text
agent_chat/
├── web_bot.py                      # Web 服务入口（Flask, SSE 流式推送）
├── cli_bot.py                      # 命令行交互入口
├── web_page.html                   # Web 前端页面（单文件）
├── requirements.txt                # Python 依赖
├── .env                            # 环境变量（不提交到版本控制）
│
├── config/
│   ├── config.py                   # 全局配置（模型、数据库、搜索、RAG）
│   └── templates/data/
│       └── bot.py                  # 提示词模板与机器人人设配置
│
├── server/
│   ├── bot/                        # 各模式的 Bot 实现
│   │   ├── chat_bot.py             # 聊天模式 Bot
│   │   ├── agent_bot.py            # 智能体模式 Bot（LangGraph ReAct）
│   │   ├── rag_bot.py              # 知识库问答 Bot
│   │   ├── web_swarm_bot.py        # Web 端多智能体协作 Bot
│   │   └── swarm_agent_bot.py      # 飞书端 Swarm Bot
│   ├── client/                     # 模型客户端抽象层
│   │   ├── base_client.py          # 客户端基类（ainvoke / astream）
│   │   ├── model_factory.py        # 模型工厂（按模式和 provider 创建客户端）
│   │   ├── qwen_client.py          # Qwen API 客户端
│   │   ├── async_ollama_client.py  # Ollama 异步客户端
│   │   └── moonshot_client.py      # Moonshot/Kimi 客户端
│   └── rag/                        # RAG 知识库模块
│       ├── knowledge_base_manager.py  # 知识库 CRUD 与索引管理
│       └── v1/                     # RAG 核心实现
│           ├── rag_client.py       # RAG 检索客户端
│           ├── embedding/          # 嵌入模型
│           ├── vectorstore/        # 向量存储与检索
│           ├── chatmodel/          # 对话模型封装
│           └── tool/               # 文档加载工具
│
├── tools/
│   ├── tool_loader.py              # 工具动态加载器
│   ├── file_processor.py           # 文件处理（文档解析、图片分析）
│   └── agent_tool/                 # 智能体可调用工具
│       ├── search_tool/tool.py     # 联网搜索工具（Tavily / DuckDuckGo）
│       └── code_gen/tool.py        # 代码生成工具（已跳过，由模型自身处理）
│
├── playground/
│   ├── feishu/                     # 飞书机器人接入
│   │   ├── main.py                 # 飞书服务入口
│   │   ├── feishu_message_handler.py  # 消息处理
│   │   └── send_message.py         # 消息发送
│   └── swarm_agent/                # Swarm 框架独立实验
│
├── data/knowledge_bases/           # 知识库数据存储
├── uploads/                        # Web 端上传文件
└── downloads/                      # 飞书端下载文件
```

## 数据与接口

### Web API 路由

Web 服务启动后监听 `http://0.0.0.0:5000`，所有接口均返回 JSON。

#### 对话接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 返回 Web 前端页面 |
| `POST` | `/chat/stream` | 流式对话（SSE），支持 `mode`、`model_provider`、`knowledge_base_id` |
| `GET` | `/chat/history` | 获取所有会话摘要列表 |
| `GET/DELETE` | `/chat/history/<session_id>` | 获取或删除指定会话 |

`POST /chat/stream` 请求体：

```json
{
  "messages": [{"role": "user", "content": "你好"}],
  "mode": "chat",
  "session_id": "xxx",
  "model_provider": "qwen",
  "file_path": "uploads/xxx.pdf",
  "knowledge_base_id": "kb_xxx"
}
```

`mode` 可选值：`chat`、`agent`、`rag`、`swarm`。

SSE 响应格式：

```json
{"type": "status", "content": "正在分析...", "done": false}
{"type": "content", "content": "回答文本片段", "done": false}
{"type": "content", "content": "", "done": true}
```

#### 文件上传接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/upload/file` | 上传文档（自动解析内容） |
| `POST` | `/upload/image` | 上传图片 |

#### 知识库管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET/POST` | `/rag/knowledge-base` | 列出全部知识库 / 创建知识库 |
| `GET/PUT/DELETE` | `/rag/knowledge-base/<kb_id>` | 查看 / 更新 / 删除知识库 |
| `POST` | `/rag/knowledge-base/<kb_id>/documents` | 上传文档到知识库 |
| `DELETE` | `/rag/knowledge-base/<kb_id>/documents/<doc_id>` | 删除知识库中的文档 |
| `POST` | `/rag/knowledge-base/<kb_id>/index` | 构建向量索引 |
| `GET` | `/rag/knowledge-base/<kb_id>/index-status` | 查询索引构建状态 |

#### 系统接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/models` | 返回当前启用的可用模型列表 |
| `GET` | `/health` | 健康检查（Redis 状态、模型启用状态） |

## 模块说明

### `web_bot.py` — Web 服务入口

Flask 应用主文件。负责路由定义、SSE 流式推送、文件上传处理、会话管理。根据请求中的 `mode` 字段分发到不同 Bot 实现。

### `server/bot/` — Bot 实现层

每种工作模式对应一个 Bot 类：

| 文件 | 类 | 说明 |
|------|-----|------|
| `chat_bot.py` | `ChatBot` | 基础对话，调用模型工厂获取客户端 |
| `agent_bot.py` | `AgentBot` | 基于 `langgraph.prebuilt.create_react_agent`，绑定工具列表，流式输出事件 |
| `rag_bot.py` | `RAGBot` | 加载知识库向量 → 检索 top-k → 构造 RAG 提示词 → 流式生成回答 |
| `web_swarm_bot.py` | `WebSwarmBot` | 分诊智能体路由到代码 / 搜索 / 问答专家 |

### `server/client/` — 模型客户端抽象

通过 `model_factory.create_model_client(mode, provider)` 统一创建。所有客户端继承 `BaseModelClient`，实现 `ainvoke(messages) -> str` 和 `astream(messages) -> AsyncIterator[str]`。

### `tools/` — 工具系统

`ToolLoader` 扫描 `tools/agent_tool/` 下的子目录，动态加载每个工具的 `register_tool()` 函数。工具以 LangChain `@tool` 装饰器定义，自动注入到 AgentBot 的工具列表中。

当前可用工具：

| 工具 | 说明 |
|------|------|
| `search_tool` | 联网搜索，按优先级尝试 Tavily → DuckDuckGo |
| `code_gen` | 代码生成（已配置跳过，由模型自身能力处理） |

添加新工具：在 `tools/agent_tool/` 下创建子目录，编写 `tool.py` 并导出 `register_tool()` 函数即可。

### `server/rag/` — RAG 知识库

处理流程：

1. 用户通过 API 创建知识库并上传文档
2. 调用索引构建接口 → 文档分块 → 嵌入向量化 → 持久化到 `data/knowledge_bases/<kb_id>/`
3. 问答时加载向量 → 检索 top-k 最相关片段 → 拼接上下文 → LLM 生成回答

支持文档格式：PDF、TXT、Markdown。

## 已知限制

- Moonshot `kimi-k2.5` 模型的 thinking 模式与 LangGraph 工具调用不兼容，智能体模式下自动禁用 thinking 并使用 `temperature=0.6`
- DuckDuckGo 搜索在国内网络环境下可能不稳定，建议优先配置 Tavily
- Swarm 模式依赖 `openai/swarm` 包，该包为实验性质
- 文件上传大小限制 50MB
- 知识库仅支持 PDF / TXT / Markdown 格式
- Redis 未连接时会话历史不可用，但不影响对话功能

## License

MIT
