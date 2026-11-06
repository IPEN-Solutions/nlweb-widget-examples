import asyncio

from flask import Flask
from nlweb_widget.integrations.flask_integration import mount_flask_nlweb

from examples.scenario_data import build_example_widget

widget = build_example_widget("https://marketing.example", __file__)
asyncio.run(widget.startup())
app = mount_flask_nlweb(Flask(__name__), widget)
