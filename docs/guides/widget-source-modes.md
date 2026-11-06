# Published vs local widget

The examples support two development modes.

## Published dependency

Use the normal project dependency when testing the examples against a released widget package.

## Local editable checkout

For simultaneous development of both repositories:

```text
workspace/
├── nlweb_widget/
└── nlweb-widget-examples/
```

Install the sibling checkout:

```powershell
uv pip install -e ../nlweb_widget
```

This lets example code exercise local widget changes without changing the examples repository's declared package identity.
