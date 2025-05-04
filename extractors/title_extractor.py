"""
タイトル抽出モジュール

このモジュールは、メッセージからタイトル情報を抽出する機能を提供します。
"""

import re
import logging
from typing import Optional, Tuple
import traceback

# ロガーの設定
logger = logging.getLogger(__name__)

class TitleExtractor:
    """タイトル抽出クラス"""
    
    def __init__(self):
        """初期化"""
        # 時間表現を一時的なマーカーに置き換えるためのパターン
        self.time_patterns = [
            r'\d{1,2}時(?:\d{1,2}分)?(?:から|まで)?',
            r'午前|午後|朝|昼|夕方|夜',
            r'\d{1,2}:\d{2}',
        ]
        
        # 助詞のパターン
        self.particles = 'で|に|へ|から|まで|と|の|は|が|を'
        
        # 場所を示す可能性のある語句
        self.location_indicators = 'で|にて|において|会場は|場所は'
        
        # 除外するキーワード
        self.exclude_keywords = [
            "予定を", "予定の", "予定は", "予定に", "予定で", "予定が",
            "予定を追加", "予定を削除", "予定を変更", "予定を確認",
            "追加", "削除", "変更", "確認", "教えて", "表示"
        ]
    
    def extract(self, text: str) -> str:
        """
        テキストからタイトルを抽出する
        
        Args:
            text (str): 入力テキスト
            
        Returns:
            str: 抽出されたタイトル
        """
        try:
            # 時間表現を除去
            processed_text = re.sub(r'\d{1,2}月\d{1,2}日', '', text)
            processed_text = re.sub(r'\d{1,2}時(?:\d{1,2}分)?', '', processed_text)
            
            # 参加者情報を除去
            processed_text = re.sub(r'参加者は.*?(?:と|、|。|$)', '', processed_text)
            
            # 操作タイプのキーワードを除去
            processed_text = re.sub(r'追加|削除|変更|確認|して|ください|お願い', '', processed_text)
            
            # 余分な空白と句読点を除去
            title = re.sub(r'\s+', ' ', processed_text).strip()
            title = re.sub(r'[、。]', '', title)
            
            # タイトルが空の場合はデフォルト値を返す
            if not title:
                return "予定"
            
            # タイトルが短すぎる場合はデフォルト値を返す
            if len(title) < 2:
                return "予定"
            
            return title
        except Exception as e:
            logger.error(f"タイトルの抽出中にエラーが発生: {str(e)}")
            return "予定"

    def extract_with_location(self, message: str) -> Tuple[Optional[str], Optional[str]]:
        """
        メッセージからタイトルと場所を抽出する
        
        Args:
            message (str): ユーザーからのメッセージ
            
        Returns:
            Tuple[Optional[str], Optional[str]]: タイトルと場所のタプル
        """
        try:
            logger.info(f"タイトルを抽出: {message}")
            
            # 時間表現を一時的なマーカーに置き換え
            processed_text = message
            for pattern in self.time_patterns:
                processed_text = re.sub(pattern, 'TIME_MARKER', processed_text)
            
            # タイトルの抽出パターン
            title_patterns = [
                # "〇〇の打ち合わせ"
                r'(.+?)(?:の)?(?:打ち?合わせ|ミーティング|会議)',
                # "〇〇さんと打ち合わせ"
                r'(.+?)(?:さん|君|様|氏)と(?:の)?(?:打ち?合わせ|ミーティング|会議)',
                # 一般的なパターン
                r'(.+?)(?:' + self.particles + r')',
            ]
            
            title = None
            for pattern in title_patterns:
                match = re.search(pattern, processed_text)
                if match:
                    title = match.group(1).strip()
                    # TIME_MARKERが含まれている場合は除外
                    if 'TIME_MARKER' not in title:
                        break
            
            # 場所の抽出
            location = None
            location_pattern = f'(?:{self.location_indicators})([^{self.particles}]+)'
            location_match = re.search(location_pattern, processed_text)
            if location_match:
                location = location_match.group(1).strip()
            
            # タイトルが見つからない場合は人名を探す
            if not title:
                person_match = re.search(r'([^\s]+?)(?:さん|君|様|氏)と', message)
                if person_match:
                    person = person_match.group(1)
                    title = f"{person}さんと打合せ"
                else:
                    title = "予定"
            
            return title, location
            
        except Exception as e:
            logger.error(f"タイトルの抽出中にエラーが発生: {str(e)}")
            return None, None 