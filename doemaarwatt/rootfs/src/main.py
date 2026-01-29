import asyncio
from server import DoeMaarWattServer
from datetime import datetime as dt


async def main():
    server = DoeMaarWattServer()
    await server.run()


if __name__ == "__main__":
    print(dt.now().astimezone().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3])
    asyncio.run(main())
