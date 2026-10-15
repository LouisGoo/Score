"""Local nginx routing/TLS smoke test using an isolated stub upstream, never a database."""

import asyncio
import json
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from websockets.asyncio.client import connect


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


root = Path(__file__).resolve().parents[2]
nginx = Path(sys.argv[1]).resolve()
tls_port, plain_port, api_port = port(), port(), port()
with tempfile.TemporaryDirectory(prefix="nginx22-", dir=root / ".tools") as name:
    tmp = Path(name)
    (tmp / "html/assets").mkdir(parents=True)
    (tmp / "html/index.html").write_text("SPA_SENTINEL")
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-keyout",
            str(tmp / "privkey.pem"),
            "-out",
            str(tmp / "fullchain.pem"),
        ],
        check=True,
        capture_output=True,
    )
    conf = (root / "infra/nginx/default.conf").read_text()
    conf = conf.replace("listen 80;", f"listen 127.0.0.1:{plain_port};")
    conf = conf.replace("listen 443 ssl;", f"listen 127.0.0.1:{tls_port} ssl;")
    conf = conf.replace("/etc/nginx/tls", str(tmp))
    conf = conf.replace("/usr/share/nginx/html", str(tmp / "html"))
    conf = conf.replace("http://api:8000", f"http://127.0.0.1:{api_port}")
    conf = conf.replace("/dev/stdout", str(tmp / "failure.log"))
    config = tmp / "nginx.conf"
    config.write_text(
        f"pid {tmp}/nginx.pid;\nerror_log {tmp}/startup.log;\n"
        f"events {{}}\nhttp {{ client_body_temp_path {tmp}/body; "
        f"proxy_temp_path {tmp}/proxy; fastcgi_temp_path {tmp}/fastcgi; "
        f"uwsgi_temp_path {tmp}/uwsgi; scgi_temp_path {tmp}/scgi;\n{conf}\n}}"
    )
    subprocess.run([str(nginx), "-t", "-p", str(tmp), "-c", str(config)], check=True)
    stub = """
from fastapi import FastAPI, WebSocket, Response
import uvicorn
app = FastAPI()
@app.get('/api/v1/health/live')
def live():
    return {'status': 'ok'}
@app.get('/api/v1/failure')
def fail(response: Response):
    response.status_code = 503
    response.headers['X-Request-ID'] = 'safe-id'
    return {'error': 'unavailable'}
@app.get('/api/v1/ip')
def ip():
    return {'ok': True}
@app.websocket('/api/v1/stream')
async def ws(ws: WebSocket):
    await ws.accept()
    await ws.send_text('upgraded')
    await ws.close()
uvicorn.run(app, host='127.0.0.1', port=PORT, log_level='error')
""".replace("PORT", str(api_port))
    api = subprocess.Popen([sys.executable, "-c", stub])
    proxy = subprocess.Popen(
        [str(nginx), "-p", str(tmp), "-c", str(config), "-g", "daemon off;"]
    )
    try:
        for _ in range(100):
            try:
                if (
                    httpx.get(
                        f"http://127.0.0.1:{api_port}/api/v1/health/live"
                    ).status_code
                    == 200
                ):
                    break
            except httpx.ConnectError:
                time.sleep(0.05)
        base = f"https://127.0.0.1:{tls_port}"
        with httpx.Client(verify=False, base_url=base) as client:
            assert client.get("/admin/deep/link").text == "SPA_SENTINEL"
            assert client.get("/assets/missing.js").status_code == 404
            assert client.get("/api/v1/missing").status_code == 404
            assert (
                client.get("/api/v1/missing")
                .headers["content-type"]
                .startswith("application/json")
            )
            assert client.get("/api").status_code == 404
            assert client.get("/api/v1/health/live").json() == {"status": "ok"}
            assert client.get("/api/v1/failure?ticket=TOP_SECRET").status_code == 503

        async def websocket():
            context = ssl._create_unverified_context()
            async with connect(
                f"wss://127.0.0.1:{tls_port}/api/v1/stream?ticket=TOP_SECRET",
                ssl=context,
            ) as ws:
                assert await ws.recv() == "upgraded"

        asyncio.run(websocket())
        assert httpx.get(f"http://127.0.0.1:{plain_port}/").status_code == 404
        api.terminate()
        api.wait(timeout=5)
        with httpx.Client(verify=False, base_url=base) as client:
            assert (
                client.get("/api/v1/health/live?ticket=TOP_SECRET").status_code == 502
            )
        records = [
            json.loads(line) for line in (tmp / "failure.log").read_text().splitlines()
        ]
        assert {r["status"] for r in records} == {502, 503}
        assert "TOP_SECRET" not in (tmp / "failure.log").read_text()
        assert any(r["request_id"] == "safe-id" for r in records)
        print(
            "PASS: nginx -t, TLS, SPA/API/assets routing, WebSocket upgrade, 502/503 redacted logs"
        )
    finally:
        for process in (proxy, api):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
