"""
タイトル抽出モジュール

このモジュールは、メッセージからタイトル情報を抽出する機能を提供します。
"""

import re
import logging
from typing import Optional, Tuple

# ロガーの設定
logger = logging.getLogger(__name__)

class TitleExtractor:
    """タイトル抽出クラス"""
    
    def __init__(self):
        """初期化"""
        # タイトル抽出のパターン
        self.title_patterns = [
            r"「([^」]+)」",  # 「」で囲まれたテキスト
            r"『([^』]+)』",  # 『』で囲まれたテキスト
            r"【([^】]+)】",  # 【】で囲まれたテキスト
            r"\[([^\]]+)\]",  # []で囲まれたテキスト
            r"（([^）]+)）",   # （）で囲まれたテキスト
            r"\(([^)]+)\)",   # ()で囲まれたテキスト
        ]
        
        # 除外するキーワード
        self.exclude_keywords = [
            "予定を", "予定の", "予定は", "予定に", "予定で", "予定が",
            "予定を追加", "予定を削除", "予定を変更", "予定を確認",
            "追加", "削除", "変更", "確認", "教えて", "表示"
        ]
    
    def extract(self, message: str) -> Tuple[Optional[str], Optional[str]]:
        """
        メッセージからタイトルと場所を抽出する
        
        Args:
            message (str): ユーザーからのメッセージ
            
        Returns:
            Tuple[Optional[str], Optional[str]]: タイトルと場所のタプル
        """
        try:
            logger.info(f"タイトルを抽出: {message}")
            
            # 括弧で囲まれたテキストを抽出
            title = None
            for pattern in self.title_patterns:
                match = re.search(pattern, message)
                if match:
                    title = match.group(1).strip()
                    if title:  # 空でないことを確認
                        logger.info(f"抽出されたタイトル: {title}")
                        break
            
            # 括弧で囲まれていない場合、日時情報の前後のテキストを確認
            if not title:
                # 日時情報を除去
                message_without_datetime = re.sub(
                    r'\d+月\d+日|\d+時\d+分|\d+時|今日|明日|明後日|来週\w+曜日|今週\w+曜日',
                    '', message
                )
                message_without_datetime = re.sub(r'午前|午後|\d+日後', '', message_without_datetime)
                
                # コマンドを除去
                message_without_commands = message_without_datetime
                for keyword in self.exclude_keywords:
                    message_without_commands = re.sub(keyword, '', message_without_commands)
                
                # 残りのテキストをトリム
                title = message_without_commands.strip()
                if title:
                    logger.info(f"抽出されたタイトル: {title}")
            
            # 場所の抽出
            location = None
            location_patterns = [
                r"@([^@\s]+)",  # @渋谷
                r"＠([^＠\s]+)",  # ＠渋谷
                r"で([^で\s]+)(?:で|に|へ|と|は|が|を|$)",  # 渋谷で
                r"にて([^にて\s]+)(?:で|に|へ|と|は|が|を|$)",  # 渋谷にて
                r"場所[：:]\s*([^\n]+)",  # 場所: 渋谷
                r"会場[：:]\s*([^\n]+)",  # 会場: 渋谷
                r"場所は([^\n]+)",  # 場所は渋谷
                r"会場は([^\n]+)",  # 会場は渋谷
            ]
            
            for pattern in location_patterns:
                match = re.search(pattern, message)
                if match:
                    location = match.group(1).strip()
                    if location:  # 空でないことを確認
                        logger.info(f"抽出された場所: {location}")
                        break
            
            if not title:
                logger.warning("タイトルを抽出できませんでした")
                return None, location
            
            return title, location
            
        except Exception as e:
            logger.error(f"タイトルの抽出中にエラーが発生: {str(e)}")
            return None, None 