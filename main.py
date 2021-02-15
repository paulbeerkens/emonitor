import asyncio

from EMonitorWebPage import EMonitorWebPage
from EMonitorDB import EMonitorDB

class EMonitor:
    def __init__(self):
        self.name_ = "Test"
        self.page = EMonitorWebPage('external')
        self.db_ = EMonitorDB ()

    async def run(self):
        await self.update_meta()
        while True:
            values=await self.page.get()
            self.db_.store (values)
            await asyncio.sleep(30)

    async def update_meta(self):
        values=await self.page.get_meta()
        self.db_.store_meta(values)

if __name__ == '__main__':
    app = EMonitor()
    asyncio.run(app.run())
