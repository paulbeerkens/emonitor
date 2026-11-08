from datetime import datetime, timezone

from ComEdPrices import ComEdPriceUpdater


class FakeDatabase:
  def __init__(self):
    self.stored = None

  def store_comed_price_samples(self, samples, *, retrieved_at):
    self.stored = samples
    return {"samples": len(samples), "half_hours": 1}


def test_refresh_runs_once_per_five_minutes(monkeypatch):
  database = FakeDatabase()
  updater = ComEdPriceUpdater(database)
  samples = [(datetime(2026, 10, 25, 14, 5, tzinfo=timezone.utc), 2.0)]
  monkeypatch.setattr(updater, "_download_samples", lambda start, end: samples)
  now = datetime(2026, 10, 25, 15, tzinfo=timezone.utc)

  assert updater.refresh_if_due(now) == {"samples": 1, "half_hours": 1}
  assert updater.refresh_if_due(now) is None
  assert updater.refresh_if_due(now.replace(minute=5)) == {
    "samples": 1, "half_hours": 1,
  }
  assert database.stored[0][1] == 2.0
