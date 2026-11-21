package shop.inventory;

import shop.common.Api;
import shop.common.VaultSettings;

import java.util.Map;

public final class Main {
    public static void main(String[] args) throws Exception {
        String dbUser = VaultSettings.load().text("dbUser");
        Api.serve((exchange, method, path) -> {
            if (method.equals("GET") && path.startsWith("/stock/")) {
                String sku = Api.id(path.substring("/stock/".length()));
                try (var db = Api.database(dbUser);
                     var query = db.prepareStatement("SELECT available FROM stock WHERE sku = ?")) {
                    query.setString(1, sku);
                    try (var rows = query.executeQuery()) {
                        if (!rows.next()) {
                            throw new Api.Problem(404, "SKU not found");
                        }
                        Api.reply(exchange, 200, Map.of("sku", sku, "available", rows.getInt(1)));
                    }
                }
            } else {
                throw new Api.Problem(404, "Unknown inventory route");
            }
        });
    }
}
