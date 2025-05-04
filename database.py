import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# ログ設定
logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    データベース操作を管理するクラス
    """
    def __init__(self, db_path: str = 'calendar_bot.db'):
        """
        データベースマネージャーの初期化
        
        Args:
            db_path (str): データベースファイルのパス
        """
        self.db_path = db_path
        self._initialize_database()
        
    def _initialize_database(self):
        """
        データベースの初期化
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # ユーザーテーブルの作成
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        name TEXT,
                        email TEXT,
                        is_authorized INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # イベント履歴テーブルの作成
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS event_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT,
                        operation_type TEXT,
                        event_id TEXT,
                        event_title TEXT,
                        start_time TIMESTAMP,
                        end_time TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')
                
                conn.commit()
                logger.info("データベースを初期化しました。")
                
        except Exception as e:
            logger.error(f"データベースの初期化に失敗: {str(e)}")
            raise
            
    def add_user(self, user_id: str, name: Optional[str] = None, email: Optional[str] = None) -> bool:
        """
        ユーザーを追加
        
        Args:
            user_id (str): ユーザーID
            name (Optional[str]): ユーザー名
            email (Optional[str]): メールアドレス
            
        Returns:
            bool: 成功した場合はTrue
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO users (user_id, name, email)
                    VALUES (?, ?, ?)
                ''', (user_id, name, email))
                conn.commit()
                logger.info(f"ユーザーを追加しました: {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"ユーザーの追加に失敗: {str(e)}")
            return False
            
    def authorize_user(self, user_id: str) -> bool:
        """
        ユーザーを認証
        
        Args:
            user_id (str): ユーザーID
            
        Returns:
            bool: 成功した場合はTrue
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users
                    SET is_authorized = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                ''', (user_id,))
                conn.commit()
                logger.info(f"ユーザーを認証しました: {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"ユーザーの認証に失敗: {str(e)}")
            return False
            
    def is_authorized(self, user_id: str) -> bool:
        """
        ユーザーが認証済みかどうかを確認
        
        Args:
            user_id (str): ユーザーID
            
        Returns:
            bool: 認証済みの場合はTrue
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT is_authorized
                    FROM users
                    WHERE user_id = ?
                ''', (user_id,))
                result = cursor.fetchone()
                return bool(result[0]) if result else False
                
        except Exception as e:
            logger.error(f"ユーザーの認証状態の確認に失敗: {str(e)}")
            return False
            
    def add_event_history(
        self,
        user_id: str,
        operation_type: str,
        event_id: str,
        event_title: str,
        start_time: datetime,
        end_time: datetime
    ) -> bool:
        """
        イベント履歴を追加
        
        Args:
            user_id (str): ユーザーID
            operation_type (str): 操作タイプ
            event_id (str): イベントID
            event_title (str): イベントのタイトル
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            
        Returns:
            bool: 成功した場合はTrue
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO event_history (
                        user_id, operation_type, event_id,
                        event_title, start_time, end_time
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    user_id, operation_type, event_id,
                    event_title, start_time.isoformat(), end_time.isoformat()
                ))
                conn.commit()
                logger.info(f"イベント履歴を追加しました: {event_id}")
                return True
                
        except Exception as e:
            logger.error(f"イベント履歴の追加に失敗: {str(e)}")
            return False
            
    def get_event_history(
        self,
        user_id: str,
        limit: int = 10,
        offset: int = 0
    ) -> List[Dict]:
        """
        イベント履歴を取得
        
        Args:
            user_id (str): ユーザーID
            limit (int): 取得件数
            offset (int): 開始位置
            
        Returns:
            List[Dict]: イベント履歴のリスト
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT
                        operation_type, event_id, event_title,
                        start_time, end_time, created_at
                    FROM event_history
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                ''', (user_id, limit, offset))
                
                history = []
                for row in cursor.fetchall():
                    history.append({
                        'operation_type': row[0],
                        'event_id': row[1],
                        'event_title': row[2],
                        'start_time': datetime.fromisoformat(row[3]),
                        'end_time': datetime.fromisoformat(row[4]),
                        'created_at': datetime.fromisoformat(row[5])
                    })
                    
                return history
                
        except Exception as e:
            logger.error(f"イベント履歴の取得に失敗: {str(e)}")
            return []
            
    def get_user_statistics(self, user_id: str) -> Dict:
        """
        ユーザーの統計情報を取得
        
        Args:
            user_id (str): ユーザーID
            
        Returns:
            Dict: 統計情報
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 操作タイプごとの件数を取得
                cursor.execute('''
                    SELECT operation_type, COUNT(*)
                    FROM event_history
                    WHERE user_id = ?
                    GROUP BY operation_type
                ''', (user_id,))
                
                operation_counts = dict(cursor.fetchall())
                
                # 最近の操作を取得
                cursor.execute('''
                    SELECT operation_type, created_at
                    FROM event_history
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                ''', (user_id,))
                
                last_operation = cursor.fetchone()
                
                return {
                    'operation_counts': operation_counts,
                    'last_operation': {
                        'type': last_operation[0] if last_operation else None,
                        'time': datetime.fromisoformat(last_operation[1]) if last_operation else None
                    }
                }
                
        except Exception as e:
            logger.error(f"ユーザー統計情報の取得に失敗: {str(e)}")
            return {
                'operation_counts': {},
                'last_operation': None
            } 