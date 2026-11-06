import tomllib
from pathlib import Path


def test_zensical_navigation_targets_exist() -> None:
    config = tomllib.loads(Path("zensical.toml").read_text(encoding="utf-8"))

    def walk(items: list[object]) -> list[str]:
        paths: list[str] = []
        for item in items:
            if isinstance(item, str):
                paths.append(item)
            elif isinstance(item, dict):
                for value in item.values():
                    if isinstance(value, str):
                        paths.append(value)
                    elif isinstance(value, list):
                        paths.extend(walk(value))
        return paths

    targets = walk(config["project"]["nav"])
    docs_root = Path(config["project"]["docs_dir"])
    assert targets
    assert all((docs_root / target).is_file() for target in targets)
