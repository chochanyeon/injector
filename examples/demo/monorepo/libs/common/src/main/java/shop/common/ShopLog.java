package shop.common;

import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Semaphore;

public final class ShopLog {
    private static final Semaphore IN_FLIGHT = new Semaphore(16);

    private ShopLog() {}

    public static void write(String event, String requestId, Map<String, ?> details) {
        if (!IN_FLIGHT.tryAcquire()) {
            return;
        }
        try {
            var entry = Api.JSON.createObjectNode().put("event", event);
            if (requestId != null) {
                entry.put("requestId", requestId);
            }
            entry.set("details", Api.JSON.valueToTree(details));
            Instant now = Instant.now();
            String timestamp = Long.toString(now.getEpochSecond() * 1_000_000_000L + now.getNano());
            var stream = Map.of("stream", Map.of("app", "injector-shop", "service", Api.env("SHOP_SERVICE")),
                    "values", List.of(List.of(timestamp, entry.toString())));
            var request = HttpRequest.newBuilder(Api.url("LOKI_URL", "/loki/api/v1/push"))
                    .timeout(Duration.ofSeconds(3)).header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(Api.JSON.writeValueAsString(Map.of("streams", List.of(stream)))))
                    .build();
            Api.CLIENT.sendAsync(request, HttpResponse.BodyHandlers.discarding()).whenComplete((response, error) -> {
                IN_FLIGHT.release();
                if (error != null || response.statusCode() != 204) {
                    System.err.println("Could not deliver demo log to Loki");
                }
            });
        } catch (Exception error) {
            IN_FLIGHT.release();
            System.err.println("Could not prepare demo log for Loki");
        }
    }
}
