# 로컬 Vault API 대역

이 디렉터리는 WireMock의 매핑과 로컬 설정값이다. 실제 Vault 이미지를 실행하거나 회사 Vault에 접속하지 않는다.

## 실행과 확인

저장소 루트에서 실행한다.

```powershell
python injector.py up --profile mock --vault-service orders
python injector.py vault-demo --vault-service orders
python injector.py vault-demo --vault-service payments
```

Vault 대역은 `http://localhost:18083`, Docker 네트워크에서는 `http://vault-mock:8080`이다. 모든 서비스가 같은 주소를 사용하고 secret 경로로 응답을 구분한다. --vault-service는 대역을 활성화하고 VAULT_PATH를 선택한다. --with-vault만 쓰거나 vault-demo에서 서비스를 생략하면 원본 설정의 defaultService인 orders를 사용한다.

생성된 IntelliJ 실행 구성과 Docker 환경에 `VAULT_ADDR`, `VAULT_PATH`, `VAULT_TOKEN`을 넣는다. 기존 Java Main은 이 값을 소비하지 않는다. `vault-demo`는 별도 Python 설정 소비 앱을 실행해 KV v2 조회와 값 사용을 확인한다.

## 현재 재현하는 요청

```http
GET /v1/secret/data/orders
X-Vault-Token: local-demo-token
```

정상 응답은 [KV v2 read 형식](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2)의 `data.data`와 `data.metadata`를 사용한다. 토큰이 없거나 다르면 JSON 403, 올바른 토큰으로 미등록 `/v1/` 경로·메서드·query를 요청하면 JSON 404를 반환한다.

고정 토큰 검사는 매핑 선택 조건일 뿐 실제 인증·정책 엔진이 아니다. login, token lookup/renew, lease, KV v1, 쓰기·버전 조회, Vault namespace, TLS 등은 재현하지 않는다. 회사 앱이 요구하는 요청은 소스와 실제 로컬 요청 기록을 근거로 추가해야 한다. 회사 앱·Vault SDK 호환성을 검증한 상태는 아니다.

Payments는 같은 토큰과 주소에 `GET /v1/secret/data/payments`를 사용한다. 두 응답은 같은 키를 갖지만 서로 다른 message·database_username·database_password를 반환한다. 토큰은 공유하므로 경로 구분은 응답 식별 규칙이며 서비스별 접근 권한 제어는 아니다.

## 앱이 읽어갈 값 변경

1. [__files/orders.json](__files/orders.json) 또는 [__files/payments.json](__files/payments.json)의 `data.data`에 해당 서비스가 읽을 키·로컬 값을 넣는다. 서비스 간 설정값을 합치지 않는다.
2. 매핑의 `request.url`은 `/v1/<mount>/data/<서비스 ID>`, `bodyFileName`은 해당 서비스 JSON 파일이다. [Orders 매핑](mappings/read-orders.json)과 [Payments 매핑](mappings/read-payments.json)을 참고한다. CLI는 데모 원본 설정의 vaultMock.mount와 선택한 서비스 이름으로 VAULT_PATH를 만든다.
3. 변경 후 `docker compose -p injector-poc -f examples/demo/docker/compose.yaml restart vault-mock`를 실행하고 다시 조회한다.

앱을 추가하려면 서비스 ID마다 매핑·응답 파일을 추가하고 재기동한 뒤 `--vault-service <ID>`로 선택한다. 서비스 ID는 소문자로 시작하며 소문자·숫자·하이픈만 사용한다. 경로·대문자·빈 이름은 거부한다. 예시는 orders와 payments를 제공하며 미등록 ID는 404다. 기존 단일 injector-demo 경로는 제거했다.

현재 소비 앱은 `message`, `feature_enabled`, `database_username`, `database_password`를 사용한다. `feature_enabled`를 false로 바꾸면 메시지가 `feature disabled`로 바뀐다. 자격증명 값 자체는 소비 앱 출력에 포함하지 않는다. fixtures의 토큰·비밀번호는 데모용 고정값이며 실제 자격증명을 저장소에 넣지 않는다.

실제 앱 적용에서는 환경변수 이름도 해당 앱의 설정 바인딩에 맞춰야 한다. 예를 들어 VAULT_ADDR라는 이름만 넣는다고 모든 프레임워크가 그 값을 자동 인식하는 것은 아니다.

## 테스트와 종료

```powershell
$env:INJECTOR_TEST_VAULT_URL = 'http://127.0.0.1:18083'
python -m unittest discover -s tests -p test_vault_mock_integration.py -v
```

이 URL을 지정하지 않으면 WireMock 통합 테스트 5개는 건너뛴다. 종료는 `python injector.py down`이며 데모 Compose 프로젝트 전체를 종료한다. Vault 대역만 멈추려면 Compose의 `stop vault-mock`을 사용한다. 이후 `up`에서 --with-vault를 생략해도 이미 실행 중인 대역을 자동 종료하지는 않는다.
