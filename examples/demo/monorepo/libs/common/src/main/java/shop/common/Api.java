package shop.common;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.time.Duration;
import java.util.Map;
import java.util.UUID;

public final class Api {
    public static final ObjectMapper JSON = new ObjectMapper();
    public static final String REQUEST_ID = "X-Request-Id";
    static final HttpClient CLIENT = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(2)).version(HttpClient.Version.HTTP_1_1).build();
    private static final ThreadLocal<String> REQUEST = new ThreadLocal<>();

    private Api() {}

    public static String env(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("Missing demo setting " + name);
        }
        return value;
    }

    public static int port(String name) {
        return Integer.parseInt(env(name));
    }

    public static Connection database() throws SQLException {
        return database(env("DB_USER"));
    }

    public static Connection database(String user) throws SQLException {
        String url = "jdbc:postgresql://" + env("DB_HOST") + ":" + port("DB_PORT") + "/" + env("DB_NAME");
        return DriverManager.getConnection(url, user, env("DB_PASSWORD"));
    }

    public static String broker() {
        return env("KAFKA_HOST") + ":" + port("KAFKA_PORT");
    }

    static URI url(String address, String path) {
        return URI.create(env(address).replaceAll("/+$", "") + path);
    }

    public static String requestId() {
        return REQUEST.get();
    }

    public static String id(String value) {
        if (!value.matches("[a-zA-Z0-9-]{1,40}")) {
            throw new Problem(400, "Use an ID of 1 to 40 letters, digits or hyphens");
        }
        return value;
    }

    public static int quantity(JsonNode body) {
        JsonNode value = body.path("quantity");
        if (!value.isIntegralNumber() || !value.canConvertToInt() || value.intValue() < 1 || value.intValue() > 10) {
            throw new Problem(400, "quantity must be an integer from 1 to 10");
        }
        return value.intValue();
    }

    public static JsonNode body(HttpExchange exchange) throws IOException {
        byte[] bytes = exchange.getRequestBody().readNBytes(8193);
        if (bytes.length > 8192) {
            throw new Problem(413, "Demo requests are limited to 8 KiB");
        }
        try {
            JsonNode body = JSON.readTree(bytes);
            if (body == null || !body.isObject()) {
                throw new Problem(400, "Expected a JSON object");
            }
            return body;
        } catch (com.fasterxml.jackson.core.JacksonException error) {
            throw new Problem(400, "Invalid JSON");
        }
    }

    public static JsonNode request(String address, String path, JsonNode body) throws Exception {
        HttpRequest.Builder request = HttpRequest.newBuilder(url(address, path))
                .timeout(Duration.ofSeconds(8));
        if (requestId() != null) {
            request.header(REQUEST_ID, requestId());
        }
        if (body != null) {
            request.header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(JSON.writeValueAsBytes(body)));
        }
        HttpResponse<byte[]> response = CLIENT.send(request.build(), HttpResponse.BodyHandlers.ofByteArray());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            int status = response.statusCode();
            throw new Problem(status >= 400 && status < 500 ? status : 502, "Upstream " + address + " returned " + status);
        }
        return JSON.readTree(response.body());
    }

    public static void reply(HttpExchange exchange, int status, Object result) throws IOException {
        byte[] content = JSON.writeValueAsBytes(result);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, content.length);
        exchange.getResponseBody().write(content);
    }

    public static void serve(Route handler) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port("APP_PORT")), 0);
        server.createContext("/", exchange -> {
            String method = exchange.getRequestMethod();
            String path = exchange.getRequestURI().getPath();
            boolean health = method.equals("GET") && path.equals("/health");
            String incoming = exchange.getRequestHeaders().getFirst(REQUEST_ID);
            String requestId = incoming != null && incoming.matches("[a-zA-Z0-9_-]{1,80}")
                    ? incoming : UUID.randomUUID().toString();
            REQUEST.set(requestId);
            exchange.getResponseHeaders().set(REQUEST_ID, requestId);
            try (exchange) {
                try {
                    if (health) {
                        reply(exchange, 200, Map.of("status", "ready"));
                    } else {
                        handler.handle(exchange, method, path);
                    }
                } catch (Problem problem) {
                    reply(exchange, problem.status, Map.of("error", problem.getMessage()));
                } catch (Exception error) {
                    System.err.println("Demo request failed: " + error.getClass().getSimpleName());
                    reply(exchange, 503, Map.of("error", "Dependency unavailable"));
                }
            } finally {
                REQUEST.remove();
                if (!health && exchange.getResponseCode() >= 200) {
                    ShopLog.write("http_request", requestId,
                            Map.of("method", method, "path", path, "status", exchange.getResponseCode()));
                }
            }
        });
        server.start();
    }

    @FunctionalInterface
    public interface Route {
        void handle(HttpExchange exchange, String method, String path) throws Exception;
    }

    public static final class Problem extends RuntimeException {
        private final int status;

        public Problem(int status, String message) {
            super(message);
            this.status = status;
        }
    }
}
