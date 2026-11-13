from __future__ import annotations

import unittest
from unittest import mock


class JgfwGatewayTests(unittest.TestCase):
    def test_encrypt_token_matches_known_vector(self) -> None:
        from data_mcp.shared.integrations.jgfw_gateway import encrypt_token

        # generate_jgfw_token.py --token test-jgfw-api-token --salt ABC... --date 20261008
        got = encrypt_token(
            "test-jgfw-api-token",
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
            day="20261008",
        )
        self.assertEqual(
            got,
            "801d32f80bd305282c09b92d67ebb1e3f0e95a5c17fbee1bc5207c3cc60b8595",
        )

    def test_build_headers_uses_example_static_fields_and_dynamic_token(self) -> None:
        from data_mcp.shared.integrations.jgfw_gateway import build_jgfw_gateway_headers

        with mock.patch(
            "data_mcp.shared.integrations.jgfw_gateway.generate_salt",
            return_value="ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        ), mock.patch(
            "data_mcp.shared.integrations.jgfw_gateway.date"
        ) as mock_date:
            mock_date.today.return_value.strftime.return_value = "20261008"
            headers = build_jgfw_gateway_headers(
                {
                    "x_gw_appid": "AIZT",
                    "x_gw_org": "VOLCENGINE",
                    "x_gw_token": "test-jgfw-api-token",
                    "x_gw_route": "",
                }
            )

        self.assertEqual(headers["x-gw-appid"], "AIZT")
        self.assertEqual(headers["x-gw-org"], "VOLCENGINE")
        self.assertEqual(headers["x-gw-salt-key"], "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345")
        self.assertEqual(
            headers["x-gw-token"],
            "801d32f80bd305282c09b92d67ebb1e3f0e95a5c17fbee1bc5207c3cc60b8595",
        )
        self.assertNotIn("x-gw-route", headers)

    def test_build_headers_skips_token_when_raw_empty(self) -> None:
        from data_mcp.shared.integrations.jgfw_gateway import build_jgfw_gateway_headers

        headers = build_jgfw_gateway_headers(
            {"x_gw_appid": "AIZT", "x_gw_org": "VOLCENGINE", "x_gw_token": ""}
        )
        self.assertEqual(headers, {"x-gw-appid": "AIZT", "x-gw-org": "VOLCENGINE"})


if __name__ == "__main__":
    unittest.main()
