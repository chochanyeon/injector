# Spring configuration checklist

**English** · [한국어](spring-configuration-audit.ko.md)

Check each selected app, runner, and Spring profile combination. Mark evidence as verified, inapplicable, or unresolved, and explain which unresolved inputs block execution. Confirm values using source files, effective launch inputs, and consumers.

## 1. Inspect the launch inputs

| Area | What to check |
|---|---|
| Version and entry point | Boot and Spring Cloud versions, main method, `SpringApplication` or `SpringApplicationBuilder` profiles, defaults, and command-line behavior |
| IDE and local | Shared `.run/`, `.idea/runConfigurations/`, scripts, `bootRun`, and `spring-boot:run`. Record working directory, program arguments, JVM options, `-D`, environment variables, and environment files. |
| Containers and deployment | Docker `ENTRYPOINT` and `CMD`; Compose `command`, `environment`, `env_file`, and mounts; applicable Helm, Kubernetes, and CI settings. For unavailable values, record references and owners. |
| Process environment | `SPRING_APPLICATION_JSON`, `JAVA_TOOL_OPTIONS`, and scripts that convert variables to JVM options or program arguments |

Record build profiles and active Spring profiles separately. Follow resource templates, conditional filters, and sources of generated values.

## 2. Trace the loaded sources

- Inspect `application.yml`, `application.yaml`, `application.properties`, and profile-specific documents in app and shared resources, working directories, and external locations. Check `spring.config.activate.on-profile` and active, default, included, and grouped profiles.
- Follow `spring.config.name`, `spring.config.location`, `spring.config.additional-location`, and `spring.config.import`. Record whether a source is a file, classpath resource, configuration tree, or remote provider, its relative base, optionality, and precedence for the relevant Boot version. [Spring Boot external configuration](https://docs.spring.io/spring-boot/reference/features/external-config.html)
- Trace Cloud Config and Vault through imports, clients, or direct calls. Check evidence that `bootstrap.*` is loaded. Record remote addresses, keys, and auth references, and confirm the local supply method. [Spring Cloud Config client](https://docs.spring.io/spring-cloud-config/reference/client.html)
- Follow `${KEY:default}` to the environment, another property, or a default. Record candidate sources, selection rules, order, and any actual values that remain unknown.

## 3. Trace consumers back to their sources

Use `rg -n` in the app and its shared modules to follow both directions.

- Check `@ConfigurationProperties`, `@Value`, `Environment.getProperty`, and `Binder`. Inspect auto-configuration, `@Profile`, and `@ConditionalOnProperty` for clients, data sources, and scheduled tasks.
- Trace `System.getenv`, `System.getProperty`, `System.setProperty`, and wrappers. Use the actual read channel.
- Check `@PropertySource`, `EnvironmentPostProcessor`, added property sources, and direct file parsers. Record independent file contracts separately.
- Connect keys to HTTP/gRPC clients, database and migrations, Kafka, Redis, Vault, and configuration servers. Check management port, health path, TLS, and authentication. Record test-only sources such as `@TestPropertySource` and `@DynamicPropertySource` separately.

## 4. Record evidence and injection

| Example key | Consumer | Source candidates | Local channel |
|---|---|---|---|
| `clients.catalog.base-url` | Spring binding in CatalogProperties | `application-local.yml` and environment | Catalog endpoint through `springProperty` |
| `company.runtime.mode` | `System.getProperty` in RuntimeMode | Shared IntelliJ `-D` option | App file `vmProperties` |
| `DB_PASSWORD` | `System.getenv` or a placeholder | Execution environment | Reference the variable in a supported channel and confirm the local supplier |

Record source-relative files and lines, activation conditions, and behavior on missing values. Verify precedence and relaxed binding against the applicable Boot release. For reviewed registration, check bootstrap settings, runner support, and secret supply with the [runtime registry guide](runtime-registry-guide.md). Mark ambiguous precedence as unresolved. [Spring Boot binding and precedence](https://docs.spring.io/spring-boot/reference/features/external-config.html)

For each launch-blocking or scenario-critical key, keep a short chain in findings: consumer → canonical key and aliases → active candidate sources with evidence → effective value or unresolved reason → supported injector channel or required user input. Record variable names for secrets. Before closing a chain, check whether the selected launcher (including its process environment), an imported source, or a conditional bean can change it. Group questions by the decision they unblock. For example, ask which local Catalog endpoint should replace the remote fallback and point to the launch profile and client that would use it.
