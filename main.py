import asyncio


class EMonitor:
    def __init__(self):
        self.name_ = "Test"

    async def run(self):
        while True:
            print("Hi")
            await asyncio.sleep(10)


async def run():
    while True:
        print("Hi")
        await asyncio.sleep(10)

async def main():
    print("Hi")
    await asyncio.sleep(10)

if __name__ == '__main__':
    #asyncio.run(main())
    app = EMonitor()
    asyncio.run(run ())
