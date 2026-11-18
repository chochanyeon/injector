# Spring 설정 조사 체크리스트

[English](spring-configuration-audit.md) · **한국어**

선택한 **앱 × 실행 방식 × Spring 프로필**마다 확인한다. 각 항목을 확인됨·해당 없음·미확인으로 표시하고, 미확인 항목이 실행을 막는지 기록한다. 최종값은 원본 파일, 실제로 선택한 실행 방식, 값을 읽는 코드의 근거가 일치할 때 확정한다.

## 1. 실제 실행 입력 확인

| 범위 | 확인할 항목 |
|---|---|
| 버전과 시작 코드 | 빌드의 Spring Boot·Spring Cloud 버전, main 진입점, `SpringApplication`·`SpringApplicationBuilder`에 설정된 프로필·기본 속성·명령행 옵션 처리 여부 |
| IDE와 로컬 실행 | 공유 `.run/`, `.idea/runConfigurations/`, 기동 스크립트, `bootRun`·`spring-boot:run` 정의. 작업 디렉터리, 프로그램 인자, JVM 옵션·`-D`, 직접 전달하는 환경 변수와 환경 파일 경로 |
| 컨테이너와 배포 | Dockerfile의 `ENTRYPOINT`·`CMD`, Compose의 `command`·`environment`·`env_file`·마운트, 해당 앱의 Helm·Kubernetes·CI 실행 변수와 설정 파일 주입 선언. 리포지터리에서 알 수 없는 값은 변수 이름과 발급 주체만 기록 |
| 프로세스 환경 | `SPRING_APPLICATION_JSON`, `JAVA_TOOL_OPTIONS` 등 JVM·Spring 설정을 묶어서 전달하는 입력. 실행 스크립트가 환경 변수를 읽고 JVM 옵션 또는 프로그램 인자로 변환하는지 확인 |

Gradle·Maven 빌드 프로필과 Spring 활성 프로필을 각각 기록한다. 빌드에서 리소스를 필터링하거나 생성한다면 소스 템플릿, 적용 조건, 값의 출처를 함께 확인한다.

## 2. 실제로 읽히는 파일과 외부 출처 연결

- 앱 리소스와 공유 모듈, 작업 디렉터리와 외부 설정 경로에서 `application.yml`, `application.yaml`, `application.properties` 및 프로필별 파일을 찾는다. 다중 문서의 `spring.config.activate.on-profile` 조건, 활성화·기본·추가·그룹 프로필을 확인한다.
- `spring.config.name`, `spring.config.location`, `spring.config.additional-location`, `spring.config.import`를 따라간다. 파일·클래스패스·설정 트리·원격 공급원을 구분하고, 상대 import의 기준 위치와 `optional:` 여부를 기록한다. 기존 경로를 대체할지 추가할지는 적용 버전에서 확인한다. [Spring Boot 외부 설정](https://docs.spring.io/spring-boot/reference/features/external-config.html)
- Cloud Config·Vault 같은 외부 출처는 import 선언, 설정 클라이언트 또는 직접 호출 코드를 구분한다. `bootstrap.*`가 있으면 실제로 bootstrap이 활성화되는 근거를 확인한다. 원격 소스는 주소·설정 키·인증 참조를 기록하고 실제 값은 로컬 공급 방법이 확인될 때 분류한다. [Spring Cloud Config 클라이언트](https://docs.spring.io/spring-cloud-config/reference/client.html)
- `${KEY:default}` 참조를 환경 변수·다른 속성·기본값까지 추적한다. 같은 키가 여러 소스에 있으면 후보, 선택 기준, 적용 순서를 남긴다. 소스에서 확인한 기본값과 현재 실행 환경의 실제 값을 구분한다.

## 3. 값을 읽는 코드에서 역으로 대조

`rg -n`으로 다음 단서를 앱과 해당 앱이 사용하는 공통 모듈에서 찾는다. 설정 파일 → 읽는 코드와 읽는 코드 → 설정 출처를 양방향으로 대조한다.

- `@ConfigurationProperties`, `@Value`, `Environment.getProperty`, `Binder`의 접두사와 키를 추적한다. Spring 자동 설정과 `@Profile`, `@ConditionalOnProperty`가 클라이언트·데이터소스·스케줄러를 활성화하는 조건도 확인한다.
- `System.getenv`, `System.getProperty`, `System.setProperty`와 이를 감싼 사내 래퍼를 따라간다. 같은 키가 보여도 실제 읽는 채널을 기준으로 분류한다.
- `@PropertySource`, `EnvironmentPostProcessor`, `PropertySource` 추가, 파일 직접 읽기, 사용자 정의 YAML·properties 파싱을 찾는다. Spring `Environment` 외의 파일은 별도의 입력 계약으로 기록한다.
- HTTP·gRPC 클라이언트, DB·마이그레이션, Kafka·Redis, Vault·설정 서버의 주소와 사용 키를 연결한다. 메인 포트 외에 관리 포트와 상태 확인 경로, TLS·인증 입력도 확인한다. 테스트용 `@TestPropertySource`·`@DynamicPropertySource`가 주입한 값은 테스트 범위로 기록한다.

## 4. 근거와 주입 위치 기록

| 키 | 읽는 위치 | 값의 후보 출처 | 로컬 설정 또는 확인 항목 |
|---|---|---|---|
| `clients.catalog.base-url` | 예시 `CatalogProperties`의 Spring 바인딩 | 예시 `application-local.yml`과 실행 환경 변수 | Catalog 접속점으로 연결할 `springProperty` 주입 |
| `company.runtime.mode` | 예시 `RuntimeMode`의 `System.getProperty` | 예시 공유 IntelliJ 구성의 `-D` 옵션 | 앱 파일의 `vmProperties` |
| `DB_PASSWORD` | 예시 `System.getenv` 또는 설정 placeholder | 값은 실행 환경에서 제공 | 지원되는 실행 채널에서 변수 참조를 사용하고 사용자에게 로컬 공급 방법 확인 |

실제 조사 결과에는 각 근거의 상대 파일 경로와 줄 번호, 활성화 조건, 값이 없을 때의 동작을 붙인다. 위 예시 이름과 달리 실제 식별자는 소스에서 찾는다. 릴리스별 속성 우선순위와 relaxed binding의 환경 변수 이름은 해당 Spring Boot 버전으로 확인한다. [Spring Boot 외부 설정과 바인딩](https://docs.spring.io/spring-boot/reference/features/external-config.html)

사용자가 실행 등록을 요청했다면 [실행 등록 관리 가이드](runtime-registry-guide.ko.md)에 따라 채널을 선택한다. `spring.config.*`와 활성 프로필처럼 초기 로딩에 필요한 값, 실행 방식에서 지원하지 않는 채널, 비밀값 참조의 공급 방법을 따로 점검한다. 여러 출처 중 어느 값이 이기는지 정적 근거로 확인할 수 없으면 그 조합을 미확인으로 남긴다.

기동이나 선택한 시나리오에 중요한 키는 조사 기록에 소비 코드 → 정규 키와 별칭 → 활성 후보 출처와 근거 → 유효 값 또는 미확인 이유 → Injector 주입 채널 또는 사용자에게 필요한 입력을 연결해 둔다. 비밀값은 변수 이름을 기록한다. 실행기와 프로세스 환경, import, 조건부 빈이 결과를 바꿀 수 있는지 확인한다. 질문은 막고 있는 결정별로 묶는다. 예를 들어 원격 기본 주소 대신 어느 로컬 Catalog 접속점을 쓸지 물을 때, 그 주소를 읽을 프로필과 클라이언트의 근거를 함께 제시한다.
