if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nlweb_widget.integrations.fastapi_integration import mount_fastapi_nlweb

from examples.provider_backends.common.widget import build_provider_widget

widget = build_provider_widget("sqlite", "https://sqlite.example", __file__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await widget.startup()
    yield
    await widget.close()


app = FastAPI(title="SQLite + sqlite-vec Provider Example", lifespan=lifespan)
mount_fastapi_nlweb(app, widget)
