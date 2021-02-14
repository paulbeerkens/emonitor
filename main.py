import asyncio
import aiohttp

from EMonitorWebPage import EMonitorWebPage

class EMonitor:
    def __init__(self):
        self.name_ = "Test"
        self.page = EMonitorWebPage()

    async def run(self):
        while True:
            values=await self.page.get ()
            print (values)
            await asyncio.sleep(30)


if __name__ == '__main__':
    app = EMonitor()
    asyncio.run(app.run())
