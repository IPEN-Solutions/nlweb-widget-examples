import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "examples.django_services.settings")

import django
from django.core.management import execute_from_command_line

django.setup()


if __name__ == "__main__":
    execute_from_command_line(["manage_demo.py", "runserver", "127.0.0.1:8000"])
