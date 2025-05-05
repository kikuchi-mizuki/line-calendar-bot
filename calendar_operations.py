from datetime import datetime, timedelta
import logging
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import json
import asyncio
from functools import lru_cache
from typing import Dict, List, Optional, Tuple, Union
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import signal
from contextlib import contextmanager
from tenacity import retry, stop_after_attempt, wait_exponential

# ログ設定
logger = logging.getLogger(__name__)

# タイムアウト設定（秒）
CALENDAR_TIMEOUT_SECONDS = 30

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
        self.calendar_id = None
        self._initialize_service()
        
    def _initialize_service(self):
        """
        Google Calendar APIサービスを初期化
        """
        try:
            if not os.path.exists(self.credentials_path):
                raise ValueError(f"認証情報ファイルが見つかりません: {self.credentials_path}")
                
            # サービスアカウントの認証情報を使用
            credentials = service_account.Credentials.from_service_account_file(
                self.credentials_path,
                scopes=['https://www.googleapis.com/auth/calendar']
            )
            
            self.service = build('calendar', 'v3', credentials=credentials)
            # カレンダーIDを取得
            self.calendar_id = self._get_calendar_id()
            logger.info(f"Google Calendar APIサービスを初期化しました (カレンダーID: {self.calendar_id})")
        except Exception as e:
            logger.error(f"Google Calendar APIサービスの初期化に失敗: {str(e)}")
            logger.error(traceback.format_exc())
            raise
        
    @lru_cache(maxsize=100)
    def _get_calendar_id(self) -> str:
        """
        カレンダーIDを返す
        """
        try:
            # カレンダーリストを取得
            calendar_list = self.service.calendarList().list().execute()
            calendars = calendar_list.get('items', [])
            
            # カレンダーリストの詳細をログ出力
            logger.debug(f"利用可能なカレンダー数: {len(calendars)}")
            for calendar in calendars:
                calendar_id = calendar.get('id', 'N/A')
                calendar_summary = calendar.get('summary', 'N/A')
                calendar_primary = calendar.get('primary', False)
                calendar_access_role = calendar.get('accessRole', 'N/A')
                logger.debug(f"カレンダー詳細: ID={calendar_id}, タイトル={calendar_summary}, プライマリー={calendar_primary}, アクセス権限={calendar_access_role}")
            
            # プライマリーカレンダーを検索
            for calendar in calendars:
                if calendar.get('primary', False):
                    calendar_id = calendar['id']
                    logger.info(f"プライマリーカレンダーを使用します: {calendar_id}")
                    return calendar_id
            
            # プライマリーカレンダーが見つからない場合は、最初のカレンダーを使用
            if calendars:
                calendar_id = calendars[0]['id']
                logger.info(f"プライマリーカレンダーが見つからないため、最初のカレンダーを使用します: {calendar_id}")
                return calendar_id
            
            # カレンダーが見つからない場合は、デフォルトのカレンダーIDを使用
            logger.warning("利用可能なカレンダーが見つかりません。デフォルトのカレンダーIDを使用します。")
            return 'primary'
            
        except Exception as e:
            logger.error(f"カレンダーIDの取得に失敗: {str(e)}")
            logger.error(traceback.format_exc())
            return 'primary'
            
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
            # タイムゾーンを設定
            time_zone = pytz.timezone('Asia/Tokyo')
            start_time = time_zone.localize(start_time) if start_time.tzinfo is None else start_time.astimezone(time_zone)
            end_time = time_zone.localize(end_time) if end_time.tzinfo is None else end_time.astimezone(time_zone)
            
            # イベントの重複チェック
            overlapping_events = await self._check_overlapping_events(start_time, end_time, title)
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
                    'timeZone': time_zone.zone
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': time_zone.zone
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
            
            # ThreadPoolExecutorを使用してタイムアウトを実装
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self.service.events().insert,
                    calendarId=self.calendar_id,
                    body=event
                )
                try:
                    result = future.result(timeout=CALENDAR_TIMEOUT_SECONDS)
                    logger.info(f"イベントを追加しました: {title}")
                    return {
                        "success": True,
                        "message": "予定を追加しました。",
                        "event": result
                    }
                except TimeoutError:
                    logger.error(f"イベントの追加が{CALENDAR_TIMEOUT_SECONDS}秒でタイムアウトしました")
                    return {
                        "success": False,
                        "message": "予定の追加に時間がかかりすぎています。もう一度お試しください。",
                        "error": "タイムアウト"
                    }
                except Exception as e:
                    logger.error(f"イベントの追加中にエラーが発生: {str(e)}")
                    logger.error(traceback.format_exc())
                    return {
                        "success": False,
                        "message": "予定の追加に失敗しました。",
                        "error": str(e)
                    }
                
        except Exception as e:
            logger.error(f"イベントの追加中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": "予定の追加に失敗しました。",
                "error": str(e)
            }
            
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1))
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
            
            # ThreadPoolExecutorを使用してタイムアウトを実装
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self.service.events().list,
                    calendarId=self.calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy='startTime'
                )
                try:
                    result = future.result(timeout=CALENDAR_TIMEOUT_SECONDS)
                    events = result.get('items', [])
                    
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
                        
                    # ThreadPoolExecutorを使用してタイムアウトを実装
                    deleted_count = 0
                    for event in events:
                        if title and event.get('summary') != title:
                            continue

                        future = executor.submit(
                            self.service.events().delete,
                            calendarId=self.calendar_id,
                            eventId=event['id']
                        )
                        try:
                            future.result(timeout=CALENDAR_TIMEOUT_SECONDS)
                            deleted_count += 1
                            logger.debug(f"検出されたイベント: {event.get('summary', '')} ({event['start'].get('dateTime', '')} - {event['end'].get('dateTime', '')})")
                        except TimeoutError:
                            logger.error(f"イベントの削除が{CALENDAR_TIMEOUT_SECONDS}秒でタイムアウトしました")
                        except Exception as e:
                            logger.error(f"イベントの削除中にエラーが発生: {str(e)}")
                            logger.error(traceback.format_exc())
                    
                    logger.info(f"イベントを削除しました: {deleted_count}件")
                    return {
                        'success': True,
                        'deleted_count': deleted_count
                    }
                    
                except TimeoutError:
                    logger.error(f"イベントの削除が{CALENDAR_TIMEOUT_SECONDS}秒でタイムアウトしました")
                    return {
                        'success': False,
                        'message': '予定の削除に時間がかかりすぎています。もう一度お試しください。',
                        'error': 'タイムアウト'
                    }
                except Exception as e:
                    logger.error(f"イベントの削除中にエラーが発生: {str(e)}")
                    logger.error(traceback.format_exc())
                    return {
                        'success': False,
                        'message': str(e),
                        'context': 'イベントの削除中にエラーが発生しました。'
                    }
            
        except Exception as e:
            logger.error(f"イベントの削除中にエラーが発生: {str(e)}")
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
                calendarId=self.calendar_id,
                eventId=event_id,
                body=event
            ).execute()
            
            logger.info(f"イベントを更新しました: {updated_event['id']}")
            return True
            
        except Exception as e:
            logger.error(f"イベントの更新中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return False
            
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1))
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
            else:
                start_time = start_time.astimezone(jst)
            if end_time.tzinfo is None:
                end_time = jst.localize(end_time)
            else:
                end_time = end_time.astimezone(jst)
            
            # イベントの検索条件を設定
            time_min = start_time.isoformat()
            time_max = end_time.isoformat()
            
            logger.debug(f"イベント検索範囲: {time_min} から {time_max}")
            logger.debug(f"カレンダーID: {self.calendar_id}")
            
            # ThreadPoolExecutorを使用してタイムアウトを実装
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self.service.events().list,
                    calendarId=self.calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy='startTime',
                    timeZone='Asia/Tokyo'
                )
                try:
                    result = future.result(timeout=CALENDAR_TIMEOUT_SECONDS)
                    # APIリクエストを実行して結果を取得
                    response = result.execute()
                    events = response.get('items', [])
                    
                    # タイトルでフィルタリング
                    if title:
                        events = [event for event in events if title in event.get('summary', '')]
                    
                    # イベントの詳細をログ出力
                    logger.debug(f"取得したイベント数: {len(events)}")
                    for event in events:
                        event_id = event.get('id', 'N/A')
                        event_summary = event.get('summary', 'N/A')
                        event_start = event.get('start', {}).get('dateTime', 'N/A')
                        event_end = event.get('end', {}).get('dateTime', 'N/A')
                        event_status = event.get('status', 'N/A')
                        logger.debug(f"イベント詳細: ID={event_id}, タイトル={event_summary}, 開始={event_start}, 終了={event_end}, ステータス={event_status}")
                    
                    logger.info(f"イベントを取得しました: {len(events)}件")
                    return events
                    
                except TimeoutError:
                    logger.error(f"イベントの取得が{CALENDAR_TIMEOUT_SECONDS}秒でタイムアウトしました")
                    return []
                except Exception as e:
                    logger.error(f"イベントの取得中にエラーが発生: {str(e)}")
                    logger.error(traceback.format_exc())
                    return []
            
        except Exception as e:
            logger.error(f"イベントの取得中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1))
    async def _check_overlapping_events(
        self,
        start_time: datetime,
        end_time: datetime,
        title: Optional[str] = None
    ) -> List[Dict]:
        """
        重複するイベントをチェック
        
        Args:
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            title (Optional[str]): イベントのタイトル
            
        Returns:
            List[Dict]: 重複するイベントのリスト
        """
        try:
            events = await self.get_events(start_time, end_time)
            overlapping_events = []
            
            for event in events:
                event_start = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00')).astimezone(pytz.timezone('Asia/Tokyo'))
                event_end = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00')).astimezone(pytz.timezone('Asia/Tokyo'))
                
                # タイトルが指定されている場合は、タイトルも一致する必要がある
                if title and event.get('summary') != title:
                    continue
                    
                # 完全な重複のみをチェック
                if (event_start == start_time and event_end == end_time):
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
            logger.error(f"重複チェック中にエラーが発生: {str(e)}")
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
                start_time = pytz.timezone('Asia/Tokyo').localize(start_time)
            if end_time.tzinfo is None:
                end_time = pytz.timezone('Asia/Tokyo').localize(end_time)
                
            # イベントの取得
            events = self.get_events(start_time, end_time)
            
            # 空き時間の計算
            free_times = []
            current_time = start_time
            
            for event in events:
                event_start = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00')).astimezone(pytz.timezone('Asia/Tokyo'))
                event_end = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00')).astimezone(pytz.timezone('Asia/Tokyo'))
                
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