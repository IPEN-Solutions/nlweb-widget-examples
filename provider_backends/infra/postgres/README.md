# PostgreSQL + pgvector initialization

The SQL here is the human-readable provider bootstrap shipped by the package. The same resources are included in the wheel and can be emitted/applied with:

```powershell
uv run fastapi-nlweb postgres init
uv run fastapi-nlweb postgres sql --output .\infra\postgres\generated.sql
```

The target database must have pgvector installed. The first statement enables it with `CREATE EXTENSION IF NOT EXISTS vector`.
