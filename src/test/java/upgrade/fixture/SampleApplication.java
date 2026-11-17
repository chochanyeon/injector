package upgrade.fixture;

import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.context.annotation.Import;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.apache.commons.codec.digest.DigestUtils;

import java.time.Instant;
import java.util.UUID;

/** An isolated demonstration backend; production source is never needed or modified. */
@SpringBootConfiguration
@EnableAutoConfiguration
@Import(SampleApplication.SampleController.class)
public class SampleApplication {
    public record SampleDto(String name, int count, Instant createdAt, UUID id, String checksum) { }

    @RestController
    public static class SampleController {
        @GetMapping("/api/sample")
        public SampleDto sample() {
            return new SampleDto("sample", 7, Instant.parse("2020-01-02T03:04:05Z"),
                    UUID.fromString("00000000-0000-0000-0000-000000000007"), DigestUtils.sha256Hex("sample"));
        }
    }
}
