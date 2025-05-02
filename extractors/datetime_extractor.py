"""
日時抽出モジュール

このモジュールは、メッセージから日時情報を抽出する機能を提供します。
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple
import traceback

# ロガーの設定
logger = logging.getLogger(__name__)

class DateTimeExtractor:
    """日時抽出クラス"""
    
    def __init__(self):
        """初期化"""
        # 日付パターンの定義
        self.date_patterns = [
            (r"今日", lambda _: datetime.now()),
            (r"明日", lambda _: datetime.now() + timedelta(days=1)),
            (r"明後日", lambda _: datetime.now() + timedelta(days=2)),
            (r"(\d+)日後", lambda m: datetime.now() + timedelta(days=int(m.group(1)))),
            (r"(\d+)月(\d+)日", lambda m: self._create_date(int(m.group(1)), int(m.group(2)))),
            (r"(\d{4})年(\d{1,2})月(\d{1,2})日", lambda m: datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
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
    
    def extract(self, message: str) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        メッセージから日時を抽出する
        
        Args:
            message (str): ユーザーからのメッセージ
            
        Returns:
            Tuple[Optional[datetime], Optional[datetime]]: 開始時刻と終了時刻のタプル
        """
        try:
            logger.info(f"日時を抽出: {message}")
            
            # 日付の抽出
            extracted_date = None
            for pattern, date_func in self.date_patterns:
                match = re.search(pattern, message)
                if match:
                    extracted_date = date_func(match)
                    logger.info(f"抽出された日付: {extracted_date}")
                    break
            
            if not extracted_date:
                logger.warning("日付を抽出できませんでした")
                return None, None
            
            # 時刻の抽出
            start_time = None
            end_time = None
            
            # 開始時刻の抽出
            for pattern, time_func in self.time_patterns:
                # "から"の前の時刻を開始時刻として抽出
                match = re.search(f"{pattern}(?:から|まで|で|に|へ|と|は|が|を|の|も|や|か|ね|よ|な|わ|ぞ|ぜ|だ|です|ます|けど|ので|のに|ば|たら|なら|て|$)", message)
                if match:
                    hours, minutes = time_func(match)
                    start_time = extracted_date.replace(hour=hours, minute=minutes)
                    logger.info(f"抽出された開始時刻: {start_time}")
                    break
            
            # 終了時刻の抽出
            for pattern, time_func in self.time_patterns:
                # "まで"の前の時刻を終了時刻として抽出
                match = re.search(f"{pattern}まで", message)
                if match:
                    hours, minutes = time_func(match)
                    end_time = extracted_date.replace(hour=hours, minute=minutes)
                    logger.info(f"抽出された終了時刻: {end_time}")
                    break
            
            # 終了時刻が抽出できなかった場合、開始時刻から1時間後をデフォルトとする
            if start_time and not end_time:
                end_time = start_time + timedelta(hours=1)
                logger.info(f"デフォルトの終了時刻を設定: {end_time}")
            
            if not start_time or not end_time:
                logger.warning("時刻を抽出できませんでした")
                return None, None
            
            # 終了時刻が開始時刻より前の場合、翌日として扱う
            if end_time < start_time:
                end_time += timedelta(days=1)
                logger.info(f"終了時刻を翌日に設定: {end_time}")
            
            logger.info(f"最終的な日時: {start_time} - {end_time}")
            return start_time, end_time
            
        except Exception as e:
            logger.error(f"日時の抽出中にエラーが発生: {str(e)}")
            logger.error("スタックトレース:")
            logger.error(traceback.format_exc())
            return None, None
    
    def _create_date(self, month: int, day: int) -> datetime:
        """
        月と日から日付を作成する
        
        Args:
            month (int): 月
            day (int): 日
            
        Returns:
            datetime: 作成された日付
        """
        today = datetime.now()
        year = today.year
        
        # 月が現在より前の場合、来年として扱う
        if month < today.month or (month == today.month and day < today.day):
            year += 1
            
        return datetime(year, month, day)
    
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
        now = datetime.now()
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
        now = datetime.now()
        days_ahead = target_weekday - now.weekday()
        if days_ahead < 0:
            days_ahead += 7
        return now + timedelta(days=days_ahead) 