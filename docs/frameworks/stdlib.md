# Python stdlib HTTP

Path: `examples/stdlib_directory/`

The standard-library example is the lowest-level reference in the suite. It uses `http.server` directly.

## Why study it

This example makes the framework boundary visible. It helps answer:

> What does the widget actually require from an application framework?

## Consumer takeaway

If your framework is not represented by a dedicated adapter, use this example to understand the protocol boundary and then map that boundary to your framework's HTTP facilities.

The scenario data is in `examples/stdlib_directory/data.json` and demonstrates a small directory of professional/local business offerings.
