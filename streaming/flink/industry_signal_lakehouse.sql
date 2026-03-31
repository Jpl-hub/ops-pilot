-- OpsPilot-X 流式湖仓升级版
-- 目标：
-- 1. 保留 Kafka 外部信号源；
-- 2. 把公司级窗口特征、子行业热度、异动评分直接写入 Paimon；
-- 3. 通过 Iceberg 兼容元数据，把结果暴露给 Spark / Trino / Iceberg Reader。

SET 'table.local-time-zone' = 'Asia/Shanghai';

CREATE TEMPORARY TABLE external_signal_events (
  event_id STRING,
  ingest_batch_id STRING,
  event_time TIMESTAMP_LTZ(3),
  publish_date STRING,
  signal_kind STRING,
  signal_status STRING,
  priority INT,
  source STRING,
  source_name STRING,
  company_name STRING,
  industry_name STRING,
  security_code STRING,
  exchange STRING,
  subindustry STRING,
  headline STRING,
  source_url STRING,
  detail_url STRING,
  local_path STRING,
  is_summary BOOLEAN,
  report_type STRING,
  ingested_at TIMESTAMP_LTZ(3),
  WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = 'opspilot.external_signals',
  'properties.bootstrap.servers' = 'redpanda:9092',
  'properties.group.id' = 'opspilot-flink-lakehouse',
  'scan.startup.mode' = 'earliest-offset',
  'format' = 'json',
  'json.fail-on-missing-field' = 'true',
  'json.ignore-parse-errors' = 'false'
);

CREATE CATALOG ops_pilot_lakehouse WITH (
  'type' = 'paimon',
  'warehouse' = 'file:///workspace/data/lakehouse/paimon'
);

USE CATALOG ops_pilot_lakehouse;

CREATE DATABASE IF NOT EXISTS opspilot_rt;
USE opspilot_rt;

CREATE TABLE IF NOT EXISTS company_signal_window_rt (
  window_date STRING,
  window_hour STRING,
  window_start TIMESTAMP_LTZ(3),
  window_end TIMESTAMP_LTZ(3),
  company_name STRING,
  subindustry STRING,
  signal_count BIGINT,
  external_heat BIGINT,
  periodic_report_count BIGINT,
  company_research_count BIGINT,
  industry_research_count BIGINT,
  company_snapshot_count BIGINT,
  latest_event_time TIMESTAMP_LTZ(3),
  PRIMARY KEY (window_date, window_hour, company_name) NOT ENFORCED
) PARTITIONED BY (window_date, window_hour)
WITH (
  'bucket' = '4',
  'metadata.iceberg.storage' = 'hadoop-catalog'
);

CREATE TABLE IF NOT EXISTS company_signal_anomaly_rt (
  window_date STRING,
  window_hour STRING,
  window_start TIMESTAMP_LTZ(3),
  window_end TIMESTAMP_LTZ(3),
  company_name STRING,
  subindustry STRING,
  signal_count BIGINT,
  source_count BIGINT,
  external_heat BIGINT,
  periodic_report_count BIGINT,
  company_research_count BIGINT,
  industry_research_count BIGINT,
  company_snapshot_count BIGINT,
  latest_event_time TIMESTAMP_LTZ(3),
  anomaly_score BIGINT,
  anomaly_level STRING,
  PRIMARY KEY (window_date, window_hour, company_name) NOT ENFORCED
) PARTITIONED BY (window_date, window_hour)
WITH (
  'bucket' = '4',
  'metadata.iceberg.storage' = 'hadoop-catalog'
);

CREATE TABLE IF NOT EXISTS subindustry_signal_window_rt (
  window_date STRING,
  window_hour STRING,
  window_start TIMESTAMP_LTZ(3),
  window_end TIMESTAMP_LTZ(3),
  subindustry STRING,
  signal_count BIGINT,
  external_heat BIGINT,
  periodic_report_count BIGINT,
  company_research_count BIGINT,
  industry_research_count BIGINT,
  company_snapshot_count BIGINT,
  latest_event_time TIMESTAMP_LTZ(3),
  PRIMARY KEY (window_date, window_hour, subindustry) NOT ENFORCED
) PARTITIONED BY (window_date, window_hour)
WITH (
  'bucket' = '4',
  'metadata.iceberg.storage' = 'hadoop-catalog'
);

CREATE TEMPORARY VIEW company_signal_window_base AS
SELECT
  DATE_FORMAT(window_start, 'yyyyMMdd') AS window_date,
  DATE_FORMAT(window_start, 'HH') AS window_hour,
  window_start,
  window_end,
  company_name,
  MAX(subindustry) AS subindustry,
  COUNT(*) AS signal_count,
  SUM(
    CASE signal_kind
      WHEN 'periodic_report' THEN 4
      WHEN 'company_research' THEN 3
      WHEN 'industry_research' THEN 2
      ELSE 1
    END
  ) AS external_heat,
  SUM(CASE WHEN signal_kind = 'periodic_report' THEN 1 ELSE 0 END) AS periodic_report_count,
  SUM(CASE WHEN signal_kind = 'company_research' THEN 1 ELSE 0 END) AS company_research_count,
  SUM(CASE WHEN signal_kind = 'industry_research' THEN 1 ELSE 0 END) AS industry_research_count,
  SUM(CASE WHEN signal_kind = 'company_snapshot' THEN 1 ELSE 0 END) AS company_snapshot_count,
  MAX(event_time) AS latest_event_time
FROM TABLE(
  TUMBLE(TABLE external_signal_events, DESCRIPTOR(event_time), INTERVAL '1' HOUR)
)
GROUP BY
  window_start,
  window_end,
  company_name;

CREATE TEMPORARY VIEW company_signal_anomaly_base AS
SELECT
  window_date,
  window_hour,
  window_start,
  window_end,
  company_name,
  subindustry,
  signal_count,
  (
    CASE WHEN periodic_report_count > 0 THEN 1 ELSE 0 END +
    CASE WHEN company_research_count > 0 THEN 1 ELSE 0 END +
    CASE WHEN industry_research_count > 0 THEN 1 ELSE 0 END +
    CASE WHEN company_snapshot_count > 0 THEN 1 ELSE 0 END
  ) AS source_count,
  external_heat,
  periodic_report_count,
  company_research_count,
  industry_research_count,
  company_snapshot_count,
  latest_event_time,
  CAST(
    external_heat * 3 +
    signal_count * 4 +
    CASE WHEN periodic_report_count > 0 THEN 8 ELSE 0 END +
    CASE WHEN company_research_count > 0 THEN 5 ELSE 0 END +
    CASE WHEN industry_research_count > 0 THEN 3 ELSE 0 END +
    CASE WHEN company_snapshot_count > 0 THEN 2 ELSE 0 END
    AS BIGINT
  ) AS anomaly_score
FROM company_signal_window_base;

CREATE TEMPORARY VIEW subindustry_signal_window_base AS
SELECT
  DATE_FORMAT(window_start, 'yyyyMMdd') AS window_date,
  DATE_FORMAT(window_start, 'HH') AS window_hour,
  window_start,
  window_end,
  subindustry,
  COUNT(*) AS signal_count,
  SUM(
    CASE signal_kind
      WHEN 'periodic_report' THEN 4
      WHEN 'company_research' THEN 3
      WHEN 'industry_research' THEN 2
      ELSE 1
    END
  ) AS external_heat,
  SUM(CASE WHEN signal_kind = 'periodic_report' THEN 1 ELSE 0 END) AS periodic_report_count,
  SUM(CASE WHEN signal_kind = 'company_research' THEN 1 ELSE 0 END) AS company_research_count,
  SUM(CASE WHEN signal_kind = 'industry_research' THEN 1 ELSE 0 END) AS industry_research_count,
  SUM(CASE WHEN signal_kind = 'company_snapshot' THEN 1 ELSE 0 END) AS company_snapshot_count,
  MAX(event_time) AS latest_event_time
FROM TABLE(
  TUMBLE(TABLE external_signal_events, DESCRIPTOR(event_time), INTERVAL '1' HOUR)
)
GROUP BY
  window_start,
  window_end,
  subindustry;

EXECUTE STATEMENT SET
BEGIN

INSERT INTO company_signal_window_rt
SELECT
  window_date,
  window_hour,
  window_start,
  window_end,
  company_name,
  subindustry,
  signal_count,
  external_heat,
  periodic_report_count,
  company_research_count,
  industry_research_count,
  company_snapshot_count,
  latest_event_time
FROM company_signal_window_base;

INSERT INTO company_signal_anomaly_rt
SELECT
  window_date,
  window_hour,
  window_start,
  window_end,
  company_name,
  subindustry,
  signal_count,
  source_count,
  external_heat,
  periodic_report_count,
  company_research_count,
  industry_research_count,
  company_snapshot_count,
  latest_event_time,
  anomaly_score,
  CASE
    WHEN anomaly_score >= 32 THEN 'critical'
    WHEN anomaly_score >= 24 THEN 'high'
    WHEN anomaly_score >= 16 THEN 'medium'
    ELSE 'low'
  END AS anomaly_level
FROM company_signal_anomaly_base;

INSERT INTO subindustry_signal_window_rt
SELECT
  window_date,
  window_hour,
  window_start,
  window_end,
  subindustry,
  signal_count,
  external_heat,
  periodic_report_count,
  company_research_count,
  industry_research_count,
  company_snapshot_count,
  latest_event_time
FROM subindustry_signal_window_base;

END;
