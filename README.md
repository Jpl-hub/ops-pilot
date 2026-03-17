# OpsPilot-X

OpsPilot-X 是一个面向新能源上市公司运营分析与决策支持的比赛项目仓库。当前仓库已经从 P0 样本演示推进到真实数据阶段：基于交易所定期报告与东财研报构建评分引擎、风险与机会规则、证据回放、统一审计协议、FastAPI 服务以及 NiceGUI 演示前端。

## 当前范围

- 行业范围固定为新能源产业链
- 数据主线当前优先使用 `data/raw/official/`、`data/bronze/official/`、`data/silver/official/` 的真实产物
- `data/bootstrap/` 当前仅保留为开发联调兜底数据，不作为正式展示主链路
- 已落地接口：
  - `GET /api/v1/healthz`
  - `POST /api/v1/chat/turn`
  - `POST /api/v1/company/score`
  - `POST /api/v1/company/benchmark`
  - `GET /api/v1/evidence/{chunk_id}`
- 当前实现以“可信闭环演示”为目标，后续再接比赛正式数据与智能体能力

## 仓库结构

```text
data/bootstrap/        样本公司与证据数据
src/opspilot/          应用代码
tests/                 首批单元测试
OpsPilot_需求与设计文档.md  项目母版文档
```

## 本地启动

### 方式一：直接按命令启动

1. 使用 Python 3.11 创建虚拟环境并激活。
2. 安装依赖：

```bash
pip install -r requirements.txt
pip install -e .
```

3. 复制 `.env.example` 为 `.env` 并按需修改。
4. 启动后端 API：

```bash
ops-pilot-api
```

默认监听 `http://127.0.0.1:8000`。

5. 启动前端 UI（当前前端为 NiceGUI，不是独立 Vue 工程）：

```bash
ops-pilot-ui
```

默认监听 `http://127.0.0.1:8080`。

如果提示 `8000` 或 `8080` 端口已被占用，通常说明你已经起过一份 API / UI，或者 Docker 里的同名服务仍在运行；先停止旧进程或执行 `docker compose stop api ui` 再重试。

### 方式二：Docker Compose 一键启动

```bash
docker compose up --build
```

启动后：

- API：`http://127.0.0.1:8000`
- UI：`http://127.0.0.1:8080`
- PostgreSQL：`127.0.0.1:5432`

### 常用开发命令

```bash
python -m unittest discover -s tests -t .
ops-pilot-fetch-real-data --codes 601012,002129,300750,300014,300274,002202
ops-pilot-parse-official-reports --codes 601012,002129,300750,300014,300274,002202
ops-pilot-build-silver-metrics --codes 601012,002129,300750,300014,300274,002202
```

当前环境若未安装 `nicegui`，API 仍可运行，UI 启动会给出明确提示。

## 前端说明

当前仓库前端采用 `NiceGUI`，原因是：

- 与项目母版文档当前冻结技术栈一致
- 单仓库全 Python，更适合比赛阶段快速迭代
- 现在 UI 还处于业务闭环验证期，尚未进入复杂前后端分离阶段

如果后面我们确定要冲更强展示效果、复杂交互和多页面工程化，我同意在后续阶段切到 `Vue 3 + ECharts`。但当前阶段不建议立刻迁移，否则会打断真实数据、指标体系、证据链这条主线。

## 官方真实数据抓取

当前仓库已经接入三类官方源：

- 上交所定期报告
- 深交所定期报告
- 东方财富个股研报详情页

执行抓取：

```bash
ops-pilot-fetch-real-data --codes 601012,002129,300750,300014,300274,002202
```

执行 bronze 解析：

```bash
ops-pilot-parse-official-reports --codes 601012,002129,300750,300014,300274,002202
```

执行 silver 指标抽取：

```bash
ops-pilot-build-silver-metrics --codes 601012,002129,300750,300014,300274,002202
```

输出目录：

- `data/universe/formal_company_pool.json`：正式公司池
- `data/raw/official/manifests/`：抓取结果清单
- `data/raw/official/periodic_reports/`：交易所 PDF
- `data/raw/official/research_reports/`：东财研报详情页 HTML
- `data/bronze/official/manifests/`：页级抽取与 chunk 清单
- `data/bronze/official/page_text/`：页级文本 JSON
- `data/bronze/official/chunks/`：chunk JSONL
- `data/silver/official/manifests/`：真实财务摘要指标 manifest

当前 silver v2 已完成：

- 从真实财报摘要页抽取营收、归母净利润、扣非净利润、经营现金流、总资产、归母权益
- 从真实资产负债表抽取货币资金、流动资产合计、流动负债合计、负债合计、短期借款、一年内到期非流动负债
- 从真实合并利润表抽取营业成本、销售费用、管理费用、研发费用、财务费用
- 从真实资产负债表与利润表联合派生存货周转天数、应收账款周转天数
- 从真实财报事件页抽取政府补助依赖、诉讼/处罚、减值压力信号，并为季报回填同年最近一期正式披露的审计/诉讼结论
- 基于上一年同期间真实应收账款余额补齐 `C3`，当前 `2025Q3` 公司池已做到 6/6 覆盖
- 基于利润总额与利息费用补齐 `S3`，当前 `2025Q3` 公司池已做到 6/6 覆盖
- `I2` 审计信号当前已支持跨页搜索与同年最近一期回填，`2025Q3` 公司池已做到 6/6 覆盖
- `C3 / S3` 已补充字段级证据，支持当前页、上一年同页与公式结果联动回放
- `NiceGUI` 体检页已升级为卡片化展示，直接展示总分、标签、双图表、`C3 / S3` 公式回放与证据入口
- 评分页已新增“标签拆解”区，把风险/机会标签、触发信号、关联指标和证据链接集中展示
- 自动识别 `元 / 千元 / 万元 / 百万元` 单位并统一换算
- 对三季报统一采用“年初至报告期末”累计口径
- 已接入真实评分的核心指标扩展到 `G1 / G2 / G3 / P1 / P2 / P3 / P4 / P5 / C1 / C2 / C3 / S1 / S2 / S3 / S4 / I1 / I2 / I3 / I4`
- 事件指标当前采用“当期直接抽取优先，同年最近一期正式披露回填兜底”的策略，适配 `Q3` 等简版报告
- 当前真实财报池已扩展到 42 份定期报告，覆盖 `2025` 主周期及主要 `2024` 可比口径
- `S3` 的下一步重点从“补覆盖”转为“补严谨度”，后续继续从附注完善 EBIT / 利息保障的更严格口径
- API 在未显式传 `report_period` 时，默认优先使用当前可比主周期 `2025Q3`

二进制原始文件默认不纳入 Git，仓库只保留脚本、公司池和 manifest 结构。

## 下一步

- 接入官方比赛数据下载链路
- 替换样本证据为真实财报 / 研报切片
- 上线 AgentScope 编排与 Skill 路由
- 接入 PostgreSQL + pgvector + Alembic 迁移
