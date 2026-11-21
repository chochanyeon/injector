"""Two small apps showing a downstream change behind an unchanged response."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sys
from urllib.request import ProxyHandler, Request, build_opener


role = sys.argv[1]


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"status": "ready"})
        else:
            self.send_error(404)

    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if role == "catalog" and self.path == "/lookup":
            self.reply(200, {"available": True})
        elif role == "orders" and self.path == "/orders":
            if os.environ.get("DEMO_SKIP_LOOKUP") != "1":
                body = json.dumps({"product": value["product"], "warehouse": os.environ["DEMO_WAREHOUSE"],
                                   "internalNote": "not selected for observation"}).encode("utf-8")
                request = Request(os.environ["CATALOG_URL"] + "lookup", data=body,
                                  headers={"Content-Type": "application/json"})
                with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
                    response.read()
            self.reply(201, {"accepted": True})
        else:
            self.send_error(404)


if __name__ == "__main__":
    with HTTPServer(("127.0.0.1", int(os.environ["DEMO_PORT"])), Handler) as server:
        server.serve_forever()
