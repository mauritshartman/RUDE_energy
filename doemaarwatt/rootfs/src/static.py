import asyncio
from typing import Callable, Awaitable
from pathlib import Path

from aiohttp import web


@web.middleware
async def filter_ingress_prefix(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    resp = await handler(request)
    print(request.headers)
    print(request.path)
    return resp
