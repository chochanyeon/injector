CREATE TABLE stock (
    sku TEXT PRIMARY KEY,
    available INTEGER NOT NULL CHECK (available >= 0)
);

CREATE TABLE orders (
    id TEXT PRIMARY KEY,
    sku TEXT NOT NULL REFERENCES stock(sku),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
    published BOOLEAN NOT NULL DEFAULT FALSE
);

INSERT INTO stock (sku, available) VALUES ('sample', 10);
