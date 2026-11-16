# 전체 개발 현황

최종 갱신: 2026-11-17. [작업 인덱스](index.md). 각 작업의 설계·개발·검증 상세는 해당 T-ID 문서를 기준으로 확인한다.

## 1. 현재 단계

**단일 데모 프로젝트의 실행 POC가 동작하는 단계다. 실행용 등록 스키마 v1.0을 추가했다. 외부 프로젝트의 등록 검증 CLI도 추가했다. 주소 해석·설정 합성도 추가했다. DFS 실행 계획·실제 실행 엔진은 아직 없다.** Python·JSON·Compose는 POC의 선택이며 제품 기술 스택은 미확정이다.

저장소 루트는 Injector 개발 공간이다. Java 데모와 데모 전용 설정·Docker·생성 파일은 `examples/demo/`에 둔다. 루트에서 `python injector.py ...`를 실행하며, IntelliJ에서는 `examples/demo/pom.xml`을 별도 프로젝트로 연다.

## 2. 기능별 상태

| 항목 | 상태 | 실제 구현과 제한 | 근거 |
|---|---|---|---|
| VM 옵션·환경변수 합성 | 부분 구현 | 공통 env에 프로필 env 덮어쓰기, VM 옵션 배열 연결. 충돌 해결·출처 추적 없음 | `injector.py:resolve` |
| IntelliJ 주입 | 부분 구현 | 데모의 `.run/Injector-*.run.xml` 생성. 기존 구성 병합·IDE 자동 실행 없음 | `injector.py:generate` |
| 모의 API·실제 API 전환 | 부분 구현 | mock/real 두 프로필로 WireMock 또는 Catalog 선택. 일반적인 의존성별 선택 아님 | 데모 `config/project.json` |
| DB·Kafka·Redis 기동 | 부분 구현 | Compose의 고정 서비스 선택 및 healthcheck 대기. 데모 앱의 실제 인프라 사용은 없음 | 데모 `docker/compose.yaml` |
| 메인 앱 실행 | 부분 구현 | CLI Java 실행과 Docker 실행. IntelliJ Debug는 개발자가 직접 시작 | `injector.py:main` |
| `plan` | 부분 구현 | 프로필·서비스·env 키 요약 출력. 그래프 실행 계획 기능 아님 | `injector.py:main` |
| `down` | 부분 구현 | 고정 Compose 프로젝트의 컨테이너·네트워크 제거. 세션 소유권·복구 관리 아님 | `injector.py:compose` |
| LLM 등록 지원 | 완료 | 조사 스킬·프로토콜·예시 제공. 실제 모노레포 조사와 자동 import는 미수행 | `skills/injector-register-monorepo/` |
| 실행용 등록 스키마 | 완료 | JSON Schema v1.0과 다중 앱·공통 의존성 예시. 실행 엔진 아님 | T-010 |
| 앱 등록 로딩·외부 프로젝트 지정 | 완료(검증) | --project의 registry.json 구조·참조·경로 검사. 실제 실행은 데모에 고정 | T-020 |
| 접속점·호스트·포트·주입 참조 해석 | 완료(메모리 결과) | 호출자별 주소·설정 합성·출처·충돌·비밀 참조 처리. 일반 등록의 실행 연결은 미구현 | T-030 |
| DFS·공통 의존성·순환 검출 | 미착수 | 설계만 존재 | T-040 |
| 일반화된 실행·준비 상태 확인 | 미착수 | Compose 외 실행별 수명 관리 없음 | T-050 |
| 의존성 전체 준비 후 대상 앱 실행 | 미착수 | 단일 작업으로 연결된 그래프 파이프라인 없음 | T-060 |
| 사용자 정의 이름 해석 | 미착수 | hosts/DNS 등록·복원 없음 | T-070 |
| 모드별 하위 그래프 선택 | 미착수 | 두 데모 프로필 전환만 있음 | T-080 |
| 세션·실패 복구·데이터 정책 | 미착수 | 포트·Compose 프로젝트명 고정, 익명 볼륨 사용 | T-090 |

스킬의 `registration-draft.json`은 검토용 산출물 계약이다. 실행용 설정으로 읽거나 현재 `project.json`에 바로 넣을 수 없다.

## 3. 코드와 자료 위치

| 위치 | 책임 |
|---|---|
| [injector.py](../injector.py) | 현재 POC의 설정 해석·XML 생성·Compose 호출·Java 실행 |
| [tests/test_injector.py](../tests/test_injector.py) | 설정 합성과 생성 결과 검사 2개 |
| [schemas/registry-v1.schema.json](../schemas/registry-v1.schema.json) | 실행용 등록 v1.0의 구조 계약 |
| [injector_core/registry.py](../injector_core/registry.py) | 임의 프로젝트의 등록 로딩·참조 검증 |
| [tests/test_registry.py](../tests/test_registry.py) | 로더·검증 CLI 검사 15개 |
| [examples/demo/config/project.json](../examples/demo/config/project.json) | 데모 전용 설정 |
| [examples/demo/src/main/java/poc](../examples/demo/src/main/java/poc/) | 메인 앱과 Catalog |
| [examples/demo/docker](../examples/demo/docker/) | Compose, 앱 Dockerfile, WireMock 매핑 |
| [skills/injector-register-monorepo](../skills/injector-register-monorepo/) | 저장소에서 유지하는 등록 스킬 원본 |

로컬 스킬 폴더에 설치한 사본은 Git에 포함되지 않는다. 스킬 수정 시 저장소 원본을 기준으로 사본을 동기화하고 검증한다.

## 4. 검증 수준

- 자동 검증: 설정 2개·실행 스키마 8개·로더/CLI 15개·주소/합성 13개, 총 38개. 그래프·세션 테스트는 아직 없다.
- 수동 통합 검증: 로컬 JVM·Docker에서 mock/real 호출과 주입, 인프라 기본 동작 확인.
- IntelliJ: 디렉터리 분리 전에 두 프로필의 Debug와 브레이크포인트 중단·재개 확인. 분리 후 XML 경로·모듈만 재확인.
- 스킬: 형식 검사, 예시 JSON 파싱·참조 무결성 확인. 실제 업무 모노레포 적용 검증은 아직 없다.

환경과 과거 절차는 [기존 검증 이력](validation-history.md), 작업별 최신 결과는 인덱스의 해당 작업 문서를 따른다. 이전 검증을 현재 실행 환경의 정상 동작 보장으로 해석하지 않는다.

## 5. 현재 인계

- 진행 중 구현: 없음. T-030의 주소·설정 해석을 검증했다.
- 다음 작업: **[T-040 DFS 실행 계획](work-items/T-040.md)**.
- 입력: 설계 R-08~R-11, 15~16절, 등록 프로토콜 v0.1, 현재 데모 설정.
- 첫 산출물: 선택한 대상의 DFS 후위 순서, 공통 의존성 단일 포함, 순환 경로 검출과 안전한 계획 출력.
- 다음 작업에 필요한 사용자 입력: 현재 없음. 실제 업무 모노레포가 제공되기 전까지 로컬 fixture로 모델을 검증할 수 있다.
- 남은 제품 결정: D-01~D-09는 공통 설계의 미결정 표를 참고한다. 필요한 결정은 해당 T-ID에서 이유를 기록하고 처리한다.
- 런타임 상태: 이 문서에 기동 상태를 고정 기록하지 않는다. 재개 시 확인한다.

## 6. 작업 종료 때 갱신할 인계 항목

진행한 작업 문서에 완료한 산출물, 실제 실행한 검증, 미해결 문제, 다음 조치를 남긴다. 작업 도중 중단되면 수정 파일·실패한 명령·재현 방법도 같은 문서에 기록한다. 인덱스와 이 전체 요약을 함께 갱신한다.
