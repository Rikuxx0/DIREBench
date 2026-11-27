"""Dummy HTTP workload. Only stdlib and experiment-only resources are used."""
import json
import os
import sqlite3
import ssl
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROLE = os.environ.get("ROLE", "unknown")
NS = os.environ.get("POD_NAMESPACE", "direbench")
DB_FILE = "/tmp/direbench.sqlite3"


def request(url, method="GET", data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None, headers=headers, method=method)
    ctx = ssl.create_default_context(cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt") if url.startswith("https://kubernetes.default") else None
    try:
        with urllib.request.urlopen(req, timeout=2, context=ctx) as res:
            body = res.read().decode()
            return res.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode()[:300]}
    except Exception as exc:
        return 0, {"error": str(exc)}


def kube_get(kind, name):
    with open("/var/run/secrets/kubernetes.io/serviceaccount/token", encoding="utf8") as handle:
        token = handle.read()
    return request(f"https://kubernetes.default.svc/api/v1/namespaces/{NS}/{kind}/{name}", token=token)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send(self, status, body):
        raw = json.dumps(body, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path in ("/health", "/ready"):
            return self.send(200, {"role": ROLE, "ok": True})
        if ROLE == "database" and path == "/value":
            with sqlite3.connect(DB_FILE) as db:
                db.execute("CREATE TABLE IF NOT EXISTS counter (value INTEGER)")
                db.execute("INSERT INTO counter SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM counter)")
                value = db.execute("SELECT value FROM counter").fetchone()[0]
            return self.send(200, {"value": value})
        if path == "/probe-secret" and ROLE in ("adversary", "recovery"):
            status, body = kube_get("secrets", "protected-data")
            return self.send(200, {"access": status == 200, "status": status, "resourceVersion": body.get("metadata", {}).get("resourceVersion")})
        if path == "/probe-backend" and ROLE == "adversary":
            target = urllib.parse.parse_qs(query).get("target", [""])[0]
            if not target or not all(c.isdigit() or c == "." for c in target):
                return self.send(400, {"error": "target must be an IPv4 Pod address"})
            status, _ = request(f"http://{target}:8080/health")
            return self.send(200, {"access": status == 200, "status": status})
        return self.send(404, {"error": "unknown path"})

    def do_POST(self):
        if self.path != "/transaction":
            return self.send(404, {"error": "unknown path"})
        if ROLE == "database":
            with sqlite3.connect(DB_FILE) as db:
                db.execute("CREATE TABLE IF NOT EXISTS counter (value INTEGER)")
                db.execute("INSERT INTO counter SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM counter)")
                db.execute("UPDATE counter SET value=value+1")
                value = db.execute("SELECT value FROM counter").fetchone()[0]
            return self.send(200, {"value": value})
        if ROLE == "backend":
            status, body = request("http://database:8080/transaction", method="POST", data={})
            return self.send(200 if status == 200 else 503, {"downstream": status, "database": body})
        if ROLE == "frontend":
            status, body = request("http://backend:8080/transaction", method="POST", data={})
            return self.send(200 if status == 200 else 503, {"downstream": status, "backend": body})
        if ROLE in ("worker", "recovery"):
            status, _ = kube_get("configmaps", "workflow")
            if status != 200:
                return self.send(503, {"configmap_status": status})
            status, body = request("http://backend:8080/transaction", method="POST", data={})
            return self.send(200 if status == 200 else 503, {"downstream": status, "backend": body})
        return self.send(403, {"error": "not a workload"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
