""" 生成 API 平台网关头（HMAC-SM3）。
  data = token + 当天yyyyMMdd
  x-gw-token = HMAC-SM3(data, key=salt).hex()
"""

from __future__ import annotations

import random
import struct
from datetime import date
from typing import Any

CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_IV = [
    0x7380166F,
    0x4914B2B9,
    0x172442D7,
    0xDA8A0600,
    0xA96F30BC,
    0x163138AA,
    0xE38DEE4D,
    0xB0FB0E4E,
]


def _rotl(x: int, n: int) -> int:
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _tj(j: int) -> int:
    return 0x79CC4519 if j < 16 else 0x7A879D8A


def _ff(x: int, y: int, z: int, j: int) -> int:
    return (x ^ y ^ z) if j < 16 else ((x & y) | (x & z) | (y & z))


def _gg(x: int, y: int, z: int, j: int) -> int:
    return (x ^ y ^ z) if j < 16 else ((x & y) | ((~x) & z))


def _p0(x: int) -> int:
    return x ^ _rotl(x, 9) ^ _rotl(x, 17)


def _p1(x: int) -> int:
    return x ^ _rotl(x, 15) ^ _rotl(x, 23)


def _sm3_compress(v: list[int], block: bytes) -> list[int]:
    w = list(struct.unpack(">16I", block)) + [0] * 52
    for j in range(16, 68):
        w[j] = _p1(w[j - 16] ^ w[j - 9] ^ _rotl(w[j - 3], 15)) ^ _rotl(w[j - 13], 7) ^ w[j - 6]
        w[j] &= 0xFFFFFFFF
    w1 = [(w[j] ^ w[j + 4]) & 0xFFFFFFFF for j in range(64)]

    a, b, c, d, e, f, g, h = v
    for j in range(64):
        ss1 = _rotl((_rotl(a, 12) + e + _rotl(_tj(j), j % 32)) & 0xFFFFFFFF, 7)
        ss2 = ss1 ^ _rotl(a, 12)
        tt1 = (_ff(a, b, c, j) + d + ss2 + w1[j]) & 0xFFFFFFFF
        tt2 = (_gg(e, f, g, j) + h + ss1 + w[j]) & 0xFFFFFFFF
        d, c, b, a = c, _rotl(b, 9), a, tt1
        h, g, f, e = g, _rotl(f, 19), e, _p0(tt2)
    return [(x ^ y) & 0xFFFFFFFF for x, y in zip(v, [a, b, c, d, e, f, g, h])]


def sm3(data: bytes) -> bytes:
    length = len(data)
    data = data + b"\x80"
    data += b"\x00" * ((56 - (length + 1) % 64) % 64)
    data += struct.pack(">Q", length * 8)

    v = _IV[:]
    for i in range(0, len(data), 64):
        v = _sm3_compress(v, data[i : i + 64])
    return b"".join(struct.pack(">I", x) for x in v)


def hmac_sm3(key: bytes, msg: bytes) -> bytes:
    """与 BouncyCastle HMac(SM3Digest) 一致，块长 64。"""
    block = 64
    if len(key) > block:
        key = sm3(key)
    key = key.ljust(block, b"\x00")
    o_key = bytes(b ^ 0x5C for b in key)
    i_key = bytes(b ^ 0x36 for b in key)
    return sm3(o_key + sm3(i_key + msg))


def generate_salt(length: int = 32) -> str:
    return "".join(random.choice(CHARSET) for _ in range(length))


def encrypt_token(token: str, salt: str, day: str | None = None) -> str:
    day = day or date.today().strftime("%Y%m%d")
    data = f"{token}{day}"
    return hmac_sm3(salt.encode("utf-8"), data.encode("utf-8")).hex()


def build_jgfw_gateway_headers(cfg: dict[str, Any]) -> dict[str, str]:
    """从配置构建 API 平台网关头；每次请求随机盐并加密 token。

    配置字段：
      x_gw_appid / x_gw_org / x_gw_route：静态透传（有值才带）
      x_gw_token：原始 jgfw.api.token（非已加密值）；有值时生成 salt 并写入加密后的 x-gw-token
    """
    headers: dict[str, str] = {}
    for key in ("x_gw_appid", "x_gw_org", "x_gw_route"):
        val = str(cfg.get(key) or "").strip()
        if val:
            headers[key.replace("_", "-")] = val

    raw_token = str(cfg.get("x_gw_token") or "").strip()
    if raw_token:
        salt = generate_salt()
        headers["x-gw-salt-key"] = salt
        headers["x-gw-token"] = encrypt_token(raw_token, salt)
    return headers
