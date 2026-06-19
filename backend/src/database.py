def save_analysis_cache(
    match_id: str,
    frame_id: int,
    result_json: dict,
    supabase_url: str,
    supabase_key: str,
) -> bool:
    """
    【2年生担当タスク】
    計算済みのPitch Control結果（JSON）をSupabaseのテーブルに保存する。
    """
    raise NotImplementedError("save_analysis_cache は2年生が実装してください。")
