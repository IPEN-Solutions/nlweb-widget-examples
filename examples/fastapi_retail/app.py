from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nlweb_widget.integrations.fastapi_integration import mount_fastapi_nlweb

from examples.scenario_data import build_example_widget

widget = build_example_widget("https://retail.example", __file__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await widget.startup()
    yield
    await widget.close()


app = FastAPI(title="Retail AI Visibility", lifespan=lifespan)
mount_fastapi_nlweb(app, widget)
