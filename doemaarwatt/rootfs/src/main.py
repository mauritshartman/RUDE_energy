import asyncio
from server import DoeMaarWattServer
from datetime import datetime as dt


async def main():
    server = DoeMaarWattServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
