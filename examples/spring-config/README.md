# Spring 외부 YAML 및 VM 전용 설정 검증 앱

JDK 17 이상, Maven으로 빌드한다. 샘플은 Spring Boot 3.5.16을 사용한다.

```text
mvn -f examples/spring-config/pom.xml package
python injector.py render --project examples/spring-config --profile local --node spring-probe
```

IntelliJ에서 이 디렉터리의 pom.xml을 별도 프로젝트로 열고 `Injector-local-spring-probe`를 Debug로 실행한다. 실행한 IDE/앱 환경에 PROBE_SECRET을 제공해야 한다. 이 예제의 일반 등록 자동 기동은 아직 구현하지 않았다.

`http://localhost:18090/probe`에서 다음을 확인할 수 있다.

- application-local.yml의 original-profile이 생성 YAML의 value-from-generated-yaml로 바뀐다.
- 리스트는 local-a, local-b로 바뀐다.
- probe.vm-only는 -D JVM 속성으로 읽힌다.
- YAML 값은 System.getProperty에 자동으로 들어가지 않는다.
- PROBE_SECRET은 생성 YAML에 ${PROBE_SECRET}로 남고 실제 값은 앱 환경에서 읽는다. 응답에 비밀값을 출력하지 않는다.

원본 YAML과 registry는 소스이며, .local·.run·target은 생성 결과다. 값 변경은 registry.json에 반영하고 render를 다시 실행한다. 해당 경로는 이 저장소의 .gitignore에서 제외한다.

자동 실앱 검증은 INJECTOR_TEST_SPRING_JAR에 빌드한 JAR 절대 경로, INJECTOR_TEST_JAVA에 실제 JDK의 java 실행 파일 절대 경로를 지정한 뒤 `python -m unittest discover -s tests -p test_spring_boot_integration.py -v`로 수행한다. 테스트는 별도 포트·임시 폴더에서 앱을 시작하고 종료한다.
