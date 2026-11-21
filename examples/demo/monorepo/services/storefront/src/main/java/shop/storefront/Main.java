package shop.storefront;

import redis.clients.jedis.JedisPooled;
import shop.common.Api;

import java.util.Map;

public final class Main {
    public static void main(String[] args) throws Exception {
        JedisPooled redis = new JedisPooled(Api.env("REDIS_HOST"), Api.port("REDIS_PORT"));
        Api.serve((exchange, method, path) -> {
            if (method.equals("POST") && path.equals("/checkout")) {
                var order = Api.request("ORDERS_URL", "/orders", Api.body(exchange));
                redis.incr("shop:checkout-count");
                Api.reply(exchange, 201, order);
            } else if (method.equals("GET") && path.startsWith("/items/")) {
                String sku = Api.id(path.substring("/items/".length()));
                Api.reply(exchange, 200, Api.request("CATALOG_URL", "/items/" + sku, null));
            } else if (method.equals("GET") && path.startsWith("/deliveries/")) {
                String id = Api.id(path.substring("/deliveries/".length()));
                Api.reply(exchange, 200, Api.request("NOTIFICATIONS_URL", "/deliveries/" + id, null));
            } else if (method.equals("GET") && path.equals("/metrics")) {
                String count = redis.get("shop:checkout-count");
                Api.reply(exchange, 200, Map.of("checkouts", count == null ? 0 : Long.parseLong(count)));
            } else {
                throw new Api.Problem(404, "Unknown storefront route");
            }
        });
    }
}
