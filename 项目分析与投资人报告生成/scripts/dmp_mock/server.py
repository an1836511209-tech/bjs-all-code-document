"""Standalone, standard-library-only DMP simulator with bounded diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

PATH = "/v3/API_DMP_DMP_APEX_InquiryInvestorProfileMatchingSrv"
APP_KEY = "mock-dmp-app-key"
APP_SECRET = "mock-dmp-app-secret"
GATEWAY_TOKEN = "mock-dmp-gateway-token"
SCENARIOS = (
    "normal",
    "empty",
    "dirty",
    "invalid_json",
    "invalid_items",
    "http_401",
    "http_429",
    "http_500",
    "timeout",
    "fail_once",
    "oversize",
)


@dataclass(frozen=True)
class MockConfig:
    environment: str = "test"
    institutions: int = 10_000
    individuals: int = 50_000
    label_count: int = 3_000
    wrapper: str = "direct"
    report_scenario: str = "normal"
    export_scenario: str = "normal"
    delay_seconds: float = 35

    def __post_init__(self):
        if self.environment not in {"test", "uat"} or os.getenv(
            "APP_ENV", self.environment
        ) not in {"test", "uat"}:
            raise ValueError("DMP mock is restricted to test/uat")
        if (
            not 1 <= self.institutions <= 100_000
            or not 1 <= self.individuals <= 100_000
            or not 0 <= self.label_count <= 10_000
            or not 0 <= self.delay_seconds <= 120
        ):
            raise ValueError("Invalid DMP mock size/delay limits")
        if self.wrapper not in {"direct", "body", "data"}:
            raise ValueError("Invalid DMP mock wrapper")
        if (
            self.report_scenario not in SCENARIOS
            or self.export_scenario not in SCENARIOS
        ):
            raise ValueError("Invalid DMP mock scenario")


class MockServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, config: MockConfig):
        self.config = config
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(2)
        self.calls = 0
        self.recent: deque = deque(maxlen=100)
        self.attempts: OrderedDict = OrderedDict()
        # Build one shared long string; never materialize the entire simulated population.
        self.extra_labels = ",".join(
            f"模拟无关行业标签{i:05d}" for i in range(config.label_count)
        )
        super().__init__(address, MockHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.sendall(b"HTTP/1.0 503 Busy\r\nContent-Length: 0\r\n\r\n")
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def attempt(self, caller, query):
        key = (caller, query["investor_type"], query["label_name"])
        with self.lock:
            value = self.attempts.pop(key, 0) + 1
            self.attempts[key] = value
            if len(self.attempts) > 256:
                self.attempts.popitem(last=False)
            return value


class MockHandler(BaseHTTPRequestHandler):
    server: MockServer

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass  # Never log authentication headers or long raw payloads.

    def send_bytes(self, status, body, scenario="normal"):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-DMP-Mock", "true")
        self.send_header("X-DMP-Mock-Scenario", scenario)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, value, scenario="normal"):
        content = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_bytes(status, content, scenario)
        return len(content)

    def authenticate(self):
        timestamp = self.headers.get("timestamp", "")
        nonce = self.headers.get("nonce", "")
        if (
            self.headers.get("appKey") != APP_KEY
            or not timestamp.isdigit()
            or len(timestamp) > 16
            or not re.fullmatch(r"[A-Za-z0-9]{10}", nonce)
            or abs(time.time() * 1000 - int(timestamp)) > 300_000
        ):
            return False
        expected = hashlib.sha1(
            f"{APP_KEY}{APP_SECRET}{timestamp}{nonce}".encode()
        ).hexdigest()
        signature = self.headers.get("signature", "")
        if not re.fullmatch(r"[0-9a-f]{40}", signature) or not hmac.compare_digest(
            expected, signature
        ):
            return False
        salt = self.headers.get("x-gw-salt-key", "")
        token = self.headers.get("x-gw-token", "")
        if not re.fullmatch(r"[A-Z0-9]{32}", salt) or not re.fullmatch(
            r"[0-9a-f]{64}", token
        ):
            return False
        # Date window accommodates the client's host timezone around midnight.
        return any(
            hmac.compare_digest(
                token,
                hmac.new(
                    salt.encode(),
                    f"{GATEWAY_TOKEN}{(datetime.now(UTC).date() + timedelta(days=d)):%Y%m%d}".encode(),
                    "sm3",
                ).hexdigest(),
            )
            for d in (-1, 0, 1)
        )

    def query(self):
        if self.command == "GET":
            params = parse_qs(urlsplit(self.path).query, strict_parsing=True)
            if any(len(value) != 1 for value in params.values()):
                raise ValueError("Duplicate query fields")
            result = {key: value[0] for key, value in params.items()}
            for key in ("offset", "limit"):
                if not re.fullmatch(r"\d{1,7}", result.get(key, "")):
                    raise ValueError("Invalid page")
                result[key] = int(result[key])
        else:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16_384 or self.headers.get("Transfer-Encoding"):
                raise ValueError("Invalid request size")
            result = json.loads(self.rfile.read(size))
        if (
            not isinstance(result, dict)
            or set(result)
            != {"label_type", "label_name", "investor_type", "offset", "limit"}
            or result["label_type"] != "股权转让/增资"
            or result["investor_type"] not in {"机构", "个人"}
            or type(result["offset"]) is not int
            or not 0 <= result["offset"] <= 100_000
            or type(result["limit"]) is not int
            or not 1 <= result["limit"] <= 500
            or not isinstance(result["label_name"], str)
            or len(result["label_name"]) > 16_000
        ):
            raise ValueError("Invalid DMP request")
        tags = result["label_name"].split(",")
        if (
            not tags
            or any(not tag.strip() or len(tag.strip()) > 160 for tag in tags)
            or len(tags) > 100
        ):
            raise ValueError("Invalid labels")
        return result, list(dict.fromkeys(tag.strip() for tag in tags))

    def payload(self, query, tags, dirty):
        cfg = self.server.config
        total = (
            cfg.institutions if query["investor_type"] == "机构" else cfg.individuals
        )
        stop = min(total, query["offset"] + query["limit"])
        rows = []
        for index in range(query["offset"], stop):
            matched = tags if index % 3 == 0 else [tags[index % len(tags)]]
            row = {
                "investor_name": f"测试机构{index + 1:06d}有限公司"
                if query["investor_type"] == "机构"
                else f"测试个人{index + 1:06d}",
                "match_label_weight_sum": round(100_000 - index * 0.25, 2),
                "match_label_num": len(matched),
                "label_name_list": ",".join(
                    [
                        *matched,
                        self.server.extra_labels
                        if query["investor_type"] == "机构"
                        else "模拟个人标签",
                    ]
                ).strip(","),
            }
            if dirty:
                if index % 11 == 0:
                    row["investor_name"] = ""
                elif index % 11 == 1:
                    row["match_label_weight_sum"] = "82.5"
                    row["match_label_num"] = "2.0"
                elif index % 11 == 2:
                    row["label_name_list"] = f"{tags[0]},其他标签…"
                elif index % 11 == 3:
                    row["match_label_weight_sum"] = "NaN"
                    row["label_name_list"] = None
            rows.append(row)
        return {"count": len(rows), "hasMore": stop < total, "items": rows}

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            self.send_json(
                200, {"service": "dmp-mock", "mock": True, **vars(self.server.config)}
            )
        elif path == "/__mock__/stats":
            with self.server.lock:
                snapshot = {
                    "calls": self.server.calls,
                    "recent": list(self.server.recent),
                }
            self.send_json(200, snapshot)
        else:
            self.handle_query()

    def do_POST(self):
        self.handle_query()

    def handle_query(self):
        if urlsplit(self.path).path != PATH:
            self.send_json(404, {"error": "NOT_FOUND"})
            return
        if not self.authenticate():
            self.send_json(401, {"error": "INVALID_TEST_AUTH"})
            return
        try:
            query, tags = self.query()
        except (ValueError, TypeError, UnicodeError):
            self.send_json(400, {"error": "INVALID_DMP_REQUEST"})
            return
        caller = self.headers.get("X-DMP-Mock-Caller", "")
        if caller not in {"report_match", "workbook_export"}:
            self.send_json(400, {"error": "MISSING_MOCK_CALLER"})
            return
        cfg = self.server.config
        scenario = (
            cfg.export_scenario if caller == "workbook_export" else cfg.report_scenario
        )
        attempt = self.server.attempt(caller, query)
        event = {
            "caller": caller,
            "scenario": scenario,
            "method": self.command,
            "investor_type": query["investor_type"],
            "offset": query["offset"],
            "limit": query["limit"],
            "query_sha256": hashlib.sha256(query["label_name"].encode()).hexdigest(),
            "tag_count": len(tags),
            "attempt": attempt,
            "response_bytes": 0,
            "status": 200,
        }
        started = time.monotonic()
        try:
            if scenario.startswith("http_") or (
                scenario == "fail_once" and attempt == 1
            ):
                event["status"] = (
                    int(scenario[5:]) if scenario.startswith("http_") else 500
                )
                event["response_bytes"] = self.send_json(
                    event["status"], {"error": "SIMULATED_FAILURE"}, scenario
                )
                return
            if scenario == "timeout":
                time.sleep(cfg.delay_seconds)
            if scenario == "oversize":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-DMP-Mock", "true")
                self.end_headers()
                prefix = b'{"count":1,"hasMore":false,"items":[{"investor_name":"TEST","label_name_list":"'
                self.wfile.write(prefix)
                chunk = b"x" * 65536
                for _ in range(1056):  # 66 MiB, streamed rather than held in memory.
                    self.wfile.write(chunk)
                    event["response_bytes"] += len(chunk)
                self.wfile.write(b'"}]}')
                return
            if scenario == "invalid_json":
                self.send_bytes(200, b"{invalid-json", scenario)
                return
            if scenario == "empty":
                payload = {"count": 0, "hasMore": False, "items": []}
            elif scenario == "invalid_items":
                payload = {"count": 0, "hasMore": False, "items": {"invalid": True}}
            elif query["investor_type"] == "机构":
                row_bytes = (
                    len(self.server.extra_labels.encode("utf-8"))
                    + sum(len(t.encode("utf-8")) * 2 + 4 for t in tags)
                    + 1024
                )
                rows = max(0, min(query["limit"], cfg.institutions - query["offset"]))
                if row_bytes * rows > 48 * 1024 * 1024:
                    event["status"] = 413
                    event["response_bytes"] = self.send_json(
                        413, {"error": "MOCK_RESPONSE_LIMIT_USE_OVERSIZE"}, scenario
                    )
                    return
                payload = self.payload(query, tags, scenario == "dirty")
            else:
                payload = self.payload(query, tags, scenario == "dirty")
            if cfg.wrapper != "direct":
                payload = {cfg.wrapper: payload}
            event["response_bytes"] = self.send_json(200, payload, scenario)
        except (BrokenPipeError, ConnectionError, TimeoutError):
            event["client_disconnected"] = True
        finally:
            event["elapsed_ms"] = round((time.monotonic() - started) * 1000)
            with self.server.lock:
                self.server.calls += 1
                self.server.recent.append(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8025)
    parser.add_argument("--environment", default=os.getenv("APP_ENV", "test"))
    parser.add_argument("--institutions", type=int, default=10_000)
    parser.add_argument("--individuals", type=int, default=50_000)
    parser.add_argument("--labels", type=int, default=3_000)
    parser.add_argument(
        "--wrapper", choices=("direct", "body", "data"), default="direct"
    )
    parser.add_argument("--report-scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--export-scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--delay", type=float, default=35)
    args = parser.parse_args()
    config = MockConfig(
        args.environment,
        args.institutions,
        args.individuals,
        args.labels,
        args.wrapper,
        args.report_scenario,
        args.export_scenario,
        args.delay,
    )
    with MockServer((args.host, args.port), config) as server:
        print(
            json.dumps(
                {
                    "service": "dmp-mock",
                    "host": args.host,
                    "port": server.server_port,
                    **vars(config),
                }
            ),
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
