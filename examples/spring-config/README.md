# Spring YAML and JVM property probe

**English** · [한국어](README.ko.md)

Build with Maven and JDK 17 or newer. The example uses Spring Boot 3.5.16.

```text
mvn -f examples/spring-config/pom.xml package
python injector.py render --project examples/spring-config --profile local --node spring-probe
```

Open this directory's `pom.xml` as a separate project in IntelliJ and Debug `Injector-local-spring-probe`. Supply `PROBE_SECRET` to the IDE or app environment. The original workflow starts the probe manually.

Check `http://localhost:18090/probe`.

- `value-from-generated-yaml` replaces `original-profile` from `application-local.yml`.
- The list becomes `local-a`, `local-b`.
- The JVM reads `probe.vm-only` through `-D`. Spring YAML values remain Spring properties.
- The generated file keeps the `${PROBE_SECRET}` placeholder. The app reads the supplied value and omits it from the response.

Edit `registry.json` and rerun render to change generated values. Source YAML stays intact. Git ignores outputs under `.local/`, `.run/` for the generated configuration, and `target/`.

For integration testing, set `INJECTOR_TEST_SPRING_JAR` and `INJECTOR_TEST_JAVA` to the built JAR and real JDK executable, then run `python -m unittest discover -s tests -p test_spring_boot_integration.py -v`. The test starts and stops the app on a separate port in a temporary directory.
