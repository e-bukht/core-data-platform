from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


def configure_openapi(app: FastAPI, *, issuer: str) -> None:
    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["oidc"] = {
            "type": "openIdConnect",
            "openIdConnectUrl": discovery_url,
        }
        paths = schema.get("paths", {})
        for path, operations in paths.items():
            if path.startswith("/platform/") and isinstance(operations, dict):
                for operation in operations.values():
                    if isinstance(operation, dict):
                        operation["security"] = [{"oidc": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
