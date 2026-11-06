# Starter profiles

Starter profiles are reusable Schema.org/JSON-LD scenario seeds for the reference examples. They are not part of the `nlweb-widget` runtime package.

The framework scenarios deliberately combine profile concepts into concrete `examples/<scenario>/data.json` files:

| Scenario | Profile seeds |
|---|---|
| `fastapi_retail` | `ai-digital-transformation-agency`, `ecommerce` |
| `flask_marketing` | `ai-reach-marketing-agency`, `publisher` |
| `django_services` | `professional-services`, `generic-business` |
| `starlette_catalog` | `saas`, `documentation` |
| `stdlib_directory` | `local-business`, `organization` |

The scenario `data.json` files are the runnable example projections. Profiles are reusable source material for developers creating their own examples.
