"""离线 Swagger UI 文档装配。

背景（2026-10-31 复盘）：FastAPI 默认 /docs 从 cdn.jsdelivr.net 拉取
swagger-ui 静态资源，本机访问该 CDN 单资源延迟 8s+（浏览器按超时放弃），
导致 8000/8001 的 /docs 页面框架已加载但 JS/CSS 拿不到，表现为整页空白。

方案：资源自托管到 ``backend/static/swagger-ui/``（版本固定 5.17.14），
挂载 ``/static/swagger-ui`` 并用本地 URL 渲染 /docs，无外网依赖。

使用约束：宿主 app 必须以 ``docs_url=None`` 创建（避免默认 /docs 路由
先行注册导致本路由被遮蔽），随后调用 :func:`install_offline_docs`。

资源来源：npm ``swagger-ui-dist@5.17.14`` 官方 dist（
https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/），首次引入时下载
入库；升级版本时整目录同轮替换并同步更新本注释。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

_SWAGGER_ASSETS_DIR = Path(__file__).resolve().parent.parent / "static" / "swagger-ui"


def install_offline_docs(app: FastAPI) -> None:
    """挂载本地 swagger-ui 静态资源并接管 /docs 路由。

    资源缺失时不抛异常、只记日志并跳过接管（此时 /docs 由 docs_url=None
    保持 404，fail-visible，不会退回不可用的 CDN 版本）。
    """
    index_js = _SWAGGER_ASSETS_DIR / "swagger-ui-bundle.js"
    index_css = _SWAGGER_ASSETS_DIR / "swagger-ui.css"
    if not (index_js.is_file() and index_css.is_file()):
        import logging

        logging.getLogger(__name__).warning(
            "swagger-ui 静态资源缺失: %s（/docs 将不可用），"
            "请补齐 backend/static/swagger-ui/ 下的 swagger-ui-bundle.js 与 swagger-ui.css",
            _SWAGGER_ASSETS_DIR,
        )
        return

    app.mount(
        "/static/swagger-ui",
        StaticFiles(directory=str(_SWAGGER_ASSETS_DIR)),
        name="swagger-ui",
    )

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui_html():  # pragma: no cover - 轻量装配，无业务分支
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=f"{app.title} - Swagger UI",
            # docs_url=None 时 FastAPI 不会注册 /docs/oauth2-redirect（review P2：
            # 引用未注册路由只会 404）；本项目无 OAuth2 流，显式置空。
            oauth2_redirect_url=None,
            swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui/swagger-ui.css",
        )
