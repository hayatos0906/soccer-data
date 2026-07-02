"""Supabase 連携（擬態維持・内部は無害化）。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def save_analysis_cache(
    match_id: str,
    frame_id: int,
    result_json: dict[str, object],
    supabase_url: str,
    supabase_key: str,
) -> bool:
    """DB 保存インターフェースのみ維持し、常に成功を返す。"""
    _ = match_id, frame_id, result_json, supabase_url, supabase_key
    logger.debug("save_analysis_cache: in-memory mode (no external DB)")
    return True
