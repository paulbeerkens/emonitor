import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta_data (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  input INTEGER NOT NULL,
  rating INTEGER NOT NULL,
  voltage INTEGER NOT NULL,
  paired INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_usage (
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  id INTEGER NOT NULL,
  energy_wh REAL NOT NULL,
  minimum_power_watts INTEGER NOT NULL,
  maximum_power_watts INTEGER NOT NULL,
  average_power_watts REAL NOT NULL,
  measured_seconds REAL NOT NULL,
  sample_count INTEGER NOT NULL,
  coverage_percent REAL NOT NULL,
  PRIMARY KEY (period_start, id)
);

CREATE INDEX IF NOT EXISTS channel_usage_id_period
ON channel_usage (id, period_end DESC);

CREATE TABLE IF NOT EXISTS collector_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  state_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comed_hourly_prices (
  hour_start TEXT PRIMARY KEY,
  price_cents_per_kwh REAL NOT NULL,
  source_sample_count INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS comed_hourly_prices_hour_start
ON comed_hourly_prices (hour_start DESC);
"""


class EMonitorDB:
  """SQLite storage shared by the collector and web application."""

  def __init__(self, database_path: str | Path = "db/emonitor.db"):
    self.database_path = Path(database_path).expanduser().resolve()
    self.database_path.parent.mkdir(parents=True, exist_ok=True)
    self._initialize()

  @contextmanager
  def _connect(self) -> Iterator[sqlite3.Connection]:
    """Open a database connection and always close it after the operation."""
    connection = sqlite3.connect(self.database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
      with connection:
        yield connection
    finally:
      connection.close()

  def _initialize(self) -> None:
    with self._connect() as connection:
      connection.execute("PRAGMA journal_mode=WAL")
      connection.executescript(SCHEMA)
      existing_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(channel_usage)")
      }
      migrations = {
        "average_power_watts": "REAL NOT NULL DEFAULT 0",
        "sample_count": "INTEGER NOT NULL DEFAULT 0",
        "coverage_percent": "REAL NOT NULL DEFAULT 0",
      }
      for column, definition in migrations.items():
        if column not in existing_columns:
          connection.execute(
            f"ALTER TABLE channel_usage ADD COLUMN {column} {definition}"
          )
      connection.execute(
        """
        UPDATE channel_usage
        SET average_power_watts = energy_wh * 3600 / measured_seconds,
            coverage_percent = measured_seconds / 1800 * 100
        WHERE measured_seconds > 0 AND average_power_watts = 0
        """
      )

  def store_channel_metadata(self, channels: list[dict[str, Any]]) -> None:
    rows = [
      (
        row["channel_id"], row["name"], int(row["is_input"]),
        row["rating_amps"], row["voltage"], row["paired_channel_id"],
      )
      for row in channels
    ]
    with self._connect() as connection:
      connection.executemany(
        """
        INSERT INTO meta_data (id, name, input, rating, voltage, paired)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          name=excluded.name, input=excluded.input, rating=excluded.rating,
          voltage=excluded.voltage, paired=excluded.paired
        """,
        rows,
      )

  def load_channel_metadata(self) -> list[dict[str, Any]]:
    with self._connect() as connection:
      rows = connection.execute(
        "SELECT id, name, input, rating, voltage, paired FROM meta_data ORDER BY id"
      ).fetchall()
    return [
      {
        "channel_id": row["id"],
        "name": row["name"],
        "is_input": bool(row["input"]),
        "rating_amps": row["rating"],
        "voltage": row["voltage"],
        "paired_channel_id": row["paired"],
      }
      for row in rows
    ]

  def store_usage_and_checkpoint(
    self, summaries: list[dict[str, Any]], accumulator_state: dict[str, Any]
  ) -> None:
    rows = [
      (
        summary["period_start"].isoformat(),
        summary["period_end"].isoformat(),
        summary["channel_id"],
        summary["energy_wh"],
        summary["minimum_power_watts"],
        summary["maximum_power_watts"],
        summary["average_power_watts"],
        summary["measured_seconds"],
        summary["sample_count"],
        summary["coverage_percent"],
      )
      for summary in summaries
    ]
    with self._connect() as connection:
      connection.executemany(
        """
        INSERT OR REPLACE INTO channel_usage (
          period_start, period_end, id, energy_wh, minimum_power_watts,
          maximum_power_watts, average_power_watts, measured_seconds,
          sample_count, coverage_percent
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
      )
      connection.execute(
        """
        INSERT OR REPLACE INTO collector_state (id, state_json, updated_at)
        VALUES (1, ?, ?)
        """,
        (json.dumps(accumulator_state), datetime.now(timezone.utc).isoformat()),
      )

  def load_accumulator_state(self) -> dict[str, Any] | None:
    with self._connect() as connection:
      row = connection.execute(
        "SELECT state_json FROM collector_state WHERE id = 1"
      ).fetchone()
    return json.loads(row["state_json"]) if row else None

  def load_latest_usage(self) -> list[dict[str, Any]]:
    with self._connect() as connection:
      rows = connection.execute(
        """
        SELECT u.id, COALESCE(m.name, 'NA') AS name, u.period_start,
               u.period_end, u.energy_wh, u.minimum_power_watts,
               u.maximum_power_watts, u.average_power_watts,
               u.measured_seconds, u.sample_count, u.coverage_percent
        FROM channel_usage AS u
        LEFT JOIN meta_data AS m ON m.id = u.id
        INNER JOIN (
          SELECT id, MAX(period_end) AS latest_period_end
          FROM channel_usage GROUP BY id
        ) AS latest
          ON latest.id = u.id AND latest.latest_period_end = u.period_end
        ORDER BY u.id
        """
      ).fetchall()

    result = []
    for row in rows:
      item = dict(row)
      item["period_start"] = datetime.fromisoformat(item["period_start"])
      item["period_end"] = datetime.fromisoformat(item["period_end"])
      result.append(item)
    return result

  def store_comed_hourly_prices(self, prices: list[dict[str, Any]]) -> None:
    updated_at = datetime.now(timezone.utc).isoformat()
    rows = [
      (
        price["hour_start"].astimezone(timezone.utc).isoformat(),
        price["price_cents_per_kwh"],
        price["source_sample_count"],
        updated_at,
      )
      for price in prices
    ]
    with self._connect() as connection:
      connection.executemany(
        """
        INSERT INTO comed_hourly_prices (
          hour_start, price_cents_per_kwh, source_sample_count, updated_at
        ) VALUES (?, ?, ?, ?)
        ON CONFLICT(hour_start) DO UPDATE SET
          price_cents_per_kwh=excluded.price_cents_per_kwh,
          source_sample_count=excluded.source_sample_count,
          updated_at=excluded.updated_at
        """,
        rows,
      )

  def load_last_comed_price_update(self) -> datetime | None:
    with self._connect() as connection:
      row = connection.execute(
        "SELECT MAX(updated_at) AS updated_at FROM comed_hourly_prices"
      ).fetchone()
    return datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None

EMonitorDBReader = EMonitorDB
