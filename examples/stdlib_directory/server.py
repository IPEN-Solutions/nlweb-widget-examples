import asyncio
from http.server import HTTPServer

from nlweb_widget.integrations.stdlib_http_integration import make_stdlib_handler

from examples.scenario_data import build_example_widget

widget = build_example_widget("http://localhost:8080", __file__)
asyncio.run(widget.startup())


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8080), make_stdlib_handler(widget)).serve_forever()
