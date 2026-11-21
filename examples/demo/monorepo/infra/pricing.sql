CREATE TABLE prices (
    sku TEXT PRIMARY KEY,
    unit_cents INTEGER NOT NULL CHECK (unit_cents >= 0)
);

INSERT INTO prices (sku, unit_cents) VALUES ('sample', 1299);
