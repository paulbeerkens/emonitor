import asyncio
import logging
from io import StringIO
from typing import TypedDict

import aiohttp
import pandas


class PowerReading(TypedDict):
  channel_id: int
  channel_name: str
  power_watts: int


class ChannelMetadata(TypedDict):
  channel_id: int
  name: str
  is_input: bool
  rating_amps: int
  voltage: int
  paired_channel_id: int


def _convert_html_to_channel_table(
  html: str, expected_columns: set[str]
) -> pandas.DataFrame:
  """Find the monitor's data table and verify that it has the expected shape."""
  tables = pandas.read_html(
    StringIO(html),
    attrs={"class": "channel-data"},
  )
  if len(tables) != 1:
    raise ValueError(f"Expected one channel-data table, found {len(tables)}")

  table = tables[0]
  missing_columns = expected_columns - set(table.columns)
  if missing_columns:
    missing = ", ".join(sorted(missing_columns))
    raise ValueError(f"The channel-data table is missing columns: {missing}")
  return table


def parse_power_readings(html: str) -> list[PowerReading]:
  """Convert each row in the Current Data table into one power reading."""
  table = _convert_html_to_channel_table(
    html, {"#", "Channel Name", "Power (w)"}
  )

  readings = []
  for _, html_row in table.iterrows():
    reading: PowerReading = {
      "channel_id": int(html_row["#"]),
      "channel_name": str(html_row["Channel Name"]).strip(),
      "power_watts": int(html_row["Power (w)"]),
    }
    readings.append(reading)
  return readings


def parse_channel_metadata(html: str) -> list[ChannelMetadata]:
  """Convert each row in the Channel Information table into channel metadata."""
  expected_columns = {"#", "Name", "Input", "CT Rating", "Voltage", "Paired"}
  table = _convert_html_to_channel_table(html, expected_columns)

  channels = []
  for _, html_row in table.iterrows():
    channel: ChannelMetadata = {
      "channel_id": int(html_row["#"]),
      "name": str(html_row["Name"]).strip(),
      "is_input": int(html_row["Input"]) == 1,
      "rating_amps": int(html_row["CT Rating"]),
      "voltage": int(html_row["Voltage"]),
      "paired_channel_id": int(html_row["Paired"]),
    }
    channels.append(channel)
  return channels


class EMonitorWebPage:
  def __init__(
    self,
    base_url: str,
    timeout_seconds: float = 15,
    retry_delay_seconds: float = 0.5,
  ):
    self.base_url = base_url.rstrip("/")
    self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    self.retry_delay_seconds = retry_delay_seconds
    self.logger = logging.getLogger("emonitor")
    self._session: aiohttp.ClientSession | None = None
    self.last_attempt_count = 0
    self.last_attempt_errors: list[str] = []
    self.last_request_succeeded = False
    self.last_request_elapsed_seconds = 0.0

  def _get_session(self) -> aiohttp.ClientSession:
    if self._session is None or self._session.closed:
      self._session = aiohttp.ClientSession(
        timeout=self.timeout,
        connector=aiohttp.TCPConnector(limit=1),
      )
    return self._session

  async def close(self) -> None:
    """Close the reusable HTTP session and its connection pool."""
    if self._session is not None and not self._session.closed:
      await self._session.close()
    self._session = None

  async def _reconnect(self) -> None:
    """Discard a failed connection pool; the next request creates a new one."""
    await self.close()

  async def _fetch_html(self, path: str) -> str:
    """Download one HTML page, retrying once after a transient failure."""
    url = f"{self.base_url}{path}"
    self.last_attempt_count = 0
    self.last_attempt_errors = []
    self.last_request_succeeded = False
    started = asyncio.get_running_loop().time()
    try:
      for attempt in range(2):
        self.last_attempt_count += 1
        try:
          async with self._get_session().get(url) as response:
            response.raise_for_status()
            html = await response.text()
            self.last_request_succeeded = True
            return html
        except (TimeoutError, aiohttp.ClientError) as error:
          self.last_attempt_errors.append(type(error).__name__)
          if attempt == 1:
            raise
          if not isinstance(error, aiohttp.ClientResponseError):
            await self._reconnect()
            self.logger.warning(
              "Monitor connection failed; reconnecting and retrying once "
              "in %.1f seconds",
              self.retry_delay_seconds,
            )
          else:
            self.logger.warning(
              "Monitor request failed; retrying once in %.1f seconds",
              self.retry_delay_seconds,
            )
          await asyncio.sleep(self.retry_delay_seconds)
      raise AssertionError("unreachable")
    finally:
      self.last_request_elapsed_seconds = (
        asyncio.get_running_loop().time() - started
      )

  async def get_power_readings(self) -> list[PowerReading]:
    html = await self._fetch_html("")
    return parse_power_readings(html)

  async def get_channel_metadata(self) -> list[ChannelMetadata]:
    html = await self._fetch_html("/channel.html")
    return parse_channel_metadata(html)
