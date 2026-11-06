// Mirrors Neo4jKnowledgeGraphStore.initialize() in nlweb_widget/content/neo4j.py.
CREATE CONSTRAINT nlweb_document_id IF NOT EXISTS
FOR (d:NLWebDocument) REQUIRE d.id IS UNIQUE;

CREATE CONSTRAINT nlweb_entity_key IF NOT EXISTS
FOR (e:NLWebEntity) REQUIRE e.key IS UNIQUE;

CREATE INDEX nlweb_document_site IF NOT EXISTS
FOR (d:NLWebDocument) ON (d.site);
