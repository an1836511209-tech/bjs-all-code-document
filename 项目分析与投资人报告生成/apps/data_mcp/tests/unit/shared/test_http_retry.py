"""HTTP 重试客户端单元测试。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import tests.support  # noqa: F401
from data_mcp.shared.http.retry_client import http_request, is_retryable_http_error


class RetryableErrorTests(unittest.TestCase):
    def test_retryable_status_codes(self) -> None:
        import httpx

        self.assertTrue(is_retryable_http_error(httpx.TimeoutException("timeout")))
        self.assertTrue(is_retryable_http_error(httpx.ConnectError("conn")))

        resp_429 = MagicMock()
        resp_429.status_code = 429
        self.assertTrue(
            is_retryable_http_error(httpx.HTTPStatusError("rate", request=MagicMock(), response=resp_429))
        )

        resp_500 = MagicMock()
        resp_500.status_code = 500
        self.assertTrue(
            is_retryable_http_error(httpx.HTTPStatusError("srv", request=MagicMock(), response=resp_500))
        )

        resp_400 = MagicMock()
        resp_400.status_code = 400
        self.assertFalse(
            is_retryable_http_error(httpx.HTTPStatusError("bad", request=MagicMock(), response=resp_400))
        )


class HttpRequestRetryTests(unittest.TestCase):
    @patch("data_mcp.shared.http.retry_client.time.sleep")
    @patch("data_mcp.shared.http.retry_client.httpx.request")
    def test_retries_on_500_then_succeeds(self, mock_request, mock_sleep) -> None:
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        fail_resp.raise_for_status.side_effect = __import__("httpx").HTTPStatusError(
            "500",
            request=MagicMock(),
            response=fail_resp,
        )

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = MagicMock()

        mock_request.side_effect = [fail_resp, ok_resp]

        response = http_request("GET", "http://example.test/api", timeout=1.0, max_retries=2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_request.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("data_mcp.shared.http.retry_client.httpx.request")
    def test_does_not_retry_400(self, mock_request) -> None:
        import httpx

        bad_resp = MagicMock()
        bad_resp.status_code = 400
        bad_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400",
            request=MagicMock(),
            response=bad_resp,
        )
        mock_request.return_value = bad_resp

        with self.assertRaises(httpx.HTTPStatusError):
            http_request("POST", "http://example.test/api", json={"x": 1}, max_retries=2)
        self.assertEqual(mock_request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
