"""Real HTTP DMP + MCP + workbook coordinator, using isolated synthetic state."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import yaml
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data_mcp.features.investor_match import dmp_client
from data_mcp.shared import settings as data_settings
from data_mcp.shared.integrations.jgfw_gateway import build_jgfw_gateway_headers

from scripts.dmp_mock.server import (
    APP_KEY,
    APP_SECRET,
    GATEWAY_TOKEN,
    PATH,
    MockConfig,
    MockServer,
)


@pytest.fixture(autouse=True)
def test_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("DMP_MOCK_BASE_URL", raising=False)


@contextmanager
def mock_server(**kwargs):
    server = MockServer(("127.0.0.1", 0), MockConfig(**kwargs))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def configure(monkeypatch, tmp_path, server, *, method="POST", request_timeout=30):
    config = {
        "current_env": "test",
        "investor_match": {
            "dmp": {
                "mode": "mock",
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "path": PATH,
                "method": method,
                "timeout_seconds": 1,
                "individual_limit": 500,
            },
            "workbook_export": {"request_timeout_seconds": request_timeout},
        },
        "http_retry": {
            "max_retries": 2,
            "backoff_base_seconds": 0,
            "backoff_max_seconds": 0,
        },
    }
    path = tmp_path / "dmp.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr(data_settings, "CONFIG_PATH", path)
    return path


def request_headers(caller="workbook_export"):
    cfg = {"app_key": APP_KEY, "app_secret": APP_SECRET, "x_gw_token": GATEWAY_TOKEN}
    return {
        **dmp_client.build_dmp_auth_headers(cfg),
        **build_jgfw_gateway_headers(cfg),
        "X-DMP-Mock-Caller": caller,
    }


def query_body(**kwargs):
    return {
        "label_type": "股权转让/增资",
        "label_name": "速冻食品制造,互联网零售",
        "investor_type": "机构",
        "offset": 0,
        "limit": 200,
        **kwargs,
    }


def test_auth_request_validation_and_private_bounded_stats():
    with mock_server(label_count=4) as server:
        url = f"http://127.0.0.1:{server.server_port}"
        assert httpx.get(url + "/health").json()["mock"] is True
        headers = request_headers()
        response = httpx.post(url + PATH, headers=headers, json=query_body(limit=2))
        assert response.status_code == 200 and response.json()["count"] == 2
        assert response.json()["hasMore"] is True
        invalid = httpx.post(
            url + PATH, headers={**headers, "signature": "bad"}, json=query_body()
        )
        assert invalid.status_code == 401
        assert (
            httpx.post(
                url + PATH, headers=headers, json=query_body(limit=True)
            ).status_code
            == 400
        )
        stats = httpx.get(url + "/__mock__/stats").json()
        assert stats["calls"] == 1 and len(stats["recent"]) == 1
        assert APP_SECRET not in json.dumps(stats) and GATEWAY_TOKEN not in json.dumps(
            stats
        )


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("wrapper", ["direct", "body", "data"])
def test_report_and_export_use_same_protocol_and_keep_page_limits(
    monkeypatch, tmp_path, method, wrapper
):
    with mock_server(label_count=4, wrapper=wrapper) as server:
        configure(monkeypatch, tmp_path, server, method=method)
        report = dmp_client.query_dmp_investors(["速冻食品制造", "互联网零售"])
        assert len(report["institutions"]) == 30 and report["individual_count"] == 500
        assert "label_name_list" not in json.dumps(report)
        result = dmp_client.query_dmp_institutions_for_export(
            ["速冻食品制造", "互联网零售"]
        )
        assert len(result.rows) == 200
        assert result.rows[0]["matched_labels"] == ["速冻食品制造", "互联网零售"]
        assert [c["limit"] for c in server.recent] == [30, 500, 200]
        assert [c["caller"] for c in server.recent] == [
            "report_match",
            "report_match",
            "workbook_export",
        ]


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("invalid_json", "DMP_EXPORT_INVALID_RESPONSE"),
        ("invalid_items", "DMP_EXPORT_INVALID_RESPONSE"),
        ("http_401", "DMP_EXPORT_HTTP_ERROR"),
        ("http_429", "DMP_EXPORT_HTTP_ERROR"),
        ("http_500", "DMP_EXPORT_HTTP_ERROR"),
        ("timeout", "DMP_EXPORT_TIMEOUT"),
        ("oversize", "DMP_EXPORT_RESPONSE_TOO_LARGE"),
    ],
)
def test_export_failures_are_isolated_and_not_automatically_retried(
    monkeypatch, tmp_path, scenario, code
):
    from data_mcp.mcp.server import export_matched_institutions

    with mock_server(
        label_count=4, export_scenario=scenario, delay_seconds=1.3
    ) as server:
        configure(
            monkeypatch,
            tmp_path,
            server,
            request_timeout=1 if scenario == "timeout" else 30,
        )
        report = dmp_client.query_dmp_investors(["食品制造"])
        assert len(report["institutions"]) == 30
        payload = export_matched_institutions(["食品制造"])
        assert payload["status"] == "failed" and payload["warnings"][0]["code"] == code
        assert server.attempts[("workbook_export", "机构", "食品制造")] == 1
        assert len(dmp_client.query_dmp_investors(["食品制造"])["institutions"]) == 30


@pytest.mark.parametrize(
    "scenario,status",
    [("empty", "empty"), ("dirty", "partial"), ("fail_once", "success")],
)
def test_empty_dirty_and_manual_retry(monkeypatch, tmp_path, scenario, status):
    from data_mcp.mcp.server import export_matched_institutions
    from report_agent.application.institution_workbook.files import validate_file

    with mock_server(label_count=4, export_scenario=scenario) as server:
        configure(monkeypatch, tmp_path, server)
        if scenario == "fail_once":
            assert export_matched_institutions(["食品制造"])["status"] == "failed"
        payload = export_matched_institutions(["食品制造"])
        content, preview = validate_file(payload, ["食品制造"], 2 * 1024 * 1024)
        assert payload["status"] == status and content[:2] == b"PK"
        assert preview["row_count"] == (
            0 if scenario == "empty" else 181 if scenario == "dirty" else 200
        )


def test_default_large_response_cleans_down_to_small_real_workbook(
    monkeypatch, tmp_path
):
    from data_mcp.mcp.server import export_matched_institutions
    from report_agent.application.institution_workbook.files import validate_file

    with mock_server() as server:
        configure(monkeypatch, tmp_path, server)
        payload = export_matched_institutions(["速冻食品制造", "互联网零售"])
        content, preview = validate_file(
            payload, ["速冻食品制造", "互联网零售"], 2 * 1024 * 1024
        )
        assert preview["row_count"] == 200
        assert server.recent[-1]["response_bytes"] > 16 * 1024 * 1024
        assert len(json.dumps(payload)) < 100_000 and len(content) < 100_000
        assert "模拟无关行业标签" not in json.dumps(payload, ensure_ascii=False)
        book = load_workbook(io.BytesIO(content))
        assert book.active.max_row == 201 and book.active.max_column == 4
        book.close()
        print(
            json.dumps(
                {
                    "large_response_bytes": server.recent[-1]["response_bytes"],
                    "xlsx_bytes": len(content),
                    "mcp_json_bytes": len(json.dumps(payload)),
                    "simulated_institutions": server.config.institutions,
                    "exported_rows": 200,
                }
            )
        )


@pytest.mark.parametrize("environment", ["dev", "prod"])
def test_mock_server_rejects_unsupported_environments(monkeypatch, environment):
    monkeypatch.setenv("APP_ENV", environment)
    with pytest.raises(ValueError, match="restricted"):
        MockConfig(environment=environment)


@pytest.mark.parametrize(
    "env,mode,url",
    [
        ("prod", "mock", "http://127.0.0.1:8025"),
        ("prod", "real", "http://dmp-mock:8025"),
        ("test", "mock", "http://10.3.1.71:30011"),
        ("uat", "mock", "http://user:password@127.0.0.1:8025"),
    ],
)
def test_client_configuration_fails_closed(monkeypatch, tmp_path, env, mode, url):
    path = tmp_path / "guard.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "current_env": env,
                "investor_match": {
                    "dmp": {"mode": mode, "base_url": url, "path": PATH}
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(data_settings, "CONFIG_PATH", path)
    monkeypatch.setenv("APP_ENV", env)
    with pytest.raises(ValueError, match="DMP_"):
        data_settings.load_investor_match_config()


def test_test_uat_deployments_enable_mock_and_worker_configuration():
    for env in ("test", "uat"):
        config = yaml.safe_load(
            (ROOT / f"deploy/environments/{env}/data-mcp.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert config["investor_match"]["dmp"]["mode"] == "mock"
        report = yaml.safe_load(
            (ROOT / f"deploy/environments/{env}/report-agent.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert report["institution_workbook"]["enabled"] is True
    prod = yaml.safe_load(
        (ROOT / "deploy/environments/prod/data-mcp.yaml").read_text(encoding="utf-8")
    )
    assert prod["investor_match"]["dmp"].get("mode", "real") == "real"
    compose = yaml.safe_load(
        (ROOT / "compose.dmp-mock.yaml").read_text(encoding="utf-8")
    )
    worker = compose["services"]["institution-workbook-worker"]
    assert "dmp-mock" in worker["profiles"]
    assert worker["volumes"] == compose["services"]["report-agent"]["volumes"]


@contextmanager
def mcp_server(config_path, tmp_path):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME"}
    }
    env.update(
        APP_ENV="test",
        DATA_MCP_CONFIG=str(config_path),
        DATA_MCP_CONTRACTS_DIR=str(ROOT / "contracts/mcp"),
        PYTHONIOENCODING="utf-8",
        NO_PROXY="127.0.0.1,localhost",
    )
    log_path = tmp_path / "mcp.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "data_mcp.entrypoints",
                "--transport",
                "streamable-http",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError(f"MCP exited; inspect {log_path}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError(f"MCP startup timeout; inspect {log_path}")
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                else:
                    process.terminate()
                process.wait(timeout=10)


@pytest.mark.asyncio
@pytest.mark.parametrize("label_count", [4, 3000])
async def test_actual_mcp_repeated_exports_and_coordinator_delivery(
    monkeypatch, tmp_path, label_count
):
    from report_agent.application.institution_workbook.service import (
        InstitutionWorkbookService,
    )
    from report_agent.infrastructure.mcp.streamable_http import (
        StreamableHttpMcpTransport,
    )
    from report_agent.infrastructure.persistence.memory import InMemoryRunRepository

    sys.path.insert(0, str(ROOT / "apps/report_agent/tests/unit"))
    from test_institution_workbook import (
        MemoryJobs,
        Publisher,
        build_context,
        completed_run,
        settings,
    )

    repeats = (
        int(os.getenv("DMP_MOCK_STRESS_ITERATIONS", "5")) if label_count == 4 else 1
    )
    with mock_server(label_count=label_count) as server:
        config_path = configure(monkeypatch, tmp_path, server)
        with mcp_server(config_path, tmp_path) as url:
            transport = StreamableHttpMcpTransport(url, timeout_seconds=45)
            assert "export_matched_institutions" in await transport.list_tools()
            tags = ["速冻食品制造", "互联网零售"]
            started = time.monotonic()
            for _ in range(repeats):
                payload = await transport.call_tool(
                    "export_matched_institutions", {"track_tags": tags}
                )
                assert (
                    payload["status"] == "success"
                    and payload["data"]["row_count"] == 200
                )
                assert (
                    len(base64.b64decode(payload["data"]["content_base64"])) < 100_000
                )
                from report_agent.application.institution_workbook.files import (
                    validate_file,
                )

                _, checked = validate_file(payload, tags, 2 * 1024 * 1024)
                assert checked["row_count"] == 200 and checked["query_tags"] == tags
            identity, _, _, _ = build_context(tmp_path, matched_tags=tags)
            runs = InMemoryRunRepository()
            completed_run(runs, identity)
            original = runs.get_run(identity.run_id)
            jobs = MemoryJobs(runs)
            publisher = Publisher()
            service = InstitutionWorkbookService(
                settings(),
                tmp_path,
                runs,
                jobs,
                transport=transport,
                publisher=publisher,
            )
            service.discover()
            await service.execute(jobs.claim(120))
            saved = jobs.list(identity.task_id)[0]
            assert (
                saved["status"] == "succeeded" and saved["preview"]["row_count"] == 200
            )
            assert runs.get_run(identity.run_id).status == "completed"
            assert runs.get_run(identity.run_id).artifacts[0] == original.artifacts[0]
            from report_agent.api.app import create_app
            from report_agent.application.runs import SynchronousRunService

            app = create_app(
                SynchronousRunService(tmp_path, lambda: None, runs),
                dev_ui_enabled=True,
                artifact_service=publisher,
                institution_workbook_service=service,
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                preview = await client.get(
                    f"/api/artifacts/{saved['artifact_id']}/preview"
                )
                downloaded = await client.get(
                    f"/api/artifacts/{saved['artifact_id']}/content"
                )
            assert (
                preview.json()["row_count"] == 200 and downloaded.content[:2] == b"PK"
            )
            assert server.calls == repeats + 1
            if label_count == 4:
                identities = []
                for index in range(10):
                    item, _, _, _ = build_context(
                        tmp_path, matched_tags=[f"队列测试标签{index}"]
                    )
                    completed_run(runs, item)
                    identities.append(item)
                await asyncio.gather(
                    *(
                        service.enqueue_manual(
                            item.task_id, {"client_request_id": f"queue-test-{index}"}
                        )
                        for index, item in enumerate(identities)
                    )
                )
                for _ in identities:
                    await service.execute(jobs.claim(120))
                for index, item in enumerate(identities):
                    final = jobs.list(item.task_id)[0]
                    assert final["status"] == "succeeded"
                    assert final["preview"]["query_tags"] == [f"队列测试标签{index}"]
            else:
                assert server.recent[-1]["response_bytes"] > 16 * 1024 * 1024
            output = {
                "mcp_repeats": repeats,
                "rows_per_export": 200,
                "coordinator_delivery": True,
                "labels_per_institution": label_count,
                "queue_tasks": 10 if label_count == 4 else 0,
                "elapsed_seconds": round(time.monotonic() - started, 2),
            }
            (tmp_path / "stability.json").write_text(
                json.dumps(output), encoding="utf-8"
            )
            print(json.dumps(output))


@pytest.mark.asyncio
async def test_actual_mcp_failure_keeps_report_and_manual_retry_recovers(
    monkeypatch, tmp_path
):
    from report_agent.application.institution_workbook.service import (
        InstitutionWorkbookService,
    )
    from report_agent.infrastructure.mcp.streamable_http import (
        StreamableHttpMcpTransport,
    )
    from report_agent.infrastructure.persistence.memory import InMemoryRunRepository

    sys.path.insert(0, str(ROOT / "apps/report_agent/tests/unit"))
    from test_institution_workbook import (
        MemoryJobs,
        Publisher,
        build_context,
        completed_run,
        settings,
    )

    with mock_server(label_count=4, export_scenario="fail_once") as server:
        config_path = configure(monkeypatch, tmp_path, server)
        with mcp_server(config_path, tmp_path) as url:
            identity, _, _, _ = build_context(tmp_path, matched_tags=["食品制造"])
            runs = InMemoryRunRepository()
            completed_run(runs, identity)
            original = runs.get_run(identity.run_id)
            jobs = MemoryJobs(runs)
            service = InstitutionWorkbookService(
                settings(),
                tmp_path,
                runs,
                jobs,
                transport=StreamableHttpMcpTransport(url),
                publisher=Publisher(),
            )
            service.discover()
            await service.execute(jobs.claim(120))
            failed = service.list_jobs(identity.task_id)[0]
            assert (
                failed["status"] == "failed"
                and failed["error_code"] == "DMP_EXPORT_HTTP_ERROR"
            )
            assert runs.get_run(identity.run_id) == original
            retry = await service.enqueue_manual(
                identity.task_id,
                {
                    "client_request_id": "real-http-manual-retry",
                    "source_job_id": failed["job_id"],
                    "expected_context_fingerprint": failed["context_fingerprint"],
                    "expected_tag_group_fingerprint": failed["tag_group_fingerprint"],
                },
            )
            await service.execute(jobs.claim(120))
            assert jobs.rows[retry["job_id"]]["status"] == "succeeded"
            assert (
                server.calls == 2 and len(runs.get_run(identity.run_id).artifacts) == 2
            )
            assert runs.get_run(identity.run_id).status == "completed"


def test_report_retry_and_mock_credentials_do_not_use_platform_secrets(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("API_PLATFORM_TOKEN", "private-real-token")
    monkeypatch.setenv("DMP_APP_SECRET", "private-real-secret")
    with mock_server(label_count=4, report_scenario="fail_once") as server:
        configure(monkeypatch, tmp_path, server)
        config = data_settings.load_investor_match_config()["dmp"]
        assert (
            config["x_gw_token"] == GATEWAY_TOKEN and config["app_secret"] == APP_SECRET
        )
        result = dmp_client.query_dmp_investors(["食品制造"])
        assert result["individual_count"] == 500 and len(result["institutions"]) == 30
        assert [event["status"] for event in server.recent] == [500, 200, 500, 200]


def test_regular_response_allocation_is_bounded():
    with mock_server(label_count=10_000) as server:
        response = httpx.post(
            f"http://127.0.0.1:{server.server_port}{PATH}",
            headers=request_headers(),
            json=query_body(limit=500),
        )
        assert response.status_code == 413
        assert response.json()["error"] == "MOCK_RESPONSE_LIMIT_USE_OVERSIZE"


def test_mock_mode_does_not_read_real_secret_references(monkeypatch, tmp_path):
    path = tmp_path / "secrets.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "current_env": "test",
                "investor_match": {
                    "dmp": {
                        "mode": "mock",
                        "base_url": "http://127.0.0.1:8025",
                        "path": PATH,
                        "x_gw_token": {"env": "API_PLATFORM_TOKEN"},
                        "app_secret": {"env": "DMP_APP_SECRET"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(data_settings, "CONFIG_PATH", path)
    original = os.getenv

    def getenv(name, default=None):
        if name in {"API_PLATFORM_TOKEN", "DMP_APP_SECRET"}:
            pytest.fail("mock mode must not resolve real secret references")
        return original(name, default)

    monkeypatch.setattr(os, "getenv", getenv)
    config = data_settings.load_investor_match_config()["dmp"]
    assert config["app_secret"] == APP_SECRET and config["x_gw_token"] == GATEWAY_TOKEN
