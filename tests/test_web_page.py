import asyncio

from EMonitorWebPage import (
  EMonitorWebPage,
  parse_channel_metadata,
  parse_power_readings,
)


def test_parse_power_readings_uses_channel_data_table():
  html = """
    <table><tr><td>Decorative logo table</td></tr></table>
    <table class="channel-data">
      <tr><th>#</th><th>Channel Name</th><th>Power (w)</th></tr>
      <tr><td>1</td><td>Main Power</td><td>831</td></tr>
      <tr><td>2</td><td>Kitchen Fridge</td><td>82</td></tr>
    </table>
  """

  assert parse_power_readings(html) == [
    {"channel_id": 1, "channel_name": "Main Power", "power_watts": 831},
    {"channel_id": 2, "channel_name": "Kitchen Fridge", "power_watts": 82},
  ]


def test_parse_channel_metadata():
  html = """
    <table class="channel-data">
      <tr>
        <th>#</th><th>Name</th><th>Active</th><th>Input</th>
        <th>CT Rating</th><th>Voltage</th><th>Paired</th>
      </tr>
      <tr><td>1</td><td>Main Power</td><td>1</td><td>1</td><td>150</td><td>120</td><td>2</td></tr>
    </table>
  """

  assert parse_channel_metadata(html) == [{
    "channel_id": 1,
    "name": "Main Power",
    "is_input": True,
    "rating_amps": 150,
    "voltage": 120,
    "paired_channel_id": 2,
  }]


def test_fetch_retries_once_and_reuses_session():
  async def exercise():
    connection_count = 0
    request_count = 0

    async def handle_client(reader, writer):
      nonlocal connection_count, request_count
      connection_count += 1
      try:
        while True:
          await reader.readuntil(b"\r\n\r\n")
          request_count += 1
          if request_count == 1:
            response = (
              b"HTTP/1.1 503 Service Unavailable\r\n"
              b"Content-Length: 0\r\nConnection: keep-alive\r\n\r\n"
            )
          else:
            response = (
              b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
              b"Connection: keep-alive\r\n\r\nok"
            )
          writer.write(response)
          await writer.drain()
      except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
      finally:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    page = EMonitorWebPage(
      f"http://127.0.0.1:{port}", timeout_seconds=1, retry_delay_seconds=0
    )
    try:
      assert await page._fetch_html("") == "ok"
      assert await page._fetch_html("") == "ok"
      assert request_count == 3
      assert connection_count == 1
    finally:
      await page.close()
      server.close()
      await server.wait_closed()

    assert page._session is None

  asyncio.run(exercise())


def test_fetch_reconnects_after_connection_failure():
  async def exercise():
    connection_count = 0
    request_count = 0

    async def handle_client(reader, writer):
      nonlocal connection_count, request_count
      connection_count += 1
      this_connection = connection_count
      try:
        while True:
          await reader.readuntil(b"\r\n\r\n")
          request_count += 1
          if this_connection == 1:
            writer.close()
            await writer.wait_closed()
            return
          writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
            b"Connection: keep-alive\r\n\r\nok"
          )
          await writer.drain()
      except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
      finally:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    page = EMonitorWebPage(
      f"http://127.0.0.1:{port}", timeout_seconds=1, retry_delay_seconds=0
    )
    try:
      assert await page._fetch_html("") == "ok"
      assert await page._fetch_html("") == "ok"
      assert request_count == 3
      assert connection_count == 2
    finally:
      await page.close()
      server.close()
      await server.wait_closed()

  asyncio.run(exercise())
