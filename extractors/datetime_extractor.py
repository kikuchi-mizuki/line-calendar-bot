"""
日時抽出モジュール

このモジュールは、メッセージから日時情報を抽出する機能を提供します。
"""

import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import traceback
import pytz

# ロガーの設定
logger = logging.getLogger(__name__)

class DateTimeExtractor:
    """日時抽出クラス"""
    
    def __init__(self):
        """初期化"""
        self.timezone = pytz.timezone('Asia/Tokyo')
        self.date_pattern = re.compile(r'(\d+)月(\d+)日')
        self.time_pattern = re.compile(r'(\d{1,2})時')
        
        # 日付パターンの定義
        self.date_patterns = [
            (r"今日", lambda _: datetime.now(self.timezone)),
            (r"明日", lambda _: datetime.now(self.timezone) + timedelta(days=1)),
            (r"明後日", lambda _: datetime.now(self.timezone) + timedelta(days=2)),
            (r"(\d+)日後", lambda m: datetime.now(self.timezone) + timedelta(days=int(m.group(1)))),
            (r"(\d{4})年(\d{1,2})月(\d{1,2})日", lambda m: self.timezone.localize(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))))),
            (r"(\d{1,2})月(\d{1,2})日", lambda m: self._create_date(int(m.group(1)), int(m.group(2)))),
            (r"(\d{1,2})/(\d{1,2})", lambda m: self._create_date(int(m.group(1)), int(m.group(2)))),
            (r"来週(\w+)曜日", lambda m: self._get_next_weekday(m.group(1))),
            (r"今週(\w+)曜日", lambda m: self._get_this_weekday(m.group(1))),
        ]
        
        # 時刻パターンの定義
        self.time_patterns = [
            (r"(\d{1,2})時(\d{2})分", lambda m: (int(m.group(1)), int(m.group(2)))),
            (r"(\d{1,2})時", lambda m: (int(m.group(1)), 0)),
            (r"午前(\d{1,2})時(\d{2})分", lambda m: (int(m.group(1)), int(m.group(2)))),
            (r"午前(\d{1,2})時", lambda m: (int(m.group(1)), 0)),
            (r"午後(\d{1,2})時(\d{2})分", lambda m: (int(m.group(1)) + 12, int(m.group(2)))),
            (r"午後(\d{1,2})時", lambda m: (int(m.group(1)) + 12, 0)),
            (r"(\d{1,2}):(\d{2})", lambda m: (int(m.group(1)), int(m.group(2)))),
            (r"(\d{1,2})時から", lambda m: (int(m.group(1)), 0)),
            (r"(\d{1,2})時半", lambda m: (int(m.group(1)), 30)),
        ]
        
        # 曜日のマッピング
        self.weekday_map = {
            "月": 0, "火": 1, "水": 2, "木": 3,
            "金": 4, "土": 5, "日": 6
        }
    
    def extract(self, text: str) -> Tuple[datetime, datetime, bool]:
        """
        テキストから日時情報を抽出する
        
        Args:
            text (str): 入力テキスト
            
        Returns:
            Tuple[datetime, datetime, bool]: (開始時刻, 終了時刻, 日付のみフラグ)
        """
        try:
            logger.info(f"日時を抽出: {text}")
            
            # 相対的な日付表現を先にチェック
            for pattern, func in self.date_patterns:
                match = re.search(pattern, text)
                if match:
                    date = func(match)
                    logger.info(f"相対的な日付を抽出: {date}")
                    
                    # 時刻の抽出を試みる
                    for time_pattern, time_func in self.time_patterns:
                        time_match = re.search(time_pattern, text)
                        if time_match:
                            hour, minute = time_func(time_match)
                            # 開始時刻を作成
                            start_time = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                            # 終了時刻を設定（デフォルトで1時間後）
                            end_time = start_time + timedelta(hours=1)
                            logger.info(f"時刻を含む日時を抽出: {start_time} - {end_time}")
                            return start_time, end_time, False
                    
                    # 時刻が見つからない場合は、その日の0:00から23:59を範囲とする
                    start_time = date.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_time = date.replace(hour=23, minute=59, second=59, microsecond=999999)
                    logger.info(f"日付のみを抽出: {start_time} - {end_time}")
                    return start_time, end_time, True
            
            # 特定の日付パターンをチェック
            date_match = re.search(r'(\d+)月(\d+)日', text)
            if date_match:
                month = int(date_match.group(1))
                day = int(date_match.group(2))
                current_year = datetime.now(self.timezone).year
                naive_date = datetime(current_year, month, day)
                date = self.timezone.localize(naive_date)
                logger.info(f"特定の日付を抽出: {date}")

                # 時刻の抽出を試みる
                for time_pattern, time_func in self.time_patterns:
                    time_match = re.search(time_pattern, text)
                    if time_match:
                        hour, minute = time_func(time_match)
                        start_time = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        end_time = start_time + timedelta(hours=1)
                        logger.info(f"時刻を含む日時を抽出: {start_time} - {end_time}")
                        return start_time, end_time, False
                
                # 時刻が見つからない場合は、その日の0:00から23:59を範囲とする
                start_time = date.replace(hour=0, minute=0, second=0, microsecond=0)
                end_time = date.replace(hour=23, minute=59, second=59, microsecond=999999)
                logger.info(f"日付のみを抽出: {start_time} - {end_time}")
                return start_time, end_time, True

            # 相対的な日付表現の追加パターン
            relative_patterns = [
                (r"明日", lambda _: datetime.now(self.timezone) + timedelta(days=1)),
                (r"明後日", lambda _: datetime.now(self.timezone) + timedelta(days=2)),
                (r"(\d+)日後", lambda m: datetime.now(self.timezone) + timedelta(days=int(m.group(1)))),
                (r"来週(\w+)曜日", lambda m: self._get_next_weekday(m.group(1))),
                (r"今週(\w+)曜日", lambda m: self._get_this_weekday(m.group(1)))
            ]

            for pattern, func in relative_patterns:
                match = re.search(pattern, text)
                if match:
                    date = func(match)
                    logger.info(f"相対的な日付を抽出: {date}")
                    
                    # 時刻の抽出を試みる
                    for time_pattern, time_func in self.time_patterns:
                        time_match = re.search(time_pattern, text)
                        if time_match:
                            hour, minute = time_func(time_match)
                            start_time = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                            end_time = start_time + timedelta(hours=1)
                            logger.info(f"時刻を含む日時を抽出: {start_time} - {end_time}")
                            return start_time, end_time, False
                    
                    # 時刻が見つからない場合は、その日の0:00から23:59を範囲とする
                    start_time = date.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_time = date.replace(hour=23, minute=59, second=59, microsecond=999999)
                    logger.info(f"日付のみを抽出: {start_time} - {end_time}")
                    return start_time, end_time, True

            # 日付が見つからない場合は、今日の日付で0:00〜23:59を返す
            now = datetime.now(self.timezone)
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            logger.info(f"デフォルトで今日の日付を返します: {start_time} - {end_time}")
            return start_time, end_time, True

        except Exception as e:
            logger.error(f"日時抽出中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            # エラー時も今日の日付を返す
            now = datetime.now(self.timezone)
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            return start_time, end_time, True
    
    def _create_date(self, month: int, day: int) -> datetime:
        """
        月と日から日付を作成する
        
        Args:
            month (int): 月
            day (int): 日
            
        Returns:
            datetime: 作成された日付
        """
        today = datetime.now(self.timezone)
        year = today.year
        
        # 月が現在より前の場合、来年として扱う
        if month < today.month or (month == today.month and day < today.day):
            year += 1
            
        # 日付を作成し、タイムゾーンを設定
        naive_date = datetime(year, month, day)
        date = self.timezone.localize(naive_date)
        return date
    
    def _get_next_weekday(self, weekday_str: str) -> datetime:
        """
        次の指定された曜日の日付を取得する
        
        Args:
            weekday_str (str): 曜日の文字列（月、火、水、木、金、土、日）
            
        Returns:
            datetime: 次の指定された曜日の日付
        """
        if weekday_str not in self.weekday_map:
            raise ValueError(f"無効な曜日: {weekday_str}")
        
        target_weekday = self.weekday_map[weekday_str]
        now = datetime.now(self.timezone)
        days_ahead = target_weekday - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return now + timedelta(days=days_ahead)
    
    def _get_this_weekday(self, weekday_str: str) -> datetime:
        """
        今週の指定された曜日の日付を取得する
        
        Args:
            weekday_str (str): 曜日の文字列（月、火、水、木、金、土、日）
            
        Returns:
            datetime: 今週の指定された曜日の日付
        """
        if weekday_str not in self.weekday_map:
            raise ValueError(f"無効な曜日: {weekday_str}")
        
        target_weekday = self.weekday_map[weekday_str]
        now = datetime.now(self.timezone)
        days_ahead = target_weekday - now.weekday()
        if days_ahead < 0:
            days_ahead += 7
        return now + timedelta(days=days_ahead) 