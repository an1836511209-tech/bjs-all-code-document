"""北交所 API 统一管控平台 — 服务提供方适配包"""

__all__ = ["PlatformGwMiddleware", "build_platform_router"]


def __getattr__(name: str):
    if name == "PlatformGwMiddleware":
        from src.platform_gw.middleware import PlatformGwMiddleware

        return PlatformGwMiddleware
    if name == "build_platform_router":
        from src.platform_gw.router import build_platform_router

        return build_platform_router
    raise AttributeError(name)
