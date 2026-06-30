import logging
from supabase import Client, create_client

# ロガーの設定（エラー発生時のデバッグ用）
logger = logging.getLogger(__name__)


def save_analysis_cache(
    match_id: str,
    frame_id: int,
    result_json: dict,
    supabase_url: str,
    supabase_key: str,
) -> bool:
    """計算済みのPitch Control結果（JSON）をSupabaseのテーブルに保存する。

    Args:
        match_id (str): 試合の識別子
        frame_id (int): フレーム番号
        result_json (dict): 保存する分析結果データ
        supabase_url (str): SupabaseのプロジェクトURL
        supabase_key (str): SupabaseのAPIキー（Anon Key または Service Role Key）

    Returns:
        bool: 保存に成功した場合は True、失敗した場合は False
    """
    # 引数のバリデーション（簡易チェック）
    if not supabase_url or not supabase_key:
        logger.error("SupabaseのURLまたはKEYが設定されていません。")
        return False

    try:
        # 1. Supabaseクライアントの初期化
        supabase: Client = create_client(supabase_url, supabase_key)

        # 2. 挿入するデータの構築
        # ※テーブル名やカラム名は、Supabase側で作成したスキーマに合わせて適宜調整してください。
        # ここでは一般的なカラム名（match_id, frame_id, result）と仮定しています。
        data_to_insert = {
            "match_id": match_id,
            "frame_id": frame_id,
            "result": result_json,
        }

        # 3. データの挿入（upsertにすることで、同じ試合・フレームの重複エラーを防ぐ設計がおすすめ）
        # テーブル名：'analysis_cache' と仮定
        response = (
            supabase.table("analysis_cache").upsert(data_to_insert).execute()
        )

        # 4. レスポンスの確認
        # supabase-py では、成功すると .data に挿入されたレコードのリストが返ります
        if response.data:
            return True

        logger.warning(
            f"データは送信されましたが、返り値が空です。 (match_id: {match_id}, frame_id: {frame_id})"
        )
        return False

    except Exception as e:
        # データベース接続エラーやテーブル不在などの例外をキャッチ
        logger.error(
            f"Supabaseへのデータ保存中にエラーが発生しました: {str(e)} "
            f"(match_id: {match_id}, frame_id: {frame_id})"
        )
        return False