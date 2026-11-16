# Injector POC

IntelliJ에서 JVM 애플리케이션을 디버깅하면서 VM 옵션·환경변수를 주입하고, 주변 API와 인프라를 로컬에서 준비하는 실험 프로젝트다.

**개발을 재개할 때는 [작업 인덱스](docs/index.md)부터 읽는다.** 각 T-ID 문서 하나에 설계 → 개발 → 검증과 재개 지점을 함께 기록한다. 인덱스에서 작업 순서와 단계별 상태를 확인하고 해당 작업 문서로 이동한다.

저장소 루트는 Injector 자체의 개발 공간이다. Java 데모 앱과 데모 전용 설정·Docker 구성은 `examples/demo/`에 별도 프로젝트로 보관한다.

```text
injector/
├── injector.py          # Injector CLI
├── tests/               # Injector 테스트
├── docs/                # 설계·검증 기록
└── examples/demo/       # Injector를 적용하는 데모 프로젝트
    ├── pom.xml
    ├── src/main/java/poc/
    ├── config/project.json
    ├── docker/
    └── .run/            # 생성된 IntelliJ 실행 구성 (Git 제외)
```

아래 CLI 명령은 저장소 루트에서 실행한다. 현재 POC의 기본 대상은 `examples/demo/`이며, IntelliJ에서는 데모 프로젝트를 별도로 연다.

## 준비

- JDK 17 이상 (`java`, `javac`를 PATH에 등록)
- Python 3.10 이상. `python -m pip install -r requirements.txt`로 등록 스키마 검증·테스트 의존성을 설치한다.
- Docker Desktop 또는 Docker Engine과 Compose
- IntelliJ IDEA. `examples/demo/pom.xml`을 Maven 프로젝트로 연다.

## IntelliJ에서 실행하기

프로젝트 루트에서 다음을 실행한다. 첫 실행에는 컨테이너 이미지를 내려받는다.

```powershell
python injector.py up --profile mock --infra postgres redis kafka
```

이 명령은 WireMock과 선택한 인프라가 준비될 때까지 기다리고, `examples/demo/.run/Injector-mock.run.xml`을 생성한다. 메인 앱은 실행하지 않는다.

1. IntelliJ에서 `examples/demo/pom.xml`을 별도 프로젝트로 열고 JDK 17 이상을 선택한다.
2. Maven 프로젝트 가져오기가 끝나면 `Injector-mock` 실행 구성을 선택한다.
3. 데모 프로젝트의 `src/main/java/poc/Main.java`에서 `body = ...` 줄에 브레이크포인트를 설정한다.
4. Debug로 실행한다.
5. `http://localhost:18080/demo`를 호출한다.

`injector.profile` 시스템 속성, `DEMO_MESSAGE` 환경변수, API 응답을 확인할 수 있다. 응답의 `downstream`은 하위 API가 반환한 JSON을 문자열로 담는다.

실제 샘플 API로 전환하려면 메인 앱 디버깅을 종료하고 다음 명령을 실행한 뒤, IntelliJ에서 `Injector-real` 구성을 Debug로 실행한다.

```powershell
python injector.py up --profile real --infra postgres redis kafka
```

`mock`은 WireMock에, `real`은 별도 Java 샘플 앱인 Catalog에 연결한다. 두 의존 앱은 서로 다른 포트를 쓰며, 구성 전환 시 이전 의존 앱을 자동 종료하지 않는다.

## IDE 없이 확인하기

```powershell
python injector.py run --profile mock
```

먼저 해당 구성의 `up`을 실행해야 한다. 이 명령은 Java 소스를 컴파일하고 메인 앱을 포그라운드에서 실행한다. 종료는 Ctrl+C다.

메인 앱도 Docker에서 실행할 수 있다. IntelliJ 또는 CLI에서 실행 중인 메인 앱은 먼저 종료한다.

```powershell
python injector.py up --profile mock --main-docker
```

## 설정과 명령

설정 파일은 `examples/demo/config/project.json`이다. 공통 환경변수에 프로필별 값을 덮어쓰고, VM 옵션은 공통 옵션 뒤에 프로필 옵션을 붙인다. 복잡한 충돌 해결·비밀값 저장 기능은 아직 없다.

```powershell
python injector.py plan --profile real --infra redis
python injector.py generate --profile real
python injector.py down
python -m unittest discover -s tests -v
```

`plan`은 값 대신 환경변수 키를 출력한다. `generate`는 컨테이너 기동 없이 IntelliJ 실행 구성과 Docker용 설정을 생성한다. 생성 파일에는 설정값이 포함되므로 데모 프로젝트의 `.run/Injector-*.run.xml`과 `.local/`은 Git에서 제외한다. 저장소에 들어 있는 DB 비밀번호는 로컬 데모용 고정값이며 실제 자격증명을 넣어 커밋하면 안 된다.

`down`은 `injector-poc` Compose 프로젝트의 컨테이너와 네트워크를 제거한다. 볼륨은 삭제하지 않지만 현재는 이미지의 익명 볼륨을 사용하므로, 이후 `up`에서 데이터 재연결을 보장하지 않는다. 데이터 보존·초기화 정책은 후속 설계 대상이다.

## 포트

| 대상 | 호스트 주소 |
|---|---|
| 메인 앱 | `localhost:18080/demo` |
| WireMock | `localhost:18081` |
| 실제 Catalog | `localhost:18082` |
| PostgreSQL | `localhost:15432`, DB·사용자 `demo` |
| Redis | `localhost:16379` |
| Kafka | `localhost:19092` |

컨테이너에서 다른 컨테이너를 호출할 때는 Compose 서비스 이름과 내부 포트를 사용한다. 포트 공개 범위는 로컬 루프백으로 제한했다. 외부 통신 자체를 차단하는 기능은 없다.

## 현재 검증 상태와 제한

- 설정 합성과 생성 파일의 한글·XML 특수문자·공백 포함 옵션을 검사하는 테스트 2개 통과
- JDK 25에서 Java 17 대상으로 컴파일 통과
- WireMock 매핑 응답 확인
- PostgreSQL 쿼리, Redis PING, Kafka 토픽 생성 확인
- IntelliJ IDEA 2025.3.3 / JDK 21에서 `mock`·`real` 모두 Debug 실행, 브레이크포인트 중단·재개 확인
- IntelliJ 메인 앱 → WireMock / 실제 Catalog 호출 및 VM 옵션·환경변수 주입 확인
- Docker 메인 앱에서도 `mock`·`real` 모두 내부 서비스 주소로 호출 성공

구체적인 검증 절차와 결과는 [POC 검증 기록](docs/validation-history.md)에 있다.

현재 샘플 앱은 인프라 접속값을 전달받지만 DB·Kafka·Redis를 직접 사용하지 않는다. 해당 인프라는 기동과 기본 동작만 검증했다. 일반 등록의 실제 기동, 세션별 격리, 자동 정리·복구 기능은 아직 없다. 실행 가능한 기존 데모는 구성과 포트가 고정되어 있으므로 동시에 하나의 POC 환경을 사용한다.

작업별 설계·구현·완료 기준·검증 결과는 [작업 인덱스](docs/index.md)에서 확인한다. [공통 설계](docs/design.md)와 [전체 현황](docs/status.md)은 여러 작업에 걸친 배경 자료다. 이번 POC의 Python·JSON·Compose·실행 구성 생성 방식은 검증용 선택이며, 제품의 최종 기술 스택을 확정하지 않는다.

## 실행용 앱 등록 검증

버전 `1.0`의 실행용 등록을 프로젝트 루트의 `registry.json`에 두고 검증할 수 있다.

```powershell
python injector.py validate --project examples/registry
python injector.py validate --project examples/registry --profile local-real
```

프로필을 생략하면 모든 프로필을 검사한다. `--project`는 상대·절대 디렉터리 경로를 받는다. 검증은 구조·노드·의존성·선택 모드·접속점 참조를 확인하고, 프로세스 기동이나 설정 파일 생성을 하지 않는다. 비밀값 참조도 이 단계에서 실제 값으로 읽지 않는다.

접속 정보와 설정을 합성하고 값이 가려진 출처를 확인하려면 다음을 실행한다.

```powershell
python injector.py resolve --project examples/registry --profile local-real --node catalog
```

`resolve`는 `fromEnv` 참조를 실제 프로세스 환경에서 읽으므로 필요한 환경변수가 있어야 한다. 출력에서는 모든 설정값을 가리고 키와 출처만 보여준다. 주소 해석·설정 합성은 [T-030](docs/work-items/T-030.md)에 기록하며, 앱 실행에 연결하는 작업은 후속 단계다.

선택된 프로필의 전이적 의존성과 DFS 후위 순서를 확인할 수 있다.

```powershell
python injector.py plan --project examples/registry --profile local-real
python injector.py plan --project examples/registry --profile local-mock
```

이 계획 조회에는 환경변수의 실제 비밀값이 필요하지 않다. 공통 의존성은 한 번만 포함하고 순환은 경로와 함께 오류로 보고한다. 설정값 해석은 별도의 `resolve`, 실제 기동은 후속 작업이다. `--project` 없이 실행하는 기존 데모 plan 요약도 유지한다.

[등록 예시](examples/registry/README.md)는 모델 설명용이며 실행 앱을 제공하지 않는다. 실제 실행은 기존 `examples/demo/` POC 명령으로 확인한다. 등록 스키마는 [T-010](docs/work-items/T-010.md), 로딩·검증은 [T-020](docs/work-items/T-020.md), DFS 계획은 [T-040](docs/work-items/T-040.md)에서 관리한다.

## LLM으로 모노레포 등록 준비

[등록 스킬](skills/injector-register-monorepo/SKILL.md)과 [등록 프로토콜](skills/injector-register-monorepo/references/registration-protocol.md)을 준비했다. 스킬 기능이 없는 LLM에도 이 문서를 제공해 사용할 수 있다.

예시 요청:

```text
skills/injector-register-monorepo/SKILL.md를 읽고,
<모노레포 경로>의 <대상 앱>을 local 프로필로 조사해 줘.
앱별 접속 정보와 전이적 의존성, 설정 주입 위치를 근거와 함께 정리하고,
등록 JSON 초안과 미확인 사항 보고서를 만들어 줘.
```

기본 산출물은 조사 대상 모노레포의 `injector-onboarding/registration-draft.json`과 `findings.md`다. 기존 앱 실행, hosts/DNS 변경, 실제 등록 적용까지 수행하는 작업은 아니다. 초안 JSON은 현재 CLI가 읽는 `project.json`과 별도 형식이며 자동 실행되지 않는다.

## 작업 저장

검증을 마친 작업 단위마다 의미 있는 커밋을 만들고 `https://github.com/chochanyeon/injector`에 푸시한다. 미검증 항목은 검증 완료 항목과 구분해 기록한다.

## 참고

- [WireMock Docker 실행](https://wiremock.org/docs/standalone/docker/)
- [IntelliJ Application 실행 구성](https://www.jetbrains.com/help/idea/run-debug-configuration-java-application.html)
