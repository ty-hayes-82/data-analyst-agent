#!/usr/bin/env python3
"""Sync HTTP wrapper for FastAPI app.

Uvicorn does not work in this container (PID 1 is node, not init —
orphaned async processes get killed). This wrapper uses ThreadingHTTPServer
which survives daemonization via setsid/nohup.
"""
import os
import sys
import signal

# Daemonize: double-fork to fully detach from parent
if os.fork() > 0:
    sys.exit(0)
os.setsid()
if os.fork() > 0:
    sys.exit(0)

# Redirect stdio
sys.stdin = open(os.devnull, "r")
log = open("/tmp/webapp.log", "a")
sys.stdout = log
sys.stderr = log

# Write PID file
with open("/tmp/webapp.pid", "w") as f:
    f.write(str(os.getpid()))

sys.path.insert(0, "/data/data-analyst-agent")
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from starlette.testclient import TestClient
from web.app import app

client = TestClient(app)

class Handler(BaseHTTPRequestHandler):
    def _proxy(self, method):
        cl = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(cl) if cl else None
        ct = self.headers.get("content-type", "application/json")
        headers = {"content-type": ct} if body else {}
        fn = getattr(client, method)
        if body:
            response = fn(self.path, content=body, headers=headers)
        else:
            response = fn(self.path)
        self.send_response(response.status_code)
        skip = {"transfer-encoding", "content-length", "content-encoding"}
        for k, v in response.headers.items():
            if k.lower() not in skip:
                self.send_header(k, v)
        rb = response.content
        self.send_header("Content-Length", str(len(rb)))
        self.end_headers()
        self.wfile.write(rb)

    def do_GET(self): self._proxy("get")
    def do_POST(self): self._proxy("post")
    def do_PUT(self): self._proxy("put")
    def do_DELETE(self): self._proxy("delete")

    def log_message(self, fmt, *args):
        print(f"[HTTP] {fmt % args}", flush=True)

def shutdown(signum, frame):
    print("Shutting down...", flush=True)
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
print(f"Serving on 0.0.0.0:8080 (PID {os.getpid()})", flush=True)
server.serve_forever()
