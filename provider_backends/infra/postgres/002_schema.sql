-- Mirrors PgVectorStore.initialize() in nlweb_widget/content/store.py.
-- The Widget implementation is authoritative; this script is the deployable default-dimension bootstrap.
CREATE TABLE IF NOT EXISTS nlweb_documents (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    schema_object JSONB NOT NULL DEFAULT '{}'::jsonb,
    site TEXT NOT NULL DEFAULT 'default',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(384) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
