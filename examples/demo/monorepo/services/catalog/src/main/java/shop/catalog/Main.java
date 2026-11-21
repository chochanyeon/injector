package shop.catalog;

import com.fasterxml.jackson.databind.node.ObjectNode;
import redis.clients.jedis.JedisPooled;
import shop.common.Api;

public final class Main {
    public static void main(String[] args) throws Exception {
        JedisPooled redis = new JedisPooled(Api.env("REDIS_HOST"), Api.port("REDIS_PORT"));
        Api.serve((exchange, method, path) -> {
            if (!method.equals("GET") || !path.startsWith("/items/")) {
                throw new Api.Problem(404, "Unknown catalog route");
            }
            String sku = Api.id(path.substring("/items/".length()));
            String key = "shop:catalog:" + sku;
            String cached = redis.get(key);
            if (cached != null) {
                Api.reply(exchange, 200, ((ObjectNode) Api.JSON.readTree(cached)).put("cache", "hit"));
            } else {
                var price = (ObjectNode) Api.request("PRICING_URL", "/prices/" + sku, null);
                redis.setex(key, 120, Api.JSON.writeValueAsString(price));
                Api.reply(exchange, 200, price.put("cache", "miss"));
            }
        });
    }
}
