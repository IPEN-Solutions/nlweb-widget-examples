import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from examples.visibility_demo import run

if __name__ == "__main__":
    asyncio.run(run("https://example.test", "fastapi_retail"))
