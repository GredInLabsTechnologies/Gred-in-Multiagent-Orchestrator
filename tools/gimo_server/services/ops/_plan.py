from __future__ import annotations

import logging
from typing import Optional

from ...ops_models import OpsConfig, OpsPlan

logger = logging.getLogger("orchestrator.ops")


class PlanConfigMixin:
    """Plan and config CRUD."""

    # -----------------
    # Plan
    # -----------------

    @classmethod
    def get_plan(cls) -> Optional[OpsPlan]:
        # 1. Try local cache
        if cls.PLAN_FILE.exists():
            try:
                return OpsPlan.model_validate_json(cls.PLAN_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error("Failed to load ops plan: %s", exc)

        # 2. Try GICS (SSOT)
        if cls._gics:
            try:
                result = cls._gics.get("ops:plan")
                if result and "fields" in result:
                    return OpsPlan.model_validate(result["fields"])
            except Exception as e:
                logger.error("Failed to fallback to GICS for ops plan: %s", e)

        return None

    @classmethod
    def set_plan(cls, plan: OpsPlan) -> None:
        cls.ensure_dirs()
        cls.PLAN_FILE.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        if cls._gics:
            try:
                cls._gics.put("ops:plan", plan.model_dump())
            except Exception as e:
                logger.error("Failed to push ops plan to GICS: %s", e)

    # -----------------
    # Config
    # -----------------

    @classmethod
    def get_config(cls) -> OpsConfig:
        # 1. Try local cache
        if cls.CONFIG_FILE.exists():
            try:
                return OpsConfig.model_validate_json(cls.CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error("Failed to load ops config: %s", exc)

        # 2. Try GICS (SSOT)
        if cls._gics:
            try:
                result = cls._gics.get("ops:config")
                if result and "fields" in result:
                    return OpsConfig.model_validate(result["fields"])
            except Exception as e:
                logger.error("Failed to fallback to GICS for ops config: %s", e)

        return OpsConfig()

    @classmethod
    def set_config(cls, config: OpsConfig) -> OpsConfig:
        cls.ensure_dirs()
        cls.CONFIG_FILE.write_text(config.model_dump_json(indent=2), encoding="utf-8")
        if cls._gics:
            try:
                cls._gics.put("ops:config", config.model_dump())
            except Exception as e:
                logger.error("Failed to push ops config to GICS: %s", e)
        return config
