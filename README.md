# EMonitor

EMonitor polls an energy monitor's HTML status page at a configurable interval.
It integrates the sampled power into clock-aligned half-hour energy totals and
stores each channel's watt-hours, average watts, minimum watts, maximum watts,
sample count, and measurement coverage in SQLite. Paired monitor channels are
combined into one logical circuit before accumulation. Individual logical-channel
power samples are retained for seven days for detailed short-horizon graphs. A
small Flask application displays the newest completed period for every circuit.

Every five minutes, the collector downloads an overlapping 48-hour window from
ComEd's 5-minute price feed. Unique samples are upserted into
`comed_price_samples`, then affected 30-minute averages are rebuilt in
`comed_half_hour_prices`. The overlap makes restarts and short outages safe;
legacy hourly prices remain available for older historical cost estimates.

## Setup (Python 3.13)

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

## Run automatically with systemd

On a production Linux machine such as a Raspberry Pi, finish the setup above,
then install the collector as a system service:

```bash
sudo ./deployment/install-service.sh
```

The installer uses the account that invoked `sudo`, inserts that account and
the current project directory into the service template, enables the collector
at boot, and starts it immediately. Re-run the command after changing the
template or moving the project.

```bash
systemctl status emonitor
journalctl -u emonitor -f
sudo systemctl restart emonitor
sudo systemctl stop emonitor
```

Do not install the service on a development machine where you only want short
manual or Visual Studio Code runs.

The defaults poll every 15 seconds and finish UTC periods at `:00` and `:30`. Energy
between polls is calculated as elapsed time multiplied by the previous sampled
power, then converted from watt-seconds to watt-hours. Override the intervals
with `POLL_INTERVAL_SECONDS` and `WRITE_INTERVAL_MINUTES` in `.env` or your shell.
Transient monitor timeouts are logged as one-line warnings without a traceback;
`MONITOR_TIMEOUT_SECONDS` controls how long each HTTP request may take.

Intervals longer than `MAX_SAMPLE_GAP_SECONDS` are treated as missing data and
do not contribute estimated energy. The coverage percentage exposes incomplete
periods. In-progress accumulation is checkpointed in SQLite after every poll so
a restart can resume without discarding the current period. Detailed readings
are stored in `power_samples`; `SAMPLE_RETENTION_DAYS` controls their rolling
retention window and defaults to seven days. Expired detailed samples are
removed when a half-hour period closes.

## Test

```bash
.venv/bin/pytest
```
