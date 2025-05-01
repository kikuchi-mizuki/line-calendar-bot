import unittest
from datetime import datetime, timedelta
import re
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_datetime_from_message(message):
    """メッセージから日時情報を抽出する"""
    try:
        # 現在の日時を取得
        now = datetime.now()
        
        # 日付の抽出を試みる
        date = None
        time_str = None
        
        # 今日、明日、明後日のパターン
        if "今日" in message:
            date = now.date()
        elif "明日" in message:
            date = (now + timedelta(days=1)).date()
        elif "明後日" in message:
            date = (now + timedelta(days=2)).date()
        else:
            # 数字の日付パターン（例：5月1日、5/1）
            date_patterns = [
                r'(\d{1,2})月(\d{1,2})日',
                r'(\d{1,2})/(\d{1,2})',
                r'(\d{1,2})-(\d{1,2})'
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, message)
                if match:
                    month = int(match.group(1))
                    day = int(match.group(2))
                    year = now.year
                    
                    # 月が現在より前の場合、来年として扱う
                    if month < now.month or (month == now.month and day < now.day):
                        year += 1
                        
                    date = datetime(year, month, day).date()
                    break
        
        # 時刻の抽出
        time_patterns = [
            r'(\d{1,2})時(\d{2})分',
            r'(\d{1,2}):(\d{2})',
            r'(\d{1,2})時'
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, message)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2)) if len(match.groups()) > 1 else 0
                time_str = f"{hour:02d}:{minute:02d}"
                break
        
        if not date or not time_str:
            return None, None
            
        # 日付と時刻を結合
        start_time = datetime.combine(date, datetime.strptime(time_str, "%H:%M").time())
        
        # 終了時間の推定（デフォルトで1時間後）
        end_time = start_time + timedelta(hours=1)
        
        return start_time, end_time
        
    except Exception as e:
        logger.error(f"Error in extract_datetime_from_message: {str(e)}")
        return None, None

def extract_reschedule_times(message):
    """メッセージから予定変更の時間情報を抽出する"""
    try:
        # 予定変更のパターンを検出
        reschedule_patterns = [
            r'(\d{1,2}時(?:\d{2}分)?|\d{1,2}:\d{2})から(\d{1,2}時(?:\d{2}分)?|\d{1,2}:\d{2})(?:に|へ)変更',
            r'(\d{1,2}時(?:\d{2}分)?|\d{1,2}:\d{2})を(\d{1,2}時(?:\d{2}分)?|\d{1,2}:\d{2})(?:に|へ)変更'
        ]
        
        for pattern in reschedule_patterns:
            match = re.search(pattern, message)
            if match:
                old_time_str = match.group(1)
                new_time_str = match.group(2)
                
                # 日付情報を含むメッセージを作成
                date_info = ""
                if "今日" in message:
                    date_info = "今日"
                elif "明日" in message:
                    date_info = "明日"
                elif "明後日" in message:
                    date_info = "明後日"
                else:
                    # 日付パターンの検索
                    date_patterns = [
                        r'(\d{1,2})月(\d{1,2})日',
                        r'(\d{1,2})[/-](\d{1,2})'  # スラッシュとハイフンを同時に処理
                    ]
                    for date_pattern in date_patterns:
                        date_match = re.search(date_pattern, message)
                        if date_match:
                            month = date_match.group(1)
                            day = date_match.group(2)
                            date_info = f"{month}月{day}日"
                            break
                
                # 日付情報を含むメッセージを作成
                old_time_message = f"{date_info}{old_time_str}"
                new_time_message = f"{date_info}{new_time_str}"
                
                # 日時情報を抽出
                old_start, old_end = extract_datetime_from_message(old_time_message)
                new_start, new_end = extract_datetime_from_message(new_time_message)
                
                if old_start and new_start:
                    return old_start, old_end, new_start, new_end
                
        return None, None, None, None
        
    except Exception as e:
        logger.error(f"Error in extract_reschedule_times: {str(e)}")
        return None, None, None, None

class TestExtractRescheduleTimes(unittest.TestCase):
    def setUp(self):
        # テストの基準となる現在時刻を設定
        self.now = datetime.now()
        
    def test_today_time_change(self):
        # 今日の予定変更テスト
        message = "今日の12時30分から13時30分に変更"
        old_start, old_end, new_start, new_end = extract_reschedule_times(message)
        
        self.assertIsNotNone(old_start)
        self.assertIsNotNone(new_start)
        self.assertEqual(old_start.hour, 12)
        self.assertEqual(old_start.minute, 30)
        self.assertEqual(new_start.hour, 13)
        self.assertEqual(new_start.minute, 30)
        self.assertEqual(old_start.date(), self.now.date())
        self.assertEqual(new_start.date(), self.now.date())

    def test_tomorrow_time_change(self):
        # 明日の予定変更テスト
        message = "明日の14:00から15:00へ変更"
        old_start, old_end, new_start, new_end = extract_reschedule_times(message)
        
        self.assertIsNotNone(old_start)
        self.assertIsNotNone(new_start)
        self.assertEqual(old_start.hour, 14)
        self.assertEqual(old_start.minute, 0)
        self.assertEqual(new_start.hour, 15)
        self.assertEqual(new_start.minute, 0)
        self.assertEqual(old_start.date(), (self.now + timedelta(days=1)).date())
        self.assertEqual(new_start.date(), (self.now + timedelta(days=1)).date())

    def test_day_after_tomorrow_time_change(self):
        # 明後日の予定変更テスト
        message = "明後日の9時を10時に変更"
        old_start, old_end, new_start, new_end = extract_reschedule_times(message)
        
        self.assertIsNotNone(old_start)
        self.assertIsNotNone(new_start)
        self.assertEqual(old_start.hour, 9)
        self.assertEqual(old_start.minute, 0)
        self.assertEqual(new_start.hour, 10)
        self.assertEqual(new_start.minute, 0)
        self.assertEqual(old_start.date(), (self.now + timedelta(days=2)).date())
        self.assertEqual(new_start.date(), (self.now + timedelta(days=2)).date())

    def test_specific_date_time_change(self):
        # 特定の日付の予定変更テスト
        message = "5月1日の12:30を13:30に変更"
        old_start, old_end, new_start, new_end = extract_reschedule_times(message)
        
        self.assertIsNotNone(old_start)
        self.assertIsNotNone(new_start)
        self.assertEqual(old_start.month, 5)
        self.assertEqual(old_start.day, 1)
        self.assertEqual(old_start.hour, 12)
        self.assertEqual(old_start.minute, 30)
        self.assertEqual(new_start.hour, 13)
        self.assertEqual(new_start.minute, 30)

    def test_invalid_message(self):
        # 無効なメッセージのテスト
        message = "予定を変更します"
        old_start, old_end, new_start, new_end = extract_reschedule_times(message)
        
        self.assertIsNone(old_start)
        self.assertIsNone(old_end)
        self.assertIsNone(new_start)
        self.assertIsNone(new_end)

    def test_different_date_formats(self):
        # 異なる日付形式のテスト
        test_cases = [
            ("3/15 9時を10時に変更", 3, 15),
            ("3-15 9時を10時に変更", 3, 15),
            ("3月15日 9時を10時に変更", 3, 15)
        ]
        
        for message, expected_month, expected_day in test_cases:
            old_start, old_end, new_start, new_end = extract_reschedule_times(message)
            self.assertIsNotNone(old_start)
            self.assertEqual(old_start.month, expected_month)
            self.assertEqual(old_start.day, expected_day)

if __name__ == '__main__':
    unittest.main() 