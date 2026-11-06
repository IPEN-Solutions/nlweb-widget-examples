// Verify the minimum graph objects created by 001_schema.cypher and
// 002_vector_index.cypher. Run against the example database.

SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties
WHERE name IN ['nlweb_document_id', 'nlweb_entity_key']
RETURN name, type, labelsOrTypes, properties
ORDER BY name;

SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties
WHERE name = 'nlweb_document_site'
RETURN name, type, entityType, labelsOrTypes, properties;

SHOW VECTOR INDEXES YIELD name, state, entityType, labelsOrTypes, properties, indexConfig
WHERE name = 'nlweb_document_embedding'
RETURN name, state, entityType, labelsOrTypes, properties, indexConfig;

// Exercise the minimum document/entity graph shape and verify the relationship.
CREATE (d:NLWebDocument {
  id: 'nlweb-smoke-test',
  url: 'https://example.com/nlweb-smoke-test',
  title: 'NLWeb smoke test',
  content: 'Temporary document used to verify the NLWeb Neo4j schema.'
});

CREATE (e:NLWebEntity {
  key: 'example:smoke-test',
  entityType: 'TestEntity',
  name: 'NLWeb smoke test entity'
});

MATCH (d:NLWebDocument {id: 'nlweb-smoke-test'}),
      (e:NLWebEntity {key: 'example:smoke-test'})
MERGE (d)-[:MENTIONS]->(e);

MATCH (d:NLWebDocument {id: 'nlweb-smoke-test'})-[:MENTIONS]->
      (e:NLWebEntity {key: 'example:smoke-test'})
RETURN count(*) AS smoke_relationships;

MATCH (d:NLWebDocument {id: 'nlweb-smoke-test'})
DETACH DELETE d;
MATCH (e:NLWebEntity {key: 'example:smoke-test'})
DETACH DELETE e;
