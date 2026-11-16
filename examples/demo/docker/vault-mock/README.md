# 로컬 Vault API 대역

이 디렉터리는 WireMock의 매핑과 로컬 설정값이다. 실제 Vault 이미지를 실행하거나 회사 Vault에 접속하지 않는다.

## 실행과 확인

저장소 루트에서 실행한다.

```powershell
python injector.py up --profile mock --with-vault
python injector.py vault-demo
```

Vault 대역은 `http://localhost:18083`, Docker 네트워크에서는 `http://vault-mock:8080`이다. `--with-vault`를 쓰면 생성된 IntelliJ 실행 구성과 Docker 환경에도 `VAULT_ADDR`, `VAULT_PATH`, `VAULT_TOKEN`을 넣는다. 기존 Java Main은 이 값을 소비하지 않는다. `vault-demo`는 별도 Python 설정 소비 앱을 실행해 KV v2 조회와 값 사용을 확인한다.

## 현재 재현하는 요청

```http
GET /v1/secret/data/injector-demo
X-Vault-Token: local-demo-token
```

정상 응답은 [KV v2 read 형식](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2)의 `data.data`와 `data.metadata`를 사용한다. 토큰이 없거나 다르면 JSON 403, 올바른 토큰으로 미등록 `/v1/` 경로·메서드·query를 요청하면 JSON 404를 반환한다.

고정 토큰 검사는 매핑 선택 조건일 뿐 실제 인증·정책 엔진이 아니다. login, token lookup/renew, lease, KV v1, 쓰기·버전 조회, Vault namespace, TLS 등은 재현하지 않는다. 회사 앱이 요구하는 요청은 소스와 실제 로컬 요청 기록을 근거로 추가해야 한다. 회사 앱·Vault SDK 호환성을 검증한 상태는 아니다.

## 앱이 읽어갈 값 변경

1. [__files/injector-demo.json](__files/injector-demo.json)의 `data.data`에 앱이 읽을 키·로컬 값을 넣는다.
2. 앱의 mount·secret path가 다르면 [mappings/read-config.json](mappings/read-config.json)의 `request.url`과 데모 `config/project.json`의 `vaultMock.env.VAULT_PATH`를 함께 맞춘다. VAULT_PATH는 `/v1/`을 제외한 경로다.
3. 변경 후 `docker compose -p injector-poc -f examples/demo/docker/compose.yaml restart vault-mock`를 실행하고 다시 조회한다.

앱이 여러 개면 앱별로 서로 다른 `request.url`과 `bodyFileName`을 가진 매핑·응답 파일을 추가한다. 각 앱이 읽는 VAULT_PATH도 해당 경로와 맞춘다. 현재 예시는 하나의 앱 경로만 제공한다.

현재 소비 앱은 `message`, `feature_enabled`, `database_username`, `database_password`를 사용한다. `feature_enabled`를 false로 바꾸면 메시지가 `feature disabled`로 바뀐다. 자격증명 값 자체는 소비 앱 출력에 포함하지 않는다. fixtures의 토큰·비밀번호는 데모용 고정값이며 실제 자격증명을 저장소에 넣지 않는다.

실제 앱 적용에서는 환경변수 이름도 해당 앱의 설정 바인딩에 맞춰야 한다. 예를 들어 VAULT_ADDR라는 이름만 넣는다고 모든 프레임워크가 그 값을 자동 인식하는 것은 아니다.

## 테스트와 종료

```powershell
$env:INJECTOR_TEST_VAULT_URL = 'http://127.0.0.1:18083'
python -m unittest discover -s tests -p test_vault_mock_integration.py -v
```

이 URL을 지정하지 않으면 WireMock 통합 테스트 4개는 건너뛴다. 종료는 `python injector.py down`이며 데모 Compose 프로젝트 전체를 종료한다. Vault 대역만 멈추려면 Compose의 `stop vault-mock`을 사용한다. 이후 `up`에서 --with-vault를 생략해도 이미 실행 중인 대역을 자동 종료하지는 않는다.
