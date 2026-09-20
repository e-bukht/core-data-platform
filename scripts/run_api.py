from __future__ import annotations

import asyncio
import selectors
import sys

import uvicorn


def _selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


async def _serve(server: uvicorn.Server) -> None:
    if sys.platform == "win32":
        loop = asyncio.get_running_loop()
        if not isinstance(loop, asyncio.SelectorEventLoop):
            raise RuntimeError(
                f"Windows runtime requires SelectorEventLoop, got {type(loop).__name__}"
            )

    await server.serve()


def main() -> None:
    config = uvicorn.Config(
        "core_platform.host.main:app",
        host="127.0.0.1",
        port=8080,
        loop="none",
    )
    server = uvicorn.Server(config)

    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=_selector_loop_factory) as runner:
            runner.run(_serve(server))
    else:
        asyncio.run(_serve(server))


if __name__ == "__main__":
    main()
