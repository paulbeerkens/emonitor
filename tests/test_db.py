import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from EMonitorDB import EMonitorDB


def test_connection_context_closes_database(tmp_path):
  db = EMonitorDB(tmp_path / "emonitor.db")

  with db._connect() as connection:
    connection.execute("SELECT 1").fetchone()

  with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
    connection.execute("SELECT 1").fetchone()


def test_store_and_load_latest_usage(tmp_path):
  db = EMonitorDB(tmp_path / "emonitor.db")
  db.store_channel_metadata([
    {
      "channel_id": 1, "name": "Kitchen", "is_input": True,
      "rating_amps": 100, "voltage": 120, "paired_channel_id": 0,
    }
  ])
  accumulator_state = {"last_sample_time": "2026-10-25T10:30:00+00:00"}
  db.store_usage_and_checkpoint([{
    "period_start": datetime.fromisoformat("2026-10-25T10:00:00+00:00"),
    "period_end": datetime.fromisoformat("2026-10-25T10:30:00+00:00"),
    "channel_id": 1,
    "energy_wh": 125.5,
    "minimum_power_watts": 100,
    "maximum_power_watts": 600,
    "average_power_watts": 251.0,
    "measured_seconds": 1800,
    "sample_count": 180,
    "coverage_percent": 100.0,
  }], accumulator_state)

  assert db.load_latest_usage() == [{
    "id": 1,
    "name": "Kitchen",
    "period_start": datetime.fromisoformat("2026-10-25T10:00:00+00:00"),
    "period_end": datetime.fromisoformat("2026-10-25T10:30:00+00:00"),
    "energy_wh": 125.5,
    "minimum_power_watts": 100,
    "maximum_power_watts": 600,
    "average_power_watts": 251.0,
    "measured_seconds": 1800,
    "sample_count": 180,
    "coverage_percent": 100.0,
  }]
  assert db.load_accumulator_state() == accumulator_state

  with db._connect() as connection:
    assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_store_comed_hourly_prices_upserts_existing_hour(tmp_path):
  db = EMonitorDB(tmp_path / "emonitor.db")
  hour_start = datetime(2026, 10, 25, 18, tzinfo=timezone.utc)
  db.store_comed_hourly_prices([{
    "hour_start": hour_start,
    "price_cents_per_kwh": 3.5,
    "source_sample_count": 12,
  }])
  db.store_comed_hourly_prices([{
    "hour_start": hour_start,
    "price_cents_per_kwh": 4.25,
    "source_sample_count": 11,
  }])

  with db._connect() as connection:
    row = connection.execute(
      "SELECT * FROM comed_hourly_prices WHERE hour_start = ?",
      (hour_start.isoformat(),),
    ).fetchone()

  assert row["price_cents_per_kwh"] == 4.25
  assert row["source_sample_count"] == 11
  assert db.load_last_comed_price_update() is not None


def test_comed_samples_are_restart_safe_and_rebuild_half_hours(tmp_path):
  db = EMonitorDB(tmp_path / "emonitor.db")
  start = datetime(2026, 10, 25, 14, 0, tzinfo=timezone.utc)
  first = [(start + timedelta(minutes=offset), 2.0 + offset / 10)
           for offset in (0, 5, 10, 15)]
  complete = [(start + timedelta(minutes=offset), 2.0 + offset / 10)
              for offset in (0, 5, 10, 15, 20, 25)]

  db.store_comed_price_samples(first, retrieved_at=start + timedelta(minutes=16))
  db.store_comed_price_samples(
    complete, retrieved_at=start + timedelta(minutes=31)
  )

  with db._connect() as connection:
    assert connection.execute(
      "SELECT COUNT(*) FROM comed_price_samples"
    ).fetchone()[0] == 6
    row = connection.execute(
      "SELECT * FROM comed_half_hour_prices"
    ).fetchone()

  assert row["sample_count"] == 6
  assert row["price_sum_cents_per_kwh"] == pytest.approx(
    sum(price for _, price in complete)
  )
  assert row["average_price_cents_per_kwh"] == pytest.approx(
    sum(price for _, price in complete) / 6
  )
  assert row["is_complete"] == 1


def test_stores_and_prunes_detailed_power_samples(tmp_path):
  db = EMonitorDB(tmp_path / "emonitor.db")
  db.store_channel_metadata([
    {
      "channel_id": 1, "name": "Kitchen", "is_input": False,
      "rating_amps": 20, "voltage": 120, "paired_channel_id": 0,
    },
    {
      "channel_id": 2, "name": "Living Room", "is_input": False,
      "rating_amps": 20, "voltage": 120, "paired_channel_id": 0,
    },
  ])
  old_time = datetime.fromisoformat("2026-10-01T12:00:00+00:00")
  recent_time = datetime.fromisoformat("2026-10-09T12:00:00+00:00")

  db.store_usage_and_checkpoint(
    [], {}, sampled_at=old_time,
    readings=[{"channel_id": 1, "power_watts": 100}],
  )
  db.store_usage_and_checkpoint(
    [], {}, sampled_at=recent_time,
    readings=[
      {"channel_id": 1, "power_watts": 250},
      {"channel_id": 2, "power_watts": 75},
    ],
  )

  with db._connect() as connection:
    assert connection.execute("SELECT COUNT(*) FROM power_samples").fetchone()[0] == 3

  db.store_usage_and_checkpoint(
    [], {}, sampled_at=recent_time + timedelta(seconds=15),
    readings=[{"channel_id": 1, "power_watts": 275}],
    prune_samples=True,
  )

  samples = db.load_power_samples(
    recent_time - timedelta(minutes=1),
    recent_time + timedelta(minutes=1),
    channel_ids=[1],
  )
  assert samples == [
    {
      "sampled_at": recent_time,
      "channel_id": 1,
      "channel_name": "Kitchen",
      "power_watts": 250,
    },
    {
      "sampled_at": recent_time + timedelta(seconds=15),
      "channel_id": 1,
      "channel_name": "Kitchen",
      "power_watts": 275,
    },
  ]

  with db._connect() as connection:
    assert connection.execute("SELECT COUNT(*) FROM power_samples").fetchone()[0] == 3
