# Example runtime registry

**English** · [한국어](README.ko.md)

`registry.json` illustrates schema 1.0 from T-010 in a fictional monorepo. Orders and Catalog share a database, and Catalog can be real or mocked. Orders requires the database directly, so `local-mock` still includes it.

`apps/orders`, `compose.yaml`, and `/health` illustrate the model. Use [the demo](../demo/) for runnable apps. See the [schema](../../schemas/registry-v1.schema.json) and [T-010](../../docs/work-items/T-010.md) for the structural contract. T-020 validates references and selections. T-040 validates cycles and calculates DFS order.

From the repository root, run `python injector.py validate --project examples/registry` and `python injector.py plan --project examples/registry --profile local-real`. These checks leave executable files, DNS, and service startup to runtime.
