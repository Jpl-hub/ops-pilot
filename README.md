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

## Docker

```bash
docker compose up --build
```

## 下一步

- 接入官方比赛数据下载链路
- 替换样本证据为真实财报 / 研报切片
- 上线 AgentScope 编排与 Skill 路由
- 接入 PostgreSQL + pgvector + Alembic 迁移
