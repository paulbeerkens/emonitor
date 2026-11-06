import json
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


COMED_API_URL = "https://hourlypricing.comed.com/api"
CHICAGO = ZoneInfo("America/Chicago")


class ComEdPriceUpdater:
  """Download ComEd's 5-minute feed and store one average per hour."""

  def __init__(self, database, api_url: str = COMED_API_URL):
    self.database = database
    self.api_url = api_url
    self._last_attempt_date = None

  def refresh_if_due(self, now: datetime | None = None) -> int | None:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
      raise ValueError("now must include a timezone")

    local_now = now.astimezone(CHICAGO)
    if self._last_attempt_date == local_now.date():
      return None
    self._last_attempt_date = local_now.date()
    last_update = self.database.load_last_comed_price_update()
    if last_update and last_update.astimezone(CHICAGO).date() == local_now.date():
      return None

    start_local = datetime.combine(
      local_now.date() - timedelta(days=1), time.min, CHICAGO
    )
    samples = self._download_samples(start_local, local_now)
    hourly_prices = self._average_by_hour(samples)
    if not hourly_prices:
      raise RuntimeError("ComEd returned no price data")
    self.database.store_comed_hourly_prices(hourly_prices)
    return len(hourly_prices)

  def _download_samples(
    self, start_local: datetime, end_local: datetime
  ) -> list[tuple[datetime, float]]:
    query = urllib.parse.urlencode({
      "type": "5minutefeed",
      "datestart": start_local.strftime("%Y%m%d%H%M"),
      "dateend": end_local.strftime("%Y%m%d%H%M"),
      "format": "json",
    })
    with urllib.request.urlopen(f"{self.api_url}?{query}", timeout=30) as response:
      payload: list[dict[str, Any]] = json.load(response)
    return [
      (
        datetime.fromtimestamp(int(item["millisUTC"]) / 1000, timezone.utc),
        float(item["price"]),
      )
      for item in payload
    ]

  @staticmethod
  def _average_by_hour(
    samples: list[tuple[datetime, float]],
  ) -> list[dict[str, Any]]:
    grouped: dict[datetime, list[float]] = defaultdict(list)
    for sampled_at, price in samples:
      hour_start = sampled_at.astimezone(timezone.utc).replace(
        minute=0, second=0, microsecond=0
      )
      grouped[hour_start].append(price)
    return [
      {
        "hour_start": hour_start,
        "price_cents_per_kwh": sum(values) / len(values),
        "source_sample_count": len(values),
      }
      for hour_start, values in sorted(grouped.items())
    ]
