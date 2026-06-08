from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.data.database import get_db
from backend.data.repository_factory import create_repository


router = APIRouter(tags=["fusion-strategy-projection"])

_SERVICE_CLASS: type[Any] | None = None
_SERVICE_MODULE: Any | None = None


def _get_service_class() -> type[Any]:
    global _SERVICE_CLASS, _SERVICE_MODULE
    if _SERVICE_CLASS is not None:
        return _SERVICE_CLASS

    service_path = Path(__file__).resolve().parent.parent / "services" / "fusion_strategy_projection_service.py"
    spec = spec_from_file_location("backend_fusion_strategy_projection_service", service_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load fusion projection service: {service_path}")

    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _SERVICE_MODULE = module
    _SERVICE_CLASS = module.FusionStrategyProjectionService
    return _SERVICE_CLASS


def _get_unsupported_strategy_error() -> type[Exception]:
    _get_service_class()
    if _SERVICE_MODULE is None:
        raise RuntimeError("fusion projection service module not loaded")
    return _SERVICE_MODULE.UnsupportedFusionStrategyError


def _get_fusion_strategy_name() -> str:
    _get_service_class()
    if _SERVICE_MODULE is None:
        raise RuntimeError("fusion projection service module not loaded")
    return str(getattr(_SERVICE_MODULE, "FUSION_STRATEGY_NAME", "ranktrend_early_big_move_v3_lifecycle_fusion"))


@router.get("/api/backtests/{run_id}/fusion-projections")
def get_fusion_strategy_projections(
    run_id: str,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    repo = create_repository(db)
    service_class = _get_service_class()
    unsupported_strategy_error = _get_unsupported_strategy_error()
    fusion_strategy_name = _get_fusion_strategy_name()
    try:
        result = service_class(repo).build_backtest_projection_response(run_id)
    except unsupported_strategy_error as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "unsupported_strategy",
                "runId": run_id,
                "strategyName": getattr(exc, "strategy_name", ""),
                "expectedStrategyName": fusion_strategy_name,
            },
        ) from exc
    if not result:
        raise HTTPException(status_code=404, detail={"code": "run_not_found", "runId": run_id})
    return result
