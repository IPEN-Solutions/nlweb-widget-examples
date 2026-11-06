# Generic remote storage options

The domain-site extractor can read supported object-storage prefixes through the optional `remote-storage` extra (`fsspec` plus `s3fs` for S3-compatible URLs). `remote_storage_options` is deliberately provider-neutral: it passes filesystem-specific keyword options to `fsspec.core.url_to_fs(url, **kwargs)`, so S3-compatible services are not tied to a particular vendor.

Example registry options:

```json
{
  "remote_storage_options": {
    "key": "${NLWEB_REMOTE_STORAGE_ACCESS_KEY}",
    "secret": "${NLWEB_REMOTE_STORAGE_SECRET_KEY}",
    "prefix": "",
    "client_kwargs": {
      "region_name": "${NLWEB_REMOTE_STORAGE_REGION}",
      "endpoint_url": "${NLWEB_REMOTE_STORAGE_ENDPOINT_URL}"
    }
  }
}
```

The bucket is named once, in the source URI: `s3://${NLWEB_REMOTE_STORAGE_BUCKET}/`. This example reads all supported artifacts at the bucket root because `prefix` is an empty string; there is no `/your-domain/inbox/` prefix. Set `remote_storage_options.prefix` to a bucket subdirectory such as `domain-a/inbox` when you intentionally partition a bucket. This setting is per registry entry, so multiple source entries can read separate prefixes. If you intentionally organize objects under a prefix, set the `prefix` option on that source entry (for example, `"prefix": "inbox"`) while keeping `location` at the bucket root. The loader enumerates and reads objects for ingestion; it does not upload objects or call `put`.

For S3-compatible services such as Backblaze B2, configure `NLWEB_REMOTE_STORAGE_BUCKET` and `NLWEB_REMOTE_STORAGE_ENDPOINT_URL` in the example `.env`. Endpoint values may be supplied as a bare host name or as a full URL; bare host names are normalized to `https://`. Every `.env.example` includes blank `NLWEB_REMOTE_STORAGE_ACCESS_KEY`, `NLWEB_REMOTE_STORAGE_SECRET_KEY`, and `NLWEB_REMOTE_STORAGE_REGION` assignments because the registry references those placeholders. Keep them blank while the remote source is disabled; populate them in the private `.env` when enabling the source. Never commit real credentials. The registry `location` is the only source of truth for bucket and prefix. Do not duplicate it in metadata. The adapter privately recovers the raw registry URI if Widget 0.9.12 normalizes a non-HTTP location before invoking the custom loader; the immutable runtime and its baseline are unchanged.

The per-source `remote_storage_options` are passed to `fsspec.core.url_to_fs(location, **kwargs)`. For the S3-compatible example, `key` and `secret` are top-level options; `region_name` and `endpoint_url` are nested under `client_kwargs` as required by the S3 filesystem adapter. The example-only `prefix` option is consumed by the adapter and is not forwarded to fsspec as a client option. Other fsspec backends may use different option names. `${ENV_VAR}` placeholders are resolved at runtime; empty optional values are omitted so provider-native credential chains may be used. Keep secrets out of version control and never log resolved options. There is no secondary `NLWEB_REMOTE_STORAGE_OPTIONS_JSON` configuration path.

Never commit secrets. Keep credentials in local `.env` files excluded from version control or in a deployment secret manager. Do not log resolved options. Local paths and mounted volumes remain the default and do not require fsspec.


### All three source modes in each example registry

Each example registry exposes local disk, S3-compatible remote storage, and CouchDB document-store source entries. Local/scenario sources are enabled for the runnable baseline; remote and CouchDB entries are disabled by default and can be enabled after configuration. They are complementary sources, not a precedence chain. Each `name` is a distinct identity and receives its own retrieval-ID namespace. Successful sync replaces that source's current projection and removes stale IDs from that source only.


Install the S3 filesystem backend as well as fsspec with `uv sync --extra remote-storage`; installing fsspec alone is not sufficient for `s3://` URLs.
