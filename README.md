# OpsPilot-X

**智能体赋能的新能源企业运营分析与决策支持系统**

OpsPilot-X 面向新能源上市公司，提供企业评分、行业风险扫描、研报观点核验、同业对标、智能问答与证据追溯等核心能力。系统采用半开放式 LLM Orchestrator + 真实工具调用 + Hybrid RAG 架构，实现"可信分析、可追溯证据、可复算数值"的决策支持。

## 快速启动

### 环境要求

- Python `3.11`
- Node.js `20+`
- PostgreSQL `16` + pgvector

### 本地启动

```bash
# 1. 安装后端
pip install -e .

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 OPS_PILOT_OPENAI_API_KEY 等

# 3. 启动后端 API
ops-pilot-api

# 4. 启动前端（另一个终端）
cd frontend
npm install
npm run dev
```

- API 默认地址：`http://127.0.0.1:8000`
- 前端默认地址：`http://127.0.0.1:8080`
- 登录/注册依赖 `OPS_PILOT_POSTGRES_DSN` 指向可用数据库

### Docker 启动

```bash
# 编辑 .env 填入 OPS_PILOT_OPENAI_API_KEY
docker compose up --build
```

- API：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:8080`
- PostgreSQL：`127.0.0.1:5432`

## 配置

示例环境变量见 `.env.example`。关键配置项：

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `OPS_PILOT_OPENAI_API_KEY` | OpenAI API Key（必填） | `sk-xxx` |
| `OPS_PILOT_OPENAI_BASE_URL` | API 端点 | `https://api.openai.com/v1` |
| `OPS_PILOT_POSTGRES_DSN` | 数据库连接 | `postgresql+psycopg://...` |
| `OPS_PILOT_DEFAULT_PERIOD` | 默认分析报期 | `2025Q3` |

## 数据流水线

```bash
# 官方财报 & 研报抓取
ops-pilot-fetch-real-data --codes 601012,002129,300750,300014,300274,002202

# PDF 解析 → bronze chunks
ops-pilot-parse-official-reports --codes 601012,002129,300750

# 结构化指标提取 → silver metrics
ops-pilot-build-silver-metrics --codes 601012,002129,300750
```

数据目录结构：

```
data/
├── bootstrap/          # 联调样本数据
├── raw/official/       # 原始 PDF & 研报
├── bronze/official/    # 页级文本 & chunk
├── silver/official/    # 结构化财务指标
└── universe/           # 正式公司池
```

## 系统能力

| 功能 | API 路径 | 说明 |
|------|----------|------|
| 智能问答 | `/api/v1/chat/turn` | LLM Orchestrator + 真实工具调用 |
| 企业评分 | `/api/v1/company/score` | 五维评分体系（19 项指标） |
| 同业对标 | `/api/v1/company/benchmark` | 子行业分位排名 |
| 行业风险扫描 | `/api/v1/industry/risk-scan` | 批量风险/机会标签 |
| 研报观点核验 | `/api/v1/claim/verify` | 研报断言 vs 官方财报核验 |
| 压力测试 | `/api/v1/company/stress-test` | 极端场景传导模拟 |
| 证据查看 | `/api/v1/evidence/{chunk_id}` | 原文溯源 & 页码定位 |

覆盖指标：`G1-G3 / P1-P5 / C1-C3 / S1-S4 / I1-I4`（共 19 项）

## 技术架构

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Vue 3 UI   │───▶│  FastAPI API  │───▶│  PostgreSQL  │
│  Vite + TS   │    │  + Uvicorn   │    │  + pgvector  │
└──────────────┘    └──────┬───────┘    └──────────────┘
                           │
                    ┌──────▼───────┐
                    │ LLM Orch.    │
                    │ gpt-4o-mini  │
                    │ Tool Calling │
                    │ Hybrid RAG   │
                    └──────────────┘
```

- **Agent 架构**：半开放式 Orchestrator，确定性前处理 + 受限 LLM 工具选择
- **检索架构**：BM25 + Dense ANN → RRF 融合 → LLM Reranker
- **评分引擎**：同子行业分位映射 + 事件规则触发 + 缺失值权重重分配

## 开发验证

```bash
python -m pytest tests/ -v
python -m compileall src
```

## License

MIT
