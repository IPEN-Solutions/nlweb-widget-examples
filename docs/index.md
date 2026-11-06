# NLWeb Widget Examples

The **NLWeb Widget Examples** repository is the runnable reference and learning suite for `nlweb-widget`.

It answers a different question from the production package documentation:

> **How does an existing application become reachable through the NLWeb protocol, and what does that look like in my framework?**

The examples deliberately keep three concerns separate:

1. **Your application and domain data** remain authoritative.
2. **`nlweb-widget`** provides the protocol/integration boundary.
3. **An external consumer such as AskAgent** can optionally exercise that boundary.

Start with [the overview](getting-started/overview.md), then choose the framework closest to your application.

For optional hosted-domain acquisition examples, see [external hosted-domain sources](guides/external-hosted-sources.md).

## Authoritative data contract

See the [authoritative domain data and evidence manifest guide](guides/authoritative-domain-data-contract.md) for canonical artifact URLs, optional grounding metadata, and source-type precedence.

The [official NLWeb Specification](https://nlweb.ai/docs/specification) is authoritative for protocol behavior. The example manifest and ingestion pipeline are replaceable consumer conventions, not additional mandatory protocol requirements.
