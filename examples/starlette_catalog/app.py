import asyncio

from nlweb_widget.integrations.starlette_integration import build_starlette_nlweb_routes
from starlette.applications import Starlette

from examples.scenario_data import build_example_widget

widget = build_example_widget("https://catalog.example", __file__)
asyncio.run(widget.startup())
app = Starlette(routes=list(build_starlette_nlweb_routes(widget)))
