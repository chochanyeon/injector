# Upgrade Consistency Verifier

[English](README.md) · **한국어** · [Injector](../README.ko.md)

Injector에서 기록한 HTTP 파일 두 개는 루트에서 `python injector.py compare-http <baseline.json> --candidate <current.json>`으로 비교한다. `compare-worktrees`는 기존 워크트리 두 개에서 같은 시나리오를 실행해 기록과 비교를 한 번에 수행한다. [HTTP 관측 데모](../examples/demo/http-observation/README.ko.md)

두 명령 모두 Loki에서 수집한 버전 2 HTTP·Kafka 요청 흐름을 비교할 수 있다. [쇼핑몰 주문 흐름](../examples/demo/monorepo/README.ko.md#주문-흐름-비교)

## 로컬에서 버그 수정 검증

버전 2 시나리오에서 `expect`로 주 요청의 기대 응답을, `stateChecks`로 의존성 그래프 안의 읽기 전용 GET 검사를 지정한다. `before` 검사로 초기 상태를 확인한다. 비동기 결과를 확인하는 `after` 검사에는 `timeoutSeconds`를 지정할 수 있다. 증거 파일에 보관해도 되는 필드만 선택한다.

- 회귀 비교에는 `compare-worktrees`를 사용한다. 양쪽 모두 기대 동작을 충족하고 관측 결과가 일치해야 한다.
- `--prove-fix CHECK_ID`를 추가하면 기준 쪽에서 지정한 실패가 재현되고 후보 쪽에서 모든 검사가 통과해야 한다. `response`, `after` 검사 ID, 이벤트 횟수 검사 ID를 지정할 수 있다. `compare-http`에도 같은 옵션을 사용할 수 있다.
- 비교 출력 폴더의 `report.json`에서 판정, 노드별 기동 단계, 저장된 기록을 확인한다. 초기 상태가 다르거나 증거를 수집하지 못하면 `INCONCLUSIVE`가 나올 수 있다.

[쇼핑몰 주문 수정 검증](../examples/demo/monorepo/README.ko.md#주문-버그-수정-검증)

`trace.eventCounts`에서 서비스, 이벤트 종류, 필요한 경우 의존성에 해당하는 이벤트의 기대 횟수를 지정한다. 각 검사는 `id`, `match`, `count`를 사용한다. 필수 이벤트가 모두 도착하고 기록이 `trace.settleSeconds` 동안 동일하게 유지되면 Verifier가 횟수를 센다. 횟수 0은 해당 요청과 관측 시간에 적용한다. 기록이 부족하거나 계속 바뀌면 `INCONCLUSIVE`다.

## 스위트 실행

`verify-suite`로 같은 대상과 프로필의 여러 시나리오를 실행한다. 버전 1 스위트는 `target`, `profile`, `cases`를 지정한다. 각 시나리오 경로는 스위트 파일이 있는 폴더 기준으로 작성한다. 기준 버전에 특정 실패를 재현하는 항목에는 `proveFix`를 지정한다. 나머지는 회귀 비교로 실행한다. 시나리오는 한 번씩 지정한다.

```text
python injector.py verify-suite examples/demo/monorepo/scenarios/checkout-fix-suite.json --project path/to/baseline --candidate-project path/to/candidate --output .local/checkout-suite
```

서비스를 시작하기 전에 모든 항목을 검사한다. 워크트리와 시나리오마다 새 세션을 열며, 데이터를 보존하는 의존성은 초기 상태를 확인하거나 임시 저장소를 사용한다. 동작 차이가 확인돼도 다음 비교를 계속한다. 기동이나 정리에 실패하면 스위트를 중단하고 남은 항목을 `NOT_RUN`으로 표시한다. 실패가 하나라도 확인되면 전체 `FAIL`이다. 확인된 실패가 없고 증거가 부족하면 `INCONCLUSIVE`다.

검토할 때는 `summary.md`를, 자동화에서는 `report.json`을 사용한다. 각 항목은 두 워크트리의 상세 보고서와 기록으로 연결된다. `compare-worktrees`와 같은 `--registry` 옵션도 사용할 수 있다.

의존성 업그레이드 전 **HEAD**와 변경 후 **현재 작업 디렉터리**에서 같은 검증 코드를 실행하는 로컬 POC다. 특정 라이브러리의 API를 하드코딩하지 않는다. 검증 항목이 모두 같으면 `PASS` / exit 0, 하나라도 다르거나 실행을 완료하지 못하면 `FAIL` / exit 1이다. stdout에는 판정 한 줄만 출력하며 Gradle 로그와 실패 원인은 stderr / JUnit 리포트에 남긴다.

Gradle 검증은 **Java 17 이상, Spring Boot 3.x, Spring MVC, Jackson 2, Gradle Java 플러그인**을 사용하는 서비스가 대상이다. 데모는 Boot 3.5.7이다. 대상 저장소는 Groovy / Kotlin DSL 모두 가능하며, 대상의 Gradle Wrapper와 JDK 호환성은 해당 프로젝트 설정을 따른다. 이 도구 자체의 Wrapper(Gradle 9.3.1)는 데모 실행용이다. Gradle 검증 소스는 `src/test`에 있다.

## 다른 서비스에서 실행

Git Bash 또는 Linux/macOS Bash, Git, JDK가 필요하다. 대상 저장소에는 커밋된 HEAD와 `gradlew`가 있어야 한다.

```bash
bash /path/to/verifier/verify-upgrade.sh --repo /path/to/service -- \
  -Pverify.application=com.example.Application \
  -Pverify.profiles=upgrade-verification \
  '-Pverify.get.paths=/api/products/7,/api/products?page=0'
echo "$?"  # 0 또는 1
```

멀티 모듈 프로젝트는 애플리케이션을 포함한 Java 모듈을 지정한다.

```bash
bash /path/to/verifier/verify-upgrade.sh \
  --repo /path/to/service --project :services:catalog -- \
  -Pverify.application=com.example.catalog.Application \
  '-Pverify.get.paths=/api/catalog/7'
```

## 한 번 실행할 때 일어나는 일

1. **비교 대상 고정.** `--repo`에서 Git 저장소 루트를 찾고 실행 시작 시점의 `HEAD` 커밋을 확인한다. `/tmp/upgrade-verifier.*` 아래에 이 커밋의 detached worktree를 만든다. 검증기의 Gradle 스크립트와 `src/test/java/upgrade/verifier/`도 같은 임시 디렉터리에 복사한다.
2. **HEAD 기록.** HEAD worktree에서 해당 저장소의 `gradlew`로 선택한 모듈의 `test --tests '*UpgradeConsistencyVerifierTest'`를 `-Pverify.mode=record`로 실행한다. Init script가 임시 스냅샷을 `upgradeVerification` 소스 세트에 연결한다. 이 소스 세트는 앱의 메인 클래스와 의존성을 사용한다. 서비스 자체의 테스트 코드, `src/test/resources`, `testRuntimeOnly`는 검증 소스 세트에 포함되지 않는다. Gradle의 구성 캐시와 빌드 캐시를 끄고 태스크를 다시 실행한다. 런타임 검사와 모든 동작 검사가 완료되면 절대 경로의 임시 `baseline.json`에 결과를 기록한다.
3. **현재 코드 비교.** 기준선이 생성되면 원래 작업 디렉터리에서 동일한 검증 스냅샷과 같은 기준선 경로로 `-Pverify.mode=verify`를 실행한다. 현재 앱의 클래스패스를 독립적으로 검사하고 같은 방식으로 지문을 만든다. 지문 비교와 Spring 컨텍스트 종료가 성공하면 JUnit이 임시 완료 파일을 기록한다. 기준선 기록이 실패하면 이 단계는 실행되지 않는다.
4. **정리 후 결과 출력.** 두 실행, 완료 파일 확인, 임시 worktree와 파일 정리가 모두 성공하면 stdout에 `PASS` 한 줄을 출력하고 `0`을 반환한다. 불일치, 빌드·기동 오류, 테스트 생략으로 인한 기준선 또는 완료 파일 누락, 정리 오류는 `FAIL` 한 줄과 종료 코드 `1`로 처리한다. `INT`/`TERM`에도 정리를 실행한다. `SIGKILL`과 전원 종료에는 정리 코드가 실행되지 않는다.

현재 디렉터리의 다른 미커밋 변경도 비교에 포함된다. 의존성만 평가하려면 다른 애플리케이션 변경은 분리한다. HEAD에서 참조할 수 없는 로컬 파일 의존성, 미커밋 Gradle Wrapper, worktree 밖의 상대경로 의존성은 HEAD 빌드가 실패할 수 있다.

## 판정 항목

두 실행 모두 클래스패스를 먼저 검사한다. 그다음 설정한 애플리케이션과 Spring 프로필로 Servlet 컨텍스트를 띄운다. 내장 서버 포트는 `0`으로 요청해 실행 시 배정받는다.

| 검사 | 수집하는 값과 실패 조건 |
| --- | --- |
| 런타임 JAR | Gradle의 `runtimeClasspath`와 검증 클래스패스의 의존성 결정을 일치시키고, 앱 런타임 아티팩트 파일이 실제 검증 클래스패스에 모두 포함됐는지 확인한다. JAR의 Gradle 좌표와 `META-INF/maven/**/pom.properties`를 검사한다. 좌표를 확인할 수 없는 JAR, 동일 `groupId:artifactId`의 복수 버전, 설정한 정렬 규칙 위반은 그 실행에서 FAIL이다. |
| Bean 정의 | `getBeanDefinitionNames()`의 전체 이름을 정렬해 비교한다. Bean의 내부 상태는 사용자 정의 프로브로 관찰할 수 있다. |
| MVC 매핑 | 컨텍스트의 모든 `RequestMappingHandlerMapping`에서 매핑 Bean 이름, 경로, HTTP 메서드, 쿼리·헤더 조건, `consumes`, `produces`, 커스텀 조건의 문자열, 핸들러 메서드 시그니처를 모아 정렬한다. |
| DTO | 실제 MVC 매핑과 ClassGraph가 찾은 `@RestController`, `@KafkaListener`, `@KafkaHandler` 메서드 시그니처 및 `verify.dto.classes`에서 DTO를 모은다. 앱의 각 `ObjectMapper` Bean에서 샘플을 직렬화·역직렬화·재직렬화한다. 각 실행에서 왕복 전후 JSON이 일치해야 하고, 실행 간에는 Mapper 이름과 DTO 클래스 이름별로 직렬화 결과를 비교한다. 기본 샘플은 리플렉션으로 만들며 시간과 UUID에 고정값을 넣는다. 생성이 어려운 DTO는 `verify.dto.samples`로 샘플을 지정한다. |
| GET 응답 | MockMvc로 Servlet Filter Bean을 적용하고 `Accept: application/json` 요청을 보낸다. `/actuator/health`와 최소 한 개의 앱 GET 경로가 필요하다. 경로 미지정 시 명시적 GET 매핑에서 쿼리·헤더 조건, 경로 변수, 와일드카드, `/error`, `/actuator`로 시작하는 경로를 제외해 선택한다. 각 경로의 정확한 HTTP 상태 코드와 본문을 비교하며, 동기 응답·2xx·비어 있지 않은 유효한 JSON이 각각 필요하다. |
| 사용자 정의 프로브 | `verify.probe.classes`에 등록된 클래스에 실제 Spring 컨텍스트를 전달하고, 클래스별로 반환된 JSON을 비교한다. |

`baseline.json`에는 형식 버전 `schema`, JAR 파일명과 버전을 기록한 `runtimeArtifacts`, 비교 대상인 `fingerprint`가 들어간다. `fingerprint`에는 `configuration`, `beans`, `endpoints`, `dtos`, `http`, `probes`가 저장된다. `configuration`에는 애플리케이션 클래스, 탐색 패키지, 검증 옵션과 DTO 샘플 내용이 포함된다. 라이브러리 버전은 각 실행의 혼재 검사에 사용하며 전후 비교에서는 `fingerprint`를 사용한다.

JSON 객체의 키 순서는 무시한다. 키의 추가·삭제, 배열 순서, 숫자 값의 차이, `null`과 필드 부재는 구분한다. 소수는 정밀도를 유지해 읽으며 JSON 값 뒤에 추가 데이터가 있으면 실패한다. `verify.ignore.json.pointers`를 설정하면 지정한 필드나 배열 원소를 DTO·GET 응답·프로브의 본문에서 제거한 후 비교한다. 구조가 다르면 처음 발견한 위치를 `AssertionError`에 표시한다. 예를 들어 데모의 `/api/sample` 응답에서 `name`이 바뀌면 `/fingerprint/http/~1api~1sample/body/name`이 보고된다. JSON Pointer의 `~1`은 경로에 포함된 `/`를 뜻한다.

스크립트가 임시 기준선을 정리하므로 기준선 내용을 보존하려면 아래 수동 실행에 원하는 `baseline.path`를 지정한다. 로그를 분리해 보려면 `2>verify.log`를 붙인다. 변경 후 테스트가 실행됐다면 선택한 모듈의 기본 JUnit XML 경로 `build/test-results/test/TEST-upgrade.verifier.UpgradeConsistencyVerifierTest.xml`에서도 상세 실패 메시지를 확인할 수 있다.

### 여러 모듈의 버전 정렬

동일 groupId 안에도 버전 체계가 서로 다른 정상적인 artifact가 있을 수 있다. 그래서 기본 검사는 모든 라이브러리의 동일 G:A 복수 버전을 거부하고, **계열 전체의 동일 버전 요구는 groupId 정규식으로 명시**한다. 예를 들어 다음 규칙은 Jackson 전체 / Netty / Bouncy Castle 각각의 버전 혼재를 거부한다. 다른 라이브러리도 같은 방식으로 추가한다. 규칙이 어떤 JAR에도 매치되지 않으면 오타로 인한 검증 누락을 막기 위해 FAIL 처리한다.

```bash
bash verify-upgrade.sh --repo /path/to/service -- \
  -Pverify.application=com.example.Application \
  '-Pverify.alignment.groups=com\.fasterxml\.jackson(\..*)?,io\.netty,org\.bouncycastle'
```

예를 들어 Jackson 2.12.7과 2.12.7.2도 이 엄격한 규칙에서는 혼재로 판정한다. 해당 계열이 원래 그런 패치 버전 조합을 의도했다면 더 좁은 groupId 규칙을 사용하거나, 그 계열 정렬 규칙을 적용하지 않는다.

## 설정

프로퍼티는 `-P`로 전달하면 테스트 JVM의 동일 이름 시스템 프로퍼티가 된다.

| 프로퍼티 | 설명 |
| --- | --- |
| `verify.mode` | `record` / `verify`. 자동화 스크립트가 지정한다. |
| `baseline.path` | 절대 JSON 파일 경로. 자동화 스크립트가 같은 임시 경로를 지정한다. |
| `verify.application` | 실행할 Spring Boot 설정 클래스. 없으면 유일한 `@SpringBootApplication`을 찾는다. |
| `verify.project` | 대상 Gradle 모듈. 스크립트에서는 `--project` 사용. 기본 `:`. |
| `verify.profiles` | 활성화할 Spring 프로필. 쉼표 구분. |
| `verify.scan.packages` | DTO 탐색 패키지. 기본 애플리케이션 패키지. 쉼표 구분. |
| `verify.dto.classes` | 추가 DTO 클래스 이름. 쉼표 구분. 중첩 클래스는 `$` 사용. |
| `verify.dto.samples` | DTO 이름 → 샘플 JSON 객체를 담은 파일의 절대 경로. 양쪽에서 같은 파일을 읽는다. |
| `verify.get.paths` | health 외 GET URI 목록. 쿼리 문자열 가능. 쉼표 구분, URI 내 쉼표는 `%2C` 사용. |
| `verify.ignore.json.pointers` | 쉼표로 구분하는 RFC 6901 JSON 포인터. 배열은 원본 인덱스를 기준으로 제외한다. |
| `verify.alignment.groups` | 버전 정렬을 강제할 groupId 정규식 목록. 쉼표 구분. |
| `verify.probe.classes` | `RuntimeProbe` 구현 클래스 목록. 쉼표 구분. |

샘플 JSON 예:

```json
{
  "com.example.OrderDto": {
    "id": "00000000-0000-0000-0000-000000000007",
    "createdAt": "2020-01-02T03:04:05Z",
    "amount": 100
  }
}
```

기본 생성자가 없는 immutable DTO, 다형성, 복잡한 generic DTO 등은 샘플을 제공한다. 샘플도 애플리케이션의 ObjectMapper로 읽으므로 모듈과 생성자 설정을 실제로 검증한다. JSON을 만들지 못하거나 왕복 결과의 JSON이 달라지면 FAIL이다. DTO가 하나도 발견되지 않아도 FAIL이므로 별도 패키지 DTO는 탐색 패키지나 클래스 목록을 설정한다.

동적 응답은 먼저 테스트 프로필의 고정 시계·고정 데이터로 재현 가능하게 만든다. 꼭 필요한 경우에만 `'-Pverify.ignore.json.pointers=/timestamp,/requestId'`처럼 제외한다. 이 포인터들은 모든 DTO/프로브/HTTP 본문에 동일하게 적용된다. 자동으로 UUID나 타임스탬프를 찾아 삭제하지 않는다. 샘플 내용과 제외 규칙도 지문에 포함되어 검증 설정 변경을 감지한다.

## 사용자 정의 검증

추가 Java 파일을 **도구의** `src/test/java/upgrade/verifier/` 아래에 넣으면 두 체크아웃에 함께 주입된다. 공개 기본 생성자를 제공하고 `UpgradeConsistencyVerifierTest.RuntimeProbe`를 구현한다.

```java
package upgrade.verifier;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import org.springframework.context.ConfigurableApplicationContext;

public class DomainProbe implements UpgradeConsistencyVerifierTest.RuntimeProbe {
    public JsonNode fingerprint(ConfigurableApplicationContext context) {
        // 실제 서비스 Bean에 결정적인 입력을 넣고 관찰한 결과를 JSON으로 반환한다.
        return JsonNodeFactory.instance.objectNode().put("result", "replace-with-observed-value");
    }
}
```

`-Pverify.probe.classes=upgrade.verifier.DomainProbe`로 등록한다. 암호화 결과의 무작위 nonce처럼 원래 변하는 결과는 고정 입력/시드나 복호화 결과 등의 의미 있는 불변량을 관찰한다.

## Gradle 구성

`upgrade-verifier.init.gradle`이 선택한 모듈에 `upgrade-verifier.gradle`을 적용하며 검증 소스 세트에 다음 의존성을 추가한다. 서비스가 기존 `src/test/resources`에만 둔 설정을 사용한다면 두 체크아웃에서 공통으로 참조할 외부 설정이나 환경 변수를 준비한다.

* JUnit BOM 5.11.4 / Jupiter / Platform Launcher
* ClassGraph 4.8.179
* **대상 런타임 spring-core와 동일 버전**의 spring-test

대상의 Spring / Jackson BOM을 추가하거나 덮어쓰지 않는다. Spring Boot, MVC, Jackson 및 Actuator는 대상 애플리케이션의 것을 사용한다. Actuator가 없거나 health가 다른 관리 포트/경로에만 존재하면 기본 health 검사는 FAIL이다.

수동으로 실행하려면 자동화 스크립트와 같은 검증 파일 스냅샷을 만든다. `tool`은 이 도구 저장소의 절대 경로다.

```bash
tool=/path/to/verifier
snapshot=$(mktemp -d /tmp/verifier-manual.XXXXXXXX)
mkdir -p "$snapshot/src/test/java/upgrade"
cp -R "$tool/src/test/java/upgrade/verifier" "$snapshot/src/test/java/upgrade/"
cp "$tool/upgrade-verifier.init.gradle" "$tool/upgrade-verifier.gradle" "$snapshot/"
```

HEAD 체크아웃에서 `record`를 실행한다. 변경 후 체크아웃에서는 같은 절대 경로와 옵션으로 `verify`를 실행한다. 멀티 모듈에서는 태스크를 `:services:catalog:test`처럼 지정하고 `-Pverify.project=:services:catalog`를 추가한다. 수동 실행에서 만든 스냅샷과 기준선은 작업이 끝난 후 직접 관리한다.

```bash
./gradlew test --tests '*UpgradeConsistencyVerifierTest' \
  --no-configuration-cache \
  -I "$snapshot/upgrade-verifier.init.gradle" \
  "-Pverify.tool.home=$snapshot" \
  -Pverify.application=com.example.Application \
  -Pverify.mode=record -Pbaseline.path=/absolute/path/baseline.json
# 변경 후에는 동일한 인자에 -Pverify.mode=verify 사용
```

## 도구 자체 검증

현재 저장소는 프로덕션 소스 없이 `src/test`의 작은 백엔드를 띄운다.

```bash
./gradlew test --tests '*UpgradeConsistencyVerifierTest' \
  -Pverify.mode=record -Pbaseline.path="$PWD/baseline.json"
./gradlew test --tests '*UpgradeConsistencyVerifierTest' \
  -Pverify.mode=verify -Pbaseline.path="$PWD/baseline.json"
./gradlew test --tests '*VerifierMechanicsTest'
bash src/test/scripts/integration.sh
```

Windows PowerShell에서는 `./gradlew.bat`과 따옴표로 감싼 `'-Pverify.mode=record'`, 절대 Windows 기준선 경로를 사용한다. 저장소 루트와 `src/test`에만 파일을 두기 위해 데모 Wrapper의 JAR / properties도 루트에 배치했다.

통합 검사는 실제 의존성 업그레이드, 서비스 테스트 의존성과의 충돌, 변경 후 테스트가 생략된 경우의 FAIL, HTTP 응답 변경의 FAIL, 기준선 생성 실패, 잘못된 저장소 경로, 커스텀 프로브, 멀티 모듈 선택, 이전 검증 코드 대체, 한 줄 출력, 종료 코드, worktree 정리를 확인한다.

## 판정의 범위

PASS는 **이 검증 설정과 샘플로 관찰한 항목의 동등성**을 뜻한다. 모든 입력과 운영 트래픽에 대한 호환성을 증명하지 않는다. 실제 Spring 컨텍스트와 임의 포트의 내장 서버를 시작하므로 DB/Kafka 등은 양쪽에서 같은 결정적인 테스트 환경과 프로필을 준비해야 한다. 시작 자체가 실패하면 FAIL이다.

인증이 필요한 GET, async/streaming 응답, 비 JSON 응답, Servlet FilterRegistrationBean만으로 등록된 특수 필터, 외부 프록시/네트워크 계층, WebFlux, Boot 4/Jackson 3, 비 JVM 백엔드는 기본 smoke 범위 밖이다. 해당 동작은 결정적인 프로브 또는 별도 프레임워크 어댑터로 확장해야 한다. 현재 HTTP smoke는 2xx JSON API를 대상으로 하며, 오류 응답 시나리오는 프로브로 추가한다. 커스텀 RequestCondition의 비결정적인 `toString()`도 FAIL 원인이 될 수 있다.
