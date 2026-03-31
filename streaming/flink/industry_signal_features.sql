CREATE TABLE external_signal_events (
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
  'properties.group.id' = 'opspilot-flink-signal-window',
  'scan.startup.mode' = 'earliest-offset',
  'format' = 'json',
  'json.fail-on-missing-field' = 'true',
  'json.ignore-parse-errors' = 'false'
);

CREATE TABLE company_signal_window (
  window_start TIMESTAMP_LTZ(3),
  window_end TIMESTAMP_LTZ(3),
  company_name STRING,
  subindustry STRING,
  external_heat BIGINT,
  periodic_report_count BIGINT,
  company_research_count BIGINT,
  industry_research_count BIGINT,
  company_snapshot_count BIGINT,
  latest_event_time TIMESTAMP_LTZ(3)
) WITH (
  'connector' = 'filesystem',
  'path' = 'file:///workspace/data/silver/official/stream/flink_company_signal_window',
  'format' = 'json'
);

INSERT INTO company_signal_window
SELECT
  window_start,
  window_end,
  company_name,
  MAX(subindustry) AS subindustry,
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
