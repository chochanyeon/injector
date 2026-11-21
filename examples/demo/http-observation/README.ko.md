# HTTP 관측 데모

[English](README.md) · **한국어** · [Injector](../../../README.ko.md)

같은 주문을 두 번 실행하면 둘 다 HTTP 201을 반환한다. 두 번째 실행에서 Catalog로 보내는 창고 값만 달라진다. Injector의 Python 가상환경을 활성화하고 저장소 루트에서 실행한다. 아래는 Windows PowerShell 예시다.

```powershell
$env:INJECTOR_DEMO_WAREHOUSE = "seoul"
python injector.py observe-http orders --project examples/demo/http-observation --profile local --scenario examples/demo/http-observation/scenario.json --output .local/observations/baseline.json
$env:INJECTOR_DEMO_WAREHOUSE = "busan"
python injector.py observe-http orders --project examples/demo/http-observation --profile local --scenario examples/demo/http-observation/scenario.json --output .local/observations/current.json
python injector.py compare-http .local/observations/baseline.json --candidate .local/observations/current.json
```

macOS에서는 첫 번째 실행 전 `export INJECTOR_DEMO_WAREHOUSE=seoul`, 두 번째 실행 전 `export INJECTOR_DEMO_WAREHOUSE=busan`으로 지정한다. Python 명령은 같다.

예상 결과는 `FAIL`이며 차이 경로는 `/calls/0/requestFields/~1warehouse`다. 같은 파일끼리 비교하면 `PASS`다. 관측이 빠졌거나 불완전하거나 시나리오·프로필·variant·연결이 다르면 `INCONCLUSIVE`다. 비교 종료 코드는 각각 `PASS` 0, `FAIL` 1, `INCONCLUSIVE` 2다.

웹에서 `examples/demo/http-observation`을 프로젝트로 불러온다. **의존성 그래프 → HTTP 관측 비교**에서 두 파일을 고르면 기준선과 현재 결과가 나란히 표시되고, 그래프의 `orders → catalog` 연결이 강조된다.

프로세스로 실행되는 앱 하나, 호스트 URL로 주입하는 연결 하나, 루프백 HTTP 주소, 동기 JSON 시나리오를 지원한다. 기록 중 해당 연결을 지나는 호출을 수집하므로 다른 트래픽이 없는 테스트 환경에서 사용한다. 메서드, 경로, 상태, 명시한 스칼라 JSON 필드를 기록한다. 요청과 응답 본문은 각각 1 MiB, 관측은 호출 16개와 결과 파일 2 MiB까지다. 같은 워크트리와 Registry에 활성 세션이 있으면 먼저 종료한다. 기록용 세션은 요청이 끝나면 자동으로 종료한다. 다시 기록할 때는 새 출력 경로를 사용한다. 실제 워크트리를 비교할 때는 같은 시나리오와 프로필, 동등한 초기 데이터를 사용한다. [시나리오·관측 스키마](../../../schemas/http-observation-v1.schema.json)
