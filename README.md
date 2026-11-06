# EMonitor

EMonitor polls an energy monitor's HTML status page at a configurable interval.
It integrates the sampled power into clock-aligned half-hour energy totals and
stores each channel's watt-hours, average watts, minimum watts, maximum watts,
sample count, and measurement coverage in SQLite. Paired monitor channels are
combined into one logical circuit before accumulation. A small Flask application
displays the newest completed period for every circuit.

Once per local calendar day, the collector also downloads ComEd's 5-minute price
feed, averages those samples into hourly prices, and upserts them into the
`comed_hourly_prices` SQLite table. It refreshes the previous day as well as the
current day so preliminary prices can be updated.

## Setup (Python 3.14)

```bash
./env/install.sh
cp .env.example .env
```

Edit `.env` and set `MONITOR_URL` to the monitor's base URL. SQLite creates
`db/emonitor.db` automatically, and application logs are written under `log/`.
No database server is required.

## Run

```bash
.venv/bin/python main.py
.venv/bin/flask --app web:create_app run --debug
```

Then open <http://127.0.0.1:5000>. In VS Code, select either EMonitor launch
configuration or the compound configuration to run both processes.

The defaults poll every 15 seconds and finish UTC periods at `:00` and `:30`. Energy
between polls is calculated as elapsed time multiplied by the previous sampled
power, then converted from watt-seconds to watt-hours. Override the intervals
with `POLL_INTERVAL_SECONDS` and `WRITE_INTERVAL_MINUTES` in `.env` or your shell.
Transient monitor timeouts are logged as one-line warnings without a traceback;
`MONITOR_TIMEOUT_SECONDS` controls how long each HTTP request may take.

Intervals longer than `MAX_SAMPLE_GAP_SECONDS` are treated as missing data and
do not contribute estimated energy. The coverage percentage exposes incomplete
periods. In-progress accumulation is checkpointed in SQLite after every poll so
a restart can resume without discarding the current period.

## Test

```bash
.venv/bin/pytest
```
