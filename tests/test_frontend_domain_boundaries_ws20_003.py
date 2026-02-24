from __future__ import annotations

from pathlib import Path


FRONTEND_SRC = Path("frontend/src")


def _read(path: str) -> str:
    return (FRONTEND_SRC / path).read_text(encoding="utf-8")


def test_ws20_003_domain_route_modules_cover_chat_tools_settings_ops() -> None:
    files = {
        "chat": "domains/chat/routes.ts",
        "tools": "domains/tools/routes.ts",
        "settings": "domains/settings/routes.ts",
        "ops": "domains/ops/routes.ts",
    }
    for rel in files.values():
        assert (FRONTEND_SRC / rel).exists(), rel

    assert "path: '/chat'" in _read(files["chat"])
    assert "path: '/skill'" in _read(files["tools"])
    settings_routes = _read(files["settings"])
    assert "path: '/model'" in settings_routes
    assert "path: '/memory'" in settings_routes
    assert "path: '/config'" in settings_routes
    ops_routes = _read(files["ops"])
    assert "path: '/'" in ops_routes
    assert "path: '/mind'" in ops_routes


def test_ws20_003_router_uses_domain_aggregator() -> None:
    router_routes = _read("router/routes.ts")
    assert "chatRoutes" in router_routes
    assert "toolsRoutes" in router_routes
    assert "settingsRoutes" in router_routes
    assert "opsRoutes" in router_routes

    main_ts = _read("main.ts")
    assert "import { appRoutes } from '@/router/routes'" in main_ts
    assert "routes: appRoutes" in main_ts


def test_ws20_003_chat_views_removed_cross_view_and_core_api_coupling() -> None:
    message_view = _read("views/MessageView.vue")
    floating_view = _read("views/FloatingView.vue")

    assert "@/domains/chat" in message_view
    assert "@/domains/chat" in floating_view
    assert "@/api/core" not in message_view
    assert "@/api/core" not in floating_view
    assert "@/views/MessageView.vue" not in floating_view

    for view_path in (FRONTEND_SRC / "views").glob("*.vue"):
        content = view_path.read_text(encoding="utf-8")
        assert "@/views/" not in content, view_path.name
