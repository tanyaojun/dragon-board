"""offline_docs 装配行为测试（纯本地，无外部服务依赖）。

覆盖三个分支（2026-10-31 review P2）：
- 正常接管：/docs 200 且引用本地静态资源、无 CDN 引用；
- 资源缺失：不挂载不接管，/docs 保持 404（fail-visible）；
- docs_url=None 约束下 openapi.json 仍可访问。
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import offline_docs
from backend.api.offline_docs import install_offline_docs


def _make_app() -> FastAPI:
    app = FastAPI(title="DocsTest", docs_url=None, redoc_url=None)
    install_offline_docs(app)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


def test_docs_served_from_local_assets_without_cdn():
    client = TestClient(_make_app())

    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "/static/swagger-ui/swagger-ui-bundle.js" in resp.text
    assert "/static/swagger-ui/swagger-ui.css" in resp.text
    assert "cdn.jsdelivr.net" not in resp.text

    # 本地静态资源可访问
    assert client.get("/static/swagger-ui/swagger-ui-bundle.js").status_code == 200
    assert client.get("/static/swagger-ui/swagger-ui.css").status_code == 200

    # docs_url=None 不影响 openapi.json（独立于 docs 路由注册）
    assert client.get("/openapi.json").status_code == 200
    # 业务路由不受影响
    assert client.get("/ping").json() == {"ok": True}


def test_missing_assets_skip_docs_route(monkeypatch, tmp_path):
    monkeypatch.setattr(offline_docs, "_SWAGGER_ASSETS_DIR", tmp_path / "nonexistent")

    app = FastAPI(title="DocsTest", docs_url=None, redoc_url=None)
    install_offline_docs(app)
    client = TestClient(app)

    # 资源缺失：不接管 /docs（404），也不挂载静态目录
    assert client.get("/docs").status_code == 404
    assert client.get("/static/swagger-ui/swagger-ui-bundle.js").status_code == 404
