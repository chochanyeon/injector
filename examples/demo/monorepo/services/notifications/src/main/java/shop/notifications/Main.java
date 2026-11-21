package shop.notifications;

import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.StringDeserializer;
import redis.clients.jedis.JedisPooled;
import shop.common.Api;
import shop.common.ShopLog;
import shop.common.VaultSettings;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;

public final class Main {
    public static void main(String[] args) throws Exception {
        var settings = VaultSettings.load();
        String topic = settings.text("orderTopic");
        int ttl = settings.seconds("cacheTtlSeconds");
        JedisPooled redis = new JedisPooled(Api.env("REDIS_HOST"), Api.port("REDIS_PORT"));
        var consumer = new KafkaConsumer<String, String>(Map.of(
                "bootstrap.servers", Api.broker(),
                "group.id", "injector-shop-notifications", "auto.offset.reset", "earliest",
                "enable.auto.commit", "false"), new StringDeserializer(), new StringDeserializer());
        Thread worker = new Thread(() -> {
            try (consumer) {
                consumer.subscribe(List.of(topic));
                while (true) {
                    var events = consumer.poll(Duration.ofMillis(500));
                    for (var event : events) {
                        redis.setex("shop:delivery:" + event.key(), ttl, event.value());
                        var header = event.headers().lastHeader(Api.REQUEST_ID);
                        String requestId = header == null || header.value() == null
                                ? null : new String(header.value(), StandardCharsets.UTF_8);
                        ShopLog.write("notification_stored", requestId, Map.of("orderId", event.key()));
                    }
                    if (!events.isEmpty()) {
                        consumer.commitSync();
                    }
                }
            } catch (RuntimeException error) {
                System.err.println("Kafka consumer stopped: " + error.getClass().getSimpleName());
            }
        }, "order-events");
        worker.setDaemon(true);
        worker.start();
        Api.serve((exchange, method, path) -> {
            if (!method.equals("GET") || !path.startsWith("/deliveries/")) {
                throw new Api.Problem(404, "Unknown notifications route");
            }
            if (!worker.isAlive()) {
                throw new Api.Problem(503, "Kafka consumer stopped");
            }
            String id = Api.id(path.substring("/deliveries/".length()));
            String event = redis.get("shop:delivery:" + id);
            if (event == null) {
                throw new Api.Problem(404, "Delivery is pending");
            }
            Api.reply(exchange, 200, Map.of("status", "delivered", "order", Api.JSON.readTree(event)));
        });
    }
}
