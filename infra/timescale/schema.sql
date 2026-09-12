-- Telemetry schema. Idempotent: migrate applies it on every start.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 5-minute line samples from business-sim (history backfill is hourly).
CREATE TABLE IF NOT EXISTS line_metric (
    time            timestamptz NOT NULL,
    circuit_id      text        NOT NULL,
    rx_power_dbm    real,
    tx_power_dbm    real,
    snr_db          real,
    sync_down_mbps  real NOT NULL DEFAULT 0,
    sync_up_mbps    real NOT NULL DEFAULT 0,
    latency_ms      real NOT NULL DEFAULT 0,
    jitter_ms       real NOT NULL DEFAULT 0,
    packet_loss_pct real NOT NULL DEFAULT 0,
    crc_errors      integer NOT NULL DEFAULT 0,
    resyncs         integer NOT NULL DEFAULT 0
);
SELECT create_hypertable('line_metric', by_range('time', INTERVAL '1 day'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_line_metric_circuit_time ON line_metric (circuit_id, time DESC);
ALTER TABLE line_metric SET (timescaledb.compress, timescaledb.compress_segmentby = 'circuit_id');
SELECT add_compression_policy('line_metric', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('line_metric', INTERVAL '90 days', if_not_exists => TRUE);

-- 15-minute usage samples.
CREATE TABLE IF NOT EXISTS usage_sample (
    time            timestamptz NOT NULL,
    subscription_id text        NOT NULL,
    down_gb         real NOT NULL DEFAULT 0,
    up_gb           real NOT NULL DEFAULT 0
);
SELECT create_hypertable('usage_sample', by_range('time', INTERVAL '7 days'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_usage_sub_time ON usage_sample (subscription_id, time DESC);

CREATE TABLE IF NOT EXISTS olt_metric (
    time            timestamptz NOT NULL,
    olt_id          text        NOT NULL,
    utilisation_pct real NOT NULL,
    uplink_status   text NOT NULL
);
SELECT create_hypertable('olt_metric', by_range('time', INTERVAL '7 days'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_olt_metric_olt_time ON olt_metric (olt_id, time DESC);

CREATE TABLE IF NOT EXISTS cell_metric (
    time            timestamptz NOT NULL,
    site_id         text        NOT NULL,
    utilisation_pct real NOT NULL,
    status          text NOT NULL
);
SELECT create_hypertable('cell_metric', by_range('time', INTERVAL '7 days'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_cell_metric_site_time ON cell_metric (site_id, time DESC);

-- Real-time continuous aggregates (materialized_only = false includes the newest raw rows).
CREATE MATERIALIZED VIEW IF NOT EXISTS line_metric_1h
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '1 hour', time) AS bucket,
       circuit_id,
       avg(rx_power_dbm)    AS rx_power_dbm,
       avg(tx_power_dbm)    AS tx_power_dbm,
       avg(snr_db)          AS snr_db,
       avg(sync_down_mbps)  AS sync_down_mbps,
       avg(sync_up_mbps)    AS sync_up_mbps,
       avg(latency_ms)      AS latency_ms,
       avg(jitter_ms)       AS jitter_ms,
       avg(packet_loss_pct) AS packet_loss_pct,
       sum(crc_errors)      AS crc_errors,
       sum(resyncs)         AS resyncs,
       min(rx_power_dbm)    AS min_rx_power_dbm
FROM line_metric
GROUP BY bucket, circuit_id
WITH NO DATA;
SELECT add_continuous_aggregate_policy('line_metric_1h',
    start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS usage_1h
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '1 hour', time) AS bucket, subscription_id,
       sum(down_gb) AS down_gb, sum(up_gb) AS up_gb
FROM usage_sample
GROUP BY bucket, subscription_id
WITH NO DATA;
SELECT add_continuous_aggregate_policy('usage_1h',
    start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE);

-- Daily usage in Colombo days, the unit billing cycles are counted in.
CREATE MATERIALIZED VIEW IF NOT EXISTS usage_1d
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '1 day', time, 'Asia/Colombo') AS bucket, subscription_id,
       sum(down_gb) AS down_gb, sum(up_gb) AS up_gb
FROM usage_sample
GROUP BY bucket, subscription_id
WITH NO DATA;
SELECT add_continuous_aggregate_policy('usage_1d',
    start_offset => INTERVAL '120 days', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
