# 모노레포 최초 등록

[English](monorepo-initialization.md) · **한국어**

모노레포 루트, 먼저 디버그할 앱, 로컬 실행 방식과 프로필을 확인한다. 대상 앱이 미정이면 실행 후보와 근거를 먼저 보여준다. 전체 등록을 요청받았으면 후보를 먼저 목록화하고, 실행용 설정은 앱과 전이 의존성 한 묶음씩 검증한다.

## 1. 실행 후보 목록 만들기

- `rg --files`로 Gradle `settings.gradle[.kts]`, Maven `pom.xml`, 실행 스크립트, 공유 IntelliJ 설정, Dockerfile·Compose를 찾는다. 빌드 결과와 벤더 디렉터리는 제외한다.
- Gradle의 `include`, 실제 디렉터리를 바꾸는 `projectDir`, `includeBuild`를 확인한다. 공통 convention plugin이나 `buildSrc`에서 앱 플러그인·main class·리소스 위치를 지정하는 경우 해당 정의까지 따라간다. [Gradle 멀티 프로젝트와 프로젝트 경로](https://docs.gradle.org/current/userguide/multi_project_builds.html) · [Gradle 복합 빌드](https://docs.gradle.org/current/userguide/composite_builds.html)
- Maven은 집계 POM의 `modules`, 프로필에서 추가되는 모듈, 부모 POM으로부터 적용되는 실행 플러그인과 설정을 본다. 모듈 집계와 설정 상속의 근거를 각각 기록한다. [Maven 멀티 모듈](https://maven.apache.org/guides/mini/guide-multiple-modules.html) · [Maven 빌드 프로필](https://maven.apache.org/guides/introduction/introduction-to-profiles.html)
- main 진입점과 독립 실행 근거로 앱을 확인한다. 공통 라이브러리, 집계 모듈, 테스트 전용 앱, 단발성 배치는 용도를 따로 기록한다. 정적 소스에서 확정하기 어려운 동적 모듈 목록과 실행 명령은 미확인으로 남긴다.

후보 목록에는 `앱 ID | 모듈 경로 | 종류 | 실행 근거(파일·줄) | 조사 상태`를 남긴다. 동일 앱의 ID는 워크트리 경로가 달라도 유지한다.

## 2. 대상 앱과 인프라 준비 조건 조사

1. 대상 앱의 진입점, 작업 디렉터리, 실행 명령 또는 IntelliJ 모듈, 활성 프로필, 수신 포트와 준비 상태를 확인한다. IntelliJ에서 실제로 여는 프로젝트 루트를 근거로 `projectPath`를 정한다.
2. DB·Kafka·Redis·Vault·Config Server 등 먼저 필요한 인프라나 외부 자원을 찾는다. 공유 여부와 호출 위치를 확인하고, 호스트 공개 포트·컨테이너 내부 포트·서비스 이름을 구분한다. 같은 자원은 한 노드로 등록한다.
3. 각 실행 방식에서 필요한 VM 옵션·환경 변수·설정 출처를 기록한다. Spring 앱은 [Spring 설정 조사 체크리스트](spring-configuration-audit.ko.md)를 적용한다. 설정을 조사하다 발견한 앱 간 호출은 이 단계에서 후보 간선으로 적어둔다.
4. 앱이 읽는 키와 실행에 필요한 값마다 근거, 로컬 값 확정 여부, 사용자에게 확인할 항목을 남긴다. 이어받은 조사에서 이미 확인된 값은 기존 근거와 함께 유지한다.

## 3. 앱 간 의존성 완성

- 호출 코드와 선택한 프로필의 주소 설정을 함께 보면서 호출 앱 → 서비스 ID → 접속점으로 연결한다. 빌드 의존성이나 공유 라이브러리 참조는 별도로 기록한다.
- 시작·준비에 필요한 호출, 특정 요청이나 백그라운드 작업에서만 생기는 호출을 구분한다. 선택한 로컬 시나리오에 필요한 관계를 `dependencies`에 넣고, 대상 접속점을 읽는 키를 `injections`로 연결한다.
- Kafka 등 공통 인프라를 쓰는 앱은 먼저 브로커에 연결한다. 생산자·소비자 앱까지 함께 실행해야 하는지는 시나리오와 실행 근거로 판단한다.
- 실제 앱과 대역 각각의 하위 의존성을 기록한다. 예를 들어 `orders → catalog → postgres`에서 Catalog 대역이 DB를 사용하지 않으면, 대역을 선택한 프로필에서 Orders에 PostgreSQL을 추가하지 않아도 된다. 다른 경로에서 같은 DB를 요구하는지는 전체 그래프에서 확인한다.
- 의존성이 모호하거나 순환이 나타나면 경로와 근거를 남기고 필요한 결정을 요청한다. Injector가 그래프에서 실행 순서를 계산한다.

## 4. 첫 대상 등록과 완료 기준

조사만 요청받았다면 [등록 프로토콜](registration-protocol.ko.md)에 따라 Injector의 `registries/<레포-ID>/onboarding/`에 초안·근거·미확인 항목을 남긴다. 실행용 registry까지 요청받았다면 같은 레포의 저장 폴더에 `registry.json`과 앱·인프라별 노드 파일을 작성한다. [실행 등록 관리 가이드](runtime-registry-guide.ko.md)

대상 레포는 소스와 근거의 기준으로 사용한다. 아직 확인 중인 앱은 후보 목록에 남긴다. 사용자에게 질문할 항목은 앱·프로필·키·어떤 선택이 막혔는지 함께 적는다.

- 선택한 앱과 하위 의존성의 실행 조건, 접속점, 설정 출처를 근거로 설명할 수 있다.
- 프로젝트·프로필로 `validate`를 실행하고, 선택한 앱을 타깃으로 `plan`을 실행한다. 루트 프로필과 variant 선택, 시작 순서, 공유 자원 중복, 외부 주소가 남은 위치를 확인한다.
- 실행 등록을 막는 미확인 항목과 후속 앱을 기록한다. 완료 보고에는 무기동 검증 결과와 실제 IntelliJ Debug 확인 여부를 각각 적는다.
