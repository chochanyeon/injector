# 쇼핑몰 모노레포 데모

[English](README.md) · **한국어** · [Injector](../../../README.ko.md)

JVM 서비스 여섯 개와 공통 Java 라이브러리로 구성한 Gradle 모노레포다. Injector가 서비스는 로컬 Java 프로세스로 실행하고 PostgreSQL·Redis·Kafka·WireMock은 Docker Compose로 준비한다.

```mermaid
flowchart LR
    Storefront --> Orders & Catalog & Notifications & Redis
    Orders --> Catalog & Inventory & PostgreSQL & Kafka
    Catalog --> Pricing & Redis
    Inventory --> PostgreSQL
    Pricing -->|real| PricingDB["가격 전용 PostgreSQL"]
    Notifications --> Kafka & Redis
```

| 서비스 | 실제 실행 동작 |
| --- | --- |
| Storefront | 주문·가격·배송 요청을 전달하고 checkout 횟수를 Redis에 기록한다. |
| Orders | Catalog와 Inventory에서 가격·재고를 조회한다. 주문 저장과 재고 차감은 같은 PostgreSQL 트랜잭션에서 처리하고 Kafka 이벤트를 발행한다. |
| Catalog | 가격을 Redis에 캐시하며 캐시가 비면 Pricing을 호출한다. |
| Pricing | `real`은 전용 PostgreSQL을 조회한다. `mock`은 WireMock에서 가격을 받고, 가격 전용 DB가 실행 순서에서 빠진다. |
| Inventory | Orders와 같은 PostgreSQL에서 재고를 조회한다. |
| Notifications | Kafka 주문 이벤트를 읽고 배송 상태를 Redis에 기록한다. |

## 실행

Docker Desktop, Injector Python 환경, JDK 17 이상이 필요하다. `JAVA_HOME`을 설정하고 해당 JDK의 `bin`을 `PATH`에 추가한다. Injector 저장소 루트에서 빌드한다.

```bash
bash verifier/gradlew -p examples/demo/monorepo installDist
```

Windows PowerShell에서는 `.\verifier\gradlew.bat -p examples/demo/monorepo installDist`를 사용한다. 첫 빌드는 필요한 Gradle과 Java 의존성을 다운로드한다.

```text
python injector.py plan storefront --project examples/demo/monorepo --profile real
python injector.py prepare storefront --project examples/demo/monorepo --profile real
```

웹에서 `examples/demo/monorepo`를 프로젝트로 열면 앱·프로필별 그래프를 볼 수 있다. real은 10개 노드를 준비한다. `--profile mock`으로 다시 준비하면 9개로 바뀐다. 새 세션에서 DB·캐시·브로커는 초기 샘플 데이터로 돌아간다.

```bash
curl http://127.0.0.1:19780/items/sample
curl http://127.0.0.1:19780/items/sample
curl -X POST http://127.0.0.1:19780/checkout -H 'Content-Type: application/json' --data '{"id":"demo-order","sku":"sample","quantity":2}'
curl http://127.0.0.1:19781/orders/demo-order
curl http://127.0.0.1:19784/stock/sample
curl http://127.0.0.1:19780/deliveries/demo-order
```

가격 조회는 첫 요청에서 `miss`, 두 번째 요청에서 `hit`다. 주문 합계는 real에서 2598센트, mock에서 1998센트이며 재고는 10개에서 8개로 줄어든다. 같은 주문 ID와 상품·수량으로 재요청하면 저장된 주문을 반환하고 재고는 8개다. Kafka 처리가 끝날 때까지 배송 조회는 404를 반환한다. PowerShell에서 POST를 보내려면 `Invoke-RestMethod -Method Post -ContentType 'application/json' -Body '{"id":"demo-order","sku":"sample","quantity":2}' -Uri 'http://127.0.0.1:19780/checkout'`를 사용한다.

`python injector.py stop --project examples/demo/monorepo`로 종료한다.

## 가격 조회 관측

실행 중인 쇼핑몰 세션을 종료한다. 아래 명령은 새 환경을 준비하고 `storefront → catalog` HTTP 호출을 기록한다.

```text
python injector.py observe-http storefront --project examples/demo/monorepo --profile real --scenario examples/demo/monorepo/scenarios/quote.json --output .local/shop-quote.json
```

코드 버전을 비교할 때는 같은 시나리오와 프로필로 각각 기록하고 `compare-http`로 비교한다. 실제 통합 테스트는 빌드 뒤 `INJECTOR_TEST_SHOP=1`을 설정하고 `python -m unittest discover -s tests -p test_shop_demo.py`로 실행한다.
