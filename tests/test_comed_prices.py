from datetime import datetime, timezone

from ComEdPrices import ComEdPriceUpdater


class FakeDatabase:
  def __init__(self, last_update=None):
    self.last_update = last_update
    self.stored = None

  def load_last_comed_price_update(self):
    return self.last_update

  def store_comed_hourly_prices(self, prices):
    self.stored = prices


def test_average_by_hour_uses_all_five_minute_samples():
  samples = [
    (datetime(2026, 10, 25, 14, 5, tzinfo=timezone.utc), 2.0),
    (datetime(2026, 10, 25, 14, 10, tzinfo=timezone.utc), 4.0),
    (datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc), 9.0),
  ]

  prices = ComEdPriceUpdater._average_by_hour(samples)

  assert prices == [
    {
      "hour_start": datetime(2026, 10, 25, 14, tzinfo=timezone.utc),
      "price_cents_per_kwh": 3.0,
      "source_sample_count": 2,
    },
    {
      "hour_start": datetime(2026, 10, 25, 15, tzinfo=timezone.utc),
      "price_cents_per_kwh": 9.0,
      "source_sample_count": 1,
    },
  ]


def test_refresh_runs_only_once_per_local_day(monkeypatch):
  database = FakeDatabase()
  updater = ComEdPriceUpdater(database)
  samples = [(datetime(2026, 10, 25, 14, 5, tzinfo=timezone.utc), 2.0)]
  monkeypatch.setattr(updater, "_download_samples", lambda start, end: samples)
  now = datetime(2026, 10, 25, 15, tzinfo=timezone.utc)

  assert updater.refresh_if_due(now) == 1
  assert updater.refresh_if_due(now) is None
  assert database.stored[0]["price_cents_per_kwh"] == 2.0
