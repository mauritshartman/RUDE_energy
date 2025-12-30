import asyncio
from server import DoeMaarWattServer


async def main():
    server = DoeMaarWattServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
