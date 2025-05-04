import unittest
import os
import sqlite3
from datetime import datetime, timedelta
from database import DatabaseManager

class TestDatabaseManager(unittest.TestCase):
    """
    データベースマネージャーのテスト
    """
    def setUp(self):
        """
        テストの前準備
        """
        self.db_path = 'test_calendar_bot.db'
        self.db_manager = DatabaseManager(self.db_path)
        
    def tearDown(self):
        """
        テストの後処理
        """
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
            
    def test_add_user(self):
        """
        ユーザー追加のテスト
        """
        # ユーザーを追加
        result = self.db_manager.add_user('test_user', 'Test User', 'test@example.com')
        self.assertTrue(result)
        
        # データベースを確認
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', ('test_user',))
            user = cursor.fetchone()
            
            self.assertIsNotNone(user)
            self.assertEqual(user[0], 'test_user')
            self.assertEqual(user[1], 'Test User')
            self.assertEqual(user[2], 'test@example.com')
            self.assertEqual(user[3], 0)  # is_authorized
            
    def test_authorize_user(self):
        """
        ユーザー認証のテスト
        """
        # ユーザーを追加
        self.db_manager.add_user('test_user')
        
        # ユーザーを認証
        result = self.db_manager.authorize_user('test_user')
        self.assertTrue(result)
        
        # 認証状態を確認
        is_authorized = self.db_manager.is_authorized('test_user')
        self.assertTrue(is_authorized)
        
    def test_add_event_history(self):
        """
        イベント履歴追加のテスト
        """
        # ユーザーを追加
        self.db_manager.add_user('test_user')
        
        # イベント履歴を追加
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=1)
        result = self.db_manager.add_event_history(
            user_id='test_user',
            operation_type='add',
            event_id='test_event',
            event_title='Test Event',
            start_time=start_time,
            end_time=end_time
        )
        self.assertTrue(result)
        
        # データベースを確認
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM event_history WHERE user_id = ?', ('test_user',))
            history = cursor.fetchone()
            
            self.assertIsNotNone(history)
            self.assertEqual(history[1], 'test_user')  # user_id
            self.assertEqual(history[2], 'add')  # operation_type
            self.assertEqual(history[3], 'test_event')  # event_id
            self.assertEqual(history[4], 'Test Event')  # event_title
            
    def test_get_event_history(self):
        """
        イベント履歴取得のテスト
        """
        # ユーザーを追加
        self.db_manager.add_user('test_user')
        
        # イベント履歴を追加
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=1)
        self.db_manager.add_event_history(
            user_id='test_user',
            operation_type='add',
            event_id='test_event',
            event_title='Test Event',
            start_time=start_time,
            end_time=end_time
        )
        
        # イベント履歴を取得
        history = self.db_manager.get_event_history('test_user')
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['operation_type'], 'add')
        self.assertEqual(history[0]['event_id'], 'test_event')
        self.assertEqual(history[0]['event_title'], 'Test Event')
        
    def test_get_user_statistics(self):
        """
        ユーザー統計情報取得のテスト
        """
        # ユーザーを追加
        self.db_manager.add_user('test_user')
        
        # イベント履歴を追加
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=1)
        self.db_manager.add_event_history(
            user_id='test_user',
            operation_type='add',
            event_id='test_event',
            event_title='Test Event',
            start_time=start_time,
            end_time=end_time
        )
        
        # 統計情報を取得
        stats = self.db_manager.get_user_statistics('test_user')
        self.assertEqual(stats['operation_counts']['add'], 1)
        self.assertIsNotNone(stats['last_operation'])
        self.assertEqual(stats['last_operation']['type'], 'add')
        
if __name__ == '__main__':
    unittest.main() 