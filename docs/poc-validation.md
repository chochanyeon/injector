# POC 검증 기록

검증일: 2026-11-16

## 환경

- Windows, Docker Desktop Linux 엔진
- IntelliJ IDEA 2025.3.3, Microsoft JDK 21.0.10
- CLI 컴파일: JDK 25.0.3의 `--release 17`
- Docker 앱: Eclipse Temurin JDK/JRE 17
- Python 3.14.4, Docker 29.4.0, Compose 5.1.1

## 결과

| 실행 경로 | 구성 | 확인한 의존 주소 | 결과 |
|---|---|---|---|
| IntelliJ Debug | mock | `http://localhost:18081` | WireMock 응답, 브레이크포인트 중단·재개 성공 |
| IntelliJ Debug | real | `http://localhost:18082` | 실제 Catalog 응답, 브레이크포인트 중단·재개 성공 |
| Docker | mock | `http://wiremock:8080` | 메인 앱을 통한 HTTP 호출 성공 |
| Docker | real | `http://catalog:18082` | 메인 앱을 통한 HTTP 호출 성공 |

네 실행 경로에서 `/demo` 응답의 `profile`이 선택한 구성과 일치하고, `message`가 환경변수의 `environment injected`와 일치함을 assertion으로 검사했다. `downstream`을 JSON으로 해석한 후 `source`가 각각 `wiremock` 또는 `real`인지 검사했다. Docker 실행에서는 `catalogUrl`이 컨테이너 내부 주소와 일치하는지도 검사했다.

## IntelliJ 검증 절차

1. `python injector.py up --profile mock --infra postgres redis kafka`로 의존성을 준비했다.
2. Maven 프로젝트를 가져온 IntelliJ가 생성한 `Injector-mock` 구성을 인식하는지 확인했다.
3. `Main.java:31`에 브레이크포인트를 설정하고 Debug 실행했다.
4. `/demo` 요청을 보내 `lambda$main$0` 프레임에서 실행이 중단되는지 확인했다.
5. 변수 창에서 `catalogUrl`, 요청 주소, 응답 상태 `200`을 확인했다.
6. F9로 실행을 재개하고 클라이언트에서 설정값과 응답을 검사했다.
7. Debug 세션을 종료한 뒤 `real` 의존성을 준비하고 `Injector-real`로 같은 절차를 수행했다.

두 구성 모두 IntelliJ가 JVM에 JDWP로 직접 연결했다. 메인 앱을 Docker에 넣고 원격 연결한 방식이 아니다.

## Docker 검증 절차

IntelliJ 메인 앱을 종료한 뒤 다음 두 명령을 순서대로 실행하고, 각 실행 후 `/demo` 응답을 검사했다.

```powershell
python injector.py up --profile mock --main-docker
python injector.py up --profile real --main-docker
```

공통 설정과 프로필별 설정이 Docker 메인 앱에도 반영되고, 호스트 주소가 Compose 내부 주소로 바뀌는 것을 확인했다. 검증 후 Docker의 메인 앱은 정지했다.

## 인프라 및 설정 검증

- PostgreSQL: `demo` DB에서 `select 1` 성공
- Redis: `redis-cli ping` → `PONG`
- Kafka: 단일 파티션·복제 계수 1의 `injector-poc` 토픽 생성 성공
- WireMock: `/product` 매핑 응답 확인
- 네 인프라·대역 컨테이너의 healthcheck 통과
- `python -m unittest discover -s tests -v`: 설정 테스트 2개 통과

검증 중 의존성만 준비한 경우에도 메인 앱이 실행된 것처럼 보이던 `up` 완료 문구를 수정했다. 이제 IntelliJ에서 Debug를 시작해야 한다고 안내한다.

## 해석 범위

이 결과는 샘플 프로젝트에서 설정 주입, API 대역 전환, IntelliJ 디버깅, Docker 실행이 함께 성립함을 보여준다. 기존 업무 프로젝트의 복잡한 설정을 자동 수집하거나, DB·Kafka·Redis를 샘플 앱이 직접 사용하는 것까지 검증한 결과는 아니다. 인프라의 호스트 클라이언트 연결과 데이터 보존 정책도 추가 검증이 필요하다.
