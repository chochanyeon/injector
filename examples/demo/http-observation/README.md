# HTTP observation demo

**English** · [한국어](README.ko.md) · [Injector](../../../README.md)

The same order returns HTTP 201 in both runs. The second run sends a different warehouse to Catalog. Activate the Injector Python environment, then run from the repository root on Windows PowerShell.

```powershell
$env:INJECTOR_DEMO_WAREHOUSE = "seoul"
python injector.py observe-http orders --project examples/demo/http-observation --profile local --scenario examples/demo/http-observation/scenario.json --output .local/observations/baseline.json
$env:INJECTOR_DEMO_WAREHOUSE = "busan"
python injector.py observe-http orders --project examples/demo/http-observation --profile local --scenario examples/demo/http-observation/scenario.json --output .local/observations/current.json
python injector.py compare-http .local/observations/baseline.json --candidate .local/observations/current.json
```

On macOS, set the shell variable with `export INJECTOR_DEMO_WAREHOUSE=seoul` before the first run and `export INJECTOR_DEMO_WAREHOUSE=busan` before the second. The Python commands are the same.

The expected verdict is `FAIL`, with a change at `/calls/0/requestFields/~1warehouse`. Compare the same file with itself for `PASS`. A missing or incomplete recording, or a different scenario, profile, selected variant, or edge, yields `INCONCLUSIVE`. The comparison exit codes are 0, 1, and 2, respectively.

Load `examples/demo/http-observation` in Injector's web UI. Open **HTTP 관측 비교** under **의존성 그래프** and choose the two files to view the results side by side. The graph highlights the matching `orders → catalog` edge.

The recorder uses one process target, one declared host URL injection, literal loopback HTTP addresses, and one synchronous JSON scenario. Use a quiet test environment because the recorder attributes calls to the active time window. It captures the method, path, status, and explicitly selected scalar JSON fields. It limits each exchange body to 1 MiB and each observation to 16 calls and 2 MiB. Stop any active Injector session for the same worktree and registry before recording. The recording stops its own session on completion. Choose a new output filename when repeating the steps. To compare actual worktrees, run the same scenario and profile in each checkout with equivalent starting data. [Scenario and observation schema](../../../schemas/http-observation-v1.schema.json)

Set `"requestQuery": ["warehouse"]` in the scenario to capture the `warehouse` query parameter on the dependency call. Repeated values stay in request order and blank values are retained. A call with a query and no query policy makes the observation incomplete. Set `"requestQuery": []` to intentionally ignore query parameters. Record both sides again after changing the scenario.
