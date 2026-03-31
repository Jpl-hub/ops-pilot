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
- OCR 标准能力：在 `.env` 中配置 `OPS_PILOT_OCR_ASSETS_PATH` 和 `OPS_PILOT_OCR_RUNTIME_ENABLED=true`
- API 容器启动前会自动执行 `ops-pilot-runtime-check`，OCR 资产缺失会直接阻断启动
- 首次准备模型目录可执行 `ops-pilot-init-ocr-assets`
- 需要导出运行周报时可执行 `ops-pilot-delivery-report --format markdown --output docs/ops_runtime_report.md`

### Docker 容器分工

本地容器分两组，不是所有容器都要一直开着：

- 主交付链路：`postgres`、`api`、`ui`
  用途：登录、协同分析、图谱检索、评分、核验、多模态页面联调。
- 流式 / 大数据链路：`redpanda`、`redpanda-console`、`flink-jobmanager`、`flink-taskmanager`
  用途：外部信号事件流、Kafka、Flink、湖仓联调。只有在做实时链路和大数据演示时才需要启动。

如果现在主要在打磨产品和联调主功能，只开主交付链路就够了。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-core.ps1
```

需要把流式链路一起拉起来时，再额外执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-streaming.ps1
```

全部停掉：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-local-stack.ps1
```

### 清理本地缓存

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\clean-workspace.ps1
```

该脚本会清理本地 `__pycache__`、`.pytest_cache`、`frontend/dist` 和 `tsbuildinfo`，适合交付前或反复联调后快速回到源码态。

### 上线巡检建议

启动后按以下顺序巡检，且以运营保障中心“关键检查清单”为准：

1. 打开 `http://127.0.0.1:8080`，确认登录、工作台、运营保障中心都可访问。
2. 访问 `http://127.0.0.1:8000/api/v1/healthz`，确认 API 返回 `status=ok`。
3. 在运营保障中心依次检查“运行时检查”、“系统就绪度”、“OCR Contract 质量巡检”、“关键检查清单”。
4. 确认 `OPS_PILOT_OPENAI_API_KEY`、`OPS_PILOT_POSTGRES_DSN`、数据目录路径都已配置。
5. 确认 `OPS_PILOT_OCR_ASSETS_PATH` 已落盘且 `OPS_PILOT_OCR_RUNTIME_ENABLED=true`，运营保障中心“OCR 标准引擎”显示 `ready`。
6. 如 OCR contract 存在 `missing/invalid`，先在运营保障中心筛选并执行“重跑当前筛选”，再看“最近一次执行反馈”和“治理轨迹”。
7. 执行 `ops-pilot-delivery-report --format markdown --output docs/ops_runtime_report.md`，固化当前运行状态和治理摘要。
8. 确认主评估周期、silver 指标覆盖、研报覆盖和 OCR contract 质检全部达到上线要求。

## 配置

示例环境变量见 `.env.example`。关键配置项：

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `OPS_PILOT_OPENAI_API_KEY` | OpenAI API Key（必填） | `sk-xxx` |
| `OPS_PILOT_OPENAI_BASE_URL` | API 端点 | `https://api.openai.com/v1` |
| `OPS_PILOT_POSTGRES_DSN` | 数据库连接 | `postgresql+psycopg://...` |
| `OPS_PILOT_UNIVERSE_DATA_PATH` | 正式公司池目录 | `data/universe` |
| `OPS_PILOT_OCR_ASSETS_PATH` | 标准 OCR 模型/权重目录（必填） | `models/paddleocr-vl` |
| `OPS_PILOT_OCR_RUNTIME_ENABLED` | 标准 OCR 运行时开关，生产环境必须为 `true` | `true` |
| `OPS_PILOT_DEFAULT_PERIOD` | 默认分析报期 | `2025Q3` |
| `OPS_PILOT_KAFKA_BOOTSTRAP_SERVERS` | 外部信号 Kafka 地址，可选 | `127.0.0.1:19092` |
| `OPS_PILOT_KAFKA_SIGNAL_TOPIC` | 外部信号 Topic 名称 | `opspilot.external_signals` |

交付模式下默认只读取正式公司池和正式数据，不再提供运行态样本回退。

Colab 验证和 Docker 部署作业书见 [docs/ocr_delivery_runbook.md](/D:/code/ops-pilot/docs/ocr_delivery_runbook.md)。
Colab 最小操作说明见 [docs/colab_quickstart.md](/D:/code/ops-pilot/docs/colab_quickstart.md)。

## 数据流水线

```bash
# 官方财报 & 研报抓取
ops-pilot-fetch-real-data --codes 601012,002129,300750,300014,300274,002202

# PDF 解析 → bronze chunks
ops-pilot-parse-official-reports --codes 601012,002129,300750

# 结构化指标提取 → silver metrics
ops-pilot-build-silver-metrics --codes 601012,002129,300750

# 公司快照 → snapshot silver
ops-pilot-build-snapshot-silver --codes 601012,002129,300750

# 构建向量索引
ops-pilot-build-embeddings

# 构建外部信号事件流
ops-pilot-build-signal-stream
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

## 流式事件总线

项目已补上第一版流式大数据骨架，用于把正式外部信号升级为可消费事件流：

```bash
# 1. 启动 Redpanda + Flink
docker compose -f docker-compose.streaming.yml up -d

# 2. 安装流式依赖
pip install -e .[streaming]

# 3. 生成事件流并发布 Kafka
ops-pilot-build-signal-stream --publish-kafka
```

- Kafka / Redpanda：`127.0.0.1:19092`
- Redpanda Console：`http://127.0.0.1:18080`
- Flink UI：`http://127.0.0.1:18081`
- Flink SQL 作业：`streaming/flink/industry_signal_features.sql`
- 湖仓版 SQL：`streaming/flink/industry_signal_lakehouse.sql`
- Flink connector 目录：`streaming/flink/usrlib/`
- 运行手册：`docs/streaming_runbook.md`

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
- **图谱检索**：query-aware graph retrieval + multi-hop path inference + evidence navigation
- **评分引擎**：同子行业分位映射 + 事件规则触发 + 缺失值权重重分配
- **流式底座**：Kafka / Redpanda + Flink SQL + Paimon / Iceberg compatible lakehouse

## 开发验证

```bash
python -m pytest tests/ -v
python -m compileall src
```

## License

MIT
