package poc;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

public class Catalog {
    public static void main(String[] args) throws Exception {
        int port = Integer.parseInt(System.getenv().getOrDefault("CATALOG_PORT", "18082"));
        String bind = System.getenv().getOrDefault("APP_BIND", "127.0.0.1");
        HttpServer server = HttpServer.create(new InetSocketAddress(bind, port), 0);
        server.createContext("/product", exchange -> {
            byte[] body = "{\"id\":1,\"name\":\"local product\",\"source\":\"real\"}"
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            try (var output = exchange.getResponseBody()) {
                output.write(body);
            }
        });
        server.start();
        System.out.println("Catalog ready on port " + port);
    }
}
