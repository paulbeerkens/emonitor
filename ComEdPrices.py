import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


COMED_API_URL = "https://hourlypricing.comed.com/api"
CHICAGO = ZoneInfo("America/Chicago")


class ComEdPriceUpdater:
  """Persist ComEd's five-minute feed and restart-safe half-hour averages."""

  def __init__(
    self,
    database,
    api_url: str = COMED_API_URL,
    refresh_seconds: int = 300,
    recovery_hours: int = 48,
  ):
    self.database = database
    self.api_url = api_url
    self.refresh_seconds = refresh_seconds
    self.recovery_hours = recovery_hours
    self._last_attempt: datetime | None = None

  def refresh_if_due(self, now: datetime | None = None) -> dict[str, int] | None:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
      raise ValueError("now must include a timezone")

    if (
      self._last_attempt is not None
      and (now - self._last_attempt).total_seconds() < self.refresh_seconds
    ):
      return None
    self._last_attempt = now
    local_now = now.astimezone(CHICAGO)
    start_local = local_now - timedelta(hours=self.recovery_hours)
    samples = self._download_samples(start_local, local_now)
    if not samples:
      raise RuntimeError("ComEd returned no price data")
    return self.database.store_comed_price_samples(samples, retrieved_at=now)

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
