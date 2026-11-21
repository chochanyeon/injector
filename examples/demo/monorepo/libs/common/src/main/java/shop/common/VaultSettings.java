package shop.common;

import com.fasterxml.jackson.databind.JsonNode;

import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

public final class VaultSettings {
    private final JsonNode values;

    private VaultSettings(JsonNode values) {
        this.values = values;
    }

    public static VaultSettings load() throws Exception {
        String service = Api.id(Api.env("SHOP_SERVICE"));
        var request = HttpRequest.newBuilder(Api.url("VAULT_URL", "/v1/secret/data/" + service))
                .timeout(Duration.ofSeconds(4)).header("X-Vault-Token", Api.env("VAULT_TOKEN")).build();
        var response = Api.CLIENT.send(request, HttpResponse.BodyHandlers.ofByteArray());
        if (response.statusCode() != 200) {
            throw new IllegalStateException("Vault settings unavailable for " + service + " (HTTP " + response.statusCode() + ")");
        }
        JsonNode envelope = Api.JSON.readTree(response.body());
        JsonNode data = envelope == null ? null : envelope.path("data").path("data");
        if (data == null || !data.isObject()) {
            throw new IllegalStateException("Invalid Vault KV v2 response for " + service);
        }
        ShopLog.write("vault_config_loaded", null, Map.of());
        return new VaultSettings(data);
    }

    public String text(String key) {
        JsonNode value = values.path(key);
        if (!value.isTextual() || value.textValue().isBlank()) {
            throw new IllegalStateException("Missing Vault setting " + key);
        }
        return value.textValue();
    }

    public int seconds(String key) {
        JsonNode value = values.path(key);
        if (!value.isIntegralNumber() || !value.canConvertToInt() || value.intValue() <= 0) {
            throw new IllegalStateException("Invalid Vault TTL " + key);
        }
        return value.intValue();
    }
}
