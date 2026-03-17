# OpsPilot-X

OpsPilot-X 是一个面向新能源上市公司运营分析与决策支持的比赛项目骨架仓库。当前仓库完成了 P0 首版落地：基于样本集的评分引擎、风险与机会规则、证据回放、统一审计协议、FastAPI 服务以及 NiceGUI 页面骨架。

## 当前范围

- 行业范围固定为新能源产业链
- 数据范围当前为仓库内 `data/bootstrap/` 样本数据
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

1. 使用 Python 3.11 创建虚拟环境。
2. 安装依赖：`pip install -e .`
3. 复制 `.env.example` 为 `.env` 并按需修改。
4. 启动 API：`ops-pilot-api`
5. 启动 UI：`ops-pilot-ui`

当前环境若未安装 `nicegui`，API 仍可运行，UI 启动会给出明确提示。

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

当前 silver v1 已完成：

- 从真实财报摘要页抽取营收、归母净利润、扣非净利润、经营现金流、总资产、归母权益
- 从真实资产负债表抽取货币资金、流动资产合计、流动负债合计、负债合计、短期借款、一年内到期非流动负债
- 自动识别 `元 / 千元 / 万元 / 百万元` 单位并统一换算
- 对三季报统一采用“年初至报告期末”累计口径
- 已接入真实评分的核心指标扩展到 `G1 / G2 / P2 / C1 / C2 / S1 / S2 / S4`
- API 在未显式传 `report_period` 时，默认优先使用当前可比主周期 `2025Q3`

二进制原始文件默认不纳入 Git，仓库只保留脚本、公司池和 manifest 结构。

## Docker

```bash
docker compose up --build
```

## 下一步

- 接入官方比赛数据下载链路
- 替换样本证据为真实财报 / 研报切片
- 上线 AgentScope 编排与 Skill 路由
- 接入 PostgreSQL + pgvector + Alembic 迁移
