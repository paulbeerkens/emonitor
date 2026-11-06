from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from EMonitorWebPage import ChannelMetadata, PowerReading


class ChannelUsageSummary(TypedDict):
  period_start: datetime
  period_end: datetime
  channel_id: int
  energy_wh: float
  minimum_power_watts: int
  maximum_power_watts: int
  average_power_watts: float
  measured_seconds: float
  sample_count: int
  coverage_percent: float


def combine_paired_channels(
  readings: list[PowerReading], channels: list[ChannelMetadata]
) -> list[PowerReading]:
  """Combine reciprocal channel pairs into one logical circuit."""
  readings_by_id = {reading["channel_id"]: reading for reading in readings}
  paired_by_id = {
    channel["channel_id"]: channel["paired_channel_id"] for channel in channels
  }
  combined = []
  consumed_channel_ids: set[int] = set()

  for channel_id in sorted(readings_by_id):
    if channel_id in consumed_channel_ids:
      continue

    reading = readings_by_id[channel_id]
    paired_id = paired_by_id.get(channel_id, 0)
    pair_is_reciprocal = paired_by_id.get(paired_id) == channel_id
    if paired_id in readings_by_id and pair_is_reciprocal:
      paired_reading = readings_by_id[paired_id]
      combined.append({
        "channel_id": min(channel_id, paired_id),
        "channel_name": reading["channel_name"],
        "power_watts": reading["power_watts"] + paired_reading["power_watts"],
      })
      consumed_channel_ids.update({channel_id, paired_id})
    else:
      combined.append(reading)
      consumed_channel_ids.add(channel_id)

  return combined


class HalfHourEnergyAccumulator:
  """Integrate sampled watts into clock-aligned UTC energy summaries."""

  def __init__(self, interval_minutes: int = 30, maximum_gap_seconds: float = 60):
    if interval_minutes <= 0 or 60 % interval_minutes != 0:
      raise ValueError(
        "The accumulation interval must be greater than zero and divide evenly "
        "into one hour (for example: 5, 10, 15, 20, 30, or 60 minutes)"
      )
    if maximum_gap_seconds <= 0:
      raise ValueError("The maximum sample gap must be greater than zero")

    self.interval_minutes = interval_minutes
    self.maximum_gap_seconds = maximum_gap_seconds
    self.period_start: datetime | None = None
    self.period_end: datetime | None = None
    self.last_sample_time: datetime | None = None
    self.last_readings: dict[int, PowerReading] = {}
    self.energy_watt_seconds: dict[int, float] = {}
    self.measured_seconds: dict[int, float] = {}
    self.minimum_power: dict[int, int] = {}
    self.maximum_power: dict[int, int] = {}
    self.sample_count: dict[int, int] = {}

  @staticmethod
  def _as_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
      raise ValueError("Sample timestamps must include a timezone")
    return timestamp.astimezone(timezone.utc)

  def _period_containing(self, timestamp: datetime) -> tuple[datetime, datetime]:
    period_minute = (timestamp.minute // self.interval_minutes) * self.interval_minutes
    start = timestamp.replace(minute=period_minute, second=0, microsecond=0)
    return start, start + timedelta(minutes=self.interval_minutes)

  def _record_extrema(self, readings: dict[int, PowerReading]) -> None:
    for channel_id, reading in readings.items():
      power = reading["power_watts"]
      self.minimum_power[channel_id] = min(
        power, self.minimum_power.get(channel_id, power)
      )
      self.maximum_power[channel_id] = max(
        power, self.maximum_power.get(channel_id, power)
      )

  def _record_sample(self, readings: dict[int, PowerReading]) -> None:
    self._record_extrema(readings)
    for channel_id in readings:
      self.sample_count[channel_id] = self.sample_count.get(channel_id, 0) + 1

  def _integrate(self, seconds: float) -> None:
    for channel_id, reading in self.last_readings.items():
      self.energy_watt_seconds[channel_id] = (
        self.energy_watt_seconds.get(channel_id, 0.0)
        + reading["power_watts"] * seconds
      )
      self.measured_seconds[channel_id] = (
        self.measured_seconds.get(channel_id, 0.0) + seconds
      )

  def _finish_period(self) -> list[ChannelUsageSummary]:
    assert self.period_start is not None
    assert self.period_end is not None
    period_seconds = (self.period_end - self.period_start).total_seconds()
    channel_ids = sorted(
      set(self.energy_watt_seconds) | set(self.sample_count) | set(self.minimum_power)
    )
    summaries = []
    for channel_id in channel_ids:
      measured_seconds = self.measured_seconds.get(channel_id, 0.0)
      energy_wh = self.energy_watt_seconds.get(channel_id, 0.0) / 3600
      average_power = (
        energy_wh * 3600 / measured_seconds if measured_seconds else 0.0
      )
      summaries.append({
        "period_start": self.period_start,
        "period_end": self.period_end,
        "channel_id": channel_id,
        "energy_wh": energy_wh,
        "minimum_power_watts": self.minimum_power[channel_id],
        "maximum_power_watts": self.maximum_power[channel_id],
        "average_power_watts": average_power,
        "measured_seconds": measured_seconds,
        "sample_count": self.sample_count.get(channel_id, 0),
        "coverage_percent": measured_seconds / period_seconds * 100,
      })
    return summaries

  def _begin_next_period(self, carry_previous_power: bool) -> None:
    assert self.period_end is not None
    self.period_start = self.period_end
    self.period_end = self.period_start + timedelta(minutes=self.interval_minutes)
    self.energy_watt_seconds = {}
    self.measured_seconds = {}
    self.minimum_power = {}
    self.maximum_power = {}
    self.sample_count = {}
    if carry_previous_power:
      self._record_extrema(self.last_readings)

  def add_sample(
    self, readings: list[PowerReading], sampled_at: datetime
  ) -> list[ChannelUsageSummary]:
    """Add a poll and return any periods completed by this sample."""
    sampled_at = self._as_utc(sampled_at)
    current_readings = {reading["channel_id"]: reading for reading in readings}

    if self.last_sample_time is None:
      self.period_start, self.period_end = self._period_containing(sampled_at)
      self.last_sample_time = sampled_at
      self.last_readings = current_readings
      self._record_sample(current_readings)
      return []

    if sampled_at <= self.last_sample_time:
      raise ValueError("Sample timestamps must increase")

    elapsed_seconds = (sampled_at - self.last_sample_time).total_seconds()
    gap_is_usable = elapsed_seconds <= self.maximum_gap_seconds
    completed_periods = []
    cursor = self.last_sample_time
    assert self.period_end is not None

    while cursor < sampled_at:
      segment_end = min(sampled_at, self.period_end)
      if gap_is_usable:
        self._integrate((segment_end - cursor).total_seconds())
      cursor = segment_end

      if cursor == self.period_end:
        completed_periods.extend(self._finish_period())
        self._begin_next_period(carry_previous_power=gap_is_usable)

    self.last_sample_time = sampled_at
    self.last_readings = current_readings
    self._record_sample(current_readings)
    return completed_periods

  def export_state(self) -> dict[str, Any]:
    """Return JSON-serializable state for restart recovery."""
    return {
      "period_start": self.period_start.isoformat() if self.period_start else None,
      "period_end": self.period_end.isoformat() if self.period_end else None,
      "last_sample_time": (
        self.last_sample_time.isoformat() if self.last_sample_time else None
      ),
      "last_readings": list(self.last_readings.values()),
      "energy_watt_seconds": self.energy_watt_seconds,
      "measured_seconds": self.measured_seconds,
      "minimum_power": self.minimum_power,
      "maximum_power": self.maximum_power,
      "sample_count": self.sample_count,
    }

  def recovery_statistics(self) -> tuple[int, float, int]:
    """Summarize the in-progress checkpoint without double-counting channels."""
    channel_ids = set(self.sample_count) | set(self.measured_seconds)
    return (
      max(self.sample_count.values(), default=0),
      max(self.measured_seconds.values(), default=0.0),
      len(channel_ids),
    )

  def restore_state(self, state: dict[str, Any]) -> None:
    """Restore state previously returned by export_state."""
    parse_time = lambda value: datetime.fromisoformat(value) if value else None
    self.period_start = parse_time(state.get("period_start"))
    self.period_end = parse_time(state.get("period_end"))
    self.last_sample_time = parse_time(state.get("last_sample_time"))
    self.last_readings = {
      reading["channel_id"]: reading for reading in state.get("last_readings", [])
    }
    for attribute in (
      "energy_watt_seconds", "measured_seconds", "minimum_power",
      "maximum_power", "sample_count",
    ):
      values = state.get(attribute, {})
      setattr(self, attribute, {int(key): value for key, value in values.items()})
