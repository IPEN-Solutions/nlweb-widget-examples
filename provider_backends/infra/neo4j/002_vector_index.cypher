// Mirrors Neo4jKnowledgeGraphStore.initialize() in nlweb_widget/content/neo4j.py.
// Supply $vector_dimensions from the provider-owned .env value
// NLWEB_NEO4J_VECTOR_DIMENSIONS when executing this fixture.
CREATE VECTOR INDEX nlweb_document_embedding IF NOT EXISTS
FOR (d:NLWebDocument) ON d.embedding OPTIONS { indexConfig: {
  `vector.dimensions`: $vector_dimensions,
  `vector.similarity_function`: 'cosine'
} };
