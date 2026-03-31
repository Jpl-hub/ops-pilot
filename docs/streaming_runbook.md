# 流式外部信号总线运行手册

## 目标

把正式外部信号从 `official manifests` 提升为可发布、可消费、可计算、可沉淀的实时数据产品。

当前仓库分两层：

1. 基础版：`ops-pilot-build-signal-stream` 统一归一化交易所公告、券商研报、行业研报、公司快照，并生成 Bronze / Silver / Gold 文件结果。
2. 升级版：Flink 从 Kafka 消费正式信号，直接把窗口特征、子行业热度、公司异动评分写入 `Paimon`，并同时生成 `Iceberg` 兼容元数据。

## 架构分层

```text
official manifests
  -> Bronze event stream (JSONL)
  -> Kafka / Redpanda topic
  -> Flink SQL window aggregation
  -> Paimon lakehouse tables
  -> Iceberg compatible metadata
  -> Industry Brain / Admin / downstream engines
```

## 启动流式基础设施

```bash
docker compose -f docker-compose.streaming.yml up -d
```

启动后地址：

- Redpanda Kafka 外部地址：`127.0.0.1:19092`
- Redpanda Console：`http://127.0.0.1:18080`
- Flink UI：`http://127.0.0.1:18081`

## 安装依赖

```bash
pip install -e .[streaming]
```

## 构建正式事件流

先保证正式数据清单存在：

```bash
ops-pilot-fetch-real-data --codes 601012,002129,300750,300274,002202
```

然后构建外部信号事件流：

```bash
ops-pilot-build-signal-stream
```

如果要同步推送 Kafka：

```bash
set OPS_PILOT_KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092
set OPS_PILOT_KAFKA_SIGNAL_TOPIC=opspilot.external_signals
ops-pilot-build-signal-stream --publish-kafka
```

输出结果：

- Bronze 事件流：`data/bronze/official/stream/external_signal_events/publish_date=YYYY-MM-DD/*.jsonl`
- Bronze Manifest：`data/bronze/official/manifests/external_signal_stream_manifest.json`
- Silver 快照：`data/silver/official/stream/company_signal_snapshot.json`
- Gold 公司时序：`data/gold/official/stream/company_signal_timeline.json`
- Gold 子行业热度：`data/gold/official/stream/subindustry_signal_heatmap.json`

## Flink SQL 作业清单

仓库内现有两套 SQL：

- `streaming/flink/industry_signal_features.sql`
  说明：基础版，窗口结果先落本地 JSON，适合联调和快速演示。
- `streaming/flink/industry_signal_lakehouse.sql`
  说明：升级版，窗口特征、子行业热度、异动评分直接写入 `Paimon`，并产出 `Iceberg` 兼容元数据。

## 运行基础版窗口聚合

进入 Flink JobManager 容器：

```bash
docker exec -it ops-pilot-flink-jobmanager /bin/bash
```

执行：

```bash
sql-client.sh -f /workspace/streaming/flink/industry_signal_features.sql
```

落盘位置：

```text
data/silver/official/stream/flink_company_signal_window/
```

## 运行湖仓升级版

### 1. 准备 connector jar

把下列 jar 放到：

```text
streaming/flink/usrlib/
```

至少包含：

- Kafka connector
- 对应 Flink 版本的 `Paimon` bundled jar

建议额外准备：

- `Paimon` action / compaction 相关 jar

当前 compose 使用 `Flink 1.20`，因此 jar 版本必须与 `1.20` 对齐。

### 2. 启动 SQL 作业

```bash
docker exec -it ops-pilot-flink-jobmanager /bin/bash
sql-client.sh -f /workspace/streaming/flink/industry_signal_lakehouse.sql
```

该作业会创建：

- Catalog：`ops_pilot_lakehouse`
- Database：`opspilot_rt`
- Table：`company_signal_window_rt`
- Table：`company_signal_anomaly_rt`
- Table：`subindustry_signal_window_rt`

默认 warehouse：

```text
data/lakehouse/paimon/
```

### 3. 湖仓输出说明

`company_signal_window_rt`
: 公司级 1 小时窗口特征表，保存窗口热度、信号数、各类正式来源计数、最新事件时间。

`company_signal_anomaly_rt`
: 公司级实时异动表，保存 `anomaly_score` 与 `anomaly_level`，用于行业大脑、监测板和后续在线告警。

`subindustry_signal_window_rt`
: 子行业级窗口热度表，用于看行业轮动、板块升温和信号扩散。

### 4. Iceberg 兼容

升级版 SQL 在 Paimon 表上打开了：

```text
'metadata.iceberg.storage' = 'hadoop-catalog'
```

这意味着：

- Flink 继续负责实时写入
- Spark / Trino / Iceberg Reader 可以直接读取同一批原始数据文件
- 比赛答辩时可以明确说明“不是单一引擎 demo，而是多引擎可消费的流式湖仓设计”

## 建议运维动作

### 1. 先跑基础版，再切湖仓版

第一次联调建议先运行 `industry_signal_features.sql`，确认 Kafka 源、watermark、窗口逻辑都正确；之后再切到 `industry_signal_lakehouse.sql`。

### 2. 给 Paimon 开 compaction

正式跑持续流时，应补 dedicated compaction 作业，不建议长期只靠默认小文件写入。

### 3. 用异动表驱动前端

当前后端已经有异动评分引擎；一旦 `company_signal_anomaly_rt` 稳定，可把行业大脑实时面板切成“读湖仓表 / 读其下游服务”。

## 当前边界

- 当前仓库已经具备“正式源 -> 事件流 -> Kafka -> Flink -> Paimon/Iceberg”可落地方案。
- 这次升级补的是 SQL 与运行手册，不替代线上 connector / catalog / compaction 的真实部署。
- 如果要进一步冲企业级，下一步优先补：
  1. Paimon compaction 作业
  2. 湖仓表质量监控
  3. 下游服务从文件消费切换为湖仓消费
