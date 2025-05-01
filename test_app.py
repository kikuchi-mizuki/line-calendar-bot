import pytest
from unittest.mock import Mock, patch, MagicMock
from app import app, CalendarChat
from datetime import datetime, timedelta
import pytz
import os
import json
from message_parser import parse_message
import unittest
from app import extract_reschedule_times
import re
from app import extract_datetime_from_message
from app import extract_title_from_message

# テスト用の環境変数を設定
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'test_credentials.json'
os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = 'test_access_token'
os.environ['LINE_CHANNEL_SECRET'] = 'test_channel_secret'

@pytest.fixture
def mock_calendar_chat():
    mock = MagicMock(spec=CalendarChat)
    mock.get_events.return_value = [
        {
            'id': '123',
            'summary': 'Test Event',
            'start': {'dateTime': datetime.now().isoformat()},
            'end': {'dateTime': (datetime.now() + timedelta(hours=1)).isoformat()}
        }
    ]
    return mock

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_index_route(client):
    response = client.get('/')
    assert response.status_code == 200
    assert response.data == b'OK'

def test_ping_route(client):
    response = client.get('/ping')
    assert response.status_code == 200
    assert response.json == {"status": "ok", "message": "pong"}

def test_callback_route_without_signature(client):
    """
    X-Line-Signatureヘッダーがない場合のテスト
    """
    response = client.post('/callback', headers={})
    assert response.status_code == 400

def test_callback_route_with_invalid_signature(client):
    """
    不正なX-Line-Signatureヘッダーの場合のテスト
    """
    headers = {'X-Line-Signature': 'invalid_signature'}
    data = 'test message'
    response = client.post('/callback', headers=headers, data=data)
    assert response.status_code == 400

def test_debug_events_route(client, mock_calendar_chat):
    with patch('app.calendar_chat', mock_calendar_chat):
        response = client.get('/debug/events')
        assert response.status_code == 200

def test_debug_list_events_route(client, mock_calendar_chat):
    with patch('app.calendar_chat', mock_calendar_chat):
        response = client.get('/debug/list_events')
        assert response.status_code == 200

def test_parse_message(mock_calendar_chat):
    """メッセージ解析のテスト"""
    # Test case 1: Create event
    message = "5月1日 14:30に会議を追加"
    result = parse_message(message)
    assert result is not None
    assert result['action'] == 'create'
    assert result['title'] == '会議'
    assert result['time'] is not None

    # Test case 2: Read event
    message = "5月1日の予定を確認"
    result = parse_message(message)
    assert result is not None
    assert result['action'] == 'read'
    assert result['date'] is not None

    # Test case 3: Update event
    message = "5月1日 14:30の会議を16:00に変更"
    result = parse_message(message)
    assert result is not None
    assert result['action'] == 'update'
    assert result['time'] is not None

    # Test case 4: Delete event
    message = "5月1日 14:30の会議を削除"
    result = parse_message(message)
    assert result is not None
    assert result['action'] == 'delete'
    assert result['date'] is not None
    assert result['time'] is not None

    # Test case 5: Event with duration
    message = "5月1日 14:30から2時間の会議を追加"
    result = parse_message(message)
    assert result is not None
    assert result['action'] == 'create'
    assert result['time'] is not None
    assert result['duration'] == 120

def test_extract_datetime_from_message():
    """日時抽出のテスト"""
    # Test case 1: Today with specific time
    message = "今日14時の予定を確認"
    start_time, end_time = extract_datetime_from_message(message)
    today = datetime.now().date()
    assert start_time.date() == today
    assert start_time.hour == 14
    assert start_time.minute == 0
    assert end_time.hour == 15
    assert end_time.minute == 0

    # Test case 2: Tomorrow with specific time
    message = "明日15時30分の予定を確認"
    start_time, end_time = extract_datetime_from_message(message)
    tomorrow = (datetime.now() + timedelta(days=1)).date()
    assert start_time.date() == tomorrow
    assert start_time.hour == 15
    assert start_time.minute == 30
    assert end_time.hour == 16
    assert end_time.minute == 30

    # Test case 3: Next week with specific day and time
    message = "来週月曜日10時の予定を確認"
    start_time, end_time = extract_datetime_from_message(message)
    assert start_time.hour == 10
    assert start_time.minute == 0
    assert end_time.hour == 11
    assert end_time.minute == 0

    # Test case 4: Specific date and time
    message = "5月1日 14:30の予定を確認"
    start_time, end_time = extract_datetime_from_message(message)
    assert start_time.month == 5
    assert start_time.day == 1
    assert start_time.hour == 14
    assert start_time.minute == 30
    assert end_time.hour == 15
    assert end_time.minute == 30

    # Test case 5: AM/PM format
    message = "5月1日 午後2時30分の予定を確認"
    start_time, end_time = extract_datetime_from_message(message)
    assert start_time.month == 5
    assert start_time.day == 1
    assert start_time.hour == 14
    assert start_time.minute == 30
    assert end_time.hour == 15
    assert end_time.minute == 30

def test_extract_title_from_message():
    """タイトルと場所の抽出テスト"""
    # Test case 1: Simple title
    message = "5月1日 14:30に会議を追加"
    title, location = extract_title_from_message(message)
    assert title == "会議"
    assert location == ""

    # Test case 2: Title with location using "で"
    message = "5月1日 14:30に会議室Aで打ち合わせを追加"
    title, location = extract_title_from_message(message)
    assert title == "打ち合わせ"
    assert location == "会議室A"

    # Test case 3: Title with person
    message = "5月1日 14:30に山田さんとの面談を追加"
    title, location = extract_title_from_message(message)
    assert title == "山田さんと面談"
    assert location == ""

    # Test case 4: Title with location using "@"
    message = "5月1日 14:30に@渋谷で打ち合わせを追加"
    title, location = extract_title_from_message(message)
    assert title == "打ち合わせ"
    assert location == "渋谷"

    # Test case 5: Title with location using "＠"
    message = "5月1日 14:30に＠新宿で打ち合わせを追加"
    title, location = extract_title_from_message(message)
    assert title == "打ち合わせ"
    assert location == "新宿"

def test_extract_reschedule_times():
    """予定の変更時間抽出テスト"""
    # パターン1: "X時からY時へ変更" の形式
    old_start, old_end, new_start, new_end = extract_reschedule_times("14時から15時へ変更")
    assert old_start is not None and new_start is not None
    assert old_start.hour == 14 and old_start.minute == 0
    assert new_start.hour == 15 and new_start.minute == 0
    assert old_end == old_start + timedelta(hours=1)
    assert new_end == new_start + timedelta(hours=1)

    # パターン2: "X時からY時に変更" の形式（分を含む）
    old_start, old_end, new_start, new_end = extract_reschedule_times("14時30分から15時45分に変更")
    assert old_start is not None and new_start is not None
    assert old_start.hour == 14 and old_start.minute == 30
    assert new_start.hour == 15 and new_start.minute == 45
    assert old_end == old_start + timedelta(hours=1)
    assert new_end == new_start + timedelta(hours=1)

    # パターン3: "X時からY時へ" の形式
    old_start, old_end, new_start, new_end = extract_reschedule_times("14時から15時へ")
    assert old_start is not None and new_start is not None
    assert old_start.hour == 14 and old_start.minute == 0
    assert new_start.hour == 15 and new_start.minute == 0
    assert old_end == old_start + timedelta(hours=1)
    assert new_end == new_start + timedelta(hours=1)

    # パターン4: "X時からY時に" の形式（分を含む）
    old_start, old_end, new_start, new_end = extract_reschedule_times("14時30分から15時45分に")
    assert old_start is not None and new_start is not None
    assert old_start.hour == 14 and old_start.minute == 30
    assert new_start.hour == 15 and new_start.minute == 45
    assert old_end == old_start + timedelta(hours=1)
    assert new_end == new_start + timedelta(hours=1)

    # 無効なパターン
    old_start, old_end, new_start, new_end = extract_reschedule_times("無効なメッセージ")
    assert old_start is None and old_end is None and new_start is None and new_end is None

class TestExtractRescheduleTimes(unittest.TestCase):
    """予定変更の時間情報抽出のテスト"""
    def setUp(self):
        # テストの基準となる現在時刻を設定
        self.now = datetime.now()
        
    def test_today_time_change(self):
        """今日の予定変更テスト"""
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
        """明日の予定変更テスト"""
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
        """明後日の予定変更テスト"""
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
        """特定の日付の予定変更テスト"""
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

    def test_different_date_formats(self):
        """異なる日付形式のテスト"""
        test_cases = [
            ("3/15 9時を10時に変更", 3, 15),
            ("3-15 9時を10時に変更", 3, 15),
            ("3月15日 9時を10時に変更", 3, 15)
        ]
        
        for message, expected_month, expected_day in test_cases:
            old_start, old_end, new_start, new_end = extract_reschedule_times(message)
            self.assertIsNotNone(old_start)
            self.assertIsNotNone(new_start)
            self.assertEqual(old_start.month, expected_month)
            self.assertEqual(old_start.day, expected_day)
            self.assertEqual(old_start.hour, 9)
            self.assertEqual(old_start.minute, 0)
            self.assertEqual(new_start.hour, 10)
            self.assertEqual(new_start.minute, 0)

    def test_invalid_message(self):
        """無効なメッセージのテスト"""
        message = "無効なメッセージ"
        old_start, old_end, new_start, new_end = extract_reschedule_times(message)
        self.assertIsNone(old_start)
        self.assertIsNone(old_end)
        self.assertIsNone(new_start)
        self.assertIsNone(new_end)

if __name__ == '__main__':
    unittest.main() 