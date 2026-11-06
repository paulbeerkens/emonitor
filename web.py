import os

from flask import Flask, render_template
from dotenv import load_dotenv

from EMonitorDB import EMonitorDB

load_dotenv()


def create_app(database_path: str | None = None) -> Flask:
  app = Flask(__name__)
  db = EMonitorDB(database_path or os.getenv("DATABASE_PATH", "db/emonitor.db"))

  @app.route("/")
  def current():
    latest_usage = db.load_latest_usage()
    for row in latest_usage:
      row["period_start"] = row["period_start"].astimezone()
      row["period_end"] = row["period_end"].astimezone()
    latest_time = max((row["period_end"] for row in latest_usage), default=None)
    return render_template("current.html", data=latest_usage, time=latest_time)

  return app


app = create_app()


if __name__ == "__main__":
  app.run(host=os.getenv("WEB_HOST", "127.0.0.1"), port=int(os.getenv("WEB_PORT", "5000")))
