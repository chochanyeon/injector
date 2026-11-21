package upgrade.verifier;

import com.fasterxml.jackson.databind.JavaType;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.github.classgraph.ClassGraph;
import io.github.classgraph.ClassInfo;
import io.github.classgraph.ScanResult;
import jakarta.servlet.Filter;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.WebApplicationType;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.annotation.AnnotationAwareOrderComparator;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.context.WebApplicationContext;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.mvc.method.RequestMappingInfo;
import org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping;

import java.io.InputStream;
import java.lang.reflect.*;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.net.URI;
import java.net.URL;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.regex.Pattern;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;

/** Inject this file unchanged into both revisions. No application source changes are needed. */
public class UpgradeConsistencyVerifierTest {
    private static final ObjectMapper REPORT = new ObjectMapper()
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS, DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS);
    private static final String FIXED_INSTANT = "2020-01-02T03:04:05Z";

    /** Optional test-only probes for Kafka, persistence, cryptography, etc. Results must be deterministic. */
    public interface RuntimeProbe {
        JsonNode fingerprint(ConfigurableApplicationContext context) throws Exception;
    }

    @Test
    void runtimeBehaviorMatchesBaseline() throws Exception {
        String mode = required("verify.mode");
        check(mode.equals("record") || mode.equals("verify"), "verify.mode must be record or verify");
        Path baseline = Path.of(required("baseline.path"));
        check(baseline.isAbsolute(), "baseline.path must be absolute");
        ObjectNode expected = null;
        if (mode.equals("verify")) {
            check(Files.isRegularFile(baseline), "Baseline does not exist: " + baseline);
            JsonNode stored = REPORT.readTree(baseline.toFile());
            check(stored != null && stored.isObject() && stored.path("schema").asInt() == 1
                    && stored.path("fingerprint").isObject(), "Invalid baseline schema");
            expected = (ObjectNode) stored;
        }
        ArrayNode artifacts = inspectClasspath(); // Fail even in record mode on a mixed classpath.
        Class<?> application = findApplication();
        String packages = System.getProperty("verify.scan.packages", application.getPackageName());
        check(!packages.isBlank(), "Set verify.scan.packages for an application in the default package");
        SpringApplication launcher = new SpringApplication(application);
        launcher.setWebApplicationType(WebApplicationType.SERVLET);
        // Command-line properties override application.yml without modifying the application.
        List<String> args = new ArrayList<>(List.of("--server.port=0", "--spring.main.banner-mode=off"));
        if (!System.getProperty("verify.profiles", "").isBlank()) {
            args.add("--spring.profiles.active=" + System.getProperty("verify.profiles"));
        }
        try (ConfigurableApplicationContext context = launcher.run(args.toArray(String[]::new))) {
            check(context instanceof WebApplicationContext, "A Spring MVC WebApplicationContext is required");
            ObjectNode fingerprint = REPORT.createObjectNode();
            JsonNode samples = readSamples();
            fingerprint.set("configuration", configuration(application, packages, samples));
            fingerprint.set("beans", REPORT.valueToTree(new TreeSet<>(Arrays.asList(context.getBeanDefinitionNames()))));
            SortedMap<String, Mapping> mappings = mappings(context);
            fingerprint.set("endpoints", REPORT.valueToTree(mappings.keySet()));
            Map<String, ObjectMapper> mappers = context.getBeansOfType(ObjectMapper.class);
            check(!mappers.isEmpty(), "No application ObjectMapper bean found");
            ObjectNode dtos = REPORT.createObjectNode();
            SortedSet<String> dtoNames = discoverDtos(packages, mappings.values());
            check(!dtoNames.isEmpty(), "No DTOs discovered; configure verify.dto.classes for your service");
            for (var mapperEntry : new TreeMap<>(mappers).entrySet()) {
                ObjectMapper mapper = mapperEntry.getValue();
                ObjectNode results = dtos.putObject(mapperEntry.getKey());
                for (String name : dtoNames) {
                    Class<?> type = Class.forName(name);
                    try {
                        Object sample = samples.has(name)
                                ? mapper.treeToValue(samples.get(name), type)
                                : dummy(mapper.constructType(type), mapper, new HashSet<>());
                        byte[] encoded = mapper.writeValueAsBytes(sample);
                        JsonNode before = REPORT.readTree(encoded);
                        check(before != null && !before.isNull(), "DTO sample must be non-null: " + name);
                        Object restored = mapper.readValue(encoded, type);
                        JsonNode after = REPORT.readTree(mapper.writeValueAsBytes(restored));
                        assertSame(normalized(before), normalized(after), "/roundTrip/" + name);
                        results.set(name, normalized(before));
                    } catch (Exception exception) {
                        throw new AssertionError("DTO probe failed: " + name + " using mapper "
                                + mapperEntry.getKey() + "; provide verify.dto.samples if needed", exception);
                    }
                }
            }
            fingerprint.set("dtos", dtos);
            fingerprint.set("http", smoke(context, mappings.values()));
            ObjectNode probes = fingerprint.putObject("probes");
            for (String name : csv("verify.probe.classes", "")) {
                RuntimeProbe probe = (RuntimeProbe) Class.forName(name).getDeclaredConstructor().newInstance();
                JsonNode value = probe.fingerprint(context);
                check(value != null, "Probe returned null: " + name);
                probes.set(name, normalized(value));
            }
            if (mode.equals("verify")) {
                // Persisted JSON loses Java node widths (LongNode(7) becomes IntNode(7)).
                assertSame(expected.get("fingerprint"), REPORT.readTree(fingerprint.toString()), "/fingerprint");
            } else {
                ObjectNode document = REPORT.createObjectNode();
                document.put("schema", 1);
                document.set("runtimeArtifacts", artifacts); // Evidence, not equality: versions should change.
                document.set("fingerprint", fingerprint);
                Files.createDirectories(baseline.getParent());
                Path temporary = Files.createTempFile(baseline.getParent(), "baseline-", ".json");
                try {
                    REPORT.writerWithDefaultPrettyPrinter().writeValue(temporary.toFile(), document);
                    Files.move(temporary, baseline, StandardCopyOption.REPLACE_EXISTING);
                } finally {
                    Files.deleteIfExists(temporary);
                }
            }
        }
        String receipt = System.getProperty("verify.receipt.path", "");
        if (mode.equals("verify") && !receipt.isBlank()) {
            Files.writeString(Path.of(receipt), "verified\n", StandardOpenOption.CREATE_NEW);
        }
    }

    private static Class<?> findApplication() throws ClassNotFoundException {
        String explicit = System.getProperty("verify.application", "");
        if (!explicit.isBlank()) return Class.forName(explicit);
        try (ScanResult scan = new ClassGraph().enableAnnotationInfo().scan()) {
            List<String> candidates = scan.getClassesWithAnnotation("org.springframework.boot.autoconfigure.SpringBootApplication")
                    .getNames();
            check(candidates.size() == 1, "Set verify.application to one Spring Boot class; found: " + candidates);
            return Class.forName(candidates.get(0));
        }
    }

    private static ObjectNode configuration(Class<?> application, String packages, JsonNode samples) {
        ObjectNode node = REPORT.createObjectNode();
        node.put("application", application.getName());
        node.put("scanPackages", packages);
        for (String key : List.of("verify.profiles", "verify.get.paths", "verify.dto.classes",
                "verify.ignore.json.pointers", "verify.alignment.groups", "verify.probe.classes")) {
            node.put(key, System.getProperty(key, ""));
        }
        node.set("dtoSamples", samples);
        return node;
    }

    static ArrayNode inspectClasspath() throws Exception {
        JsonNode entries = REPORT.readTree(Path.of(required("verify.classpath.file")).toFile());
        check(entries != null && entries.isArray() && !entries.isEmpty(), "Missing runtime classpath metadata");
        SortedMap<String, SortedSet<String>> versions = new TreeMap<>();
        SortedMap<String, SortedSet<String>> families = new TreeMap<>();
        List<String> rules = csv("verify.alignment.groups", "");
        ArrayNode artifacts = REPORT.createArrayNode();
        Set<Path> seen = new HashSet<>();
        for (JsonNode entry : entries) {
            Path declared = Path.of(entry.path("file").asText());
            if (!declared.toString().endsWith(".jar")) continue;
            Path file = declared.toRealPath();
            if (!seen.add(file)) continue;
            Set<String> coordinates = new TreeSet<>();
            if (entry.hasNonNull("group")) {
                coordinates.add(entry.path("group").asText() + ":" + entry.path("artifact").asText()
                        + ":" + entry.path("version").asText());
            }
            // Also inspect local file/shaded JARs that Gradle cannot assign Maven coordinates.
            try (JarFile jar = new JarFile(file.toFile())) {
                Enumeration<JarEntry> contents = jar.entries();
                while (contents.hasMoreElements()) {
                    JarEntry item = contents.nextElement();
                    if (item.getName().startsWith("META-INF/maven/") && item.getName().endsWith("/pom.properties")) {
                        Properties pom = new Properties();
                        try (InputStream stream = jar.getInputStream(item)) { pom.load(stream); }
                        if (pom.getProperty("groupId") != null && pom.getProperty("artifactId") != null
                                && pom.getProperty("version") != null) {
                            coordinates.add(pom.getProperty("groupId") + ":" + pom.getProperty("artifactId")
                                    + ":" + pom.getProperty("version"));
                        }
                    }
                }
            }
            check(!coordinates.isEmpty(), "Cannot establish JAR coordinates (fail closed): " + file
                    + "; publish it with Maven metadata instead of an opaque files(...) dependency");
            for (String coordinate : coordinates) {
                String[] parts = coordinate.split(":", 3);
                versions.computeIfAbsent(parts[0] + ":" + parts[1], ignored -> new TreeSet<>()).add(parts[2]);
                for (String rule : rules) {
                    if (Pattern.matches(rule, parts[0])) {
                        families.computeIfAbsent(rule, ignored -> new TreeSet<>()).add(parts[2]);
                    }
                }
                ObjectNode artifact = artifacts.addObject();
                artifact.put("coordinate", coordinate);
                artifact.put("jar", file.getFileName().toString());
            }
        }
        check(!versions.isEmpty(), "No runtime JARs inspected");
        for (var entry : versions.entrySet()) {
            check(entry.getValue().size() == 1, "Multiple runtime versions for " + entry.getKey() + ": " + entry.getValue());
        }
        for (var entry : families.entrySet()) {
            check(entry.getValue().size() == 1, "Version alignment violation for " + entry.getKey() + ": " + entry.getValue());
        }
        for (String rule : rules) check(families.containsKey(rule), "Alignment rule matched no artifacts: " + rule);
        return artifacts;
    }

    private record Mapping(RequestMappingInfo info, HandlerMethod handler) { }

    private static SortedMap<String, Mapping> mappings(ConfigurableApplicationContext context) {
        SortedMap<String, Mapping> result = new TreeMap<>();
        for (var bean : new TreeMap<>(context.getBeansOfType(RequestMappingHandlerMapping.class)).entrySet()) {
            bean.getValue().getHandlerMethods().forEach((info, handler) -> {
                String signature = bean.getKey() + "|paths=" + sorted(info.getPatternValues())
                        + "|methods=" + sorted(info.getMethodsCondition().getMethods())
                        + "|params=" + sorted(info.getParamsCondition().getExpressions())
                        + "|headers=" + sorted(info.getHeadersCondition().getExpressions())
                        + "|consumes=" + sorted(info.getConsumesCondition().getExpressions())
                        + "|produces=" + sorted(info.getProducesCondition().getExpressions())
                        + "|custom=" + Objects.toString(info.getCustomCondition(), "")
                        + "|handler=" + handler.getMethod().toGenericString();
                result.put(signature, new Mapping(info, handler));
            });
        }
        check(!result.isEmpty(), "No MVC endpoint mappings found");
        return result;
    }

    private static List<String> sorted(Collection<?> values) {
        return values.stream().map(Object::toString).sorted().toList();
    }

    private static SortedSet<String> discoverDtos(String packages, Collection<Mapping> mappings) {
        Set<Type> types = new LinkedHashSet<>();
        for (Mapping mapping : mappings) {
            Method method = mapping.handler().getMethod();
            types.add(method.getGenericReturnType());
            types.addAll(Arrays.asList(method.getGenericParameterTypes()));
        }
        String[] prefixes = packages.split(",");
        try (ScanResult scan = new ClassGraph().enableAllInfo().acceptPackages(prefixes).scan()) {
            Set<ClassInfo> owners = new HashSet<>(scan.getClassesWithAnnotation("org.springframework.web.bind.annotation.RestController"));
            owners.addAll(scan.getClassesWithMethodAnnotation("org.springframework.kafka.annotation.KafkaListener"));
            owners.addAll(scan.getClassesWithAnnotation("org.springframework.kafka.annotation.KafkaListener"));
            for (ClassInfo owner : owners) {
                for (Method method : owner.loadClass().getDeclaredMethods()) {
                    // All controller signatures; Kafka methods only when they carry listener/handler annotations.
                    boolean controller = owner.hasAnnotation("org.springframework.web.bind.annotation.RestController");
                    boolean listener = Arrays.stream(method.getAnnotations()).anyMatch(annotation ->
                            annotation.annotationType().getName().equals("org.springframework.kafka.annotation.KafkaListener")
                                    || annotation.annotationType().getName().equals("org.springframework.kafka.annotation.KafkaHandler"));
                    if ((controller && AnnotatedElementUtils.hasAnnotation(method, RequestMapping.class)) || listener) {
                        types.add(method.getGenericReturnType());
                        types.addAll(Arrays.asList(method.getGenericParameterTypes()));
                    }
                }
            }
        }
        SortedSet<String> names = new TreeSet<>(csv("verify.dto.classes", ""));
        Set<Type> visited = new HashSet<>();
        for (Type type : types) collectDtos(type, prefixes, names, visited);
        return names;
    }

    private static void collectDtos(Type type, String[] prefixes, Set<String> names, Set<Type> visited) {
        if (!visited.add(type)) return;
        if (type instanceof ParameterizedType parameterized) {
            for (Type argument : parameterized.getActualTypeArguments()) collectDtos(argument, prefixes, names, visited);
            type = parameterized.getRawType();
        }
        if (type instanceof GenericArrayType array) collectDtos(array.getGenericComponentType(), prefixes, names, visited);
        if (type instanceof WildcardType wildcard) {
            for (Type bound : wildcard.getUpperBounds()) collectDtos(bound, prefixes, names, visited);
        }
        if (!(type instanceof Class<?> raw)) return;
        if (raw.isArray()) { collectDtos(raw.getComponentType(), prefixes, names, visited); return; }
        if (raw.isEnum() || raw.isPrimitive() || raw.isInterface() || raw.isAnnotation()
                || Arrays.stream(prefixes).noneMatch(prefix -> raw.getPackageName().equals(prefix)
                || raw.getPackageName().startsWith(prefix + "."))) return;
        names.add(raw.getName());
    }

    private static JsonNode readSamples() throws Exception {
        String path = System.getProperty("verify.dto.samples", "");
        if (path.isBlank()) return REPORT.createObjectNode();
        JsonNode samples = REPORT.readTree(Path.of(path).toFile());
        check(samples != null && samples.isObject(), "verify.dto.samples must contain a JSON object keyed by DTO class name");
        return samples;
    }

    private static Object dummy(JavaType type, ObjectMapper mapper, Set<String> visiting) throws Exception {
        Class<?> raw = type.getRawClass();
        if (raw == String.class || raw == CharSequence.class) return "sample";
        if (raw == boolean.class || raw == Boolean.class) return true;
        if (raw == char.class || raw == Character.class) return 'x';
        if (raw == byte.class || raw == Byte.class) return (byte) 7;
        if (raw == short.class || raw == Short.class) return (short) 7;
        if (raw == int.class || raw == Integer.class) return 7;
        if (raw == long.class || raw == Long.class) return 7L;
        if (raw == float.class || raw == Float.class) return 7.5f;
        if (raw == double.class || raw == Double.class) return 7.5d;
        if (raw == BigDecimal.class) return new BigDecimal("7.50");
        if (raw == BigInteger.class) return BigInteger.valueOf(7);
        if (raw == UUID.class) return UUID.fromString("00000000-0000-0000-0000-000000000007");
        if (raw == Instant.class) return Instant.parse(FIXED_INSTANT);
        if (raw == LocalDate.class) return LocalDate.of(2020, 1, 2);
        if (raw == LocalDateTime.class) return LocalDateTime.of(2020, 1, 2, 3, 4, 5);
        if (raw == LocalTime.class) return LocalTime.of(3, 4, 5);
        if (raw == OffsetDateTime.class) return OffsetDateTime.parse(FIXED_INSTANT);
        if (raw == ZonedDateTime.class) return ZonedDateTime.parse(FIXED_INSTANT);
        if (raw == OffsetTime.class) return OffsetTime.parse("03:04:05Z");
        if (raw == Duration.class) return Duration.ofSeconds(7);
        if (raw == Period.class) return Period.ofDays(7);
        if (raw == Date.class) return Date.from(Instant.parse(FIXED_INSTANT));
        if (raw == java.sql.Date.class) return java.sql.Date.valueOf("2020-01-02");
        if (raw == java.sql.Timestamp.class) return java.sql.Timestamp.from(Instant.parse(FIXED_INSTANT));
        if (raw == URI.class) return URI.create("https://example.test/sample");
        if (raw == URL.class) return URI.create("https://example.test/sample").toURL();
        if (raw.isEnum()) {
            check(raw.getEnumConstants().length > 0, "Empty enum: " + raw.getName());
            return raw.getEnumConstants()[0];
        }
        check(raw != Object.class, "Unresolved generic/Object type; provide a DTO sample");
        String key = type.toCanonical();
        if (!visiting.add(key)) return null; // Finite, deterministic recursive fixture.
        try {
            if (raw.isArray()) {
                Object array = Array.newInstance(raw.getComponentType(), 1);
                Array.set(array, 0, dummy(type.getContentType(), mapper, visiting));
                return array;
            }
            if (Optional.class.isAssignableFrom(raw)) {
                return Optional.ofNullable(dummy(type.containedTypeOrUnknown(0), mapper, visiting));
            }
            if (Collection.class.isAssignableFrom(raw)) {
                Collection<Object> collection;
                if (raw == SortedSet.class || raw == NavigableSet.class) collection = new TreeSet<>();
                else if (raw == Set.class) collection = new LinkedHashSet<>();
                else if (raw == List.class || raw == Collection.class) collection = new ArrayList<>();
                else collection = (Collection<Object>) raw.getDeclaredConstructor().newInstance();
                collection.add(dummy(type.getContentType(), mapper, visiting));
                return collection;
            }
            if (Map.class.isAssignableFrom(raw)) {
                Map<Object, Object> map;
                if (raw == SortedMap.class || raw == NavigableMap.class) map = new TreeMap<>();
                else if (raw == Map.class) map = new LinkedHashMap<>();
                else map = (Map<Object, Object>) raw.getDeclaredConstructor().newInstance();
                map.put(dummy(type.getKeyType(), mapper, visiting), dummy(type.getContentType(), mapper, visiting));
                return map;
            }
            if (raw.isRecord()) {
                RecordComponent[] components = raw.getRecordComponents();
                Class<?>[] parameterTypes = Arrays.stream(components).map(RecordComponent::getType).toArray(Class<?>[]::new);
                Constructor<?> constructor = raw.getDeclaredConstructor(parameterTypes);
                constructor.setAccessible(true);
                Object[] arguments = new Object[components.length];
                for (int i = 0; i < components.length; i++) {
                    arguments[i] = dummy(mapper.getTypeFactory().resolveMemberType(components[i].getGenericType(), type.getBindings()), mapper, visiting);
                }
                return constructor.newInstance(arguments);
            }
            check(!raw.getPackageName().startsWith("java."), "Unsupported JDK value: " + raw.getName());
            Constructor<?> constructor = raw.getDeclaredConstructor();
            constructor.setAccessible(true);
            Object instance = constructor.newInstance();
            for (Class<?> parent = raw; parent != Object.class; parent = parent.getSuperclass()) {
                JavaType parentType = type.findSuperType(parent);
                for (Field field : parent.getDeclaredFields()) {
                    if (Modifier.isStatic(field.getModifiers()) || field.isSynthetic()) continue;
                    check(!Modifier.isFinal(field.getModifiers()), "Final DTO field needs an explicit sample: " + field);
                    field.setAccessible(true);
                    field.set(instance, dummy(mapper.getTypeFactory().resolveMemberType(field.getGenericType(), parentType.getBindings()), mapper, visiting));
                }
            }
            return instance;
        } finally {
            visiting.remove(key);
        }
    }

    private static ObjectNode smoke(ConfigurableApplicationContext context, Collection<Mapping> mappings) throws Exception {
        List<Filter> filters = new ArrayList<>(context.getBeansOfType(Filter.class).values());
        AnnotationAwareOrderComparator.sort(filters);
        MockMvc mvc = MockMvcBuilders.webAppContextSetup((WebApplicationContext) context)
                .addFilters(filters.toArray(Filter[]::new)).build();
        SortedSet<String> paths = new TreeSet<>();
        paths.add("/actuator/health");
        List<String> explicit = csv("verify.get.paths", "");
        if (!explicit.isEmpty()) paths.addAll(explicit);
        else {
            for (Mapping mapping : mappings) {
                RequestMappingInfo info = mapping.info();
                if (!info.getMethodsCondition().getMethods().contains(RequestMethod.GET)) continue;
                if (!info.getParamsCondition().isEmpty() || !info.getHeadersCondition().isEmpty()) continue;
                for (String path : info.getPatternValues()) {
                    if (!path.contains("{") && !path.contains("*") && !path.equals("/error")
                            && !path.startsWith("/actuator")) paths.add(path);
                }
            }
        }
        check(paths.size() > 1, "Configure verify.get.paths with at least one application GET API (besides health)");
        ObjectNode results = REPORT.createObjectNode();
        for (String path : paths) {
            check(path.startsWith("/"), "GET path must start with /: " + path);
            MvcResult response = mvc.perform(get(URI.create(path)).accept("application/json")).andReturn();
            check(!response.getRequest().isAsyncStarted(), "Async GET needs a custom probe: " + path);
            int status = response.getResponse().getStatus();
            check(status >= 200 && status < 300, "GET smoke failed: " + path + " returned " + status);
            byte[] body = response.getResponse().getContentAsByteArray();
            check(body.length > 0, "GET must return JSON: " + path);
            JsonNode json = REPORT.readTree(body);
            check(json != null, "Invalid JSON response: " + path);
            ObjectNode result = results.putObject(path);
            result.put("status", status);
            result.set("body", normalized(json));
        }
        return results;
    }

    static JsonNode normalized(JsonNode original) {
        JsonNode value = original.deepCopy();
        for (String pointer : csv("verify.ignore.json.pointers", "")) {
            check(pointer.startsWith("/"), "Exclusions must be RFC 6901 JSON pointers: " + pointer);
            int slash = pointer.lastIndexOf('/');
            JsonNode parent = slash == 0 ? value : value.at(pointer.substring(0, slash));
            String leaf = pointer.substring(slash + 1).replace("~1", "/").replace("~0", "~");
            if (parent.isObject()) ((ObjectNode) parent).remove(leaf);
            else if (parent.isArray() && leaf.matches("0|[1-9][0-9]*")) ((ArrayNode) parent).remove(Integer.parseInt(leaf));
        }
        return value;
    }

    static void assertSame(JsonNode expected, JsonNode actual, String path) {
        if (Objects.equals(expected, actual)) return;
        if (expected != null && actual != null && expected.isObject() && actual.isObject()) {
            SortedSet<String> fields = new TreeSet<>();
            expected.fieldNames().forEachRemaining(fields::add);
            actual.fieldNames().forEachRemaining(fields::add);
            for (String field : fields) assertSame(expected.get(field), actual.get(field), path + "/" + field.replace("~", "~0").replace("/", "~1"));
        } else if (expected != null && actual != null && expected.isArray() && actual.isArray() && expected.size() == actual.size()) {
            for (int i = 0; i < expected.size(); i++) assertSame(expected.get(i), actual.get(i), path + "/" + i);
        }
        throw new AssertionError("Fingerprint mismatch at " + path + "\nexpected: " + abbreviated(expected) + "\nactual:   " + abbreviated(actual));
    }

    private static String abbreviated(JsonNode value) {
        String text = Objects.toString(value, "<missing>");
        return text.length() > 800 ? text.substring(0, 800) + "..." : text;
    }

    private static String required(String key) {
        String value = System.getProperty(key, "");
        check(!value.isBlank(), "Missing -P" + key);
        return value;
    }

    private static List<String> csv(String key, String fallback) {
        return Arrays.stream(System.getProperty(key, fallback).split(","))
                .map(String::trim).filter(value -> !value.isEmpty()).toList();
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
