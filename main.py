import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

from ComEdPrices import ComEdPriceUpdater
from EnergyAccumulator import HalfHourEnergyAccumulator, combine_paired_channels
from EMonitorDB import EMonitorDB
from EMonitorWebPage import EMonitorWebPage, PowerReading

load_dotenv()


def summarize_power(
  readings: list[PowerReading],
) -> tuple[int, int, PowerReading | None]:
  solar_power = sum(
    reading["power_watts"]
    for reading in readings
    if reading["channel_name"].casefold() == "solar panels"
  )
  net_main_power = sum(
    reading["power_watts"]
    for reading in readings
    if reading["channel_name"].casefold() == "main power"
  )
  consumer_readings = [
    reading
    for reading in readings
    if reading["channel_name"].casefold() not in {"main power", "solar panels"}
  ]
  total_usage = net_main_power
  peak_consumer = (
    max(consumer_readings, key=lambda reading: reading["power_watts"])
    if consumer_readings
    else None
  )
  return solar_power, total_usage, peak_consumer


class EMonitor:
  def __init__(self):
    log_dir = Path(os.getenv("LOG_DIR", "log"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"writer_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
      level=os.getenv("LOG_LEVEL", "INFO").upper(),
      format="%(asctime)s|%(levelname)s|%(message)s",
      handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )
    self.logger = logging.getLogger("emonitor")
    self.poll_interval = float(os.getenv("POLL_INTERVAL_SECONDS", "15"))
    self.sample_retention_days = int(os.getenv("SAMPLE_RETENTION_DAYS", "7"))
    if self.sample_retention_days <= 0:
      raise ValueError("SAMPLE_RETENTION_DAYS must be greater than zero")
    self.write_interval = int(os.getenv("WRITE_INTERVAL_MINUTES", "30"))
    self.maximum_gap = float(os.getenv("MAX_SAMPLE_GAP_SECONDS", "60"))
    self.monitor_timeout = float(os.getenv("MONITOR_TIMEOUT_SECONDS", "10"))
    self.consecutive_poll_failures = 0
    monitor_url = os.getenv("MONITOR_URL")
    if not monitor_url:
      raise RuntimeError(
        "MONITOR_URL is not configured. Set it in the .env file, for example: "
        "MONITOR_URL=http://192.168.68.57"
      )
    self.page = EMonitorWebPage(monitor_url, self.monitor_timeout)
    self.db = EMonitorDB(os.getenv("DATABASE_PATH", "db/emonitor.db"))
    self.comed_prices = ComEdPriceUpdater(self.db)
    self.channel_metadata = self.db.load_channel_metadata()
    self.energy_accumulator = HalfHourEnergyAccumulator(
      self.write_interval, self.maximum_gap
    )
    saved_state = self.db.load_accumulator_state()
    if saved_state:
      self.energy_accumulator.restore_state(saved_state)
      sample_count, measured_seconds, channel_count = (
        self.energy_accumulator.recovery_statistics()
      )
      minutes, seconds = divmod(round(measured_seconds), 60)
      self.logger.info(
        "Recovered %d samples covering %d minutes %d seconds for %d channels "
        "from SQLite",
        sample_count,
        minutes,
        seconds,
        channel_count,
      )

  async def run(self) -> None:
    try:
      await self._run_collector()
    finally:
      await self.page.close()

  async def _run_collector(self) -> None:
    self.logger.info(
      "Starting collector; polling every %.1fs; retaining detailed samples "
      "for %d days",
      self.poll_interval,
      self.sample_retention_days,
    )
    await self._refresh_comed_prices()
    try:
      channel_metadata = await self.page.get_channel_metadata()
      self.db.store_channel_metadata(channel_metadata)
      self.channel_metadata = channel_metadata
    except (TimeoutError, aiohttp.ClientError) as error:
      reason = (
        f"timed out after {self.monitor_timeout:g} seconds"
        if isinstance(error, TimeoutError)
        else f"network error: {error or type(error).__name__}"
      )
      self.logger.warning(
        "Could not refresh channel metadata: %s; using %d cached channels "
        "from SQLite",
        reason,
        len(self.channel_metadata),
      )
    except Exception:
      self.logger.exception("Could not update channel metadata; continuing")

    while True:
      started = asyncio.get_running_loop().time()
      power_summary = None
      poll_failed = False
      try:
        physical_readings = await self.page.get_power_readings()
      except (TimeoutError, aiohttp.ClientError) as error:
        poll_failed = True
        self.consecutive_poll_failures += 1
        reason = (
          f"timed out after {self.monitor_timeout:g} seconds"
          if isinstance(error, TimeoutError)
          else f"network error: {error or type(error).__name__}"
        )
        self.logger.warning(
          "Monitor poll %s; sample skipped (consecutive failures: %d)",
          reason,
          self.consecutive_poll_failures,
        )
      except Exception:
        poll_failed = True
        self.logger.exception("Monitor poll failed")
      else:
        if self.consecutive_poll_failures:
          self.logger.info(
            "Monitor connection recovered after %d failed poll%s",
            self.consecutive_poll_failures,
            "" if self.consecutive_poll_failures == 1 else "s",
          )
          self.consecutive_poll_failures = 0
        state_before_poll = self.energy_accumulator.export_state()
        try:
          current_readings = combine_paired_channels(
            physical_readings, self.channel_metadata
          )
          sampled_at = datetime.now(timezone.utc)
          completed_summaries = self.energy_accumulator.add_sample(
            current_readings, sampled_at
          )
          self.db.store_usage_and_checkpoint(
            completed_summaries,
            self.energy_accumulator.export_state(),
            sampled_at=sampled_at,
            readings=current_readings,
            sample_retention_days=self.sample_retention_days,
            prune_samples=bool(completed_summaries),
          )
          if completed_summaries:
            self.logger.info(
              "Stored %d channel summaries through %s",
              len(completed_summaries),
              completed_summaries[-1]["period_end"].isoformat(),
            )
          power_summary = summarize_power(current_readings)
        except Exception:
          self.energy_accumulator.restore_state(state_before_poll)
          self.logger.exception("Could not process or store monitor readings")

      elapsed = asyncio.get_running_loop().time() - started
      sleep_seconds = max(0, self.poll_interval - elapsed)
      if power_summary:
        solar_power, total_usage, peak_consumer = power_summary
        peak_description = (
          f"{peak_consumer['channel_name']} ({peak_consumer['power_watts']} W)"
          if peak_consumer
          else "unavailable"
        )
        self.logger.info(
          "Elapsed: %.3f seconds; solar production: %d W; total usage: %d W; "
          "peak consumer: %s",
          elapsed,
          solar_power,
          total_usage,
          peak_description,
        )
      elif not poll_failed:
        self.logger.info(
          "Elapsed: %.3f seconds; solar production unavailable; "
          "total usage unavailable; peak consumer unavailable",
          elapsed,
        )
      await asyncio.sleep(sleep_seconds)

      await self._refresh_comed_prices()

  async def _refresh_comed_prices(self) -> None:
    try:
      result = await asyncio.to_thread(self.comed_prices.refresh_if_due)
      if result is not None:
        self.logger.info(
          "Stored or refreshed %d ComEd five-minute samples across %d "
          "half-hour price periods",
          result["samples"],
          result["half_hours"],
        )
    except Exception:
      self.logger.exception("Could not update ComEd prices; continuing")


if __name__ == "__main__":
  asyncio.run(EMonitor().run())
