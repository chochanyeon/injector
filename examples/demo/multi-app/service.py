"""Small HTTP applications that exercise sharing and replacing dependencies."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sqlite3
import sys
from urllib.request import ProxyHandler, build_opener


def increment(source):
    with sqlite3.connect(os.environ["DEMO_DATABASE"]) as database:
        database.execute("INSERT INTO visits (app, count) VALUES (?, 1) "
                         "ON CONFLICT(app) DO UPDATE SET count = count + 1", (source,))
        return dict(database.execute("SELECT app, count FROM visits"))


def main():
    role = sys.argv[1]
    if role == "fail":
        return 2
    if role == "db":
        with sqlite3.connect(os.environ["DEMO_DATABASE"]) as database:
            database.execute("CREATE TABLE IF NOT EXISTS visits (app TEXT PRIMARY KEY, count INTEGER)")
    opener = build_opener(ProxyHandler({}))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                result = {"ready": role}
            elif self.path == "/product" and role == "catalog":
                result = {"source": "real", "counts": increment(role)}
            elif self.path == "/product" and role == "mock":
                result = {"source": "mock"}
            elif self.path == "/order" and role == "orders":
                with opener.open(os.environ["CATALOG_URL"] + "product", timeout=3) as response:
                    product = json.load(response)
                result = {"product": product, "counts": increment(role)}
            else:
                self.send_error(404)
                return
            body = json.dumps(result).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with HTTPServer(("127.0.0.1", int(os.environ["DEMO_PORT"])), Handler) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
