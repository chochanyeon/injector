package poc;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

public class Main {
    public static void main(String[] args) throws Exception {
        String catalogUrl = System.getenv("CATALOG_URL");
        if (catalogUrl == null) {
            throw new IllegalArgumentException("CATALOG_URL is required; use a generated Injector configuration");
        }
        int port = Integer.parseInt(System.getenv().getOrDefault("APP_PORT", "18080"));
        String bind = System.getenv().getOrDefault("APP_BIND", "127.0.0.1");
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
        HttpServer server = HttpServer.create(new InetSocketAddress(bind, port), 0);
        server.createContext("/demo", exchange -> {
            String body;
            int status;
            try {
                HttpRequest request = HttpRequest.newBuilder(URI.create(catalogUrl + "/product"))
                        .timeout(Duration.ofSeconds(3)).GET().build();
                HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
                status = response.statusCode() == 200 ? 200 : 502;
                // Put a breakpoint here to inspect the injected values and downstream response.
                body = "{\"profile\":" + json(System.getProperty("injector.profile"))
                        + ",\"message\":" + json(System.getenv("DEMO_MESSAGE"))
                        + ",\"catalogUrl\":" + json(catalogUrl)
                        + ",\"downstream\":" + json(response.body()) + "}";
            } catch (Exception error) {
                status = 502;
                body = "{\"error\":" + json(error.getMessage()) + "}";
            }
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
            exchange.sendResponseHeaders(status, bytes.length);
            try (var output = exchange.getResponseBody()) {
                output.write(bytes);
            }
        });
        server.start();
        System.out.println("Main ready: http://localhost:" + port + "/demo (profile="
                + System.getProperty("injector.profile") + ")");
    }

    static String json(String value) {
        if (value == null) return "null";
        StringBuilder result = new StringBuilder("\"");
        for (char c : value.toCharArray()) {
            switch (c) {
                case '"' -> result.append("\\\"");
                case '\\' -> result.append("\\\\");
                default -> {
                    if (c < 32) result.append(String.format("\\u%04x", (int) c));
                    else result.append(c);
                }
            }
        }
        return result.append('"').toString();
    }
}
