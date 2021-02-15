import asyncio
import logging
from EMonitorWebPage import EMonitorWebPage
from EMonitorDB import EMonitorDB
from datetime import datetime,timedelta


class EMonitor:
  def __init__(self):
    self.logger_ = logging.getLogger('main')
    self.logger_.setLevel(logging.DEBUG)
    now = datetime.now()
    filename = f'var/writer_{now.strftime("%Y%m%d_%H%M%S")}.log'
    fh = logging.FileHandler(filename)
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s|%(levelname)s|%(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    self.logger_.addHandler(fh)
    self.logger_.addHandler(ch)

    self.logger_.info (f'Writing log file to {filename}')

    self.name_ = "Test"
    self.page = EMonitorWebPage('external')
    self.db_ = EMonitorDB()

  async def run(self):
    self.logger_.info("Starting")
    next= datetime.now()
    await self.update_meta()
    while True:
      values = await self.page.get()
      self.db_.store(values)
      next+=timedelta(seconds=5)
      await asyncio.sleep((next - datetime.now()).total_seconds())

  async def update_meta(self):
    values = await self.page.get_meta()
    self.db_.store_meta(values)


if __name__ == '__main__':
    app = EMonitor()
    asyncio.run(app.run())
