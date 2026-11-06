from main import summarize_power


def test_power_summary_separates_solar_and_excludes_aggregate_main_power():
  readings = [
    {"channel_id": 1, "channel_name": "Main Power", "power_watts": 900},
    {"channel_id": 32, "channel_name": "Solar Panels", "power_watts": 850},
    {"channel_id": 3, "channel_name": "Air Conditioner", "power_watts": 700},
    {"channel_id": 4, "channel_name": "Kitchen", "power_watts": 100},
  ]

  solar_power, total_usage, peak_consumer = summarize_power(readings)

  assert solar_power == 850
  assert total_usage == 900
  assert peak_consumer == readings[2]
