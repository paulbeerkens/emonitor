import json
import math
import sqlite3
import urllib.request
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "db" / "emonitor.db"
OUTPUT_PATH = ROOT / "output" / "pdf" / "emonitor_energy_usage_report.pdf"
BILL_MODEL_PATH = ROOT / "config" / "comed_bill_model.json"
LOCAL_ZONE = ZoneInfo("America/Chicago")
PRICE_API_BASE_URL = "https://hourlypricing.comed.com/api?type=5minutefeed"
NAVY = colors.HexColor("#17324D"); BLUE = colors.HexColor("#2E6F9E")
GREEN = colors.HexColor("#42A66A"); SOLAR = colors.HexColor("#F2B134")
TEAL = colors.HexColor("#2F8F9D"); RED = colors.HexColor("#D95D5D")
INK = colors.HexColor("#263238"); MUTED = colors.HexColor("#68737D")
PALE = colors.HexColor("#F3F6F7"); GRID = colors.HexColor("#DCE3E7")
WHITE = colors.white


def load_data():
  with sqlite3.connect(DB_PATH) as connection:
    connection.row_factory = sqlite3.Row
    return connection.execute("""
      SELECT u.*, COALESCE(m.name, 'Unknown') AS name
      FROM channel_usage AS u LEFT JOIN meta_data AS m ON m.id = u.id
      ORDER BY u.period_start, u.id
    """).fetchall()


def load_prices(start_utc, end_utc):
  start_local = start_utc.astimezone(LOCAL_ZONE).strftime("%Y%m%d%H%M")
  end_local = end_utc.astimezone(LOCAL_ZONE).strftime("%Y%m%d%H%M")
  price_api_url = (
    f"{PRICE_API_BASE_URL}&datestart={start_local}"
    f"&dateend={end_local}&format=json"
  )
  with urllib.request.urlopen(price_api_url, timeout=20) as response:
    data = json.load(response)
  utc = ZoneInfo("UTC")
  return [
    (datetime.fromtimestamp(int(item["millisUTC"]) / 1000, utc), float(item["price"]))
    for item in data
  ]


def load_bill_model():
  with BILL_MODEL_PATH.open() as stream:
    model = json.load(stream)
  variable_dollars = sum(model["variable_import_charges_dollars"].values())
  model["variable_addon_cents_per_kwh"] = (
    variable_dollars / model["import_kwh"] * 100
  )
  return model


def local_time(value): return datetime.fromisoformat(value).astimezone(LOCAL_ZONE)
def fmt_kwh(wh): return f"{wh / 1000:,.2f} kWh"


def fmt_duration(hours):
  total_minutes = max(0, round(hours * 60))
  whole_hours, minutes = divmod(total_minutes, 60)
  return f"{whole_hours}h {minutes:02d}m"


def set_font(pdf, size, bold=False, color=INK):
  pdf.setFillColor(color)
  pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)


def rounded_card(pdf, x, y, width, height):
  pdf.setFillColor(WHITE); pdf.setStrokeColor(GRID)
  pdf.roundRect(x, y, width, height, 8, fill=1, stroke=1)


def draw_header(pdf, title, subtitle, page):
  width, height = letter
  pdf.setFillColor(NAVY); pdf.rect(0, height - 92, width, 92, fill=1, stroke=0)
  title_size = 24
  while stringWidth(title, "Helvetica-Bold", title_size) > width - 145:
    title_size -= 1
  set_font(pdf, title_size, True, WHITE); pdf.drawString(40, height - 48, title)
  set_font(pdf, 9.5, False, colors.HexColor("#D9E6EF")); pdf.drawString(40, height - 69, subtitle)
  set_font(pdf, 9, True, colors.HexColor("#D9E6EF")); pdf.drawRightString(width - 40, height - 69, f"PAGE {page}")


def draw_footer(pdf):
  width, _ = letter; pdf.setStrokeColor(GRID); pdf.line(40, 30, width - 40, 30)
  set_font(pdf, 7.5, False, MUTED); pdf.drawString(40, 18, "Source: EMonitor SQLite half-hour summaries")
  pdf.drawRightString(width - 40, 18, "Energy values are based on sampled power integration")


def draw_kpi(pdf, x, y, width, label, value, note, accent):
  rounded_card(pdf, x, y, width, 76); pdf.setFillColor(accent)
  pdf.roundRect(x, y, 5, 76, 3, fill=1, stroke=0)
  set_font(pdf, 8, True, MUTED); pdf.drawString(x + 15, y + 56, label.upper())
  set_font(pdf, 18, True, NAVY); pdf.drawString(x + 15, y + 31, value)
  set_font(pdf, 7.5, False, MUTED); pdf.drawString(x + 15, y + 13, note)


def draw_section_title(pdf, x, y, title, note=None):
  set_font(pdf, 12, True, NAVY); pdf.drawString(x, y, title)
  if note:
    set_font(pdf, 7.5, False, MUTED); pdf.drawRightString(572, y + 1, note)


def draw_line_chart(pdf, x, y, width, height, periods):
  left, bottom = x + 42, y + 30; plot_w, plot_h = width - 55, height - 52
  values = [p["main_avg"] for p in periods] + [p["solar_avg"] for p in periods]
  y_max = max(500, math.ceil(max(values or [1]) / 500) * 500)
  pdf.setFillColor(WHITE); pdf.setStrokeColor(GRID); pdf.roundRect(x, y, width, height, 8, fill=1, stroke=1)
  for step in range(5):
    level = y_max * step / 4; py = bottom + plot_h * step / 4
    pdf.setStrokeColor(GRID); pdf.line(left, py, left + plot_w, py)
    set_font(pdf, 6.5, False, MUTED); pdf.drawRightString(left - 7, py - 2, f"{level:,.0f}")
  x_step = plot_w / (len(periods) - 1) if len(periods) > 1 else 0
  def line(points, color):
    path = pdf.beginPath()
    for index, value in enumerate(points):
      px, py = left + index * x_step, bottom + (value / y_max) * plot_h
      path.moveTo(px, py) if index == 0 else path.lineTo(px, py)
    pdf.setStrokeColor(color); pdf.setLineWidth(2.2); pdf.drawPath(path, stroke=1, fill=0)
    for index, value in enumerate(points):
      pdf.setFillColor(color); pdf.circle(left + index * x_step, bottom + value / y_max * plot_h, 2.2, fill=1, stroke=0)
  line([p["main_avg"] for p in periods], BLUE); line([p["solar_avg"] for p in periods], SOLAR)
  for index in sorted(set([0, len(periods) // 2, max(0, len(periods) - 1)])):
    if periods:
      set_font(pdf, 6.5, False, MUTED)
      pdf.drawCentredString(
        left + index * x_step,
        y + 13,
        periods[index]["start"].strftime("%b %d %I %p").replace(" 0", " "),
      )
  set_font(pdf, 7.5, True, BLUE); pdf.drawString(x + 14, y + height - 17, "MAIN POWER")
  set_font(pdf, 7.5, True, SOLAR); pdf.drawString(x + 95, y + height - 17, "SOLAR")
  set_font(pdf, 6.5, False, MUTED); pdf.drawRightString(x + width - 12, y + height - 17, "Half-hour average watts")


def draw_donut(pdf, cx, cy, radius, values, palette, center_top, center_bottom):
  total, start = sum(values), 90
  for value, color in zip(values, palette):
    extent = 360 * value / total if total else 0
    pdf.setFillColor(color); pdf.setStrokeColor(WHITE)
    pdf.wedge(cx - radius, cy - radius, cx + radius, cy + radius, start, extent, fill=1, stroke=1); start += extent
  pdf.setFillColor(WHITE); pdf.circle(cx, cy, radius * 0.56, fill=1, stroke=0)
  set_font(pdf, 12, True, NAVY); pdf.drawCentredString(cx, cy + 2, center_top)
  set_font(pdf, 7, False, MUTED); pdf.drawCentredString(cx, cy - 12, center_bottom)


def draw_legend(pdf, x, y, items, line_height=14):
  for index, (label, value, color) in enumerate(items):
    py = y - index * line_height; pdf.setFillColor(color); pdf.circle(x + 4, py + 3, 4, fill=1, stroke=0)
    set_font(pdf, 7.5, False, INK); pdf.drawString(x + 14, py, label)
    set_font(pdf, 7.5, True, NAVY); pdf.drawRightString(x + 150, py, value)


def draw_horizontal_bars(pdf, x, y, width, height, items):
  max_value = max((value for _, value, _ in items), default=1); row_h = height / len(items)
  label_w, bar_w = 145, width - 145 - 55
  for index, (name, value, peak) in enumerate(items):
    py = y + height - (index + 1) * row_h + 5
    set_font(pdf, 7.5, False, INK); pdf.drawString(x, py + 3, name if len(name) <= 25 else name[:24] + "...")
    pdf.setFillColor(PALE); pdf.roundRect(x + label_w, py, bar_w, 11, 5, fill=1, stroke=0)
    pdf.setFillColor(TEAL); pdf.roundRect(x + label_w, py, bar_w * value / max_value, 11, 5, fill=1, stroke=0)
    set_font(pdf, 7.2, True, NAVY); pdf.drawRightString(x + width, py + 3, f"{value / 1000:.2f} kWh  |  peak {peak:,.0f} W")


def draw_daily_energy_bars(pdf, x, y, width, height, days):
  pdf.setFillColor(WHITE); pdf.setStrokeColor(GRID)
  pdf.roundRect(x, y, width, height, 8, fill=1, stroke=1)
  left, bottom = x + 42, y + 34
  plot_w, plot_h = width - 58, height - 62
  maximum = max(
    [day["main_kwh"] for day in days] + [day["solar_kwh"] for day in days] + [1]
  )
  y_max = math.ceil(maximum)
  for step in range(5):
    value = y_max * step / 4
    py = bottom + plot_h * step / 4
    pdf.setStrokeColor(GRID); pdf.line(left, py, left + plot_w, py)
    set_font(pdf, 6.5, False, MUTED)
    pdf.drawRightString(left - 7, py - 2, f"{value:.1f}")
  group_w = plot_w / max(len(days), 1)
  bar_w = min(18, group_w * 0.32)
  for index, day in enumerate(days):
    center = left + group_w * (index + 0.5)
    for value, color, offset in (
      (day["main_kwh"], BLUE, -bar_w),
      (day["solar_kwh"], SOLAR, 0),
    ):
      bar_h = plot_h * value / y_max
      pdf.setFillColor(color)
      pdf.roundRect(center + offset, bottom, bar_w - 1, bar_h, 2, fill=1, stroke=0)
    set_font(pdf, 6.5, False, MUTED)
    pdf.drawCentredString(center - 0.5, y + 17, day["date"].strftime("%b %d"))
  set_font(pdf, 7.5, True, BLUE); pdf.drawString(x + 14, y + height - 17, "MAIN POWER")
  set_font(pdf, 7.5, True, SOLAR); pdf.drawString(x + 98, y + height - 17, "SOLAR")
  set_font(pdf, 6.5, False, MUTED); pdf.drawRightString(x + width - 12, y + height - 17, "Daily energy (kWh)")


def draw_daily_cost_bars(pdf, x, y, width, height, days):
  pdf.setFillColor(WHITE); pdf.setStrokeColor(GRID)
  pdf.roundRect(x, y, width, height, 8, fill=1, stroke=1)
  left, bottom = x + 42, y + 28
  plot_w, plot_h = width - 58, height - 48
  maximum = max((day["cost"] for day in days), default=0.01)
  group_w = plot_w / max(len(days), 1)
  bar_w = min(30, group_w * 0.55)
  for index, day in enumerate(days):
    center = left + group_w * (index + 0.5)
    bar_h = plot_h * day["cost"] / maximum if maximum else 0
    pdf.setFillColor(TEAL)
    pdf.roundRect(center - bar_w / 2, bottom, bar_w, bar_h, 3, fill=1, stroke=0)
    set_font(pdf, 6.5, True, NAVY)
    pdf.drawCentredString(center, bottom + bar_h + 5, f"${day['cost']:.2f}")
    set_font(pdf, 6.2, False, MUTED)
    pdf.drawCentredString(center, y + 12, day["date"].strftime("%b %d"))


def draw_missing_minutes_bars(pdf, x, y, width, height, days):
  pdf.setFillColor(WHITE); pdf.setStrokeColor(GRID)
  pdf.roundRect(x, y, width, height, 8, fill=1, stroke=1)
  left, bottom = x + 36, y + 32
  plot_w, plot_h = width - 49, height - 57
  maximum = max((day["missing_hours"] * 60 for day in days), default=1)
  y_max = max(60, math.ceil(maximum / 60) * 60)
  for step in range(4):
    value = y_max * step / 3
    py = bottom + plot_h * step / 3
    pdf.setStrokeColor(GRID); pdf.line(left, py, left + plot_w, py)
    set_font(pdf, 6, False, MUTED); pdf.drawRightString(left - 6, py - 2, f"{value:.0f}")
  group_w = plot_w / max(len(days), 1)
  bar_w = min(20, group_w * 0.58)
  for index, day in enumerate(days):
    minutes = day["missing_hours"] * 60
    center = left + group_w * (index + 0.5)
    bar_h = plot_h * minutes / y_max if y_max else 0
    pdf.setFillColor(RED)
    pdf.roundRect(center - bar_w / 2, bottom, bar_w, bar_h, 2, fill=1, stroke=0)
    if len(days) <= 14:
      set_font(pdf, 5.8, True, NAVY)
      pdf.drawCentredString(center, bottom + bar_h + 4, f"{minutes:.0f}")
      set_font(pdf, 5.5, False, MUTED)
      pdf.drawCentredString(center, y + 13, day["date"].strftime("%m/%d"))
  set_font(pdf, 6.5, False, MUTED)
  pdf.drawRightString(x + width - 10, y + height - 15, "Minutes missing")


def draw_coverage_bands(pdf, x, y, width, height, bands):
  pdf.setFillColor(WHITE); pdf.setStrokeColor(GRID)
  pdf.roundRect(x, y, width, height, 8, fill=1, stroke=1)
  maximum = max((count for _, count, _ in bands), default=1)
  row_y = y + height - 34
  for label, count, color in bands:
    set_font(pdf, 7, False, INK); pdf.drawString(x + 12, row_y + 3, label)
    bar_x, bar_w = x + 12, width - 56
    pdf.setFillColor(PALE); pdf.roundRect(bar_x, row_y - 10, bar_w, 8, 4, fill=1, stroke=0)
    pdf.setFillColor(color)
    if count:
      pdf.roundRect(bar_x, row_y - 10, bar_w * count / maximum, 8, 4, fill=1, stroke=0)
    set_font(pdf, 8, True, NAVY); pdf.drawRightString(x + width - 12, row_y - 8, str(count))
    row_y -= 35


def draw_solar_timeline(pdf, x, y, width, height, periods):
  pdf.setFillColor(WHITE); pdf.setStrokeColor(GRID)
  pdf.roundRect(x, y, width, height, 8, fill=1, stroke=1)
  left, bottom = x + 42, y + 31
  plot_w, plot_h = width - 57, height - 57
  maximum = max((period["solar_avg"] for period in periods), default=1)
  y_max = max(500, math.ceil(maximum / 500) * 500)
  for step in range(5):
    value = y_max * step / 4
    py = bottom + plot_h * step / 4
    pdf.setStrokeColor(GRID); pdf.line(left, py, left + plot_w, py)
    set_font(pdf, 6.5, False, MUTED); pdf.drawRightString(left - 7, py - 2, f"{value:,.0f}")
  step_w = plot_w / max(len(periods), 1)
  bar_w = max(1.5, min(8, step_w * 0.72))
  for index, period in enumerate(periods):
    value = period["solar_avg"]
    bar_h = plot_h * value / y_max
    pdf.setFillColor(SOLAR)
    pdf.rect(left + index * step_w + (step_w - bar_w) / 2, bottom, bar_w, bar_h, fill=1, stroke=0)
  for index in sorted(set([0, len(periods) // 2, max(0, len(periods) - 1)])):
    if periods:
      set_font(pdf, 6.5, False, MUTED)
      label = periods[index]["start"].strftime("%b %d %I %p").replace(" 0", " ")
      pdf.drawCentredString(left + (index + 0.5) * step_w, y + 14, label)
  set_font(pdf, 7.5, True, SOLAR); pdf.drawString(x + 14, y + height - 17, "SOLAR PRODUCTION")
  set_font(pdf, 6.5, False, MUTED); pdf.drawRightString(x + width - 12, y + height - 17, "Half-hour average watts")


def draw_solar_daily_bars(pdf, x, y, width, height, days):
  pdf.setFillColor(WHITE); pdf.setStrokeColor(GRID)
  pdf.roundRect(x, y, width, height, 8, fill=1, stroke=1)
  left, bottom = x + 20, y + 27
  plot_w, plot_h = width - 35, height - 47
  maximum = max((day["solar_kwh"] for day in days), default=1)
  group_w = plot_w / max(len(days), 1)
  bar_w = min(28, group_w * 0.5)
  for index, day in enumerate(days):
    center = left + group_w * (index + 0.5)
    bar_h = plot_h * day["solar_kwh"] / maximum if maximum else 0
    pdf.setFillColor(SOLAR)
    pdf.roundRect(center - bar_w / 2, bottom, bar_w, bar_h, 3, fill=1, stroke=0)
    set_font(pdf, 6.5, True, NAVY)
    pdf.drawCentredString(center, bottom + bar_h + 5, f"{day['solar_kwh']:.2f}")
    set_font(pdf, 6.2, False, MUTED)
    pdf.drawCentredString(center, y + 11, day["date"].strftime("%b %d"))


def draw_solar_table(pdf, x, y, width, days):
  headers = [("DATE", 0), ("GENERATED", 120), ("PEAK", 245), ("ACTIVE TIME", 345), ("MARKET VALUE", 445)]
  pdf.setFillColor(PALE); pdf.roundRect(x, y - 2, width, 22, 5, fill=1, stroke=0)
  for label, offset in headers:
    set_font(pdf, 7, True, MUTED); pdf.drawString(x + 8 + offset, y + 6, label)
  row_y = y - 20
  for index, day in enumerate(days):
    if index % 2 == 0:
      pdf.setFillColor(colors.HexColor("#F8FAFB")); pdf.rect(x, row_y - 4, width, 18, fill=1, stroke=0)
    values = [
      day["date"].strftime("%a, %b %d"), f"{day['solar_kwh']:.2f} kWh",
      f"{day['solar_peak']:,.0f} W", f"{day['solar_active_hours']:.1f} h",
      f"${day['solar_value']:.2f}",
    ]
    for value, offset in zip(values, [8, 128, 253, 353, 453]):
      set_font(pdf, 7.5, offset in {128, 253, 453}, NAVY if offset in {128, 253, 453} else INK)
      pdf.drawString(x + offset, row_y, value)
    row_y -= 18


def draw_daily_table(pdf, x, y, width, days):
  headers = [
    ("DATE", 0), ("MAIN", 90), ("SOLAR", 165), ("RECORDED", 240),
    ("MISSING", 315), ("COVERAGE", 385), ("COST", 465),
  ]
  pdf.setFillColor(PALE); pdf.roundRect(x, y - 2, width, 22, 5, fill=1, stroke=0)
  for label, offset in headers:
    set_font(pdf, 7, True, MUTED); pdf.drawString(x + 8 + offset, y + 6, label)
  row_y = y - 20
  for index, day in enumerate(days):
    if index % 2 == 0:
      pdf.setFillColor(colors.HexColor("#F8FAFB")); pdf.rect(x, row_y - 4, width, 18, fill=1, stroke=0)
    values = [
      day["date"].strftime("%a, %b %d"), f"{day['main_kwh']:.2f} kWh",
      f"{day['solar_kwh']:.2f} kWh", fmt_duration(day["measured_hours"]),
      fmt_duration(day["missing_hours"]), f"{day['coverage']:.1f}%",
      f"${day['cost']:.2f}",
    ]
    positions = [8, 98, 173, 248, 323, 393, 473]
    for value, offset in zip(values, positions):
      emphasized = offset in {98, 173, 323, 473}
      set_font(pdf, 7.5, emphasized, NAVY if emphasized else INK)
      pdf.drawString(x + offset, row_y, value)
    row_y -= 18


def draw_cost_table(pdf, x, y, width, rows):
  headers = [("PERIOD", 0), ("ENERGY", 150), ("ALL-IN RATE", 250), ("EST. COST", 370)]
  pdf.setFillColor(PALE); pdf.roundRect(x, y - 2, width, 24, 5, fill=1, stroke=0)
  for label, offset in headers:
    set_font(pdf, 7.5, True, MUTED); pdf.drawString(x + 10 + offset, y + 7, label)
  row_y = y - 22
  max_cost = max((row["cost"] for row in rows), default=1)
  for index, row in enumerate(rows):
    if index % 2 == 0:
      pdf.setFillColor(colors.HexColor("#F8FAFB")); pdf.rect(x, row_y - 5, width, 20, fill=1, stroke=0)
    set_font(pdf, 8, False, INK); pdf.drawString(x + 10, row_y, row["label"])
    pdf.drawRightString(x + 222, row_y, f"{row['energy_kwh']:.3f} kWh")
    pdf.drawRightString(x + 342, row_y, f"{row['price_cents']:.2f} cents/kWh")
    bar_x, bar_w = x + 390, 75
    pdf.setFillColor(PALE); pdf.roundRect(bar_x, row_y - 2, bar_w, 8, 4, fill=1, stroke=0)
    pdf.setFillColor(SOLAR); pdf.roundRect(bar_x, row_y - 2, bar_w * row["cost"] / max_cost, 8, 4, fill=1, stroke=0)
    set_font(pdf, 8, True, NAVY); pdf.drawRightString(x + width - 10, row_y, f"${row['cost']:.3f}")
    row_y -= 20
  return row_y


def draw_circuit_cost_table(pdf, x, y, width, rows, total_cost):
  headers = [("CIRCUIT", 0), ("ENERGY", 220), ("COST", 335), ("SHARE", 430)]
  pdf.setFillColor(PALE); pdf.roundRect(x, y - 2, width, 24, 5, fill=1, stroke=0)
  for label, offset in headers:
    set_font(pdf, 7.5, True, MUTED); pdf.drawString(x + 10 + offset, y + 7, label)
  row_y = y - 22
  for index, row in enumerate(rows):
    if index % 2 == 0:
      pdf.setFillColor(colors.HexColor("#F8FAFB")); pdf.rect(x, row_y - 5, width, 20, fill=1, stroke=0)
    set_font(pdf, 8, False, INK)
    label = row["name"] if len(row["name"]) <= 31 else row["name"][:30] + "..."
    pdf.drawString(x + 10, row_y, label)
    pdf.drawRightString(x + 310, row_y, f"{row['energy_kwh']:.2f} kWh")
    set_font(pdf, 8, True, NAVY); pdf.drawRightString(x + 410, row_y, f"${row['cost']:.3f}")
    pdf.drawRightString(x + width - 12, row_y, f"{row['cost'] / total_cost * 100:.1f}%")
    row_y -= 20


def build_report():
  rows = load_data()
  if not rows: raise RuntimeError("No channel_usage rows are available")
  bill_model = load_bill_model()
  variable_addon = bill_model["variable_addon_cents_per_kwh"]
  report_start_utc = min(datetime.fromisoformat(row["period_start"]) for row in rows)
  report_end_utc = max(datetime.fromisoformat(row["period_end"]) for row in rows)
  prices = load_prices(report_start_utc, report_end_utc)
  grouped = defaultdict(list)
  for row in rows: grouped[(row["period_start"], row["period_end"])].append(row)
  periods = []
  for (start, end), period_rows in grouped.items():
    names = {row["name"]: row for row in period_rows}
    periods.append({"start": local_time(start), "end": local_time(end),
      "coverage": min(row["coverage_percent"] for row in period_rows),
      "main_avg": names.get("Main Power", {"average_power_watts": 0})["average_power_watts"],
      "solar_avg": names.get("Solar Panels", {"average_power_watts": 0})["average_power_watts"]})
  periods.sort(key=lambda item: item["start"])
  complete_keys = {(s, e) for (s, e), rs in grouped.items() if min(r["coverage_percent"] for r in rs) >= 95}
  complete_rows = [r for r in rows if (r["period_start"], r["period_end"]) in complete_keys]
  by_name = defaultdict(list)
  for row in complete_rows: by_name[row["name"]].append(row)
  total = lambda name: sum(r["energy_wh"] for r in by_name.get(name, []))
  def weighted(name):
    target = by_name.get(name, []); seconds = sum(r["measured_seconds"] for r in target)
    return sum(r["average_power_watts"] * r["measured_seconds"] for r in target) / seconds if seconds else 0
  main_energy, solar_energy = total("Main Power"), total("Solar Panels")
  main_average = weighted("Main Power")
  solar_peak = max((r["maximum_power_watts"] for r in by_name.get("Solar Panels", [])), default=0)
  main_peak = max((r["maximum_power_watts"] for r in by_name.get("Main Power", [])), default=0)
  usable_hours = sum(r["measured_seconds"] for r in by_name.get("Main Power", [])) / 3600
  consumers = []
  for name, channel_rows in by_name.items():
    if name not in {"Main Power", "Solar Panels"}:
      consumers.append((name, sum(r["energy_wh"] for r in channel_rows), max(r["maximum_power_watts"] for r in channel_rows)))
  consumers.sort(key=lambda item: item[1], reverse=True); top_consumers = consumers[:10]

  main_by_period = {
    (row["period_start"], row["period_end"]): row
    for row in by_name.get("Main Power", [])
  }
  cost_rows = []
  average_price_by_period = {}
  for start_text, end_text in sorted(complete_keys):
    start_utc, end_utc = datetime.fromisoformat(start_text), datetime.fromisoformat(end_text)
    period_prices = [price for timestamp, price in prices if start_utc < timestamp <= end_utc]
    if not period_prices or (start_text, end_text) not in main_by_period:
      continue
    average_price = sum(period_prices) / len(period_prices)
    average_price_by_period[(start_text, end_text)] = average_price
    energy_kwh = main_by_period[(start_text, end_text)]["energy_wh"] / 1000
    cost_rows.append({
      "label": f"{start_utc.astimezone(LOCAL_ZONE):%-I:%M %p} - {end_utc.astimezone(LOCAL_ZONE):%-I:%M %p}",
      "date": start_utc.astimezone(LOCAL_ZONE).date(),
      "energy_kwh": energy_kwh,
      "market_price_cents": average_price,
      "price_cents": average_price + variable_addon,
      "market_cost": energy_kwh * average_price / 100,
      "cost": energy_kwh * (average_price + variable_addon) / 100,
    })
  market_cost = sum(row["market_cost"] for row in cost_rows)
  variable_cost = sum(row["cost"] for row in cost_rows)
  priced_energy = sum(row["energy_kwh"] for row in cost_rows)
  usage_addon_cost = priced_energy * variable_addon / 100
  total_cost = variable_cost
  weighted_price = variable_cost / priced_energy * 100 if priced_energy else 0
  price_values = [price for _, price in prices]
  highest_cost_row = max(cost_rows, key=lambda row: row["cost"])
  circuit_costs = defaultdict(lambda: {"energy_kwh": 0.0, "cost": 0.0})
  for row in complete_rows:
    if row["name"] in {"Main Power", "Solar Panels"}:
      continue
    key = (row["period_start"], row["period_end"])
    if key not in average_price_by_period:
      continue
    energy_kwh = row["energy_wh"] / 1000
    circuit_costs[row["name"]]["energy_kwh"] += energy_kwh
    circuit_costs[row["name"]]["cost"] += (
      energy_kwh * (average_price_by_period[key] + variable_addon) / 100
    )
  ranked_circuit_costs = sorted(
    [
      {"name": name, "energy_kwh": values["energy_kwh"], "cost": values["cost"]}
      for name, values in circuit_costs.items()
    ],
    key=lambda row: row["cost"],
    reverse=True,
  )

  daily_by_date = defaultdict(lambda: {
    "main_kwh": 0.0, "solar_kwh": 0.0, "cost": 0.0,
    "measured_seconds": 0.0, "expected_seconds": 0.0,
    "solar_peak": 0.0, "solar_active_hours": 0.0, "solar_value": 0.0,
  })
  for (start_text, end_text), period_rows in grouped.items():
    day = local_time(start_text).date()
    daily = daily_by_date[day]
    names = {row["name"]: row for row in period_rows}
    main_row = names.get("Main Power")
    solar_row = names.get("Solar Panels")
    if main_row:
      daily["measured_seconds"] += main_row["measured_seconds"]
    if (start_text, end_text) in complete_keys:
      daily["main_kwh"] += names.get("Main Power", {"energy_wh": 0})["energy_wh"] / 1000
      daily["solar_kwh"] += names.get("Solar Panels", {"energy_wh": 0})["energy_wh"] / 1000
      if solar_row:
        daily["solar_peak"] = max(daily["solar_peak"], solar_row["maximum_power_watts"])
        if solar_row["average_power_watts"] > 10:
          daily["solar_active_hours"] += solar_row["measured_seconds"] / 3600
        price = average_price_by_period.get((start_text, end_text))
        if price is not None:
          daily["solar_value"] += solar_row["energy_wh"] / 1000 * price / 100
  for row in cost_rows:
    daily_by_date[row["date"]]["cost"] += row["cost"]

  first_day = report_start_utc.astimezone(LOCAL_ZONE).date()
  last_day = report_end_utc.astimezone(LOCAL_ZONE).date()
  day = first_day
  while day <= last_day:
    values = daily_by_date[day]
    local_start = datetime.combine(day, time.min, LOCAL_ZONE)
    local_end = datetime.combine(day + timedelta(days=1), time.min, LOCAL_ZONE)
    expected_start = max(report_start_utc, local_start.astimezone(timezone.utc))
    expected_end = min(report_end_utc, local_end.astimezone(timezone.utc))
    values["expected_seconds"] = max(
      0, (expected_end - expected_start).total_seconds()
    )
    day += timedelta(days=1)

  daily_rows = []
  for day, values in sorted(daily_by_date.items()):
    expected = values["expected_seconds"]
    daily_rows.append({
      "date": day,
      "main_kwh": values["main_kwh"],
      "solar_kwh": values["solar_kwh"],
      "cost": values["cost"],
      "measured_hours": values["measured_seconds"] / 3600,
      "missing_hours": max(0, expected - values["measured_seconds"]) / 3600,
      "coverage": values["measured_seconds"] / expected * 100 if expected else 0,
      "solar_peak": values["solar_peak"],
      "solar_active_hours": values["solar_active_hours"],
      "solar_value": values["solar_value"],
    })

  OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
  pdf = canvas.Canvas(str(OUTPUT_PATH), pagesize=letter); pdf.setTitle("EMonitor Energy Usage Report")
  date_range = f"{periods[0]['start']:%b %d, %Y %I:%M %p} to {periods[-1]['end']:%b %d, %Y %I:%M %p} {periods[-1]['end']:%Z}"

  draw_header(pdf, "EMonitor - Energy Usage Report", date_range, 1)
  card_y, gap, card_w = 610, 8, (532 - 24) / 4
  draw_kpi(pdf, 40, card_y, card_w, "Main Power", fmt_kwh(main_energy), f"{main_average:,.0f} W weighted average", BLUE)
  draw_kpi(pdf, 40 + card_w + gap, card_y, card_w, "Solar Production", fmt_kwh(solar_energy), f"{solar_peak:,.0f} W sampled peak", SOLAR)
  draw_kpi(pdf, 40 + 2 * (card_w + gap), card_y, card_w, "Usable Data", f"{usable_hours:.1f} hours", f"{len(complete_keys)} periods at 95%+", GREEN)
  draw_kpi(pdf, 40 + 3 * (card_w + gap), card_y, card_w, "Main Peak", f"{main_peak:,.0f} W", "Highest sampled demand", RED)
  draw_section_title(pdf, 40, 586, "Power over the collection period", "All stored periods; partial periods retained")
  draw_line_chart(pdf, 40, 337, 532, 232, periods)
  draw_section_title(pdf, 40, 312, "Where measured circuit energy went", "Complete periods only; excludes Main Power and Solar")
  rounded_card(pdf, 40, 72, 532, 222)
  top_five, other = consumers[:5], sum(v for _, v, _ in consumers[5:])
  palette = [BLUE, TEAL, GREEN, SOLAR, RED, colors.HexColor("#AAB6BD")]
  values = [v for _, v, _ in top_five] + [other]
  draw_donut(pdf, 155, 180, 78, values, palette, fmt_kwh(sum(values)), "measured branches")
  legend = [(n, fmt_kwh(v), c) for (n, v, _), c in zip(top_five, palette)] + [("All other circuits", fmt_kwh(other), palette[-1])]
  draw_legend(pdf, 280, 237, legend, 28); draw_footer(pdf); pdf.showPage()

  chart_days = daily_rows[-14:]
  best_main_day = max(daily_rows, key=lambda row: row["main_kwh"])
  best_solar_day = max(daily_rows, key=lambda row: row["solar_kwh"])
  overall_daily_coverage = sum(row["measured_hours"] for row in daily_rows) / (
    sum(day["expected_seconds"] for day in daily_by_date.values()) / 3600
  ) * 100
  overall_missing_hours = sum(row["missing_hours"] for row in daily_rows)
  draw_header(pdf, "Daily Energy & Cost Trends", "Calendar-day view; first and last days may be partial", 2)
  draw_kpi(pdf, 40, card_y, card_w, "Calendar Days", str(len(daily_rows)), f"Latest {len(chart_days)} shown", BLUE)
  draw_kpi(pdf, 40 + card_w + gap, card_y, card_w, "Highest Main Day", f"{best_main_day['main_kwh']:.2f} kWh", best_main_day["date"].strftime("%b %d"), RED)
  draw_kpi(pdf, 40 + 2 * (card_w + gap), card_y, card_w, "Highest Solar Day", f"{best_solar_day['solar_kwh']:.2f} kWh", best_solar_day["date"].strftime("%b %d"), SOLAR)
  draw_kpi(pdf, 40 + 3 * (card_w + gap), card_y, card_w, "Recorded Coverage", f"{overall_daily_coverage:.1f}%", f"{fmt_duration(overall_missing_hours)} missing", GREEN)
  draw_section_title(pdf, 40, 586, "Daily Main Power and solar energy", "High-coverage half-hours only; latest 14 days")
  draw_daily_energy_bars(pdf, 40, 350, 532, 218, chart_days)
  draw_section_title(pdf, 40, 324, "Daily estimated variable cost", "Market energy plus bill-derived per-kWh charges")
  draw_daily_cost_bars(pdf, 40, 190, 532, 116, chart_days)
  draw_section_title(pdf, 40, 164, "Latest daily totals", "Missing time includes absent and partially sampled periods")
  draw_daily_table(pdf, 40, 140, 532, daily_rows[-4:])
  draw_footer(pdf); pdf.showPage()

  solar_active_hours = sum(day["solar_active_hours"] for day in daily_rows)
  solar_market_value = sum(day["solar_value"] for day in daily_rows)
  solar_active_average = solar_energy / solar_active_hours if solar_active_hours else 0
  draw_header(pdf, "Solar Generation", "Dedicated production view across high-coverage periods", 3)
  draw_kpi(pdf, 40, card_y, card_w, "Solar Generated", fmt_kwh(solar_energy), f"Across {len(daily_rows)} calendar days", SOLAR)
  draw_kpi(pdf, 40 + card_w + gap, card_y, card_w, "Sampled Peak", f"{solar_peak:,.0f} W", "Highest observed output", BLUE)
  draw_kpi(pdf, 40 + 2 * (card_w + gap), card_y, card_w, "Generating Time", f"{solar_active_hours:.1f} hours", f"{solar_active_average:,.0f} W active average", GREEN)
  draw_kpi(pdf, 40 + 3 * (card_w + gap), card_y, card_w, "Market Value", f"${solar_market_value:.2f}", "Not a utility credit", RED)
  draw_section_title(pdf, 40, 586, "Solar production over time", "Half-hour averages; partial periods retained")
  draw_solar_timeline(pdf, 40, 350, 532, 218, periods)
  draw_section_title(pdf, 40, 324, "Daily solar generation", "Latest 14 calendar days")
  draw_solar_daily_bars(pdf, 40, 176, 252, 130, chart_days)
  rounded_card(pdf, 320, 176, 252, 130)
  solar_notes = [
    f"Best recorded day: {best_solar_day['date']:%b %d} ({best_solar_day['solar_kwh']:.2f} kWh).",
    f"Active-period average: {solar_active_average:,.0f} W.",
    "Main Power is treated as already net of solar.",
    "Market value uses matching ComEd prices; it is not the bill credit.",
  ]
  py = 278
  for note in solar_notes:
    pdf.setFillColor(SOLAR); pdf.circle(337, py + 3, 3, fill=1, stroke=0)
    set_font(pdf, 8, False, INK); pdf.drawString(347, py, note); py -= 25
  draw_section_title(pdf, 40, 150, "Latest daily solar totals", "Active time uses periods averaging more than 10 W")
  draw_solar_table(pdf, 40, 126, 532, daily_rows[-4:])
  draw_footer(pdf); pdf.showPage()

  draw_header(pdf, "Circuit Detail & Data Quality", "Energy detail plus explicit daily collection gaps", 4)
  draw_section_title(pdf, 40, 674, "Top consuming circuits", "Cumulative energy across high-coverage periods")
  rounded_card(pdf, 40, 374, 532, 282); draw_horizontal_bars(pdf, 56, 392, 500, 244, top_consumers)
  quality_days = daily_rows[-31:]
  draw_section_title(pdf, 40, 347, "Missing data by day")
  draw_missing_minutes_bars(pdf, 40, 147, 332, 184, quality_days)
  expected_periods = round(
    sum(values["expected_seconds"] for values in daily_by_date.values()) / 1800
  )
  observed_coverages = [period["coverage"] for period in periods]
  coverage_bands = [
    ("90-100%", sum(value >= 90 for value in observed_coverages), GREEN),
    ("75-<90%", sum(75 <= value < 90 for value in observed_coverages), SOLAR),
    ("Below 75%", sum(value < 75 for value in observed_coverages), RED),
    ("No period", max(0, expected_periods - len(periods)), colors.HexColor("#AAB6BD")),
  ]
  draw_section_title(pdf, 392, 347, "Half-hour coverage bands")
  draw_coverage_bands(pdf, 392, 147, 180, 184, coverage_bands)
  draw_section_title(pdf, 40, 122, "Methodology & interpretation"); set_font(pdf, 8, False, MUTED)
  notes = ["Energy is integrated from sampled watts using elapsed time and reported in watt-hours.", "Paired physical channels are added before aggregation. Main Power is treated as the total usage signal.", "Missing minutes compare recorded Main Power time with each local calendar day; first and last days are clipped to the report range.", "Coverage bands count recorded half-hours by their least-complete channel; No period means the entire half-hour is absent."]
  py = 104
  for line in notes: pdf.drawString(40, py, line); py -= 13
  draw_footer(pdf); pdf.showPage()

  draw_header(pdf, "ComEd Variable Cost Estimate", "Market energy plus bill-derived per-kWh charges", 5)
  draw_kpi(pdf, 40, card_y, card_w, "Estimated Variable Cost", f"${total_cost:.2f}", f"For {priced_energy:.2f} kWh", SOLAR)
  draw_kpi(pdf, 40 + card_w + gap, card_y, card_w, "Market Energy", f"${market_cost:.2f}", "Matching real-time prices", BLUE)
  draw_kpi(pdf, 40 + 2 * (card_w + gap), card_y, card_w, "Usage Add-ons", f"${usage_addon_cost:.2f}", f"{variable_addon:.2f} cents/kWh", GREEN)
  draw_kpi(pdf, 40 + 3 * (card_w + gap), card_y, card_w, "Average Variable Rate", f"{weighted_price:.2f} cents", "Per imported kWh", RED)
  recent_cost_rows = cost_rows[-13:]
  draw_section_title(pdf, 40, 586, "Latest half-hour estimated variable charges", "Market price plus bill-derived per-kWh charges")
  rounded_card(pdf, 40, 274, 532, 294)
  draw_cost_table(pdf, 50, 535, 512, recent_cost_rows)

  draw_section_title(pdf, 40, 247, "Important billing context")
  rounded_card(pdf, 40, 72, 532, 157)
  context = [
    "Calibrated from the ComEd bill issued Oct 13, 2026 for a 32-day service period.",
    f"Usage add-ons are {variable_addon:.3f} cents/kWh for delivery, adjustments, programs, and taxes.",
    "Fixed capacity, customer, metering, and low-income recovery charges are excluded.",
    "Export credits are excluded because EMonitor does not separately measure electricity sent to the grid.",
    "Actual bills may differ as tariffs, taxes, capacity obligations, and settled prices change.",
  ]
  py = 202
  for text in context:
    pdf.setFillColor(BLUE); pdf.circle(57, py + 3, 3, fill=1, stroke=0)
    set_font(pdf, 8.5, False, INK); pdf.drawString(68, py, text); py -= 25
  set_font(pdf, 7.2, False, MUTED)
  pdf.drawString(54, 88, "Sources: ComEd 5-Minute Price Data API and the Oct 13, 2026 ComEd bill calibration")
  draw_footer(pdf); pdf.showPage()

  top_costs = ranked_circuit_costs[:5]
  other_cost = sum(row["cost"] for row in ranked_circuit_costs[5:])
  measured_branch_cost = sum(row["cost"] for row in ranked_circuit_costs)
  top_share = top_costs[0]["cost"] / measured_branch_cost * 100
  draw_header(pdf, "Measured Branch Cost Allocation", "Estimated cost shares across individually monitored circuits", 6)
  draw_kpi(pdf, 40, card_y, card_w, "Branch Estimate", f"${measured_branch_cost:.2f}", "Variable charges only", SOLAR)
  draw_kpi(pdf, 40 + card_w + gap, card_y, card_w, "Top Circuit", f"${top_costs[0]['cost']:.2f}", top_costs[0]["name"], BLUE)
  draw_kpi(pdf, 40 + 2 * (card_w + gap), card_y, card_w, "Top Share", f"{top_share:.1f}%", "Of measured branch cost", GREEN)
  draw_kpi(pdf, 40 + 3 * (card_w + gap), card_y, card_w, "Circuits", str(len(ranked_circuit_costs)), "With measured energy", RED)

  draw_section_title(pdf, 40, 586, "Cost share of measured circuits", "Market price plus bill-derived per-kWh charges")
  rounded_card(pdf, 40, 360, 532, 208)
  cost_palette = [BLUE, TEAL, GREEN, SOLAR, RED, colors.HexColor("#AAB6BD")]
  cost_values = [row["cost"] for row in top_costs] + [other_cost]
  draw_donut(pdf, 155, 465, 76, cost_values, cost_palette, f"${measured_branch_cost:.2f}", "measured branches")
  cost_legend = [
    (row["name"], f"${row['cost']:.3f}", color)
    for row, color in zip(top_costs, cost_palette)
  ] + [("All other circuits", f"${other_cost:.3f}", cost_palette[-1])]
  draw_legend(pdf, 280, 520, cost_legend, 25)

  draw_section_title(pdf, 40, 333, "Highest estimated circuit costs", "Measured branches only")
  rounded_card(pdf, 40, 55, 532, 260)
  draw_circuit_cost_table(
    pdf, 50, 282, 512, ranked_circuit_costs[:9], measured_branch_cost
  )
  set_font(pdf, 7.5, False, MUTED)
  pdf.drawString(50, 73, "Variable branch estimates exclude fixed charges and may not reconcile because branch totals differ from Main Power.")
  draw_footer(pdf); pdf.save(); print(OUTPUT_PATH)


if __name__ == "__main__": build_report()
