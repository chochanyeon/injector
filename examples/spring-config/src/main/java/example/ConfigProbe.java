package example;

import java.util.List;
import java.util.Map;
import java.util.Objects;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.bind.Bindable;
import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.core.env.Environment;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootApplication
@RestController
public class ConfigProbe {
    private final Environment environment;

    public ConfigProbe(Environment environment) {
        this.environment = environment;
    }

    public static void main(String[] args) {
        SpringApplication.run(ConfigProbe.class, args);
    }

    @GetMapping("/probe")
    public Map<String, Object> probe() {
        return Map.of(
                "message", environment.getRequiredProperty("probe.message"),
                "vmOnly", System.getProperty("probe.vm-only", "missing"),
                "yamlIsNotSystemProperty", System.getProperty("probe.message") == null,
                "labels", Binder.get(environment).bind("probe.labels", Bindable.listOf(String.class)).orElse(List.of()),
                "secretMatchesEnvironment", System.getenv("PROBE_SECRET") != null
                        && Objects.equals(environment.getProperty("probe.secret"), System.getenv("PROBE_SECRET")));
    }
}
