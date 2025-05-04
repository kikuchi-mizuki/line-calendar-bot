from datetime import datetime, timedelta
import logging
import pytz
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import os
import json
import asyncio
from functools import lru_cache
from typing import Dict, List, Optional, Tuple, Union
import traceback
from tenacity import retry, stop_after_attempt, wait_exponential
import signal
from contextlib import contextmanager

# ログ設定
logger = logging.getLogger(__name__)

# タイムアウト設定
CALENDAR_TIMEOUT_SECONDS = 5

@contextmanager
def calendar_timeout(seconds):
    def signal_handler(signum, frame):
        raise TimeoutError(f"カレンダー操作が{seconds}秒でタイムアウトしました")
    
    original_handler = signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, original_handler)

class CalendarManager:
    """
    Google Calendar APIを使用してカレンダー操作を行うクラス
    """
    def __init__(self, credentials_path: str):
        self.credentials_path = credentials_path
        self.service = None
        self._initialize_service()
        
    def _initialize_service(self):
        """
        Google Calendar APIサービスを初期化
        """
        try:
            if not os.path.exists(self.credentials_path):
                raise ValueError(f"認証情報ファイルが見つかりません: {self.credentials_path}")
                
            # サービスアカウントの認証情報を使用
            credentials = Credentials.from_service_account_file(
                self.credentials_path,
                scopes=['https://www.googleapis.com/auth/calendar']
            )
            
            self.service = build('calendar', 'v3', credentials=credentials)
            logger.info("Google Calendar APIサービスを初期化しました")
        except Exception as e:
            logger.error(f"Google Calendar APIサービスの初期化に失敗: {str(e)}")
            raise
        
    @lru_cache(maxsize=100)
    def _get_calendar_id(self) -> str:
        """
        カレンダーIDを返す
        """
        return 'mmms.dy.23@gmail.com'
            
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1))
    async def add_event(
        self,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        title: str = "",
        location: Optional[str] = None,
        person: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict:
        """
        イベントを追加
        
        Args:
            start_time (datetime): 開始時間
            end_time (Optional[datetime]): 終了時間（指定がない場合は開始時間から1時間後）
            title (str): イベントのタイトル
            location (Optional[str]): 場所
            person (Optional[str]): 参加者
            description (Optional[str]): 説明
            
        Returns:
            Dict: 操作結果
        """
        try:
            with calendar_timeout(CALENDAR_TIMEOUT_SECONDS):
                # 終了時間が指定されていない場合は1時間後を設定
                if not end_time:
                    end_time = start_time + timedelta(hours=1)
                    
                # イベントの重複チェック
                overlapping_events = await self._check_overlapping_events(start_time, end_time)
                if overlapping_events:
                    return {
                        "success": False,
                        "message": "指定された時間帯に既に予定があります。",
                        "overlapping_events": overlapping_events
                    }
                    
                # イベントの作成
                event = {
                    'summary': title,
                    'start': {
                        'dateTime': start_time.isoformat(),
                        'timeZone': 'Asia/Tokyo'
                    },
                    'end': {
                        'dateTime': end_time.isoformat(),
                        'timeZone': 'Asia/Tokyo'
                    }
                }
                
                # オプション項目の追加
                if location:
                    event['location'] = location
                    
                # 説明文の作成
                description_parts = []
                if person:
                    description_parts.append(f"参加者: {person}")
                if description:
                    description_parts.append(description)
                    
                if description_parts:
                    event['description'] = "\n".join(description_parts)
                
                # 非同期でイベントを追加
                loop = asyncio.get_event_loop()
                created_event = await loop.run_in_executor(
                    None,
                    lambda: self.service.events().insert(
                        calendarId=self._get_calendar_id(),
                        body=event
                    ).execute()
                )
                
                logger.info(f"イベントを追加しました: {title}")
                return {
                    "success": True,
                    "message": "予定を追加しました。",
                    "event": created_event
                }
                
        except TimeoutError as e:
            logger.error(f"イベントの追加がタイムアウト: {str(e)}")
            return {
                "success": False,
                "message": "予定の追加に時間がかかりすぎています。もう一度お試しください。",
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"イベントの追加に失敗: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": "予定の追加に失敗しました。",
                "error": str(e)
            }
            
    async def delete_event(
        self,
        start_time: datetime,
        end_time: datetime,
        title: Optional[str] = None
    ) -> Dict:
        """
        イベントを削除
        
        Args:
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            title (Optional[str]): イベントのタイトル（オプション）
            
        Returns:
            Dict: 操作結果
        """
        try:
            # タイムゾーンの設定
            jst = pytz.timezone('Asia/Tokyo')
            start_time = start_time.astimezone(jst)
            end_time = end_time.astimezone(jst)
            
            # イベントの検索範囲を調整（前後2時間）
            search_start = start_time - timedelta(hours=2)
            search_end = end_time + timedelta(hours=2)
            
            # 検索範囲のログ出力
            logger.debug(f"イベント検索範囲: {search_start} から {search_end}")
            
            # イベントの検索条件を設定
            time_min = search_start.isoformat()
            time_max = search_end.isoformat()
            
            # 検索条件のログ出力
            logger.debug(f"検索条件: timeMin={time_min}, timeMax={time_max}")
            
            # 非同期でイベントを取得
            events_result = await self._execute_async(
                lambda: self.service.events().list(
                    calendarId=self._get_calendar_id(),
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
            )
            
            events = events_result.get('items', [])
            
            # イベントの詳細をログ出力
            if events:
                for event in events:
                    logger.debug(f"検出されたイベント: {event.get('summary')} ({event.get('start', {}).get('dateTime')} - {event.get('end', {}).get('dateTime')})")
            else:
                logger.debug("検出されたイベントはありません")
            
            if not events:
                return {
                    'success': False,
                    'message': '指定された時間帯に予定が見つかりませんでした。',
                    'context': 'イベントの削除中に検索に失敗しました。'
                }
                
            # 非同期でイベントを削除
            loop = asyncio.get_event_loop()
            for event in events:
                await loop.run_in_executor(
                    None,
                    lambda: self.service.events().delete(
                        calendarId=self._get_calendar_id(),
                        eventId=event['id']
                    ).execute()
                )
                
            logger.info(f"イベントを削除しました: {len(events)}件")
            return {
                'success': True,
                'operation_type': 'delete',
                'event': events[0] if events else None
            }
            
        except Exception as e:
            logger.error(f"イベントの削除に失敗: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'message': str(e),
                'context': 'イベントの削除中にエラーが発生しました。'
            }
            
    def update_event(
        self,
        start_time: datetime,
        end_time: datetime,
        new_start_time: datetime,
        new_end_time: datetime,
        title: Optional[str] = None,
        location: Optional[str] = None,
        person: Optional[str] = None
    ) -> bool:
        """
        イベントを更新する
        
        Args:
            start_time (datetime): 開始時刻
            end_time (datetime): 終了時刻
            new_start_time (datetime): 新しい開始時刻
            new_end_time (datetime): 新しい終了時刻
            title (Optional[str]): タイトル
            location (Optional[str]): 場所
            person (Optional[str]): 参加者
            
        Returns:
            bool: 更新が成功したかどうか
        """
        try:
            # イベントの検索
            events = asyncio.run(self.get_events(start_time, end_time))
            if not events:
                logger.error("更新するイベントが見つかりませんでした")
                return False
                
            # 最初のイベントを更新
            event = events[0]
            event_id = event['id']
            
            # イベントの更新
            event['start']['dateTime'] = new_start_time.isoformat()
            event['end']['dateTime'] = new_end_time.isoformat()
            
            if title:
                event['summary'] = title
            if location:
                event['location'] = location
            if person:
                event['description'] = f"参加者: {person}"
                
            # イベントの更新を実行
            updated_event = self.service.events().update(
                calendarId=self._get_calendar_id(),
                eventId=event_id,
                body=event
            ).execute()
            
            logger.info(f"イベントを更新しました: {updated_event['id']}")
            return True
            
        except Exception as e:
            logger.error(f"イベントの更新中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return False
            
    async def get_events(
        self,
        start_time: datetime,
        end_time: datetime,
        title: Optional[str] = None
    ) -> List[Dict]:
        """
        指定された期間のイベントを取得
        
        Args:
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            title (Optional[str]): イベントのタイトル
            
        Returns:
            List[Dict]: イベントのリスト
        """
        try:
            # タイムゾーンの設定
            jst = pytz.timezone('Asia/Tokyo')
            if start_time.tzinfo is None:
                start_time = jst.localize(start_time)
            if end_time.tzinfo is None:
                end_time = jst.localize(end_time)
            
            # イベントの検索条件を設定
            time_min = start_time.isoformat()
            time_max = end_time.isoformat()
            
            logger.debug(f"イベント検索範囲: {time_min} から {time_max}")
            
            # 非同期でイベントを取得
            events_result = await self._execute_async(
                lambda: self.service.events().list(
                    calendarId=self._get_calendar_id(),
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy='startTime',
                    timeZone='Asia/Tokyo'
                ).execute()
            )
            
            events = events_result.get('items', [])
            
            # タイトルでフィルタリング
            if title:
                events = [event for event in events if title in event.get('summary', '')]
                
            logger.info(f"イベントを取得しました: {len(events)}件")
            return events
            
        except Exception as e:
            logger.error(f"イベントの取得に失敗: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    async def _execute_async(self, func):
        """
        非同期実行のヘルパーメソッド
        
        Args:
            func: 実行する関数
            
        Returns:
            関数の実行結果
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, func)
            
    async def _check_overlapping_events(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict]:
        """
        重複するイベントをチェック
        
        Args:
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            
        Returns:
            List[Dict]: 重複するイベントのリスト
        """
        try:
            # タイムゾーンの設定
            jst = pytz.timezone('Asia/Tokyo')
            start_time = start_time.astimezone(jst)
            end_time = end_time.astimezone(jst)
            
            # イベントの検索範囲を広げる（前後30分）
            search_start = start_time - timedelta(minutes=30)
            search_end = end_time + timedelta(minutes=30)
            
            # イベントの検索条件を設定
            time_min = search_start.isoformat()
            time_max = search_end.isoformat()
            
            # 非同期でイベントを取得
            loop = asyncio.get_event_loop()
            events_result = await loop.run_in_executor(
                None,
                lambda: self.service.events().list(
                    calendarId=self._get_calendar_id(),
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
            )
            
            events = events_result.get('items', [])
            overlapping_events = []
            
            for event in events:
                event_start = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00')).astimezone(jst)
                event_end = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00')).astimezone(jst)
                
                # 重複チェックのロジックを改善
                if (event_start < end_time and event_end > start_time):
                    overlapping_events.append({
                        'id': event['id'],
                        'summary': event.get('summary', '予定なし'),
                        'start': event_start.strftime('%Y-%m-%d %H:%M'),
                        'end': event_end.strftime('%Y-%m-%d %H:%M'),
                        'location': event.get('location', ''),
                        'description': event.get('description', '')
                    })
                    
            logger.info(f"重複チェック結果: {len(overlapping_events)}件の重複予定を検出")
            return overlapping_events
            
        except Exception as e:
            logger.error(f"重複チェックに失敗: {str(e)}")
            logger.error(traceback.format_exc())
            return []
            
    async def _find_events(
        self,
        start_time: datetime,
        end_time: datetime,
        title: Optional[str] = None
    ) -> List[Dict]:
        """
        条件に一致するイベントを検索
        
        Args:
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            title (Optional[str]): イベントのタイトル
            
        Returns:
            List[Dict]: イベントのリスト
        """
        try:
            events = await self.get_events(start_time, end_time)
            if title:
                events = [e for e in events if title in e.get('summary', '')]
            return events
            
        except Exception as e:
            logger.error(f"イベントの検索に失敗: {str(e)}")
            return []

    def get_free_time(self, start_time: datetime, end_time: datetime,
                     duration: timedelta) -> List[Tuple[datetime, datetime]]:
        """
        指定された時間帯の空き時間を取得する
        
        Args:
            start_time (datetime): 開始時刻
            end_time (datetime): 終了時刻
            duration (timedelta): 必要な時間
            
        Returns:
            List[Tuple[datetime, datetime]]: 空き時間のリスト
        """
        try:
            # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = JST.localize(start_time)
            if end_time.tzinfo is None:
                end_time = JST.localize(end_time)
                
            # イベントの取得
            events = self.get_events(start_time, end_time)
            
            # 空き時間の計算
            free_times = []
            current_time = start_time
            
            for event in events:
                event_start = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00')).astimezone(JST)
                event_end = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00')).astimezone(JST)
                
                # イベントの開始時刻までに空き時間がある場合
                if event_start - current_time >= duration:
                    free_times.append((current_time, event_start))
                    
                current_time = event_end
                
            # 最後のイベントから終了時刻までに空き時間がある場合
            if end_time - current_time >= duration:
                free_times.append((current_time, end_time))
                
            return free_times
            
        except Exception as e:
            logger.error(f"空き時間の取得中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return [] 