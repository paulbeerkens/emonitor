from datetime import datetime

import pytest

from EnergyAccumulator import HalfHourEnergyAccumulator, combine_paired_channels


def reading(power_watts):
  return [{
    "channel_id": 1,
    "channel_name": "Kitchen",
    "power_watts": power_watts,
  }]


def test_integrates_energy_and_tracks_minimum_and_maximum_power():
  accumulator = HalfHourEnergyAccumulator(maximum_gap_seconds=1200)

  assert accumulator.add_sample(
    reading(100), datetime.fromisoformat("2026-10-25T10:00:00+00:00")
  ) == []
  assert accumulator.add_sample(
    reading(200), datetime.fromisoformat("2026-10-25T10:10:00+00:00")
  ) == []
  summaries = accumulator.add_sample(
    reading(300), datetime.fromisoformat("2026-10-25T10:30:00+00:00")
  )

  assert len(summaries) == 1
  assert summaries[0]["energy_wh"] == pytest.approx(83.333333)
  assert summaries[0]["minimum_power_watts"] == 100
  assert summaries[0]["maximum_power_watts"] == 200
  assert summaries[0]["average_power_watts"] == pytest.approx(166.666667)
  assert summaries[0]["measured_seconds"] == 1800
  assert summaries[0]["sample_count"] == 2
  assert summaries[0]["coverage_percent"] == 100


def test_splits_elapsed_time_at_half_hour_boundary():
  accumulator = HalfHourEnergyAccumulator()
  accumulator.add_sample(
    reading(60), datetime.fromisoformat("2026-10-25T10:29:50+00:00")
  )
  summaries = accumulator.add_sample(
    reading(120), datetime.fromisoformat("2026-10-25T10:30:10+00:00")
  )

  assert len(summaries) == 1
  assert summaries[0]["energy_wh"] == pytest.approx(1 / 6)
  assert summaries[0]["measured_seconds"] == 10


def test_long_gap_is_excluded_from_energy_and_coverage():
  accumulator = HalfHourEnergyAccumulator(maximum_gap_seconds=60)
  accumulator.add_sample(
    reading(100), datetime.fromisoformat("2026-10-25T10:00:00+00:00")
  )
  accumulator.add_sample(
    reading(100), datetime.fromisoformat("2026-10-25T10:00:30+00:00")
  )
  accumulator.add_sample(
    reading(200), datetime.fromisoformat("2026-10-25T10:02:00+00:00")
  )
  summaries = accumulator.add_sample(
    reading(300), datetime.fromisoformat("2026-10-25T10:30:00+00:00")
  )

  assert summaries[0]["energy_wh"] == pytest.approx(100 * 30 / 3600)
  assert summaries[0]["measured_seconds"] == 30
  assert summaries[0]["sample_count"] == 3
  assert summaries[0]["coverage_percent"] == pytest.approx(30 / 1800 * 100)


def test_accumulator_state_survives_restart():
  first_process = HalfHourEnergyAccumulator(maximum_gap_seconds=1200)
  first_process.add_sample(
    reading(100), datetime.fromisoformat("2026-10-25T10:00:00+00:00")
  )
  first_process.add_sample(
    reading(200), datetime.fromisoformat("2026-10-25T10:10:00+00:00")
  )

  restarted_process = HalfHourEnergyAccumulator(maximum_gap_seconds=1200)
  restarted_process.restore_state(first_process.export_state())

  assert restarted_process.recovery_statistics() == (2, 600.0, 1)
  summaries = restarted_process.add_sample(
    reading(300), datetime.fromisoformat("2026-10-25T10:30:00+00:00")
  )

  assert summaries[0]["energy_wh"] == pytest.approx(83.333333)
  assert summaries[0]["measured_seconds"] == 1800


def test_combines_reciprocal_channel_pairs():
  readings = [
    {"channel_id": 3, "channel_name": "Air Conditioner", "power_watts": 700},
    {"channel_id": 4, "channel_name": "Air Conditioner", "power_watts": 500},
    {"channel_id": 5, "channel_name": "Kitchen", "power_watts": 100},
  ]
  channels = [
    {"channel_id": 3, "name": "Air Conditioner", "is_input": False,
     "rating_amps": 50, "voltage": 120, "paired_channel_id": 4},
    {"channel_id": 4, "name": "Air Conditioner", "is_input": False,
     "rating_amps": 50, "voltage": 120, "paired_channel_id": 3},
    {"channel_id": 5, "name": "Kitchen", "is_input": False,
     "rating_amps": 20, "voltage": 120, "paired_channel_id": 0},
  ]

  assert combine_paired_channels(readings, channels) == [
    {"channel_id": 3, "channel_name": "Air Conditioner", "power_watts": 1200},
    {"channel_id": 5, "channel_name": "Kitchen", "power_watts": 100},
  ]


def test_converts_sample_times_to_utc():
  accumulator = HalfHourEnergyAccumulator()
  accumulator.add_sample(
    reading(100), datetime.fromisoformat("2026-10-25T10:05:00-05:00")
  )

  assert accumulator.period_start == datetime.fromisoformat(
    "2026-10-25T15:00:00+00:00"
  )
