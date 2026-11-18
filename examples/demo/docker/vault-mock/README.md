# Local Vault API mock

**English** · [한국어](README.ko.md)

This directory contains WireMock mappings and local fixtures. The mock runs independently of company Vault.

## Run the mock

From the repository root:

```powershell
python injector.py up --profile mock --vault-service orders
python injector.py vault-demo --vault-service orders
python injector.py vault-demo --vault-service payments
```

Use `http://localhost:18083` from the host and `http://vault-mock:8080` in Docker. Services share the origin and select a response by secret path. `--vault-service` enables the mock and selects `VAULT_PATH`. `--with-vault` and `vault-demo` without a service use the default `orders`.

Generated IntelliJ and Docker settings include `VAULT_ADDR`, `VAULT_PATH`, and `VAULT_TOKEN`. The separate Python `vault-demo` consumer exercises KV v2 reads and uses the returned configuration.

## Request contract

```http
GET /v1/secret/data/orders
X-Vault-Token: local-demo-token
```

Valid responses include `data.data` and `data.metadata`. A missing or incorrect token returns JSON 403. An authenticated request for an unsupported `/v1/` path, method, or query returns JSON 404. The shared fixed token is a fixture rule. Login, lookup and renewal, leases, KV v1, writes, versioned reads, namespaces, and TLS are out of scope. Company SDK compatibility remains unverified. [Vault KV v2 read](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2)

Payments uses `GET /v1/secret/data/payments` with the same origin and token. The two responses share keys and give different values for message, database username, and database password. The path identifies the response.

## Edit service values

1. Set the service's local keys in `data.data`. [Orders data](__files/orders.json) · [Payments data](__files/payments.json)
2. Use `/v1/<mount>/data/<service-id>` as `request.url` and use its fixture name as `bodyFileName`. The CLI forms `VAULT_PATH` from `vaultMock.mount` and the service ID. [Orders mapping](mappings/read-orders.json) · [Payments mapping](mappings/read-payments.json)
3. Run `docker compose -p injector-poc -f examples/demo/docker/compose.yaml restart vault-mock` and repeat the request.

Add a mapping and fixture for each service. IDs start with a lowercase letter and may contain lowercase letters, digits, and hyphens. Unknown services return 404. The old `injector-demo` path has been removed.

The consumer reads `message`, `feature_enabled`, `database_username`, and `database_password`. Set `feature_enabled` to false to see `feature disabled`. Credentials are omitted from the consumer output. The checked-in token and password are fixed demo fixtures. When adapting a project, use the variable names that its app actually reads.

## Test and stop

```powershell
$env:INJECTOR_TEST_VAULT_URL = 'http://127.0.0.1:18083'
python -m unittest discover -s tests -p test_vault_mock_integration.py -v
```

Five integration tests are skipped without the URL. `python injector.py down` stops the demo Compose project. Use Compose `stop vault-mock` to stop only the mock. Omitting `--with-vault` on a later `up` leaves running mocks alone.
