# 전체 개발 현황

[English](status.md) · **한국어**

최종 갱신: 2026-11-18. [작업 인덱스](index.ko.md). 각 작업의 설계·개발·검증 상세는 해당 T-ID 문서를 기준으로 확인한다.

## 1. 현재 단계

**단일 데모 프로젝트의 실행 POC가 동작하는 단계다. 실행용 등록 스키마 v1.0·v1.1을 지원한다. 외부 프로젝트의 등록 검증 CLI도 추가했다. 주소 해석·설정 합성도 추가했다. DFS 후위 실행 계획까지 계산한다. Spring 외부 YAML·IntelliJ 실행 구성도 생성한다. 일반 등록의 process·Compose·external 의존성을 DFS 순서대로 준비하고 IntelliJ Debug 구성을 생성한다. CLI와 loopback 웹 화면이 같은 실행 함수를 사용한다. 새 IDE 구성의 실제 breakpoint와 브라우저 시각·클릭 검증은 남았다.** Python·JSON·Compose는 POC의 선택이며 제품 기술 스택은 미확정이다.

저장소 루트는 Injector 개발 공간이다. 기존 Java·Vault 데모는 `examples/demo/`, Spring 설정 검증 앱은 `examples/spring-config/`에 둔다. 루트에서 `python injector.py ...`를 실행하며, IntelliJ에서는 `examples/demo/pom.xml`을 별도 프로젝트로 연다.

## 2. 기능별 상태

| 항목 | 상태 | 실제 구현과 제한 | 근거 |
|---|---|---|---|
| VM 옵션·환경변수 합성 | 부분 구현 | 레거시 데모는 단순 합성. 일반 등록은 VM/환경/Spring 값의 출처·충돌 검사, process·Compose env·IntelliJ 연결 지원(제한은 T-060) | `injector.py:resolve` |
| IntelliJ 주입 | 부분 구현 | 데모 XML과 일반 등록의 Spring YAML·전용 XML 생성. 기존 구성 병합·IDE 자동 실행 없음 | `injector.py:generate` |
| 모의 API·실제 API 전환 | 부분 구현 | mock/real 두 프로필로 WireMock 또는 Catalog 선택. 일반적인 의존성별 선택 아님 | 데모 `config/project.json` |
| DB·Kafka·Redis 기동 | 부분 구현 | Compose의 고정 서비스 선택 및 healthcheck 대기. 데모 앱의 실제 인프라 사용은 없음 | 데모 `docker/compose.yaml` |
| 메인 앱 실행 | 부분 구현 | CLI Java 실행과 Docker 실행. IntelliJ Debug는 개발자가 직접 시작 | `injector.py:main` |
| `plan` | 완료(계획) | --project 사용 시 DFS 순서·모드·의존성 메타데이터 출력. 실제 기동 없음. 기존 데모 요약도 유지 | T-040 |
| `down` | 부분 구현 | 고정 Compose 프로젝트의 컨테이너·네트워크 제거. 세션 소유권·복구 관리 아님 | `injector.py:compose` |
| Vault API 대역 | 완료(데모) | 별도 WireMock KV v2 조회·서비스 ID별 값 분리. 고정 토큰만 사용, 회사 Vault/SDK 미연동 | T-130, T-131 |
| LLM 등록 지원 | 완료 | 최초 등록 가이드, Spring 설정 조사 체크리스트, 초안 프로토콜과 실행용 registry 가이드 제공 | T-005, T-140 |
| 실행용 등록 스키마 | 완료 | v1.0 기본 계약·v1.1 Spring 확장. 실행 엔진 아님 | T-010, T-140 |
| Spring 외부 YAML·VM 값 생성 | 완료(로컬) | 타입·환경 placeholder 보존, additional-location 주입. IntelliJ 타입만 지원 | T-140 |
| 앱 등록 로딩·외부 프로젝트 지정 | 완료(검증) | --project의 registry.json 구조·참조·경로 검사. prepare에서 외부 등록 실행 지원 | T-020 |
| 접속점·호스트·포트·주입 참조 해석 | 완료(메모리 결과) | 호출자별 주소·설정 합성·출처·충돌·비밀 참조 처리. 일반 등록의 process·Compose env·IntelliJ 연결 지원(제한은 T-060) | T-030 |
| DFS·공통 의존성·순환 검출 | 완료(계획) | 선택한 하위 그래프 후위 순회·단일 포함·순환 경로 보고 | T-040 |
| 일반화된 실행·준비 상태 확인 | 완료(첫 범위) | process/Compose/external, HTTP/TCP/healthcheck, 소유 자원 정리 | T-050 |
| 의존성 전체 준비 후 대상 앱 실행 | 구현·부분 검증 | prepare 파이프라인과 IDE Debug 준비. 새 구성의 IDE 직접 검증 남음 | T-060 |
| 클릭 준비 화면 | 구현·부분 검증 | 더블클릭 launcher, 로컬 API·화면. 실제 브라우저 확인 남음 | T-150 |
| registry.json 편집 | 구현·부분 검증 | 파일 열기·검증·저장·외부 변경 감지와 OS 기본 폴더 선택. macOS 폴더 선택 창·휴대폰 원격 미리보기 확인 남음 | T-170 |
| 앱별 설정 파일 | 구현 | 루트의 `nodeFiles`로 앱·인프라 파일을 조합하고 웹에서 개별 파일을 편집 | T-190 |
| registry 중앙 보관 | 구현·부분 검증 | Injector의 `registries/`에서 설정을 공유하고 소스 워크트리별로 실행 상태를 분리 | T-200 |
| 의존성 그래프 | 구현·부분 검증 | 프로필·앱 필터, 노드의 직접 연결 강조. 데모 화면 검증 완료, 작은 화면·대형 그래프 확인 남음 | T-180 |
| 사용자 정의 이름 해석 | 구현·부분 검증 | macOS·Windows hosts 미리보기·적용·복원과 이름 해석 확인. 관리자 시스템 파일 적용 검증 남음 | T-070, T-160 |
| macOS·Windows 시작 | 구현·부분 검증 | macOS Finder 실행 파일, Windows VBS, 두 OS의 CI. Finder 실기기 확인 남음 | T-160 |
| 모드별 하위 그래프 선택 | 완료 | 프로필의 노드별 variant를 실행 요청에서 바꾸고 계획·그래프·주입에 반영 | T-080 |
| 세션·실패 복구·데이터 정책 | 부분 구현 | 재준비 전 포트 소유권 확인, 의존성 준비 후 IDE 설정 반영, 자식 프로세스 정리. 이전 세션 복구·공유 자원 정책 후속 | T-050, T-090 |

스킬의 `registration-draft.json`은 검토용 산출물 계약이다. 실행용 설정으로 읽거나 현재 `project.json`에 바로 넣을 수 없다.

## 3. 코드와 자료 위치

| 위치 | 책임 |
|---|---|
| [injector.py](../injector.py) | 현재 POC의 설정 해석·XML 생성·Compose 호출·Java 실행 |
| [tests/test_injector.py](../tests/test_injector.py) | 설정·생성 결과·Vault opt-in/서비스 선택 검사 5개 |
| [schemas/registry-v1.schema.json](../schemas/registry-v1.schema.json) | 실행용 등록 v1.0의 구조 계약 |
| [schemas/registry-v1.1.schema.json](../schemas/registry-v1.1.schema.json) | Spring 설정용 v1.1 확장 |
| [injector_core/runtime.py](../injector_core/runtime.py) | prepare/stop 실행·세션·readiness |
| [injector_core/web.py](../injector_core/web.py) | 로컬 클릭 화면 서버·job API |
| [injector_core/rendering.py](../injector_core/rendering.py) | 생성 YAML·IntelliJ XML |
| [injector_core/registry.py](../injector_core/registry.py) | 임의 프로젝트의 등록 로딩·참조 검증 |
| [tests/test_registry.py](../tests/test_registry.py) | 로더·검증 CLI 검사 15개 |
| [examples/demo/config/project.json](../examples/demo/config/project.json) | 데모 전용 설정 |
| [examples/demo/src/main/java/poc](../examples/demo/src/main/java/poc/) | 메인 앱과 Catalog |
| [examples/demo/docker](../examples/demo/docker/) | Compose, 앱 Dockerfile, WireMock 매핑 |
| [skills/injector-register-monorepo](../skills/injector-register-monorepo/) | 저장소에서 유지하는 등록 스킬 원본 |

로컬 스킬 폴더에 설치한 사본은 Git에 포함되지 않는다. 스킬 수정 시 저장소 원본을 기준으로 사본을 동기화하고 검증한다.

## 4. 검증 수준

- 자동 검증: Windows에서 실제 Spring Boot와 WireMock Vault를 포함해 113개 통과. Linux에서 런타임 16개 통과.
- 수동 통합 검증: CLI dummy/real과 화면 API dummy 전환으로 실제 Docker 의존성 준비·정리를 확인했다. 생성 XML의 인자·환경으로 Java Main→실제 Catalog 응답도 확인했다.
- IntelliJ: 기존 데모 Debug는 분리 전 검증. Spring XML은 생성·파싱을 검증하고, 동일 JVM 인자로 실제 Boot 앱을 확인했다. 새 XML의 IDE UI 실행은 미수행.
- 스킬: 형식·상대 링크 확인, 데모 앱별 계획과 Spring 설정 채널 확인. 실제 업무 모노레포 적용 검증은 아직 없다.

환경과 과거 절차는 [기존 검증 이력](validation-history.ko.md), 작업별 최신 결과는 인덱스의 해당 작업 문서를 따른다. 이전 검증을 현재 실행 환경의 정상 동작 보장으로 해석하지 않는다.

## 5. 현재 인계

- macOS와 Windows에서 같은 로컬 UI를 사용한다. registry 편집은 T-170, 의존성 그래프는 T-180에 기록했다.
- T-080과 T-090의 포트 충돌·프로세스 정리·상대 경로 수정을 마쳤다. 이어서 멀티모듈 도그푸딩으로 등록과 혼합 실행을 검증한다. [T-090](work-items/T-090.ko.md)의 나머지 세션 정책은 별도 검증이 필요하다.
- 다음 작업에 필요한 사용자 입력: 현재 없음. 실제 업무 모노레포가 제공되기 전까지 로컬 fixture로 모델을 검증할 수 있다.
- 남은 제품 결정: D-01~D-09는 공통 설계의 미결정 표를 참고한다. 필요한 결정은 해당 T-ID에서 이유를 기록하고 처리한다.
- 런타임 상태: 이 문서에 기동 상태를 고정 기록하지 않는다. 재개 시 확인한다.

## 6. 작업 종료 때 갱신할 인계 항목

진행한 작업 문서에 완료한 산출물, 실제 실행한 검증, 미해결 문제, 다음 조치를 남긴다. 작업 도중 중단되면 수정 파일·실패한 명령·재현 방법도 같은 문서에 기록한다. 인덱스와 이 전체 요약을 함께 갱신한다.
