-- Mirrors PgVectorStore.initialize() in nlweb_widget/content/store.py.
CREATE INDEX IF NOT EXISTS nlweb_documents_embedding_hnsw
    ON nlweb_documents USING hnsw (embedding vector_cosine_ops);
