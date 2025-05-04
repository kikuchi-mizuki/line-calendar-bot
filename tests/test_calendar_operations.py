import unittest
import os
import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from calendar_operations import CalendarManager

class TestCalendarManager(unittest.TestCase):
    """
    カレンダーマネージャーのテスト
    """
    @patch('calendar_operations.InstalledAppFlow')
    @patch('calendar_operations.build')
    def setUp(self, mock_build, mock_flow):
        """
        テストの前準備
        """
        self.credentials_path = 'test_credentials.json'
        # テスト用のクレデンシャルファイルを作成
        test_credentials = {
            "installed": {
                "client_id": "test_client_id",
                "project_id": "test_project_id",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": "test_client_secret",
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"]
            }
        }
        with open(self.credentials_path, 'w') as f:
            json.dump(test_credentials, f)
            
        # モックの設定
        mock_creds = MagicMock()
        mock_flow.from_client_secrets_file.return_value.run_local_server.return_value = mock_creds
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # CalendarManagerを初期化
        with patch('builtins.open'), \
             patch('pickle.load', return_value=mock_creds), \
             patch('pickle.dump'):
            self.calendar_manager = CalendarManager(self.credentials_path)
            self.calendar_manager.service = mock_service
        
    def tearDown(self):
        """
        テストの後処理
        """
        if os.path.exists(self.credentials_path):
            os.remove(self.credentials_path)
            
    def test_add_event(self):
        """
        イベント追加のテスト
        """
        # モックの設定
        self.calendar_manager.service.events().insert().execute.return_value = {'id': 'test_event_id'}
        
        # イベント追加のテスト
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=1)
        result = self.calendar_manager.add_event(
            start_time=start_time,
            end_time=end_time,
            title='Test Event',
            location='Test Location',
            person='Test Person'
        )
        
        # 結果の確認
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], 'イベントを追加しました')
        
        # API呼び出しの確認
        self.calendar_manager.service.events().insert.assert_called_once()
        
    def test_delete_event(self):
        """
        イベント削除のテスト
        """
        # モックの設定
        self.calendar_manager.service.events().delete().execute.return_value = {}
        
        # イベント削除のテスト
        result = self.calendar_manager.delete_event(
            event_id='test_event_id'
        )
        
        # 結果の確認
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], 'イベントを削除しました')
        
        # API呼び出しの確認
        self.calendar_manager.service.events().delete.assert_called_once()
        
    def test_update_event(self):
        """
        イベント更新のテスト
        """
        # モックの設定
        self.calendar_manager.service.events().update().execute.return_value = {'id': 'test_event_id'}
        
        # イベント更新のテスト
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=1)
        result = self.calendar_manager.update_event(
            event_id='test_event_id',
            start_time=start_time,
            end_time=end_time,
            title='Updated Event',
            location='Updated Location',
            person='Updated Person'
        )
        
        # 結果の確認
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], 'イベントを更新しました')
        
        # API呼び出しの確認
        self.calendar_manager.service.events().update.assert_called_once()
        
    def test_get_events(self):
        """
        イベント取得のテスト
        """
        # モックのイベントデータ
        mock_event = {
            'id': 'test_event_id',
            'summary': 'Test Event',
            'location': 'Test Location',
            'description': 'Test Person',
            'start': {'dateTime': '2023-01-01T10:00:00+09:00'},
            'end': {'dateTime': '2023-01-01T11:00:00+09:00'}
        }
        self.calendar_manager.service.events().list().execute.return_value = {'items': [mock_event]}
        
        # イベント取得のテスト
        start_time = datetime.now()
        end_time = start_time + timedelta(days=7)
        events = self.calendar_manager.get_events(
            start_time=start_time,
            end_time=end_time
        )
        
        # 結果の確認
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['id'], 'test_event_id')
        self.assertEqual(events[0]['summary'], 'Test Event')
        
        # API呼び出しの確認
        self.calendar_manager.service.events().list.assert_called_once()
        
    def test_get_free_time(self):
        """
        空き時間取得のテスト
        """
        # モックのイベントデータ
        mock_event = {
            'id': 'test_event_id',
            'summary': 'Test Event',
            'start': {'dateTime': '2023-01-01T10:00:00+09:00'},
            'end': {'dateTime': '2023-01-01T11:00:00+09:00'}
        }
        self.calendar_manager.service.events().list().execute.return_value = {'items': [mock_event]}
        
        # 空き時間取得のテスト
        start_time = datetime.now()
        end_time = start_time + timedelta(days=1)
        free_time = self.calendar_manager.get_free_time(
            start_time=start_time,
            end_time=end_time,
            duration_minutes=30
        )
        
        # 結果の確認
        self.assertIsNotNone(free_time)
        self.assertIsInstance(free_time, list)
        
        # API呼び出しの確認
        self.calendar_manager.service.events().list.assert_called_once()
        
if __name__ == '__main__':
    unittest.main() 