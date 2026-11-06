# Troubleshooting

## VS Code says pytest is unavailable

The examples project declares pytest in its base dependency set so the selected project `.venv` can be used directly by VS Code's Python Test Explorer. If the environment predates this revision, synchronize it once:

```powershell
uv sync
```

Then in VS Code select the repository `.venv` as the Python interpreter and run **Python: Discover Tests**. The repository settings already point pytest discovery at the `tests` directory.

For a full command-line verification, use:

```powershell
uv run pytest
```

## Local widget checkout is not used

Verify the repositories are siblings and install:

```powershell
uv pip install -e ../nlweb_widget
```

Remember that the local checkout name is `nlweb_widget`, while the distribution name is `nlweb-widget`.

## AskAgent test is skipped

That is expected when `ASKAGENT_URL` is not configured. The default suite is intentionally offline.

## Provider example NumPy/DLL import failure

If a provider example reports `DLL load failed while importing _multiarray_umath` or another NumPy native-extension error while importing Sentence Transformers/Neo4j, rebuild the example environment from the declared dependency constraints:

```powershell
uv sync
```

The provider example project constrains NumPy to `>=2.2,<2.3` to avoid resolving a newer native-extension line in the supported Windows Python environment. The provider environment contract itself is unchanged.

### Neo4j configured-provider test isolation

The Neo4j configured-provider test intentionally uses the configured example database but a separate `NLWebTestDocument.embedding` schema and `test_nlweb_document_embedding_r1` vector index. Neo4j permits only one vector index over a given schema, so the label is the isolation boundary: production uses `NLWebDocument.embedding`, while tests use `NLWebTestDocument.embedding`. Test nodes never receive the production label, so their 4-dimensional vectors cannot enter the production index. No `NLWEB_NEO4J_TEST_DATABASE` setting is required.
