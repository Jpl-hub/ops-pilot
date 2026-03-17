# OpsPilot-X

OpsPilot-X 是一个面向新能源上市公司的运营分析系统，当前已接入真实官方数据，覆盖 50 家正式公司，支持企业评分、行业风险扫描、公式解释和证据追溯。

## 快速启动

### 本地启动

要求：Python `3.11`

```bash
pip install -r requirements.txt
pip install -e .
ops-pilot-api
ops-pilot-ui
```

- API 默认地址：`http://127.0.0.1:8000`
- UI 默认地址：`http://127.0.0.1:8080`

如果 `8000` 或 `8080` 被占用，先停止旧进程或执行：

```bash
docker compose stop api ui
```

### Docker 启动

```bash
docker compose up --build
```

- API：`http://127.0.0.1:8000`
- UI：`http://127.0.0.1:8080`
- PostgreSQL：`127.0.0.1:5432`

## 配置

示例环境变量见 `.env.example`。当前常用配置如下：

```env
OPS_PILOT_ENV=development
OPS_PILOT_HOST=0.0.0.0
OPS_PILOT_PORT=8000
OPS_PILOT_DEFAULT_PERIOD=2025Q3
OPS_PILOT_SAMPLE_DATA_PATH=data/bootstrap
OPS_PILOT_OFFICIAL_DATA_PATH=data/raw/official
OPS_PILOT_BRONZE_DATA_PATH=data/bronze/official
OPS_PILOT_SILVER_DATA_PATH=data/silver/official
OPS_PILOT_POSTGRES_DSN=postgresql+psycopg://ops_pilot:ops_pilot@localhost:5432/ops_pilot
```

## 数据流水线

```bash
ops-pilot-fetch-real-data --codes 601012,002129,300750,300014,300274,002202
ops-pilot-parse-official-reports --codes 601012,002129,300750,300014,300274,002202
ops-pilot-build-silver-metrics --codes 601012,002129,300750,300014,300274,002202
```

关键目录：

- `data/raw/official/`：交易所 PDF 与研报原始文件
- `data/bronze/official/`：页级文本和 chunk
- `data/silver/official/manifests/financial_metrics_manifest.json`：结构化指标产物

## 当前能力

- 企业评分：`/api/v1/company/score`
- 行业风险扫描：`/api/v1/industry/risk-scan`
- 问答入口：`/api/v1/chat/turn`
- 证据查看：`/api/v1/evidence/{chunk_id}`
- 当前正式数据规模：`50` 家公司，`154` 份定期报告 PDF，`96` 份研报详情页，`28` 份巨潮官方快照，`365` 条 silver 指标记录
- 真实指标已覆盖：`G1 / G2 / G3 / P1 / P2 / P3 / P4 / P5 / C1 / C2 / C3 / S1 / S2 / S3 / S4 / I1 / I2 / I3 / I4`
- UI 已支持标签拆解、公式回放和证据聚焦

## 开发验证

```bash
python -m unittest discover -s tests -t .
python -m compileall src
```
