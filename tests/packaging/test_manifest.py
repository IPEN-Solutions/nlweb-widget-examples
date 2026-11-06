from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def test_example_workspace_is_independent_and_governance_is_local_only() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "nlweb-widget-examples"
    assert data["project"]["requires-python"] == ">=3.12,<3.15"
    assert data["tool"]["uv"]["package"] is False
    assert not Path(".python-version").exists()

    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "/package-mutation-evidence/" in gitignore
    governance = Path("package-mutation-evidence")
    # QA bundles include the local governance records; a GitHub checkout intentionally
    # does not. The tests must pass in both environments without requiring ignored files.
    root_governance_patterns = (
        "ARTIFACT-INTEGRITY*.toml",
        "MANIFEST.release.txt",
        "MUTATION*.md",
        "PATCH-R*-QA.md",
        "GENESIS.md",
        "nlweb-widget-ecosystem-manifest.toml",
        "nlweb-widget-examples-ecosystem-manifest.toml",
        "revision-iteration-manifest-*.toml",
    )
    root_governance = [
        path
        for pattern in root_governance_patterns
        for path in Path(".").glob(pattern)
        if path.is_file()
    ]
    assert not root_governance, f"root-level governance artifacts are forbidden: {root_governance}"
    if governance.is_dir():
        policy = tomllib.loads(
            (governance / "nlweb-widget-examples-ecosystem-manifest.toml").read_text(
                encoding="utf-8"
            )
        )
        assert (
            policy["mutation_evidence_location"]["root_level_governance_artifacts_forbidden"]
            is True
        )
        assert policy["mutation_evidence_location"]["folder_is_local_only_and_gitignored"] is True


def test_test_tooling_is_available_for_ide_discovery() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert "pytest>=8,<9" in pyproject["project"]["dependencies"]
    assert "anyio>=4.13,<4.14" in pyproject["project"]["dependencies"]
    assert Path(".vscode/settings.json").is_file()


def test_base_dependencies_support_ide_pytest_discovery() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert "pytest>=8,<9" in data["project"]["dependencies"]
    assert "anyio>=4.13,<4.14" in data["project"]["dependencies"]


def test_provider_runtime_tooling_and_native_dependency_constraint() -> None:
    import json

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert "numpy>=2.2,<2.3" in pyproject["project"]["dependencies"]

    launch = json.loads(Path(".vscode/launch.json").read_text(encoding="utf-8"))
    launch_names = {entry["name"] for entry in launch["configurations"]}
    for provider in (
        "haystack_inmemory",
        "qdrant_edge",
        "qdrant_server",
        "postgres_pgvector",
        "neo4j",
        "sqlite",
    ):
        assert f"Python: Provider {provider}" in launch_names
        assert f"Python: Provider {provider} query demo" in launch_names

    tasks = json.loads(Path(".vscode/tasks.json").read_text(encoding="utf-8"))
    task_names = {entry["label"] for entry in tasks["tasks"]}
    for provider in (
        "haystack_inmemory",
        "qdrant_edge",
        "qdrant_server",
        "postgres_pgvector",
        "neo4j",
        "sqlite",
    ):
        assert f"Provider: {provider} — test" in task_names
        assert f"Provider: {provider} — run" in task_names
        assert f"Provider: {provider} — query demo" in task_names


def test_external_hosted_source_runtime_tooling() -> None:
    import json

    launch = json.loads(Path(".vscode/launch.json").read_text(encoding="utf-8"))
    launch_names = {entry["name"] for entry in launch["configurations"]}
    assert "Python: External hosted sources FastAPI" in launch_names
    assert "Python: External hosted sources query demo" in launch_names
    assert "Python: External hosted sources tests" in launch_names
    assert "Python: External hosted sources extraction demo" in launch_names

    tasks = json.loads(Path(".vscode/tasks.json").read_text(encoding="utf-8"))
    task_names = {entry["label"] for entry in tasks["tasks"]}
    for suffix in ("test", "run", "query demo", "extraction demo"):
        assert f"External hosted sources: {suffix}" in task_names


def test_public_changelogs_only_cover_approved_release_deltas() -> None:
    for path in (Path("CHANGELOG.md"), Path("docs/changelog.md")):
        content = path.read_text(encoding="utf-8").lower()
        assert "candidate-local-qa" not in content
        assert "not promoted" not in content
        assert "0.1.8 — approved release" in content


def test_standalone_workspace_does_not_pin_python_patch_version() -> None:
    assert not Path(".python-version").exists()
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["requires-python"] == ">=3.12,<3.15"
