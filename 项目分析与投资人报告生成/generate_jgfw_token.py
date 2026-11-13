#!/usr/bin/env python3
"""生成机构服务中台 / API 平台网关签名用的随机盐与 x-gw-token。

算法与后端一致（JgfwApiServiceImpl#getTokenEncrypt）：
  data = token + 当天yyyyMMdd
  x-gw-token = HMAC-SM3(data, key=salt).hex()

生产代码见 data_mcp.shared.integrations.jgfw_gateway。

用法：
  python generate_jgfw_token.py
  python generate_jgfw_token.py <jgfw-api-token>
  python generate_jgfw_token.py --token <jgfw-api-token>
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# 允许直接 python 运行本脚本时找到 data_mcp 包
_SRC = Path(__file__).resolve().parent / "apps" / "data_mcp" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from data_mcp.shared.integrations.jgfw_gateway import (  # noqa: E402
    encrypt_token,
    generate_salt,
)

# application-prod.yml 默认 jgfw.api.token
DEFAULT_TOKEN = "replace-with-jgfw-api-token"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 API 平台网关 x-gw-salt-key / x-gw-token")
    parser.add_argument(
        "token_pos",
        nargs="?",
        default=None,
        help="原始 token（也可写 --token）",
    )
    parser.add_argument(
        "--token",
        "-t",
        default=None,
        help=f"原始 jgfw.api.token，默认 {DEFAULT_TOKEN}",
    )
    parser.add_argument(
        "--salt",
        "-s",
        default=None,
        help="指定盐（不传则随机 32 位大写字母+数字）",
    )
    parser.add_argument(
        "--date",
        "-d",
        default=None,
        help="签名日期 yyyyMMdd，默认当天",
    )
    args = parser.parse_args(argv)

    token = args.token or args.token_pos or DEFAULT_TOKEN
    day = args.date or date.today().strftime("%Y%m%d")
    salt = args.salt or generate_salt()
    gw_token = encrypt_token(token, salt, day)

    print(f"原始 token     : {token}")
    print(f"签名日期       : {day}")
    print(f"签名原文       : {token}{day}")
    print(f"x-gw-salt-key  : {salt}")
    print(f"x-gw-token     : {gw_token}")
    print()
    print("Header 示例：")
    print("  x-gw-org: VOLCENGINE")
    print("  x-gw-appid: AIZT")
    print(f"  x-gw-salt-key: {salt}")
    print(f"  x-gw-token: {gw_token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
