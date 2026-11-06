import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv


def test_artifact_packaging_policy_is_fail_closed() -> None:
    manifest = Path("package-mutation-evidence/nlweb-widget-examples-ecosystem-manifest.toml")
    if manifest.is_file():
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        policy = data["artifact_packaging"]
        assert policy["fail_closed"] is True
        for fragment in (".venv/", "__pycache__/", ".pytest_cache/", ".ruff_cache/"):
            assert fragment in policy["forbidden_path_fragments"]
        assert (
            data["mutation_evidence_location"]["root_level_governance_artifacts_forbidden"] is True
        )
    else:
        # The governance directory is intentionally ignored and absent in GitHub clones.
        assert "/package-mutation-evidence/" in Path(".gitignore").read_text(encoding="utf-8")
    assert not Path(".python-version").exists()


def test_root_askagent_configuration_is_opt_in() -> None:
    lines = Path(".env.example").read_text(encoding="utf-8").splitlines()
    names = ("ASKAGENT_URL", "OPENROUTER_API_KEY", "ASKAGENT_MODEL", "ASKAGENT_EMBEDDING_MODEL")
    for name in names:
        matching = [line for line in lines if line.strip().startswith(name + "=")]
        assert not matching, f"{name} must be commented in the default root .env.example"


def test_neo4j_bootstrap_dimension_is_configuration_driven() -> None:
    cypher = Path("provider_backends/infra/neo4j/002_vector_index.cypher").read_text(
        encoding="utf-8"
    )
    assert "`vector.dimensions`: $vector_dimensions" in cypher
    assert "`vector.dimensions`: 384" not in cypher
    assert "NLWEB_NEO4J_TEST_DATABASE" not in Path(
        "examples/provider_backends/neo4j/.env.example"
    ).read_text(encoding="utf-8")


def _load_provider_env(name: str) -> None:
    root_env = Path(".env")
    if root_env.is_file():
        load_dotenv(root_env, override=False)
    provider_env = Path("examples/provider_backends") / name / ".env"
    if provider_env.is_file():
        load_dotenv(provider_env, override=True)


def _configured_embedder(dimensions: int = 4):
    class _ConfiguredTestEmbedder:
        async def embed(self, texts):
            return [[1.0 / (index + 1) for index in range(dimensions)] for _ in texts]

    return _ConfiguredTestEmbedder()


NEO4J_TEST_LABEL = "NLWebTestDocument"
NEO4J_TEST_INDEX = "test_nlweb_document_embedding_r1"
NEO4J_TEST_CONSTRAINT = "nlweb_test_document_id_r1"
NEO4J_TEST_SITE_INDEX = "nlweb_test_document_site_r1"
NEO4J_TEST_DIMENSIONS = 4


async def _prepare_neo4j_test_schema(driver, database: str) -> None:
    """Create a same-database Neo4j test schema isolated by label and index.

    The frozen Neo4j store writes ``NLWebDocument`` nodes and therefore cannot
    be pointed at a second label without changing the frozen package.  The
    configured-provider test keeps the production store untouched and uses a
    test-only label/index schema for its vector retrieval assertion.
    """
    await driver.execute_query(
        f"CREATE CONSTRAINT {NEO4J_TEST_CONSTRAINT} IF NOT EXISTS "
        f"FOR (d:{NEO4J_TEST_LABEL}) REQUIRE d.id IS UNIQUE",
        database_=database,
    )
    await driver.execute_query(
        f"CREATE INDEX {NEO4J_TEST_SITE_INDEX} IF NOT EXISTS "
        f"FOR (d:{NEO4J_TEST_LABEL}) ON (d.site)",
        database_=database,
    )
    await driver.execute_query(
        f"""CREATE VECTOR INDEX {NEO4J_TEST_INDEX} IF NOT EXISTS
        FOR (d:{NEO4J_TEST_LABEL}) ON d.embedding OPTIONS {{ indexConfig: {{
        `vector.dimensions`: {NEO4J_TEST_DIMENSIONS},
        `vector.similarity_function`: 'cosine' }} }}""",
        database_=database,
    )

    for _ in range(30):
        records, _, _ = await driver.execute_query(
            "SHOW VECTOR INDEXES YIELD name, state WHERE name = $name RETURN state",
            name=NEO4J_TEST_INDEX,
            database_=database,
        )
        if records and str(records[0]["state"]).upper() == "ONLINE":
            return
        import asyncio

        await asyncio.sleep(1)
    raise RuntimeError(f"Neo4j test vector index '{NEO4J_TEST_INDEX}' did not become ONLINE")


async def _assert_neo4j_test_index_contract(driver, database: str) -> None:
    records, _, _ = await driver.execute_query(
        "SHOW VECTOR INDEXES YIELD name, state, labelsOrTypes, properties, options "
        "WHERE name = $test "
        "RETURN name, state, labelsOrTypes, properties, options",
        test=NEO4J_TEST_INDEX,
        database_=database,
    )
    assert len(records) == 1
    test = records[0]
    assert str(test["state"]).upper() == "ONLINE"
    assert test["labelsOrTypes"] == [NEO4J_TEST_LABEL]
    assert test["properties"] == ["embedding"]
    index_config = test["options"]["indexConfig"]
    assert index_config["vector.dimensions"] == NEO4J_TEST_DIMENSIONS


async def _exercise_neo4j_test_schema(driver, database: str) -> None:
    embedder = _configured_embedder()
    document_id = "r4-neo4j-test"
    vector = (await embedder.embed(["Retail AI provider test"]))[0]
    await driver.execute_query(
        f"""MERGE (d:{NEO4J_TEST_LABEL} {{id: $id}})
        SET d.url=$url, d.title=$title, d.content=$content, d.site=$site,
            d.schemaJson=$schema, d.metadataJson=$metadata, d.embedding=$embedding,
            d.updatedAt=datetime()""",
        id=document_id,
        url="https://example.test/r4-neo4j-test",
        title="Provider test",
        content="Retail AI provider test",
        site="default",
        schema="{}",
        metadata="{}",
        embedding=[float(value) for value in vector],
        database_=database,
    )
    try:
        records, _, _ = await driver.execute_query(
            "CALL db.index.vector.queryNodes($index, $limit, $embedding) "
            "YIELD node AS d, score "
            "RETURN d.id AS id, score ORDER BY score DESC",
            index=NEO4J_TEST_INDEX,
            limit=1,
            embedding=[float(value) for value in vector],
            database_=database,
        )
        assert records and records[0]["id"] == document_id
    finally:
        await driver.execute_query(
            f"MATCH (d:{NEO4J_TEST_LABEL} {{id: $id}}) DETACH DELETE d",
            id=document_id,
            database_=database,
        )


import pytest
from nlweb_widget import ContentDocument, NLWebRequest, NLWebWidget
from nlweb_widget.settings import NLWebSettings


@pytest.mark.asyncio
async def test_postgres_provider_when_explicitly_configured():
    _load_provider_env("postgres_pgvector")
    url = os.getenv("NLWEB_POSTGRES_DATABASE_URL")
    if not url:
        pytest.skip("NLWEB_POSTGRES_DATABASE_URL is not configured")
    pytest.importorskip("sqlalchemy")
    from nlweb_widget.content import PgVectorStore

    store = PgVectorStore(
        url,
        _configured_embedder(),
        dimensions=4,
        table="test_nlweb_documents_r1_postgres",
    )
    await store.initialize()
    document = ContentDocument(
        id="r4-postgres-test",
        url="https://example.test/r4-postgres-test",
        title="Provider test",
        content="Retail AI provider test",
    )
    try:
        assert await store.upsert(document) == 1
        matches = await store.search("retail AI", limit=1)
        assert matches and matches[0][0].id == document.id
    finally:
        await store.delete([document.id])
        await store.close()


@pytest.mark.asyncio
async def test_neo4j_provider_when_explicitly_configured():
    _load_provider_env("neo4j")
    uri = os.getenv("NLWEB_NEO4J_URI")
    username = os.getenv("NLWEB_NEO4J_USERNAME", "neo4j")
    password = os.getenv("NLWEB_NEO4J_PASSWORD")
    if not uri or not password:
        pytest.skip("NLWEB_NEO4J_URI and NLWEB_NEO4J_PASSWORD are not configured")
    pytest.importorskip("neo4j")
    from neo4j import AsyncGraphDatabase

    database = os.getenv("NLWEB_NEO4J_DATABASE", "neo4j").strip() or "neo4j"

    # This test intentionally exercises only its own schema. The configured
    # production/example store and its user-owned entities are outside this
    # test's scope and are covered by the Widget package's own test suite.
    driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
    try:
        await _prepare_neo4j_test_schema(driver, database)
        await _assert_neo4j_test_index_contract(driver, database)
        await _exercise_neo4j_test_schema(driver, database)

        # Test nodes carry only the test label, so the 4D vectors can never be
        # admitted to the production NLWebDocument.embedding index.
        records, _, _ = await driver.execute_query(
            f"MATCH (d:{NEO4J_TEST_LABEL}) RETURN count(d) AS count",
            database_=database,
        )
        assert int(records[0]["count"]) == 0
    finally:
        await driver.close()


@pytest.mark.asyncio
async def test_qdrant_server_provider_when_explicitly_configured():
    _load_provider_env("qdrant_server")
    url = os.getenv("NLWEB_QDRANT_URL")
    if not url:
        pytest.skip("NLWEB_QDRANT_URL is not configured")
    pytest.importorskip("qdrant_client")
    from nlweb_widget.content import QdrantRetrievalStore

    collection = os.getenv("NLWEB_QDRANT_COLLECTION", "nlweb_examples_qdrant_server") + "_qa"
    store = QdrantRetrievalStore(
        url,
        _configured_embedder(),
        collection=collection,
        dimensions=4,
        api_key=os.getenv("NLWEB_QDRANT_API_KEY") or None,
    )
    document = ContentDocument(
        id="examples-qdrant-server-test",
        url="https://example.test/qdrant-server-test",
        title="Qdrant Server test",
        content="Qdrant Server example provider test",
    )
    try:
        await store.initialize()
        assert await store.upsert(document) == 1
        matches = await store.search("Qdrant Server example provider test", limit=1)
        assert matches and matches[0][0].id == document.id
    finally:
        await store.delete([document.id])
        await store.close()


@pytest.mark.asyncio
async def test_qdrant_edge_provider_when_explicitly_configured(tmp_path):
    _load_provider_env("qdrant_edge")
    configured_path = os.getenv("NLWEB_QDRANT_EDGE_PATH")
    if not configured_path:
        pytest.skip("NLWEB_QDRANT_EDGE_PATH is not configured")
    pytest.importorskip("qdrant_edge")
    from nlweb_widget.content import QdrantEdgeRetrievalStore

    # The provider's configured .env enables this test; its persistent test data
    # is deliberately isolated from the runnable example application state.
    dimensions = int(os.getenv("NLWEB_QDRANT_EDGE_DIMENSIONS", "384"))
    path = str(tmp_path / "qdrant-edge-test")
    store = QdrantEdgeRetrievalStore(path, _configured_embedder(dimensions), dimensions=dimensions)
    document = ContentDocument(
        id="examples-qdrant-edge-test",
        url="https://example.test/qdrant-edge-test",
        title="Qdrant Edge test",
        content="Qdrant Edge example provider test",
    )
    try:
        await store.upsert(document)
        matches = await store.search("Qdrant Edge example provider test", limit=1)
        assert matches and matches[0][0].id == document.id
        matches = await store.search("Qdrant Edge example provider test", limit=1)
        assert matches and matches[0][0].id == document.id

        # Exercise the same framework-neutral /ask path used by the example app.
        # The widget receives the already-created test store explicitly, so its
        # settings must not create or reconfigure a provider-owned persistent store.
        widget = NLWebWidget(
            store=store,
            domain="https://edge.example",
            settings=NLWebSettings(
                _env_file=None,
                retrieval_store="custom",
                enabled=True,
                content_sync_enabled=False,
                content_sync_on_startup=False,
            ),
        )
        response = await widget.ask(
            NLWebRequest.model_validate({"query": {"text": "Qdrant Edge example provider test"}})
        )
        assert response.error is None
        assert response.results and response.results[0].url == document.url
    finally:
        await store.delete([document.id])
        await store.close()


@pytest.mark.asyncio
async def test_sqlite_provider_when_explicitly_configured(tmp_path):
    _load_provider_env("sqlite")
    configured_path = os.getenv("NLWEB_SQLITE_PATH")
    if not configured_path:
        pytest.skip("NLWEB_SQLITE_PATH is not configured")
    pytest.importorskip("sqlite_vec")
    from nlweb_widget.content import SQLiteVecRetrievalStore

    dimensions = int(os.getenv("NLWEB_SQLITE_DIMENSIONS", "384"))
    path = str(tmp_path / "nlweb-sqlite-qa.db")
    store = SQLiteVecRetrievalStore(path, _configured_embedder(dimensions), dimensions=dimensions)
    document = ContentDocument(
        id="examples-sqlite-test",
        url="https://example.test/sqlite-test",
        title="SQLite provider test",
        content="SQLite vector and keyword retrieval provider test",
    )
    try:
        await store.initialize()
        assert await store.upsert(document) == 1
        matches = await store.search("SQLite keyword retrieval", limit=1)
        assert matches and matches[0][0].id == document.id
        health = await store.health()
        assert health["status"] == "ok"
        assert str(health["vec_version"]).lstrip("v") == "0.1.8"
    finally:
        await store.delete([document.id])
        await store.close()
