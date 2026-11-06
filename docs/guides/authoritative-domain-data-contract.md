# Authoritative domain data, artifact identity, and evidence manifest

This guide describes an **optional Examples ingestion convention**. It does not replace the NLWeb protocol contract. The Widget's response serialization must follow the applicable [official NLWeb Specification](https://nlweb.ai/docs/specification) even when a consumer supplies custom metadata. The manifest is a proposed example-level ingestion convention, not a mandatory Widget API requirement.

## Artifact URLs are not chunk IDs

A source artifact has one canonical artifact URL when a suitable URL is available. Every chunk produced from that artifact keeps the same URL. The unique chunk identifier remains in `ContentDocument.id` and chunk metadata; do not manufacture `#chunk-N` URL fragments. A genuine source fragment may be retained when it identifies a real section.

For structured sources, a suitable `url` takes precedence over `@id`. The source `@id` may still be retained as a schema identity. A converter-provided URL is preserved. The registry URL fallback is treated as a base mapping for an artifact and receives the artifact filename when it does not already identify a file. No public evidence URI is inferred from a filename alone.

## Optional inbox manifest

Consumers who want explicit artifact-level type and grounding declarations may place a file named `nlweb-evidence-manifest.json` in the source directory. The ingestion helper excludes this control file from ordinary content ingestion.

The version-1 shape is:

```json
{
  "version": "1",
  "artifacts": [
    {
      "artifact": "annual-review.pdf",
      "type": "Article",
      "grounding": {
        "source": "https://your-domain.example/annual-review.pdf",
        "description": "Public verification reference",
        "citations": [
          {
            "label": "Product specifications",
            "source_url": "https://example.org/products/specifications",
            "page": 4
          },
          {
            "label": "Pricing and availability",
            "source_url": "https://example.org/products/pricing"
          }
        ],
        "schema_refs": [
          "https://example.org/schemas/product-catalog-v1.json",
          "https://example.org/schemas/product-v1.json"
        ]
      }
    }
  ]
}
```

`artifact` is a safe, relative POSIX-style path from the configured source directory. Absolute paths and `..` traversal are rejected. Duplicate keys, malformed entries, and entries that do not match discovered source artifacts are errors rather than silently ignored metadata.

`type` is a consumer-declared fallback for the result type. A suitable authoritative `@type` in structured source data takes precedence. The manifest type is used only when the source does not supply a suitable type. This convention does not authorize overriding a source's type to fit a preferred response.

`grounding` is an arbitrary JSON object supplied by the consumer. The ingestion layer persists the complete object in document metadata without normalizing or rewriting its contents. If the source and manifest both supply grounding and the objects conflict, that artifact is skipped and the incident is reported so the consumer can resolve the disagreement; other healthy artifacts continue. A partial sync with skipped artifacts does not delete previously indexed source records. The Widget then serializes grounding in the official protocol response location and shape.

An absent manifest is supported. When a manifest is present, its inventory is checked against discovered files: missing, unsupported, undeclared, malformed, or conflicting artifacts are reported and skipped individually rather than aborting the whole source. An artifact without a matching manifest entry has no manifest-declared evidence URI; other source-provided grounding may still be available. A URI in the manifest is a consumer declaration, not a reachability or authenticity guarantee. Replace all placeholder URLs in the template before use, and do not expose private storage locations or internal filesystem paths to public consumers.

## Existing source templates

- `starter_profiles/` contains reusable Schema.org/JSON-LD domain data.
- Framework-specific `data.json` files demonstrate structured source records in ordinary JSON.
- `examples/provider_backends/common/templates/nlweb-evidence-manifest.example.json` is a copyable manifest template. It is intentionally not installed as an active manifest in every inbox.

The convention is optional; consumers can continue to use source-provided URLs and grounding without adopting a manifest.


### Grounding object conventions

The Examples fixture demonstrates a consumer-supplied `grounding` JSON object with a `source`, human-readable `description`, optional `citations`, and optional `schema_refs`. In the sample convention, each citation has a `label` and `source_url`, and may include a `page`; `schema_refs` is a list of schema/reference URIs. These are example-level field conventions and are retained as metadata without rewriting. Consumers may add domain-specific fields, but should validate them against the official NLWeb specification and their own data governance rules. Do not interpret these example fields as a guarantee that the referenced URLs are reachable or that the cited claims have been independently verified.

The current Widget preserves grounding as an opaque object and serializes it into the result item. The exact protocol-level shape must remain aligned with the pinned official specification; if the official specification narrows the allowed grounding structure, that requirement takes precedence over this example manifest.

### Local, mounted-volume, and object-storage sources

`nlweb-sources.json` accepts a local file or directory path, including a path to a mounted volume. The provider-backed ingestion helper also supports remote object-store prefixes through optional `fsspec` adapters (for example, `s3://bucket/prefix/`, `gs://bucket/prefix/`, or `az://container/prefix/`). Install `uv sync --extra remote-storage` and the relevant provider filesystem dependency/credentials for the storage backend you choose. The source loader materializes remote objects into a temporary directory and applies the same supported-file discovery and manifest validation rules. Do not commit credentials in the registry; configure them using the storage provider's normal credential chain. HTTP URLs are only useful when the configured filesystem supports listing/finding the source prefix; a single URL that cannot enumerate a directory is not a directory source.

The registry's `location` is intentionally a deployment-specific choice, not a universal pipeline requirement. Consumers may replace local paths, the storage adapter, conversion pipeline, chunking policy, and retrieval store according to their data architecture and resource constraints. The Widget's public request/response API and official protocol requirements are not optional.


### Optional local-first extraction path

The Examples package includes an optional Scrapy + Ollama path beside ScrapeGraphAI. It preserves source JSON-LD deterministically and uses a local model only for text claims, with evidence quotations and an unverified-extraction label. It is an example convention and does not alter the Widget API or its authoritative data contract. On low-memory hardware, use one page at a time and a small model; quality and completeness are not guaranteed. See the domain-site extractor README.

### fsspec provider options

For the S3-compatible example, `location` is the sole bucket/prefix address (for example, `s3://${NLWEB_REMOTE_STORAGE_BUCKET}/` for bucket-root ingestion); do not duplicate it as `metadata.remote_location`. The adapter recovers the raw registry URI internally if the immutable Widget 0.9.12 parser normalizes it. Remote ingestion is read-only: it enumerates and reads source objects and does not upload them. The external-hosted example may generate `metadata.excluded_filenames` in its runtime-only registry to omit the untouched placeholder `domain.jsonld` from a local inbox when a real site is configured; this is not a required template field and does not apply to remote storage.

Remote source entries can declare `remote_storage_options` as an object. The shared custom loader passes the resolved options to `fsspec.core.url_to_fs(location, **kwargs)`. Exact `${ENV_VAR}` values are resolved from the process environment. There is no second JSON fallback object; the source registry is authoritative for provider options. Keep secrets outside version control and avoid logging the resolved options. Cloud-specific option names depend on the installed fsspec backend.

### Source identity and freshness

The source registry `name` is the stable identity of a source. The Examples loader namespaces retrieval document IDs by that name, so complementary local, remote, and CouchDB sources can coexist even when artifact names match. On a successful sync, current records from that source are upserted and previously indexed IDs tracked for that same source but absent from the current result are deleted. Other sources are not deleted or overridden. Do not reuse a registry name for a different logical source; treat renames as migrations. A failed ingestion does not run stale-record cleanup.


### Source-scoped refresh behavior in the Examples package

In the Examples integration, each registry `name` is the stable source identity and document IDs are namespaced by that name. A successful sync upserts the current records and removes only stale IDs previously recorded for that source. Other source namespaces remain untouched. This is not a cross-source precedence rule or a global merge policy. The deletion step runs only after the source loader returns successfully; a failed loader must not trigger stale cleanup. The Widget 0.9.12 runtime itself remains unchanged.


### All three source modes in each example registry

Each example registry exposes local disk, S3-compatible remote storage, and CouchDB document-store source entries. Local/scenario sources are enabled for the runnable baseline; remote and CouchDB entries are disabled by default and can be enabled after configuration. They are complementary sources, not a precedence chain. Each `name` is a distinct identity and receives its own retrieval-ID namespace. Successful sync replaces that source's current projection and removes stale IDs from that source only.
