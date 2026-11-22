package shop.storefront;

import redis.clients.jedis.JedisPooled;
import shop.common.Api;
import shop.common.VaultSettings;

import java.util.Map;

public final class Main {
    public static void main(String[] args) throws Exception {
        String checkoutCounterKey = VaultSettings.load().text("checkoutCounterKey");
        JedisPooled redis = new JedisPooled(Api.env("REDIS_HOST"), Api.port("REDIS_PORT"));
        Api.serve((exchange, method, path) -> {
            if (method.equals("POST") && path.equals("/checkout")) {
                var order = Api.request("orders", "/orders", Api.body(exchange));
                redis.incr(checkoutCounterKey);
                Api.reply(exchange, 201, order);
            } else if (method.equals("GET") && path.startsWith("/items/")) {
                String sku = Api.id(path.substring("/items/".length()));
                Api.reply(exchange, 200, Api.request("catalog", "/items/" + sku, null));
            } else if (method.equals("GET") && path.startsWith("/deliveries/")) {
                String id = Api.id(path.substring("/deliveries/".length()));
                Api.reply(exchange, 200, Api.request("notifications", "/deliveries/" + id, null));
            } else if (method.equals("GET") && path.equals("/metrics")) {
                String count = redis.get(checkoutCounterKey);
                Api.reply(exchange, 200, Map.of("checkouts", count == null ? 0 : Long.parseLong(count)));
            } else {
                throw new Api.Problem(404, "Unknown storefront route");
            }
        });
    }
}
