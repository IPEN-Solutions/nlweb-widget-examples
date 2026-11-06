import subprocess
import sys
from pathlib import Path

DEMO_PATHS = [
    "examples/fastapi_retail/visibility_demo/run_demo.py",
    "examples/flask_marketing/visibility_demo/run_demo.py",
    "examples/django_services/visibility_demo/run_demo.py",
    "examples/starlette_catalog/visibility_demo/run_demo.py",
    "examples/stdlib_directory/visibility_demo/run_demo.py",
]


def test_visibility_demos_are_directly_runnable() -> None:
    for relative_path in DEMO_PATHS:
        result = subprocess.run(
            [sys.executable, relative_path],
            cwd=Path.cwd(),
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "MOCK AI-SEARCH VISIBILITY" in result.stdout
