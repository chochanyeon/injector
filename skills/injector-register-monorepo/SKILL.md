---
name: injector-register-monorepo
description: Analyze monorepos for Injector onboarding and maintain reviewed runtime registries with source evidence, endpoints, dependencies, and Spring or JVM injection rules. Use for application registration and registry updates; this workflow does not launch services.
---

# Injector 모노레포 등록

모노레포의 기존 실행 정보를 조사해 사람이 검토할 수 있는 앱 등록 초안을 만든다. Injector는 앱·인프라의 접속 정보를 관리하고, 대상 앱의 의존성을 DFS 후위 순서로 준비한 뒤 설정을 주입해 실행하는 도구를 지향한다.

최초 조사·미확인 값 정리는 [등록 프로토콜](references/registration-protocol.md)을 읽고 [예시 JSON](assets/registration-draft.example.json)을 참고한다. 사용자가 실행용 registry 작성·갱신을 요청하면 [실행 등록 관리 가이드](references/runtime-registry-guide.md)를 읽는다. 예시의 앱·주소·포트는 가상이며 실제 프로젝트의 기본값이 아니다.

## 작업 경계

- 요청한 모노레포와 대상 앱에서 시작한다. 모든 디렉터리를 무조건 읽지 말고 빌드·실행 설정을 먼저 찾아 탐색 범위를 좁힌다.
- 소스 파일을 읽어 근거를 모은다. 분석 목적으로 앱·빌드 스크립트·컨테이너를 실행하거나 hosts/DNS를 변경할 필요는 없다.
- 현재 Injector POC의 `project.json`은 다중 앱 등록 스키마가 아니다. 이 스킬의 JSON은 조사 결과를 전달하는 초안 형식이며 CLI가 읽거나 실행하는 설정이라고 설명하지 않는다.
- 검토용 초안과 실행용 registry.json을 구분한다. 실행 등록 모드에서는 Injector 저장소의 실제 schemas와 CLI를 확인하고 지원하는 필드만 사용한다. 미확인 값을 실행용 설정에 추측으로 채우지 않는다.

## 조사와 결과 작성

1. 앱 후보와 라이브러리 모듈을 구분하고, 요청한 앱의 실행 진입점·작업 디렉터리·활성 프로필을 찾는다.
2. VM 옵션·환경변수·설정 파일에서 접속점과 주입 키를 추적한다. 환경변수 참조나 기본값의 출처를 따라가고, 확인되지 않은 최종값은 확정하지 않는다.
3. 호출 대상 앱과 인프라를 식별하고 하위 의존성을 재귀적으로 조사한다. 런타임 호출 관계와 빌드 의존성을 혼동하지 않는다.
4. 선택한 실행 모드·프로필·호출자 위치에 따라 그래프를 구성한다. 공통 의존성, 순환, 포트 충돌, 해석되지 않는 참조를 확인한다.
5. 프로토콜에 따른 JSON 초안과 조사 보고서를 작성한다. 파일·줄 근거, 추론, 미확인 항목을 분리하고, 남은 질문은 실행 계획에 영향을 주는 순서로 제시한다.

기존 초안을 갱신할 때는 노드 ID와 사용자 확정값을 유지한다. 새 근거가 기존 값과 다르면 조용히 덮어쓰지 말고 차이를 보고한다. 등록 초안 작성 요청만으로 실제 설정 적용이나 서비스를 실행하지 않는다.

## 완료 기준

JSON 파싱, 참조 무결성, 근거 경로·줄의 유효성, 선택한 그래프의 DFS 순서를 확인한다. 순환이나 미확인 의존성 때문에 순서를 확정할 수 없으면 `startupOrder`를 `null`로 두고 원인을 기록한다. 준비 상태와 실행 명령이 미확인인 경우에도 실행 가능한 등록으로 표현하지 않는다.
