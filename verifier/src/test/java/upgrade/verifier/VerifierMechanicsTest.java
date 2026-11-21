package upgrade.verifier;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.jar.JarEntry;
import java.util.jar.JarOutputStream;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import org.springframework.context.ConfigurableApplicationContext;

import static org.junit.jupiter.api.Assertions.*;

class VerifierMechanicsTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    @TempDir Path temporary;

    public static class BeanCountProbe implements UpgradeConsistencyVerifierTest.RuntimeProbe {
        @Override
        public JsonNode fingerprint(ConfigurableApplicationContext context) {
            return JsonNodeFactory.instance.objectNode().put("count", (long) context.getBeanDefinitionCount());
        }
    }

    @Test
    void comparesJsonStructurallyButPreservesArrayOrderAndValues() throws Exception {
        UpgradeConsistencyVerifierTest.assertSame(JSON.readTree("{\"a\":1,\"b\":2}"),
                JSON.readTree("{\"b\":2,\"a\":1}"), "/");
        AssertionError error = assertThrows(AssertionError.class, () ->
                UpgradeConsistencyVerifierTest.assertSame(JSON.readTree("{\"a\":[1,2]}"),
                        JSON.readTree("{\"a\":[2,1]}"), "/fingerprint"));
        assertTrue(error.getMessage().contains("/fingerprint/a/0"));
        assertThrows(AssertionError.class, () -> UpgradeConsistencyVerifierTest.assertSame(
                JSON.readTree("{\"a\":null}"), JSON.readTree("{}"), "/"));
    }

    @Test
    void removesOnlyExplicitJsonPointersWithoutMutatingInput() throws Exception {
        withProperty("verify.ignore.json.pointers", "/volatile,/nested/a~1b", () -> {
            var original = JSON.readTree("{\"volatile\":12,\"stable\":7,\"nested\":{\"a/b\":3,\"ok\":true}}");
            var normalized = UpgradeConsistencyVerifierTest.normalized(original);
            assertTrue(original.has("volatile"));
            assertFalse(normalized.has("volatile"));
            assertTrue(normalized.path("nested").path("ok").asBoolean());
            assertFalse(normalized.path("nested").has("a/b"));
        });
    }

    @Test
    void appliesExclusionsToOriginalArrayIndexes() throws Exception {
        var original = JSON.readTree("{\"items\":[\"A\",\"B\",{\"hide\":1,\"keep\":2}]}");
        var expected = JSON.readTree("{\"items\":[{\"keep\":2}]}");
        for (String order : List.of("/items/0,/items/1,/items/2/hide,/items/1",
                                    "/items/2/hide,/items/1,/items/0")) {
            withProperty("verify.ignore.json.pointers", order, () ->
                    assertEquals(expected, UpgradeConsistencyVerifierTest.normalized(original)));
        }
        assertEquals(3, original.path("items").size());
        assertTrue(original.path("items").get(2).has("hide"));
    }

    @Test
    void detectsMixedVersionsForAnyLibraryIncludingLocalJarMetadata() throws Exception {
        Path first = jar("widget-one.jar", "example.backend", "widget", "1.0");
        Path second = jar("widget-two.jar", "example.backend", "widget", "2.0");
        classpath(List.of(Map.of("file", first.toString()), Map.of("file", second.toString())), () -> {
            var error = assertThrows(AssertionError.class, UpgradeConsistencyVerifierTest::inspectClasspath);
            assertTrue(error.getMessage().contains("example.backend:widget"));
        });
    }

    @Test
    void independentModulesMayHaveDifferentVersionsUnlessAlignmentIsRequired() throws Exception {
        Path first = jar("alpha.jar", "example.backend", "alpha", "1.0");
        Path second = jar("beta.jar", "example.backend", "beta", "2.0");
        classpath(List.of(Map.of("file", first.toString()), Map.of("file", second.toString())), () -> {
            assertEquals(2, UpgradeConsistencyVerifierTest.inspectClasspath().size());
            withProperty("verify.alignment.groups", "example\\.backend", () -> {
                var error = assertThrows(AssertionError.class, UpgradeConsistencyVerifierTest::inspectClasspath);
                assertTrue(error.getMessage().contains("alignment violation"));
            });
        });
    }

    @Test
    void opaqueJarsAndUnmatchedAlignmentRulesFailClosed() throws Exception {
        Path opaque = jar("opaque.jar", null, null, null);
        classpath(List.of(Map.of("file", opaque.toString())), () -> {
            assertThrows(AssertionError.class, UpgradeConsistencyVerifierTest::inspectClasspath);
        });
        Path known = jar("known.jar", "example", "known", "1");
        classpath(List.of(Map.of("file", known.toString())), () ->
                withProperty("verify.alignment.groups", "nonexistent", () -> {
                    assertThrows(AssertionError.class, UpgradeConsistencyVerifierTest::inspectClasspath);
                }));
    }

    private Path jar(String name, String group, String artifact, String version) throws Exception {
        Path path = temporary.resolve(name);
        try (JarOutputStream jar = new JarOutputStream(Files.newOutputStream(path))) {
            if (group != null) {
                jar.putNextEntry(new JarEntry("META-INF/maven/" + group + "/" + artifact + "/pom.properties"));
                Properties properties = new Properties();
                properties.setProperty("groupId", group);
                properties.setProperty("artifactId", artifact);
                properties.setProperty("version", version);
                properties.store(jar, null);
                jar.closeEntry();
            }
        }
        return path;
    }

    private void classpath(List<Map<String, String>> entries, Checked operation) throws Exception {
        Path metadata = temporary.resolve("classpath.json");
        JSON.writeValue(metadata.toFile(), entries);
        withProperty("verify.classpath.file", metadata.toString(), operation);
    }

    private static void withProperty(String key, String value, Checked operation) throws Exception {
        String previous = System.getProperty(key);
        System.setProperty(key, value);
        try { operation.run(); }
        finally {
            if (previous == null) System.clearProperty(key);
            else System.setProperty(key, previous);
        }
    }

    private interface Checked { void run() throws Exception; }
}
