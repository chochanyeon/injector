package shop.orders;

import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.serialization.StringSerializer;
import shop.common.Api;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.Map;
import java.util.concurrent.TimeUnit;

public final class Main {
    private record Order(String sku, int quantity, int totalCents, boolean published) {
        Map<String, Object> json(String id) {
            return Map.of("id", id, "sku", sku, "quantity", quantity, "totalCents", totalCents);
        }
    }

    private static Order find(Connection db, String id) throws SQLException {
        try (var query = db.prepareStatement("SELECT sku, quantity, total_cents, published FROM orders WHERE id = ?")) {
            query.setString(1, id);
            try (var rows = query.executeQuery()) {
                return rows.next() ? new Order(rows.getString(1), rows.getInt(2), rows.getInt(3), rows.getBoolean(4)) : null;
            }
        }
    }

    private static void save(Connection db, String id, Order order) throws SQLException {
        db.setAutoCommit(false);
        try (var reserve = db.prepareStatement("UPDATE stock SET available = available - ? WHERE sku = ? AND available >= ?");
             var insert = db.prepareStatement("INSERT INTO orders (id, sku, quantity, total_cents) VALUES (?, ?, ?, ?)")) {
            reserve.setInt(1, order.quantity());
            reserve.setString(2, order.sku());
            reserve.setInt(3, order.quantity());
            if (reserve.executeUpdate() != 1) {
                throw new Api.Problem(409, "Insufficient stock");
            }
            insert.setString(1, id);
            insert.setString(2, order.sku());
            insert.setInt(3, order.quantity());
            insert.setInt(4, order.totalCents());
            insert.executeUpdate();
            db.commit();
        } catch (SQLException | RuntimeException error) {
            db.rollback();
            throw error;
        }
        db.setAutoCommit(true);
    }

    public static void main(String[] args) throws Exception {
        var producer = new KafkaProducer<String, String>(Map.of(
                "bootstrap.servers", Api.broker(),
                "max.block.ms", "6000"), new StringSerializer(), new StringSerializer());
        Api.serve((exchange, method, path) -> {
            if (method.equals("GET") && path.startsWith("/orders/")) {
                String id = Api.id(path.substring("/orders/".length()));
                try (var db = Api.database()) {
                    var order = find(db, id);
                    if (order == null) {
                        throw new Api.Problem(404, "Order not found");
                    }
                    Api.reply(exchange, 200, order.json(id));
                }
            } else if (method.equals("POST") && path.equals("/orders")) {
                var body = Api.body(exchange);
                String id = Api.id(body.path("id").asText());
                String sku = Api.id(body.path("sku").asText());
                int quantity = Api.quantity(body);
                try (var db = Api.database()) {
                    var order = find(db, id);
                    if (order == null) {
                        var item = Api.request("CATALOG_URL", "/items/" + sku, null);
                        var stock = Api.request("INVENTORY_URL", "/stock/" + sku, null);
                        if (stock.required("available").intValue() < quantity) {
                            throw new Api.Problem(409, "Insufficient stock");
                        }
                        order = new Order(sku, quantity, Math.multiplyExact(item.required("unitCents").intValue(), quantity), false);
                        save(db, id, order);
                    } else if (!order.sku().equals(sku) || order.quantity() != quantity) {
                        throw new Api.Problem(409, "Order ID belongs to a different request");
                    }
                    var result = order.json(id);
                    if (!order.published()) {
                        producer.send(new ProducerRecord<>(Api.ORDER_TOPIC, id, Api.JSON.writeValueAsString(result)))
                                .get(6, TimeUnit.SECONDS);
                        try (var mark = db.prepareStatement("UPDATE orders SET published = TRUE WHERE id = ?")) {
                            mark.setString(1, id);
                            mark.executeUpdate();
                        }
                    }
                    Api.reply(exchange, 201, result);
                }
            } else {
                throw new Api.Problem(404, "Unknown orders route");
            }
        });
    }
}
