"""
繰り返し情報抽出モジュール

このモジュールは、メッセージから繰り返し情報を抽出する機能を提供します。
"""

import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any

# ロガーの設定
logger = logging.getLogger(__name__)

class RecurrenceExtractor:
    """繰り返し情報抽出クラス"""
    
    def __init__(self):
        """初期化"""
        # 繰り返しパターンの定義
        self.patterns = {
            "daily": [
                r"毎日",
                r"(\d+)日ごと",
                r"(\d+)日間隔"
            ],
            "weekly": [
                r"毎週",
                r"(\d+)週間ごと",
                r"(\d+)週間隔",
                r"毎週(月|火|水|木|金|土|日)曜日"
            ],
            "monthly": [
                r"毎月",
                r"(\d+)ヶ月ごと",
                r"(\d+)ヶ月間隔",
                r"毎月(\d+)日"
            ]
        }
        
        # 繰り返し回数のパターン
        self.count_patterns = [
            r"(\d+)回",
            r"(\d+)回目まで"
        ]
        
        # 終了日のパターン
        self.until_patterns = [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日まで",
            r"(\d{1,2})月(\d{1,2})日まで",
            r"(\d{1,2})日まで"
        ]
        
        # 曜日のマッピング
        self.weekday_map = {
            "月": "MO", "火": "TU", "水": "WE", "木": "TH",
            "金": "FR", "土": "SA", "日": "SU"
        }
    
    def extract(self, message: str) -> Optional[Dict[str, Any]]:
        """
        メッセージから繰り返し情報を抽出する
        
        Args:
            message (str): ユーザーからのメッセージ
            
        Returns:
            Optional[Dict[str, Any]]: 繰り返し情報
                - frequency: 頻度（daily, weekly, monthly）
                - interval: 間隔（1, 2, 3...）
                - count: 繰り返し回数
                - until: 終了日
                - byday: 曜日指定（weeklyの場合）
                - bymonthday: 日指定（monthlyの場合）
        """
        try:
            logger.info(f"繰り返し情報を抽出: {message}")
            
            # 頻度の検出
            frequency = None
            interval = 1
            weekday = None
            monthday = None
            
            for freq, freq_patterns in self.patterns.items():
                for pattern in freq_patterns:
                    match = re.search(pattern, message)
                    if match:
                        frequency = freq
                        if len(match.groups()) > 0:
                            if freq == "daily":
                                interval = int(match.group(1))
                            elif freq == "weekly":
                                if match.group(1) in self.weekday_map:
                                    weekday = self.weekday_map[match.group(1)]
                                else:
                                    interval = int(match.group(1))
                            elif freq == "monthly":
                                if len(match.groups()) == 1:
                                    interval = int(match.group(1))
                                else:
                                    monthday = int(match.group(2))
                        break
                if frequency:
                    break
            
            # 繰り返し回数の検出
            count = None
            for pattern in self.count_patterns:
                match = re.search(pattern, message)
                if match:
                    count = int(match.group(1))
                    break
            
            # 終了日の検出
            until = None
            for pattern in self.until_patterns:
                match = re.search(pattern, message)
                if match:
                    if len(match.groups()) == 3:
                        year = int(match.group(1))
                        month = int(match.group(2))
                        day = int(match.group(3))
                        until = datetime(year, month, day)
                    elif len(match.groups()) == 2:
                        month = int(match.group(1))
                        day = int(match.group(2))
                        year = datetime.now().year
                        until = datetime(year, month, day)
                        if until < datetime.now():
                            until = datetime(year + 1, month, day)
                    else:
                        day = int(match.group(1))
                        today = datetime.now()
                        until = datetime(today.year, today.month, day)
                        if until < today:
                            if today.month == 12:
                                until = datetime(today.year + 1, 1, day)
                            else:
                                until = datetime(today.year, today.month + 1, day)
                    break
            
            # 結果の構築
            result = None
            if frequency:
                result = {
                    "frequency": frequency,
                    "interval": interval
                }
                
                if weekday:
                    result["byday"] = weekday
                if monthday:
                    result["bymonthday"] = monthday
                if count:
                    result["count"] = count
                if until:
                    result["until"] = until
            
            logger.info(f"抽出された繰り返し情報: {result}")
            return result
            
        except Exception as e:
            logger.error(f"繰り返し情報の抽出中にエラーが発生: {str(e)}")
            return None 