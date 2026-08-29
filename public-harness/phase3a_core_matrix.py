from __future__ import annotations

import gzip
import hashlib
import json
import os
import select
import socket
import socketserver
import stat
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

RELEASES = {
    "v1.19.27": "fb3e34c55844f389ff54679e5a3aec331d5ec38006c20f8dcc476fb47768a58f",
    "v1.19.28": "d5967e079d9f793515a5a8193aabda455f7e012427eccd567dbc4f2f15498204",
    "v1.19.29": "60de76a35a6cbf7b4fa4a20f5c257c24345d1d635ab1aa3877022a1997ef413c",
    "v1.19.30": "cf06ce2c7d1421bdbda14ee4a5b6046672dc35ebf8eecd8e77504ec3c0ed9a84",
}


class TargetHandler(BaseHTTPRequestHandler):
    def _reply(self, *, head: bool = False) -> None:
        status = 204 if self.path == "/health" else 200
        self.send_response(status)
        if status == 200:
            self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if status == 200 and not head:
            self.wfile.write(b"ok")

    def do_GET(self) -> None:  # noqa: N802
        self._reply()

    def do_HEAD(self) -> None:  # noqa: N802
        self._reply(head=True)

    def log_message(self, format: str, *args: object) -> None:
        return


class ReusableTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class SocksHandler(socketserver.BaseRequestHandler):
    label = "unknown"
    connection_log: list[tuple[str, str, int]] = []

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("unexpected EOF")
            data.extend(chunk)
        return bytes(data)

    def handle(self) -> None:
        client = self.request
        upstream: socket.socket | None = None
        try:
            header = self._recv_exact(client, 2)
            if header[0] != 5:
                return
            self._recv_exact(client, header[1])
            client.sendall(b"\x05\x00")
            request = self._recv_exact(client, 4)
            if request[0] != 5 or request[1] != 1:
                return
            atyp = request[3]
            if atyp == 1:
                host = socket.inet_ntoa(self._recv_exact(client, 4))
            elif atyp == 3:
                length = self._recv_exact(client, 1)[0]
                host = self._recv_exact(client, length).decode("idna")
            elif atyp == 4:
                host = socket.inet_ntop(socket.AF_INET6, self._recv_exact(client, 16))
            else:
                return
            port = int.from_bytes(self._recv_exact(client, 2), "big")
            type(self).connection_log.append((type(self).label, host, port))
            upstream = socket.create_connection((host, port), timeout=5)
            client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            sockets = [client, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [], 5)
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    destination = upstream if source is client else client
                    destination.sendall(data)
        except (ConnectionError, OSError, TimeoutError):
            try:
                client.sendall(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
            except OSError:
                pass
        finally:
            if upstream is not None:
                try:
                    upstream.close()
                except OSError:
                    pass


def start_socks(label: str) -> tuple[ReusableTCPServer, threading.Thread, type[SocksHandler]]:
    handler = type(
        f"{label.replace('-', '_')}_Handler",
        (SocksHandler,),
        {"label": label, "connection_log": []},
    )
    server = ReusableTCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, handler


def allocate_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_json(port: int, path: str) -> dict[str, object]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
        return json.load(response)


def wait_ready(port: int, process: subprocess.Popen[str], timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Mihomo exited early: {process.returncode}")
        try:
            get_json(port, "/version")
            return
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(0.1)
    raise RuntimeError(f"Mihomo controller did not become ready: {last}")


def group(port: int, name: str) -> dict[str, object]:
    return get_json(port, f"/proxies/{urllib.parse.quote(name, safe='')}")


def wait_now(port: int, name: str, expected: set[str], timeout: float = 12) -> str:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        payload = group(port, name)
        last = str(payload.get("now") or "")
        if last in expected:
            return last
        time.sleep(0.2)
    raise AssertionError(f"{name} did not select {sorted(expected)}; now={last!r}")


def proxy_request(listener: int, target_port: int) -> int:
    with socket.create_connection(("127.0.0.1", listener), timeout=5) as sock:
        request = (
            f"GET http://127.0.0.1:{target_port}/ok HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{target_port}\r\n"
            "Connection: close\r\n\r\n"
        )
        sock.sendall(request.encode())
        data = bytearray()
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data.extend(chunk)
    first = bytes(data).split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    parts = first.split()
    if len(parts) < 2:
        raise AssertionError(f"invalid HTTP response: {first!r}")
    return int(parts[1])


def ai_provider(nodes: list[dict[str, object]], health_url: str) -> dict[str, object]:
    return {
        "type": "inline",
        "payload": nodes,
        "health-check": {
            "enable": True,
            "url": health_url,
            "interval": 1,
            "timeout": 3000,
            "lazy": False,
            "expected-status": 204,
        },
    }


def url_test(name: str, health_url: str, filter_value: str, *, exclude: str = "") -> dict[str, object]:
    result: dict[str, object] = {
        "name": name,
        "type": "url-test",
        "hidden": True,
        "use": ["AI"],
        "filter": filter_value,
        "empty-fallback": "REJECT",
        "url": health_url,
        "expected-status": 204,
        "interval": 1,
        "timeout": 3000,
        "tolerance": 5,
    }
    if exclude:
        result["exclude-filter"] = exclude
    return result


def fallback(name: str, proxies: list[str], health_url: str) -> dict[str, object]:
    return {
        "name": name,
        "type": "fallback",
        "hidden": True,
        "proxies": proxies,
        "empty-fallback": "REJECT",
        "url": health_url,
        "expected-status": 204,
        "interval": 1,
        "timeout": 3000,
    }


def build_config(
    *,
    controller: int,
    listener: int,
    health_url: str,
    nodes: list[dict[str, object]],
) -> dict[str, object]:
    universal = r"^\[AI:[^]]*U[^]]*\].*"
    universal_groups = ["🇯🇵 AI AUTO", "🇸🇬 AI AUTO", "🇺🇸 AI AUTO", "🌍 AI AUTO"]
    groups: list[dict[str, object]] = [
        {
            "name": "🤖 AI",
            "type": "select",
            "proxies": ["🤖 AI SERVICE-FALLBACK", *universal_groups],
            "empty-fallback": "REJECT",
        },
        fallback("🤖 AI SERVICE-FALLBACK", universal_groups, health_url),
        url_test("🇯🇵 AI AUTO", health_url, universal + r"(?i:🇯🇵|日本|JP|JPN|NRT|KIX)"),
        url_test("🇸🇬 AI AUTO", health_url, universal + r"(?i:🇸🇬|新加坡|SG|SGP|SIN)"),
        url_test("🇺🇸 AI AUTO", health_url, universal + r"(?i:🇺🇸|美国|US|USA|LAX|SJC|SFO|SEA|NYC|JFK|IAD)"),
        url_test(
            "🌍 AI AUTO",
            health_url,
            universal + r".+",
            exclude=r"(?i:🇯🇵|日本|JP|JPN|NRT|KIX|🇸🇬|新加坡|SG|SGP|SIN|🇺🇸|美国|US|USA|LAX|SJC|SFO|SEA|NYC|JFK|IAD)",
        ),
        {
            "name": "🤖 ChatGPT",
            "type": "select",
            "hidden": True,
            "proxies": ["🤖 ChatGPT SERVICE-FALLBACK"],
            "empty-fallback": "REJECT",
        },
        fallback(
            "🤖 ChatGPT SERVICE-FALLBACK",
            [*universal_groups, "🤖 ChatGPT NON-U AUTO"],
            health_url,
        ),
        url_test(
            "🤖 ChatGPT NON-U AUTO",
            health_url,
            r"^\[AI:[^]]*O[^]]*\].*.+",
            exclude=r"^\[AI:[^]]*U[^]]*\]",
        ),
    ]
    return {
        "external-controller": f"127.0.0.1:{controller}",
        "log-level": "warning",
        "proxy-providers": {"AI": ai_provider(nodes, health_url)},
        "proxy-groups": groups,
        "listeners": [
            {"name": "phase3a", "type": "mixed", "port": listener, "proxy": "🤖 ChatGPT"}
        ],
        "rules": ["MATCH,DIRECT"],
    }


def node(name: str, port: int) -> dict[str, object]:
    return {
        "name": name,
        "type": "socks5",
        "server": "127.0.0.1",
        "port": port,
    }


def run_scenario(binary: Path, target_port: int, u_port: int, nonu_port: int, *, universal: bool) -> None:
    controller = allocate_port()
    listener = allocate_port()
    health_url = f"http://127.0.0.1:{target_port}/health"
    nodes = [node("[AI:O][S2] 🇯🇵日本 chatgpt-nonu-good", nonu_port)]
    if universal:
        nodes.insert(0, node("[AI:OCGXU][S1] 🇺🇸美国 universal-good", u_port))
    config = build_config(
        controller=controller,
        listener=listener,
        health_url=health_url,
        nodes=nodes,
    )
    with tempfile.TemporaryDirectory(prefix="phase3a-core-") as temp:
        root = Path(temp)
        config_path = root / "config.yaml"
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        validation = subprocess.run(
            [str(binary), "-t", "-d", str(root), "-f", str(config_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if validation.returncode != 0:
            raise AssertionError(f"config validation failed: {validation.stdout}{validation.stderr}")
        process = subprocess.Popen(
            [str(binary), "-d", str(root), "-f", str(config_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            wait_ready(controller, process)
            if universal:
                wait_now(controller, "🇺🇸 AI AUTO", {"[AI:OCGXU][S1] 🇺🇸美国 universal-good"})
                wait_now(controller, "🤖 AI SERVICE-FALLBACK", {"🇺🇸 AI AUTO"})
                wait_now(controller, "🤖 ChatGPT SERVICE-FALLBACK", {"🇺🇸 AI AUTO"})
            else:
                for name in ("🇯🇵 AI AUTO", "🇸🇬 AI AUTO", "🇺🇸 AI AUTO", "🌍 AI AUTO"):
                    wait_now(controller, name, {"REJECT"})
                wait_now(controller, "🤖 ChatGPT NON-U AUTO", {"[AI:O][S2] 🇯🇵日本 chatgpt-nonu-good"})
                wait_now(controller, "🤖 ChatGPT SERVICE-FALLBACK", {"🤖 ChatGPT NON-U AUTO"})
            status = proxy_request(listener, target_port)
            if status != 200:
                raise AssertionError(f"business request returned HTTP {status}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def download_core(version: str, expected_sha: str, cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    binary = cache / f"mihomo-{version}-linux-amd64"
    if binary.exists():
        return binary
    url = f"https://github.com/MetaCubeX/mihomo/releases/download/{version}/mihomo-linux-amd64-{version}.gz"
    archive = cache / f"{version}.gz"
    urllib.request.urlretrieve(url, archive)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected_sha:
        raise AssertionError(f"{version} SHA256 mismatch: {actual}")
    with gzip.open(archive, "rb") as source, binary.open("wb") as target:
        target.write(source.read())
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def main() -> int:
    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    target_thread.start()
    u_server, u_thread, _ = start_socks("universal")
    nonu_server, nonu_thread, _ = start_socks("nonu")
    cache = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "phase3a-mihomo"
    results: list[dict[str, str]] = []
    try:
        for version, expected_sha in RELEASES.items():
            binary = download_core(version, expected_sha, cache)
            run_scenario(
                binary,
                target.server_port,
                u_server.server_address[1],
                nonu_server.server_address[1],
                universal=True,
            )
            run_scenario(
                binary,
                target.server_port,
                u_server.server_address[1],
                nonu_server.server_address[1],
                universal=False,
            )
            results.append({"core": version, "u_primary": "PASS", "non_u_fallback": "PASS"})
            print(f"{version}: U-primary PASS; NON-U fallback PASS")
    finally:
        u_server.shutdown()
        u_server.server_close()
        u_thread.join(timeout=5)
        nonu_server.shutdown()
        nonu_server.server_close()
        nonu_thread.join(timeout=5)
        target.shutdown()
        target.server_close()
        target_thread.join(timeout=5)
    print(json.dumps({"mode": "core-pass", "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())