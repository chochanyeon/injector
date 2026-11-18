---
name: injector-register-monorepo
description: Initialize Injector registration for a monorepo or update an existing registry. Discover runnable modules, trace Spring and JVM configuration to its sources, and record dependencies and injection rules with evidence. The workflow does not launch services.
---

# Injector 모노레포 등록

[English](SKILL.md) · **한국어**

모노레포의 기존 실행 정보를 조사해 사람이 검토할 수 있는 앱 등록 초안을 만든다. Injector는 앱·인프라의 접속 정보를 관리하고, 대상 앱의 의존성을 DFS 후위 순서로 준비한 뒤 설정을 주입해 실행하는 도구를 지향한다.

- 모노레포 최초 등록은 [모노레포 탐색 가이드](references/monorepo-initialization.ko.md)를 따른다. 요청받은 앱이나 하위 폴더에서 시작해 선택한 실행 방식을 재구성하고, 관련된 범위 밖 의존성만 추적한다.
- Spring 앱을 조사할 때는 [Spring 설정 조사 체크리스트](references/spring-configuration-audit.ko.md)로 선택한 실행 방식의 설정 출처와 읽는 코드를 대조한다.
- 조사 초안이 필요하면 [등록 프로토콜](references/registration-protocol.ko.md)과 [예시 JSON](assets/registration-draft.example.json)을 참고한다. 실행용 registry 작성·갱신을 요청받으면 [실행 등록 관리 가이드](references/runtime-registry-guide.ko.md)로 파일 구조와 무기동 검증 명령을 확인한다.

## 작업 경계

- 요청한 모노레포와 대상 앱에서 시작한다. 모든 디렉터리를 무조건 읽지 말고 빌드·실행 설정을 먼저 찾아 탐색 범위를 좁힌다.
- 기본 저장 위치는 Injector의 `registries/<레포-ID>/`다. 실행용 registry와 앱별 JSON, 조사 초안·근거를 이곳에 모으고 대상 소스·워크트리는 `--project`로 지정한다. 저장 폴더는 `--registry`로 전달한다.
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

JSON 파싱, 참조 무결성, 근거 경로·줄의 유효성, 선택한 그래프의 DFS 순서를 확인한다. 순환이나 미확인 의존성 때문에 순서를 확정할 수 없으면 `startupOrder`를 `null`로 두고 원인을 기록한다. 일부만 확인됐어도 조사 결과와 구체적인 질문을 남긴다. 실행용 등록에서는 실제 `plan`을 의도한 로컬 시나리오와 대조하고 남은 설정·기동 검증을 따로 알린다.
