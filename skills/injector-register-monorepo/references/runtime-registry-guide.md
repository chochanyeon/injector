# AI를 위한 실행용 registry 관리 가이드

이 가이드는 레포를 탐색해 검토된 실행 등록을 작성·수정할 때 사용한다. 최초 조사 결과에 미확인 값이 많으면 먼저 등록 프로토콜의 초안·findings를 작성한다. 사용자가 등록 파일 관리를 요청한 범위에서는 파일 수정과 무기동 검증을 수행하고, 조사만 요청한 경우 실행 설정 적용으로 범위를 확대하지 않는다.

## 1. 실제 계약 확인

작업 대상 레포와 Injector 소스 레포를 구분한다. Injector 위치를 현재 작업 문맥에서 확인하고 다음을 필요한 부분만 읽는다. 위치를 알 수 없으면 실행 형식을 추정하지 말고 확인한다.

- `docs/index.md`에서 현재 완료한 기능과 관련 T-ID.
- `schemas/registry-v1.schema.json`: v1.0 기본 실행 계약.
- `schemas/registry-v1.1.schema.json`: springProperties·springProperty 주입을 추가한 계약.
- `examples/registry/registry.json`, `examples/spring-config/registry.json`: 실제 검증 예시.
- `injector_core/registry.py`, `resolution.py`, `rendering.py`: 계약만으로 불명확한 해석·제한 사항.

루트 `registry.json`의 `nodeFiles`에 프로젝트 상대경로를 나열하면 노드마다 실행·주입 설정을 한 파일에서 관리할 수 있다. 새 모노레포 등록은 Injector 저장소의 `examples/demo/registry.json`을 참고한다. 각 파일은 `id`, `kind`, `variants`를 가진 노드 한 개다. 기존 `nodes` 인라인 등록은 유지하거나 순차적으로 옮긴다. 두 곳에 같은 ID를 정의하지 않는다.

대상과 variant 선택은 루트 `profiles`에서 유지한다. 앱의 설정은 그 앱의 variant와 `profileOverrides.<프로필>`에 둔다. 기존 루트 `profiles.<프로필>.overrides.<노드>`는 마지막에 적용되므로 이전할 때 최종 값과 VM 옵션 순서를 확인한다. 파일 참조와 작업·IDE·Compose 경로의 기준은 프로젝트 루트다.

v1.0에서 지원하지 않는 Spring 필드를 쓸 때만 검토 후 v1.1로 올린다. 기존 ID·profile·사용자 확정값을 유지하고 변경 이유를 남긴다. 노드에 evidence 같은 미지원 속성을 붙이지 말고 근거는 `injector-onboarding/findings.md`에 기록한다.

IntelliJ의 projectPath는 .run을 읽는 IDE 프로젝트 루트이며 서비스 소스 폴더와 같다고 단정하지 않는다. 모노레포 전체를 하나의 프로젝트로 열면 보통 projectPath는 루트이고 module이 서비스를 구분한다. 서비스를 별도 프로젝트로 여는 흐름이면 그 프로젝트 경로를 지정한다. 실제 IDE 실행 방식을 확인해 XML이 잘못된 하위 폴더에 생성되지 않게 한다.

## 2. 앱의 읽는 방식부터 추적

`rg --files`로 모듈·설정·실행 정의를 찾고 다음 단서를 좁혀 조사한다. 키 이름만 보고 채널을 정하지 않는다.

| 근거 | 등록할 위치 |
|---|---|
| JVM의 -Xmx, -XX, -javaagent 등 | vmOptions 인자 배열 |
| System.getProperty 또는 그 값을 읽는 wrapper | vmProperties의 이름 있는 키. raw -D 문자열은 쓰지 않음 |
| System.getenv 또는 필수 환경변수 계약 | env |
| Spring Environment, @Value, @ConfigurationProperties | v1.1 springProperties 또는 기존 placeholder에 필요한 env |
| YAML 파일을 직접 열어 자체 파싱 | Spring 외부 설정으로 덮어쓸 수 있다고 단정하지 않음. 별도 입력 경로 확인 |
| Vault API 클라이언트 | 요청 경로·응답 키 조사 후 서비스 ID별 대역. 실제 비밀값 조회와 구분 |

먼저 빌드 정의에서 Spring Boot 버전을 확인한다. `application.yml`, `application-{profile}.yml`, multi-document YAML, `spring.config.activate.on-profile`, active/include/group, import/location/additional-location, bootstrap 설정을 따라간다. Gradle/Maven의 profile과 Spring active profile을 혼동하지 않는다.

기존 .run XML·실행 스크립트의 -D, env, 프로그램 인자도 확인한다. 명령행 인자, SPRING_APPLICATION_JSON, JAVA_TOOL_OPTIONS, 코드의 setProperty/custom PropertySource가 기존 값에 영향을 주는지 기록한다. 설정 파일 하나를 읽었다는 이유로 최종값이 확인되었다고 보고하지 않는다.

검색 단서 예: `System.getProperty`, `System.getenv`, `@ConfigurationProperties`, `@Value`, `Environment`, `spring.config`, `spring.profiles`, `${...}`. 래퍼 호출·공통 라이브러리도 필요한 범위까지 추적한다.

## 3. Spring 설정 배치

예시 부분 구조이며 전체 등록 형식은 실제 스키마를 따른다.

```json
{
  "vmOptions": ["-Xmx512m"],
  "vmProperties": {
    "spring.profiles.active": "local",
    "company.runtime.mode": "local"
  },
  "springProperties": {
    "server.port": 18090,
    "clients.payment.timeout": 3000,
    "app.labels": ["local", "isolated"],
    "app.password": {"fromEnv": "LOCAL_APP_PASSWORD"}
  }
}
```

적용 규칙:

- springProperties의 최상위 키는 Spring property 이름이다. 숫자·boolean·리스트·맵은 JSON 타입을 유지한다. 필요한 leaf별 override를 하려면 dotted key로 나눈다.
- Injector는 defaults → 선택 variant → profile override 순서로 같은 최상위 키를 교체한다. 리스트·맵을 임의로 deep merge하지 않는다. 생성 YAML을 원래 설정과 합치는 단계의 Spring 바인딩 규칙은 해당 버전에서 따로 확인한다.
- env·vmProperties가 같은 Spring 키를 덮지 않는지 확인한다. 도구는 정확한 VM 키와 기본 env 이름 변환의 충돌을 검사하지만, 모든 relaxed binding 별칭·상속 환경·프로그램 인자를 분석하는 것은 아니다.
- System.getProperty 전용 값은 Spring YAML로 옮기지 않는다. YAML 값은 JVM 시스템 속성으로 자동 등록되지 않는다.
- 의존 주소는 literal로 복사하기보다 injections의 springProperty 채널과 node/endpoint/context/component 참조를 사용한다. 이 채널은 v1.1부터 지원한다.
- 원본 application YAML은 수정하지 않는다. render가 별도 YAML을 만들고 VM 속성 spring.config.additional-location으로 그 경로를 연결한다. 기존 additional-location과 충돌하면 임의 제거·교체하지 말고 기존 로딩 목적을 조사한다.
- bootstrap용 spring.config.*와 active/default/include profile 선택은 vmProperties 또는 env에 둔다. 생성 YAML 안에 넣어 읽기 순서를 바꿀 수 있다고 가정하지 않는다.
- 비밀값은 fromEnv 참조로 남긴다. Spring YAML은 ${ENV_NAME} placeholder를 생성한다. 실제 값은 앱 실행 환경에서 제공한다. 등록·진단·커밋에 실제 자격증명을 넣지 않는다.

현재 render는 IntelliJ 타입에만 제공된다. Compose 컨테이너의 YAML 마운트·경로 변환은 아직 없다. env/vmProperties의 fromEnv 실제 값을 XML에 영구 저장하는 경로도 거부한다. 이 경우 준비되지 않은 기능을 스키마 수정으로 우회하지 말고 런타임 주입의 미구현 범위를 기록한다.

실제 준비는 `prepare <app-id> --project <repo> --profile <profile>`가 담당하며 등록 스킬 자체는 실행하지 않는다. 클릭 화면은 Injector 루트의 Start-Injector.vbs 또는 `serve --open`으로 연다. process·Compose·external 의존성을 DFS 순서로 준비하고 IntelliJ 대상은 Debug용 구성을 만든다. IntelliJ 타입을 하위 의존성으로 등록하면 자동 실행되지 않으므로 process/Compose variant를 조사한다. Compose에는 env만 합성하며 VM 설정은 Compose 서비스의 명령에서 정의한다. Spring YAML은 IntelliJ 대상만 지원한다. process에 vmOptions/vmProperties가 있으면 실행 파일은 java여야 한다. 기존 프로세스·컨테이너를 포트만 보고 재사용하지 않으므로 전용 Compose projectName과 충돌 없는 호스트 포트를 확인한다. `--mode dummy/real`은 프로필 별칭이며 노드를 임의로 대역으로 바꾸지 않는다.

## 4. 근거와 갱신 순서

1. 앱 ID·프로필·선택 variant를 정하고 현재 등록의 사용자 확정값을 읽는다.
2. 각 값의 파일:줄, 읽는 코드, 적용 profile, 로컬 변경 목적, 채널을 findings 표에 남긴다. 비밀값 자체는 기록하지 않는다.
3. 앱·인프라 노드와 접속점을 등록하고 의존성은 ID로 연결한다. 공통 DB·브로커를 서비스마다 복제하지 않는다.
4. 로컬 값이 확인된 항목만 등록한다. 미확인 값은 findings의 질문으로 남긴다. 실행용 스키마의 필수값을 null·가짜 포트·임의 mainClass로 채우지 않는다.
5. 변경한 서비스·프로필의 diff를 확인하고 기존 설정을 잃지 않았는지 검증한다. 여러 앱을 갱신하면 영향받는 공유 의존성도 확인한다.

## 5. 검증 명령과 완료 보고

아래 명령의 Injector 경로와 target 경로는 실제 위치로 바꾼다. validate/plan은 무기동이며, resolve는 환경 참조를 읽고 redacted 출처를 출력한다. render는 생성 파일을 쓰지만 앱은 실행하지 않는다.

```text
python <Injector>/injector.py validate --project <target>
python <Injector>/injector.py plan --project <target> --profile <profile>
python <Injector>/injector.py resolve --project <target> --profile <profile> --node <node>
python <Injector>/injector.py render --project <target> --profile <profile> --node <node>
```

render는 `<target>/.local/injector/<profile>/<node>/spring-overrides.yml`과 앱 projectPath의 `.run/Injector-<profile>-<node>.run.xml`을 만든다. 대상 레포에서도 해당 생성 경로가 Git에서 제외되는지 확인한다. 생성물은 재생성 시 덮어쓰며 원본 입력으로 역사용하지 않는다.

완료 보고에는 변경한 앱·프로필, 실제 수행한 검증, 미확인 값, 지원하지 않는 읽기 방식, 실제 앱 실행 여부를 구분한다. validate·plan 성공을 실제 앱 기동 성공으로 보고하지 않는다. 회사 레포가 제공되지 않았으면 가상의 근거 경로를 실제 조사 사실로 제시하지 않는다.
