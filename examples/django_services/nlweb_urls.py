import asyncio

from nlweb_widget.integrations.django_integration import build_django_nlweb_urls

from examples.scenario_data import build_example_widget

widget = build_example_widget("https://services.example", __file__)
asyncio.run(widget.startup())
urlpatterns = build_django_nlweb_urls(widget)
