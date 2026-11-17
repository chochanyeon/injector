# Upgrade Consistency Verifier

의존성 업그레이드 전 **HEAD**와 변경 후 **현재 작업 디렉터리**에서 같은 검증 코드를 실행하는 로컬 POC다. 특정 라이브러리의 API를 하드코딩하지 않는다. 검증 항목이 모두 같으면 `PASS` / exit 0, 하나라도 다르거나 실행을 완료하지 못하면 `FAIL` / exit 1이다. stdout에는 판정 한 줄만 출력하며 Gradle 로그와 실패 원인은 stderr / JUnit 리포트에 남긴다.

현재 구현은 **Java 17 이상, Spring Boot 3.x, Spring MVC, Jackson 2, Gradle Java 플러그인**을 사용하는 서비스가 대상이다. 데모는 Boot 3.5.7이다. 대상 저장소는 Groovy / Kotlin DSL 모두 가능하며, 대상의 Gradle Wrapper와 JDK 호환성은 해당 프로젝트 설정을 따른다. 이 도구 자체의 Wrapper(Gradle 9.3.1)는 데모 실행용이다. 모든 소스는 `src/test`에 있으며 `src/main`은 필요하지 않다.

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

대상 `build.gradle[.kts]`을 복사하거나 덮어쓰지 않는다. `/tmp`에 HEAD worktree와 검증 파일 스냅샷을 만들고, init script가 **선택한 모듈의 테스트에만** 같은 Java 소스와 테스트 의존성을 주입한다. 아직 커밋하지 않은 검증 코드도 양쪽에 동일하게 들어간다. 대상에 같은 패키지의 검증 코드가 있으면 주입한 스냅샷을 우선한다. Gradle test 캐시와 up-to-date 생략을 비활성화한다. 정상 종료, 오류, INT/TERM 시 worktree와 기준선을 정리한다. SIGKILL / 전원 종료는 trap으로 정리할 수 없다.

현재 디렉터리의 다른 미커밋 변경도 비교에 포함된다. 의존성만 평가하려면 다른 애플리케이션 변경은 분리한다. HEAD에서 참조할 수 없는 로컬 파일 의존성, 미커밋 Gradle Wrapper, worktree 밖의 상대경로 의존성은 HEAD 빌드가 실패할 수 있다.

## 판정 항목

1. **실제 테스트 런타임 클래스패스**: Gradle Test task의 classpath와 Maven JAR 메타데이터를 검사한다. Gradle이 보통 하나의 버전으로 해결한 선언상의 충돌이 아니라, 실제 존재하는 동일 `groupId:artifactId`의 복수 버전을 거부한다. `files(...)` 및 shaded JAR의 Maven 메타데이터도 확인한다. 좌표를 판별할 수 없는 JAR은 묵인하지 않고 FAIL 처리한다.
2. **전체 Bean / MVC 매핑**: Bean 정의 이름 전체, 경로·HTTP 메서드·params·headers·consumes·produces·custom condition·핸들러 시그니처 전체를 정렬하여 비교한다.
3. **DTO 왕복**: MVC 매핑과 ClassGraph의 `@RestController`, `@KafkaListener` / `@KafkaHandler` 시그니처에서 애플리케이션 DTO를 찾는다. 각 실제 `ObjectMapper` Bean으로 직렬화 → 역직렬화 → 재직렬화하고 JSON 트리의 보존 및 기준선 일치를 검사한다. 시간과 UUID는 고정값이다. record, 기본 생성자가 있는 POJO, 기본 타입, 시간 타입, enum, 배열·컬렉션 등을 지원한다. 생성할 수 없는 DTO는 명시적인 JSON 샘플을 요구하며 조용히 건너뛰지 않는다.
4. **GET smoke**: MockMvc로 `/actuator/health`와 설정한 GET 경로들을 호출한다. 2xx와 파싱 가능한 JSON을 요구하고 HTTP 상태와 JSON 트리를 비교한다. Bean으로 등록된 Servlet Filter를 적용한다. 별도 GET 설정이 없으면 params/headers 조건과 경로 변수가 없는 명시적 GET 매핑을 자동 선택한다. health 이외에 최소 한 경로가 필요하다.
5. **선택적인 서비스 프로브**: HTTP/DTO 밖의 도메인 동작도 같은 지문에 추가할 수 있다.

JSON 객체 키 순서는 무시하고 배열 순서·숫자·null과 필드 부재는 구분한다. 첫 불일치 경로를 `AssertionError`로 보고한다. 기준선에는 클래스패스 버전 정보도 남기지만, **버전 자체를 전후 동등성 비교에 넣지는 않는다**.

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
| `verify.ignore.json.pointers` | 명시적으로 제외할 RFC 6901 JSON 포인터. 쉼표 구분. 기본 제외 없음. |
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

기본 생성자가 없는 immutable DTO, 다형성, 복잡한 generic DTO 등은 샘플을 제공한다. 샘플도 애플리케이션의 ObjectMapper로 읽으므로 모듈과 생성자 설정을 실제로 검증한다. JSON을 만들지 못하거나 왕복 과정에서 데이터가 소실되면 FAIL이다. DTO가 하나도 발견되지 않아도 FAIL이므로 별도 패키지 DTO는 탐색 패키지나 클래스 목록을 설정한다.

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

다른 서비스의 build 파일 수정은 필요 없다. `upgrade-verifier.init.gradle`이 선택한 모듈에 `upgrade-verifier.gradle`을 적용하며 다음 테스트 전용 의존성을 추가한다.

* JUnit BOM 5.11.4 / Jupiter / Platform Launcher
* ClassGraph 4.8.179
* **대상 런타임 spring-core와 동일 버전**의 spring-test

대상의 Spring / Jackson BOM을 추가하거나 덮어쓰지 않는다. Spring Boot, MVC, Jackson 및 Actuator는 대상 애플리케이션의 것을 사용한다. Actuator가 없거나 health가 다른 관리 포트/경로에만 존재하면 기본 health 검사는 FAIL이다.

수동으로 실행하려면 양쪽 checkout에서 동일한 도구 경로를 사용한다.

```bash
./gradlew test --tests '*UpgradeConsistencyVerifierTest' \
  -I /path/to/verifier/upgrade-verifier.init.gradle \
  -Pverify.tool.home=/path/to/verifier \
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

통합 검사는 임시 Git 저장소에서 실제 의존성 업그레이드의 PASS, HTTP 응답 변경의 FAIL, 기준선 생성 실패, 잘못된 저장소 경로, 커스텀 프로브, 멀티 모듈 선택, 이전 검증 코드 대체, 한 줄 출력 / 종료 코드 / worktree 정리를 확인한다.

## 판정의 범위

PASS는 **이 검증 설정과 샘플로 관찰한 항목의 동등성**을 뜻한다. 모든 입력과 운영 트래픽에 대한 호환성을 증명하지 않는다. 실제 Spring 컨텍스트와 임의 포트의 내장 서버를 시작하므로 DB/Kafka 등은 양쪽에서 같은 결정적인 테스트 환경과 프로필을 준비해야 한다. 시작 자체가 실패하면 FAIL이다.

인증이 필요한 GET, async/streaming 응답, 비 JSON 응답, Servlet FilterRegistrationBean만으로 등록된 특수 필터, 외부 프록시/네트워크 계층, WebFlux, Boot 4/Jackson 3, 비 JVM 백엔드는 기본 smoke 범위 밖이다. 해당 동작은 결정적인 프로브 또는 별도 프레임워크 어댑터로 확장해야 한다. 현재 HTTP smoke는 2xx JSON API를 대상으로 하며, 오류 응답 시나리오는 프로브로 추가한다. 커스텀 RequestCondition의 비결정적인 `toString()`도 FAIL 원인이 될 수 있다.
