# Injector POC

[English](README.md) · **한국어**

Injector는 IntelliJ에서 JVM 앱을 디버깅할 때 VM 옵션·환경변수를 주입하고, 주변 API와 인프라를 로컬에서 준비한다. Verifier는 로컬 관측 결과를 비교하고 Gradle 기반 Spring 업그레이드 검증도 수행한다. [Verifier 가이드](verifier/README.ko.md)

**개발을 재개할 때는 [작업 인덱스](docs/index.ko.md)부터 읽는다.** 각 T-ID 문서 하나에 설계 → 개발 → 검증과 재개 지점을 함께 기록한다. 인덱스에서 작업 순서와 단계별 상태를 확인하고 해당 작업 문서로 이동한다.

저장소 루트는 Injector 자체의 개발 공간이다. `examples/demo/`에 Java와 Docker 예제를 보관한다. HTTP 관측 데모에서 의존성 호출을 기록하고 같은 시나리오를 두 워크트리에서 비교할 수 있다. [HTTP 관측 데모](examples/demo/http-observation/README.ko.md)

쇼핑몰 모노레포 데모는 JVM 서비스 여섯 개, 공유 PostgreSQL·Redis, Kafka 배송 이벤트, WireMock 가격·Vault KV v2 대역을 실행한다. 주문 시나리오로 두 워크트리의 HTTP 호출과 Kafka 이벤트를 함께 비교할 수 있다. [쇼핑몰 모노레포 데모](examples/demo/monorepo/README.ko.md)

```text
injector/
├── injector.py          # Injector CLI
├── verifier/            # Gradle 업그레이드 검사와 관측 비교
├── schemas/             # Registry와 HTTP 관측 스키마
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
- Python 3.10 이상
- Docker Desktop과 Compose. 실행 환경을 준비하기 전에 Docker Desktop을 켠다.
- IntelliJ IDEA. `examples/demo/pom.xml`을 Maven 프로젝트로 연다.

macOS에서 저장소 루트의 가상 환경에 의존성을 설치한다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Windows PowerShell에서는 아래 명령을 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 클릭으로 실행 환경 준비하기

- **macOS**에서 Finder로 루트의 **`Start-Injector.command`**를 더블클릭한다. Terminal이 서버를 실행하고 기본 브라우저에서 화면을 연다.
- **Windows**에서 루트의 **`Start-Injector.vbs`**를 더블클릭한다. 기본 브라우저에서 화면을 연다.

두 OS 모두 `http://127.0.0.1:18770`을 사용하고 이미 실행 중이면 같은 서버를 연다. 화면을 사용하는 동안 macOS의 서버 Terminal 창을 열어 둔다. ZIP으로 받아 실행 권한이 빠졌다면 macOS에서 `chmod +x Start-Injector.command`를 한 번 실행한다.

1. **프로젝트 폴더**에서 소스 또는 워크트리를 선택한다. **Registry 파일** 옆의 **파일 선택**에서는 Injector 스키마에 맞는 JSON 파일을 고른다. 파일명과 확장자는 자유다. 경로를 직접 입력했다면 **불러오기**를 누른다. 폴더 경로를 지정하면 그 안의 `registry.json`을 읽는다. 입력란을 비우면 소스 폴더의 `registry.json`을 읽는다.
2. 프로필(`dummy` 또는 `real`)과 `platform-service`를 선택한다.
3. 실행 순서를 확인하고 **실행 환경 준비**를 누른다. Catalog보다 Redis가 먼저 준비되고, `real`에서는 PostgreSQL도 Catalog 전에 준비된다.
4. 준비 완료 후 IntelliJ에서 `examples/demo/pom.xml`을 열고 **`Injector-dummy-platform-service`** 또는 **`Injector-real-platform-service`**를 Debug로 실행한다. 앱 응답은 `http://127.0.0.1:19080/demo`에서 확인한다.
5. 앱은 IDE에서 종료한다. 화면의 **의존성 종료**로 Injector가 만든 프로세스·컨테이너를 종료한다. 브라우저를 닫는 것만으로 의존성이나 화면 서버가 종료되지는 않는다.

마지막으로 불러오기에 성공한 프로젝트 폴더와 Registry 파일을 다음 실행 때 자동으로 선택하고 불러온다. 새 서버를 시작하면서 `serve --project`를 지정하면 해당 경로를 우선한다. 두 경로만 Injector의 Git 제외 파일 `.local/web-selection.json`에 저장한다.

프로필을 전환하기 전에는 IDE에서 실행 중인 앱을 종료한다. 다시 준비하면 해당 프로젝트의 이전 Injector 세션 자원을 종료하고 새 설정으로 준비한다. 다른 프로그램의 열린 포트나 이미 존재하는 Compose 서비스는 충돌로 처리한다. 컨테이너 볼륨과 Compose 네트워크는 보존한다.

준비하기 전에 **실행 조건 확인**을 누르면 선택한 앱, 프로필, variant와 관련 의존성을 검사한다. 등록된 설정이나 실행 정의에서 발견한 첫 번째 문제를 표시한다. 검사 중 서비스 상태와 생성 파일은 그대로 유지된다. 호스트 이름 해석, 포트 충돌, 서비스 응답 여부는 실행 환경 준비 단계에서 확인한다.

`python injector.py check platform-service --project examples/demo --profile dummy`로 같은 검사를 CLI에서 실행할 수 있다. 공유 레지스트리는 `--registry`로 지정하고, 노드 실행 방식을 바꿔 검사하려면 `--variant NODE=VARIANT`를 쓴다. 성공하면 실행 순서와 IntelliJ 확인 정보를 JSON으로 출력한다. 검사에 실패하면 첫 원인을 표시하고 종료 코드 1을 반환한다.

Compose의 필수 `depends_on` 서비스는 이를 사용하는 노드의 Registry 의존성 그래프에 등록한다. 등록된 호스트 엔드포인트는 Compose의 고정 공개 포트와 전송 프로토콜을 대조한다. 호스트 네트워크를 쓰는 경우 호스트 포트는 바인드 포트와 일치해야 한다. Compose 검사와 실행에 모두 노드의 해석된 환경을 전달한다. IntelliJ 대상은 IDE에서 확인할 모듈과 메인 클래스가 검사 결과에 표시된다.

소스 폴더의 기본 `registry.json`을 직접 선택하거나 Registry 입력란을 비워도 같은 실행 세션을 사용한다. 관리 프로세스가 준비 전에 종료되면 오류에 해당 노드와 로컬 진단 파일의 경로가 표시된다. 진단 파일은 프로세스 출력의 마지막 64 KiB를 보관하며 애플리케이션 데이터를 포함할 수 있다. 브라우저와 CLI는 진단 파일의 경로를 표시한다.

Compose 파일이 하위 폴더에 있으면, 그 폴더에 `.env`가 없고 환경에서 기본 파일을 재지정하거나 비활성화하지 않았을 때 소스 루트의 `.env`를 사용한다. [Docker Compose 변수 치환](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)

`support-console`도 선택할 수 있다. 같은 Java 메인 클래스를 쓰며 `Injector-<프로필>-support-console`을 Debug로 실행하면 `http://127.0.0.1:19084/demo`에서 응답한다. 두 데모 앱은 Catalog를 실제 호출한다. Redis, PostgreSQL, Vault 대역은 환경 준비와 의존성 그래프를 확인하기 위해 함께 등록했다.

같은 작업을 CLI로도 실행한다. 아래 명령의 `python`은 설치한 환경의 Python을 뜻한다. 가상 환경을 활성화하지 않았다면 macOS는 `.venv/bin/python`, Windows는 `.\.venv\Scripts\python.exe`를 사용한다. `--project`를 생략하면 현재 폴더에서 registry.json을 찾는다.

```powershell
python injector.py prepare platform-service --project examples/demo --mode dummy
python injector.py prepare platform-service --project examples/demo --mode real
python injector.py plan platform-service --project examples/demo --profile dummy --variant catalog=real
python injector.py prepare platform-service --project examples/demo --profile dummy --variant catalog=real
python injector.py stop --project examples/demo
python injector.py serve --open
```

**노드별 실행 방식**에서 프로필의 variant를 바꾸면 실행 순서와 의존성 그래프가 갱신된다. CLI에서는 `--variant NODE=VARIANT`를 노드마다 한 번씩 지정한다. 선택은 해당 요청에만 적용하고 `registry.json`에 저장하지 않는다. 다른 variant로 새 의존성이 생기면 그 의존성도 프로필의 `selections`에 등록해야 한다. IntelliJ 실행 구성은 같은 프로필·앱 이름으로 다시 생성한다.

업무 프로젝트는 `--profile local-dev`처럼 등록된 프로필을 명시할 수도 있다. `--mode dummy`는 `dummy/local-mock/mock`, `real`은 `real/local-real` 중 **하나만 존재할 때** 해당 프로필을 선택한다. 프로필의 variant 선택이 실제 앱·대역·하위 의존성을 결정한다. 여러 별칭이 있으면 `--profile`을 사용한다.

현재 일반 실행 경로는 process·Compose·external 의존성, IntelliJ·process·Compose 대상을 지원한다. process의 VM 설정은 `java` 실행 파일에만 주입한다. Spring 외부 YAML 생성은 IntelliJ 대상에 한정한다. Compose는 env 주입을 지원하며 VM 설정은 서비스 자체 JVM 명령으로 정의해야 한다. IntelliJ 의존성은 자동 실행할 수 없으므로 process/Compose variant가 필요하다. 실제 비밀값을 env/vmProperties에서 XML로 저장하는 경로는 거부한다.

## 화면에서 registry.json 확인·수정하기

1. 프로젝트 폴더와 Registry 파일을 지정하고 **Registry 편집**을 누르면 모달이 열린다. 문법 오류가 있는 기존 파일도 열 수 있다. 모달의 **폴더 변경**으로 다른 워크트리의 파일을 열 수 있다.
   `nodeFiles`를 쓴 프로젝트에서는 **설정 파일** 목록에서 루트나 앱 파일을 선택한다. 새 앱 파일은 registry 폴더에 만든 뒤 루트의 `nodeFiles`에 경로를 추가한다.
2. **검증**을 누르면 JSON 문법, 스키마, 앱·의존성 참조, 각 프로필의 실행 계획에 있는 순환을 확인한다. 문법 오류에는 줄·열이 표시된다.
3. **저장**을 누르면 다시 검증하고, 통과한 경우에만 파일을 쓴다. 저장 후 앱·프로필 목록이 갱신된다.

**접기**는 화면을 가리지 않고 초안을 유지한다. 같은 프로젝트의 **Registry 편집**을 다시 누르면 이어서 편집한다. **닫기**나 `Esc`를 쓰면 저장하지 않은 변경을 버릴지 확인한다.

파일·폴더 선택 창은 Injector 서버가 실행 중인 Windows 또는 macOS 데스크톱에서 열린다. 원격 미리보기에서 그 데스크톱에 접근할 수 없으면 경로를 직접 입력한다.

열어 둔 파일을 다른 편집기에서 수정하면 저장이 거부된다. **파일 다시 읽기**로 최신 내용을 확인할 수 있다. 새 서버 API를 사용하려면 이전에 열어 둔 Injector 서버를 종료한 뒤 다시 실행한다.

## 의존성 그래프 보기

**의존성 그래프**는 현재 프로필에 포함된 앱과 이들이 사용하는 인프라를 표시한다. 화살표는 앱이나 인프라에서 직접 의존하는 노드로 향한다. 여러 앱에서 공유하는 의존성은 한 번만 나타난다.

그래프는 선택한 앱을 기준으로 열린다. **표시 범위**에서 다른 앱이나 전체 앱을 고를 수 있다. 노드를 누르면 연결선이 강조되고, 아래에서 의존 대상과 사용하는 노드를 확인할 수 있다. **직접 의존성 목록**에서는 모든 연결을 텍스트로 볼 수 있다.

상단 메뉴로 실행, 의존성, 검증 사이를 이동한다. 준비 상태와 진행률, 실행 순서는 한곳에 표시된다. **진행 기록**을 펼치면 개별 이벤트를 확인할 수 있다.

기본 데모에서 **전체 앱**을 고르면 `platform-service`와 `support-console`이 Catalog를 공유하고 두 앱에서 Vault 대역으로도 연결되는 구조를 볼 수 있다. Redis는 `platform-service`와 Catalog에서 연결된다. `dummy`는 5개 노드이며 `real`은 Catalog 아래 PostgreSQL을 추가한 6개 노드다.

## 웹에서 워크트리 검증하기

상단의 **검증**을 열면 현재 프로젝트가 기준 워크트리로 표시된다. 후보 워크트리와 스위트 JSON을 지정한다. **사전 점검**은 실행 조건에 문제가 있는 워크트리, 시나리오 또는 노드를 표시한다. **스위트 실행**은 CLI와 같은 Verifier 로직을 사용하고 항목별 판정을 표시한다. 서버는 `.local/verification/`에 증거를 저장하며, 화면에서 보고서 경로를 복사할 수 있다.

같은 서버에서 같은 프로젝트로 페이지를 새로고침하면 최근 스위트 입력과 결과를 다시 볼 수 있다. **HTTP·Kafka 관측 비교**에서 기존 관측 JSON 파일 두 개를 비교할 수 있다. [Verifier 스위트 형식](verifier/README.ko.md#스위트-실행)

## 로컬 호스트 이름 사용하기

registry의 접속점 `addresses.host.host`에 `catalog.local.test.com` 같은 이름을 사용하고, 같은 이름을 `nameMappings`에 등록한다.

```json
{"hostname": "catalog.local.test.com", "address": "127.0.0.1", "method": "hosts"}
```

```sh
.venv/bin/python injector.py hosts preview --project examples/registry
sudo .venv/bin/python injector.py hosts apply --project examples/registry
sudo .venv/bin/python injector.py hosts remove --project examples/registry
```

Windows에서는 `.\.venv\Scripts\python.exe`로 같은 하위 명령을 사용한다. `apply`와 `remove`는 관리자 PowerShell에서 실행한다. macOS에서는 `sudo`로 두 명령을 실행한다. 미리보기는 일반 권한에서 사용할 수 있다.

`examples/registry`는 선언 형식 예시다. 실제로 실행할 프로젝트의 경로를 사용한다. 같은 주소의 수동 항목을 보존하고 충돌을 알린다. `remove`는 해당 프로젝트가 추가한 행만 지운다. 프로젝트를 옮기기 전에는 기존 경로로 `remove`를 실행한다.

이미 OS에서 이름을 해석한다면 `method: external`을 쓴다. CLI와 화면의 prepare는 선택한 그래프의 등록 이름이 기대 IP로만 해석되는지 확인한다. OS hosts 변경은 위 apply/remove 명령으로 관리한다. Compose 내부 이름은 서비스 이름이나 Compose의 `extra_hosts`로 관리한다.

## 기존 단일 데모 명령으로 실행하기

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

## 전체 테스트 환경 실행

Docker Desktop을 Linux 컨테이너 모드로 시작한다. Python 3.10 이상, JDK 17 이상, `node --test`를 지원하는 Node.js, Git이 필요하다. Windows에는 Git Bash가 포함된 Git for Windows를 사용하고, macOS에서는 `bash`를 사용할 수 있어야 한다. 저장소 루트에서 다음 명령을 실행한다.

```text
python verifier/verify_environment.py
```

명령은 새 Python 환경을 만들고 Spring Boot와 쇼핑몰 서비스를 빌드한다. 격리된 WireMock Vault를 기동하고 모든 Python 통합 테스트를 활성화한다. 웹 JavaScript 테스트, JVM 기준 기록과 비교, Git 워크트리 통합 검사도 실행한다. 쇼핑몰 통합 검사는 PostgreSQL, Redis, Kafka, WireMock, Loki를 사용해 실제 수정·회귀 스위트를 실행한다. `PATH`에 Maven이 없으면 배포본의 체크섬을 검증해 실행 폴더에 내려받는다. Gradle은 저장소의 Wrapper를 사용한다.

명령은 JSON으로 결과를 출력하고 `.local/full-tests-*`의 `report.json`에도 기록한다. 단계마다 로그를 남긴다. `shop-suite` 폴더에는 워크트리 증거와 Markdown 요약이 있다. 다른 새 폴더를 사용하려면 `--output`을 지정한다. 모든 단계가 통과하고 Python 테스트를 하나도 건너뛰지 않아야 `PASS`다. 테스트가 끝나면 실행에 사용한 컨테이너를 정리한다. [전체 검증 설계](docs/work-items/T-390.ko.md)

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

구체적인 검증 절차와 결과는 [POC 검증 기록](docs/validation-history.ko.md)에 있다.

기존 샘플 앱은 인프라 접속값을 전달받지만 DB·Kafka·Redis를 직접 사용하지 않는다. 해당 인프라는 기동과 기본 동작만 검증했다. 기존 데모의 구성과 포트는 고정되어 있으므로 한 번에 하나의 POC 환경을 사용한다. 일반 등록의 준비·세션 관리와 그 제한은 [작업 인덱스](docs/index.ko.md)와 [전체 현황](docs/status.ko.md)을 참고한다.

작업별 설계·구현·완료 기준·검증 결과는 [작업 인덱스](docs/index.ko.md)에서 확인한다. [공통 설계](docs/design.ko.md)와 [전체 현황](docs/status.ko.md)은 여러 작업에 걸친 배경 자료다. 이번 POC의 Python·JSON·Compose·실행 구성 생성 방식은 검증용 선택이며, 제품의 최종 기술 스택을 확정하지 않는다.

## Vault API를 로컬 값으로 대체

```powershell
python injector.py up --profile mock --vault-service orders
python injector.py vault-demo --vault-service orders
python injector.py vault-demo --vault-service payments
```

별도 WireMock 컨테이너가 Vault KV v2 조회 API로 로컬 값을 반환한다. 실제 Vault 서버·회사 인증 연동은 사용하지 않는다. 설정 소비 데모 앱은 응답의 값을 읽어 메시지와 기능 플래그를 사용한다.

하나의 주소·포트를 공유하고 `/v1/secret/data/orders`, `/v1/secret/data/payments`처럼 서비스 이름으로 경로를 나눈다. 같은 키도 [Orders 데이터](examples/demo/docker/vault-mock/__files/orders.json)와 [Payments 데이터](examples/demo/docker/vault-mock/__files/payments.json)의 `data.data`에 서로 다른 값으로 둔다. --vault-service는 대역 사용을 활성화하며, 생략한 --with-vault의 기본 서비스는 orders다.

앱별 경로·키·값 설정은 [Vault 대역 가이드](examples/demo/docker/vault-mock/README.ko.md), 설계·개발·검증은 [T-131](docs/work-items/T-131.ko.md)에 있다. 기존 Java 앱에는 Vault 주소 등이 주입되지만, API 소비 검증은 별도 Python 앱이 담당한다.

## 실행용 앱 등록 검증

실제 프로젝트 설정은 Injector의 `registries/<레포-ID>/registry.json`에 모아 관리한다. 앱별 설정은 같은 폴더의 `nodes/`에 둔다. `registries/`는 Git에서 제외된다. 같은 레포의 다른 워크트리로 바꿀 때는 프로젝트 폴더만 바꾼다.

```text
python injector.py validate --project "<워크트리 경로>" --registry registries/my-monorepo
python injector.py plan platform-service --project "<워크트리 경로>" --registry registries/my-monorepo --profile local
python injector.py check platform-service --project "<워크트리 경로>" --registry registries/my-monorepo --profile local
python injector.py prepare platform-service --project "<워크트리 경로>" --registry registries/my-monorepo --profile local
python injector.py stop --project "<워크트리 경로>" --registry registries/my-monorepo
```

CLI에서도 `--registry registries/my-monorepo/local-dev.json`처럼 파일을 직접 지정할 수 있다. 외부 Registry를 쓰면 Injector가 생성하는 Spring YAML, IntelliJ 실행 XML, Compose override와 세션 파일은 Registry 폴더의 `.local/injector/` 아래에서 Registry 파일과 워크트리 조합별로 저장된다. IntelliJ 대상은 결과에 표시된 실행 구성을 해당 워크트리의 IDE에서 가져와 Debug한다. [IntelliJ 실행 구성 문서](https://www.jetbrains.com/help/idea/run-debug-configuration.html#share-run-debug-configurations)

### IntelliJ 실행·디버그 전에 자동 준비

```text
python injector.py ide-tool platform-service --project examples/demo --profile dummy
```

1. 반환된 `runConfiguration`을 IntelliJ에서 연다.
2. **Settings → Tools → External Tools**에서 로컬 도구를 추가한다. **Program**, **Arguments**, **Working directory**에 각각 `program`, `arguments`, `workingDirectory`를 입력한다.
3. **Run → Edit Configurations**에서 해당 구성의 **Before launch → Run External tool**에 만든 도구를 추가한다.

도구는 의존성이 준비될 때까지 기다리며 준비 실패를 종료 코드로 전달한다. 계획이 같고 자원이 준비된 상태라면 세션을 재사용할 수 있다. 앱 주입 설정을 바꿨으면 실행 구성과 도구 인자를 다시 생성해 반영한다. 기존 준비를 종료하거나 강제 중단 뒤 복구하려면 `stop`으로 정리한다. [IntelliJ External Tools](https://www.jetbrains.com/help/idea/configuring-third-party-tools.html)

기존 프로젝트 루트의 `registry.json` 형식도 지원한다. Spring YAML용 설정은 버전 1.1에서 지원한다.

앱별로 분리하려면 루트의 `nodeFiles`에 `["registry/nodes/platform-service.json", "registry/nodes/catalog.json"]`처럼 파일 경로를 넣는다. 각 파일은 `id`, `kind`, `variants`를 가진 노드 한 개다. 환경 변수, VM 옵션, Spring 설정, 의존 서비스 주입 규칙은 해당 앱의 variant에 둔다. 특정 프로필에서만 필요한 앱 설정은 노드의 `profileOverrides.<프로필>`에 넣는다. 루트는 공통 기본값과 프로필의 실행 대상·variant 선택을 관리한다. 기존 `nodes`와 `profiles.<프로필>.overrides`도 계속 사용할 수 있다.

`nodeFiles`는 선택한 Registry 파일의 상위 폴더 기준이고, `projectPath`, `workingDirectory`, Compose 경로는 소스 폴더 기준이다. [데모 registry](examples/demo/registry.json)와 [platform-service 설정](examples/demo/registry/nodes/platform-service.json)을 참고한다.

```powershell
python injector.py validate --project examples/registry
python injector.py validate --project examples/registry --profile local-real
```

프로필을 생략하면 모든 프로필을 검사한다. `--project`는 상대·절대 디렉터리 경로를 받는다. 검증은 구조·노드·의존성·선택 모드·접속점 참조를 확인하고, 프로세스 기동이나 설정 파일 생성을 하지 않는다. 비밀값 참조도 이 단계에서 실제 값으로 읽지 않는다.

접속 정보와 설정을 합성하고 값이 가려진 출처를 확인하려면 다음을 실행한다.

```powershell
python injector.py resolve --project examples/registry --profile local-real --node catalog
```

`resolve`는 `fromEnv` 참조를 실제 프로세스 환경에서 읽으므로 필요한 환경변수가 있어야 한다. 출력에서는 모든 설정값을 가리고 키와 출처만 보여준다. [주소 해석·설정 합성](docs/work-items/T-030.ko.md)

선택된 프로필의 전이적 의존성과 DFS 후위 순서를 확인할 수 있다.

```powershell
python injector.py plan --project examples/registry --profile local-real
python injector.py plan --project examples/registry --profile local-mock
```

이 계획 조회에는 환경변수의 실제 비밀값이 필요하지 않다. 공통 의존성은 한 번만 포함하고 순환은 경로와 함께 오류로 보고한다. `--project` 없이 실행하는 기존 데모 plan 요약도 유지한다.

[등록 예시](examples/registry/README.ko.md)는 모델 설명용이며 실행 앱을 제공하지 않는다. 실제 실행은 기존 `examples/demo/` POC 명령으로 확인한다. 등록 스키마는 [T-010](docs/work-items/T-010.ko.md), 로딩·검증은 [T-020](docs/work-items/T-020.ko.md), DFS 계획은 [T-040](docs/work-items/T-040.ko.md)에서 관리한다.

## Spring YAML과 VM 전용 값 생성

`vmOptions`는 JVM 플래그, `vmProperties`는 System.getProperty로 읽는 -D 값, v1.1의 `springProperties`는 Spring이 읽을 YAML 값이다. 서비스 정의의 기본값·실행 모드·프로필 override에서 관리한다.

```powershell
python injector.py render --project examples/spring-config --profile local --node spring-probe
```

원본 YAML을 수정하지 않고 `.local/injector/<profile>/<node>/spring-overrides.yml`과 해당 앱의 `.run/Injector-<profile>-<node>.run.xml`을 생성한다. XML에는 기존 VM 전용 값과 생성 파일을 가리키는 `spring.config.additional-location`을 함께 넣는다. render는 앱을 실행하지 않는다.

현재 IntelliJ 타입만 지원한다. Spring의 fromEnv 참조는 `${ENV_NAME}`으로 남겨 앱 환경에서 읽고, env/VM 속성의 비밀값 참조를 XML에 복사하는 작업은 거부한다. 등록된 YAML·VM·env 키 충돌과 기존 additional-location도 확인한다. 자세한 범위는 [T-140](docs/work-items/T-140.ko.md), 실제 예제는 [Spring 설정 검증 앱](examples/spring-config/README.ko.md)에 있다.

## LLM으로 모노레포 등록 준비

[등록 스킬](skills/injector-register-monorepo/SKILL.ko.md)과 [등록 프로토콜](skills/injector-register-monorepo/references/registration-protocol.ko.md)을 준비했다. 스킬 기능이 없는 LLM에도 이 문서를 제공해 사용할 수 있다.

처음 적용할 때는 실행 앱을 식별하고 대상 앱의 인프라와 앱 간 연결을 순서대로 조사한다. Spring 앱은 선택한 실행 방식에서 실제로 적용되는 설정 출처를 함께 추적한다. [모노레포 탐색 가이드](skills/injector-register-monorepo/references/monorepo-initialization.ko.md) · [Spring 설정 조사 체크리스트](skills/injector-register-monorepo/references/spring-configuration-audit.ko.md)

앱을 읽는 코드, YAML 프로필, VM 옵션을 추적해 주입 채널을 정한다. `draft-check`로 초안을 확인하고 `draft-convert`로 검토한 프로필에서 새 실행 후보를 만든다. 이후 `validate`, `plan`, `resolve`, `render`로 확인한다. [실행 등록 관리 가이드](skills/injector-register-monorepo/references/runtime-registry-guide.ko.md) · [변환 절차](skills/injector-register-monorepo/references/registration-protocol.ko.md#검토한-초안-변환)

예시 요청:

```text
skills/injector-register-monorepo/SKILL.md를 읽고,
<모노레포 경로>의 <대상 앱>을 local 프로필로 조사해 줘.
앱별 접속 정보와 전이적 의존성, 설정 주입 위치를 근거와 함께 정리하고,
등록 JSON 초안과 미확인 사항 보고서를 만들어 줘.
```

기본 산출물은 Injector의 `registries/<레포-ID>/onboarding/registration-draft.json`과 `findings.md`다. 등록용 파일도 같은 레포 폴더에 두고 소스는 `--project`로 지정한다. 초안 작성 단계는 조사 자료를 생성하며 실행에는 검토된 `registry.json`을 사용한다.

## 작업 저장

검증을 마친 작업 단위마다 의미 있는 커밋을 만들고 `https://github.com/chochanyeon/injector`에 푸시한다. 미검증 항목은 검증 완료 항목과 구분해 기록한다.

## 참고

- [WireMock Docker 실행](https://wiremock.org/docs/standalone/docker/)
- [IntelliJ Application 실행 구성](https://www.jetbrains.com/help/idea/run-debug-configuration-java-application.html)
