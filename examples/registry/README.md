# 실행용 등록 모델 예시

`registry.json`은 T-010의 스키마 v1.0을 설명하는 가상 모노레포 예시다. Orders와 Catalog가 같은 DB를 참조하고, Catalog만 실제 앱과 모의 대역 사이에서 전환한다. `local-mock`에서도 Orders가 DB를 직접 필요로 하므로 DB가 남는다.

`apps/orders`, `compose.yaml`, `/health` 등은 모델 예시를 위한 값이다. 실제 실행 파일이나 구현을 제공하지 않으므로 서비스 실행용 데모로 사용하지 않는다. 실행 가능한 기존 데모는 `../demo/`에 있다.

JSON Schema는 `../../schemas/registry-v1.schema.json`, 설계·개발·검증은 `../../docs/work-items/T-010.md`에서 관리한다. 스키마 검증은 자료형과 구조를 확인하고, 참조·선택 모드·그래프 실행 검증은 후속 단계에서 수행한다.
