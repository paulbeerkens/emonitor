import asyncio

from EMonitorWebPage import EMonitorWebPage
from EMonitorDB import EMonitorDB

class EMonitor:
    def __init__(self):
        self.name_ = "Test"
        self.page = EMonitorWebPage('external')
        self.db_ = EMonitorDB ()

    async def run(self):
        while True:
            values=await self.page.get ()
            print (values)
            await asyncio.sleep(30)


if __name__ == '__main__':
    app = EMonitor()
    asyncio.run(app.run())
