from datetime import datetime, timedelta, timezone

from ComEdPrices import ComEdPriceUpdater


class FakeDatabase:
  def __init__(self):
    self.stored = None

  def store_comed_price_samples(self, samples, *, retrieved_at):
    self.stored = samples
    return {"samples": len(samples), "half_hours": 1}


def test_refresh_calibrates_then_follows_comed_update_time(monkeypatch):
  database = FakeDatabase()
  updater = ComEdPriceUpdater(database)
  samples = [[(datetime(2026, 10, 25, 14, 5, tzinfo=timezone.utc), 2.0)]]
  monkeypatch.setattr(updater, "_download_samples", lambda start, end: samples[0])
  now = datetime(2026, 10, 25, 15, tzinfo=timezone.utc)

  first = updater.refresh_if_due(now)
  assert first["latest_changed"] is False
  assert first["next_refresh_seconds"] == 30
  assert updater.refresh_if_due(now + timedelta(seconds=29)) is None

  unchanged = updater.refresh_if_due(now + timedelta(seconds=30))
  assert unchanged["latest_changed"] is False
  assert unchanged["next_refresh_seconds"] == 30

  samples[0] = [
    (datetime(2026, 10, 25, 14, 10, tzinfo=timezone.utc), 2.5)
  ]
  changed = updater.refresh_if_due(now + timedelta(seconds=60))
  assert changed["latest_changed"] is True
  assert changed["next_refresh_seconds"] == 300
  assert updater.refresh_if_due(now + timedelta(seconds=359)) is None

  unchanged = updater.refresh_if_due(now + timedelta(seconds=360))
  assert unchanged["latest_changed"] is False
  assert unchanged["next_refresh_seconds"] == 30
  assert database.stored[0][1] == 2.5


def test_refresh_retries_quickly_after_failure(monkeypatch):
  updater = ComEdPriceUpdater(FakeDatabase())
  now = datetime(2026, 10, 25, 15, tzinfo=timezone.utc)
  attempts = 0

  def download(start, end):
    nonlocal attempts
    attempts += 1
    if attempts == 1:
      raise TimeoutError
    return [(datetime(2026, 10, 25, 14, 5, tzinfo=timezone.utc), 2.0)]

  monkeypatch.setattr(updater, "_download_samples", download)

  try:
    updater.refresh_if_due(now)
  except TimeoutError:
    pass
  assert updater.refresh_if_due(now + timedelta(seconds=29)) is None
  assert updater.refresh_if_due(now + timedelta(seconds=30)) is not None
