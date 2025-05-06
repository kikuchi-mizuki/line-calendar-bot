from datetime import datetime, timedelta
import logging
import pytz
from google.oauth2.credentials import Credentials
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
from google.auth.transport.requests import Request

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
    Google Calendar APIを使用してカレンダー操作を行うクラス（OAuth認証対応）
    """
    def __init__(self, credentials):
        self.credentials = credentials
        self.service = None
        self.calendar_id = None
        self._initialize_service()
        
    def _initialize_service(self):
        """
        Google Calendar APIサービスを初期化（OAuth認証）
        """
        try:
            # トークンの有効期限をチェック
            if self.credentials.expired and self.credentials.refresh_token:
                self.credentials.refresh(Request())
                # 更新された認証情報をデータベースに保存
                db_manager.save_google_credentials(
                    self.credentials.user_id,
                    {
                        'token': self.credentials.token,
                        'refresh_token': self.credentials.refresh_token,
                        'token_uri': self.credentials.token_uri,
                        'client_id': self.credentials.client_id,
                        'client_secret': self.credentials.client_secret,
                        'scopes': self.credentials.scopes,
                        'expires_at': self.credentials.expiry.timestamp() if self.credentials.expiry else None
                    }
                )
            
            self.service = build('calendar', 'v3', credentials=self.credentials)
            logger.info("Google Calendar APIサービスを初期化しました（OAuth認証）")
            # カレンダーIDを取得
            logger.info("カレンダーIDの取得を開始します")
            self.calendar_id = self._get_calendar_id()
            logger.info(f"カレンダーIDを設定しました: {self.calendar_id}")
        except Exception as e:
            logger.error(f"Google Calendar APIサービスの初期化に失敗: {str(e)}")
            logger.error(traceback.format_exc())
            raise
        
    @lru_cache(maxsize=100)
    def _get_calendar_id(self) -> str:
        """
        カレンダーIDを返す（プライマリーカレンダーを優先）
        """
        try:
            logger.info("カレンダーリストの取得を開始します")
            calendar_list = self.service.calendarList().list().execute()
            calendars = calendar_list.get('items', [])
            logger.info(f"利用可能なカレンダー数: {len(calendars)}")
            for calendar in calendars:
                calendar_id = calendar.get('id', 'N/A')
                calendar_summary = calendar.get('summary', 'N/A')
                calendar_primary = calendar.get('primary', False)
                calendar_access_role = calendar.get('accessRole', 'N/A')
                logger.info(f"カレンダー詳細: ID={calendar_id}, タイトル={calendar_summary}, プライマリー={calendar_primary}, アクセス権限={calendar_access_role}")
            # プライマリーカレンダーを優先
            for calendar in calendars:
                if calendar.get('primary', False):
                    logger.info(f"プライマリーカレンダーを使用: {calendar['id']}")
                    return calendar['id']
            # なければ最初のカレンダー
            if calendars:
                logger.warning(f"プライマリーが見つからないため最初のカレンダーを使用: {calendars[0]['id']}")
                return calendars[0]['id']
            logger.error("カレンダーが見つかりませんでした")
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
            title (Optional[str]): イベントのタイトル
            
        Returns:
            Dict: 操作結果
        """
        try:
            # タイムゾーンを設定
            time_zone = pytz.timezone('Asia/Tokyo')
            start_time = time_zone.localize(start_time) if start_time.tzinfo is None else start_time.astimezone(time_zone)
            end_time = time_zone.localize(end_time) if end_time.tzinfo is None else end_time.astimezone(time_zone)
            
            # イベントを検索
            events = await self._find_events(start_time, end_time, title)
            if not events:
                return {
                    "success": False,
                    "message": "指定された時間帯に予定が見つかりませんでした。",
                    "deleted_count": 0
                }
            
            deleted_count = 0
            for event in events:
                try:
                    # ThreadPoolExecutorを使用してタイムアウトを実装
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(
                            self.service.events().delete,
                            calendarId=self.calendar_id,
                            eventId=event['id']
                        )
                        try:
                            future.result(timeout=CALENDAR_TIMEOUT_SECONDS)
                            deleted_count += 1
                            logger.info(f"イベントを削除しました: {event.get('summary', 'タイトルなし')}")
                        except TimeoutError:
                            logger.error(f"イベントの削除が{CALENDAR_TIMEOUT_SECONDS}秒でタイムアウトしました")
                            continue
                        except Exception as e:
                            logger.error(f"イベントの削除中にエラーが発生: {str(e)}")
                            logger.error(traceback.format_exc())
                            continue
                except Exception as e:
                    logger.error(f"イベントの削除中にエラーが発生: {str(e)}")
                    logger.error(traceback.format_exc())
                    continue
            
            if deleted_count > 0:
                return {
                    "success": True,
                    "message": f"{deleted_count}件の予定を削除しました。",
                    "deleted_count": deleted_count
                }
            else:
                return {
                    "success": False,
                    "message": "予定の削除に失敗しました。",
                    "deleted_count": 0
                }
                
        except Exception as e:
            logger.error(f"イベントの削除中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": "予定の削除に失敗しました。",
                "error": str(e),
                "deleted_count": 0
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
                    response = result.execute()
                    events = response.get('items', [])
                    
                    # タイトルでフィルタリング
                    if title:
                        events = [event for event in events if title in event.get('summary', '')]
                    
                    # イベントの詳細をログ出力
                    logger.debug(f"APIから取得したイベント: {events}")
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
        条件に一致するイベントを検索（前後1時間も含めて柔軟に）
        """
        try:
            from datetime import timedelta
            # 検索範囲を前後1時間に拡大
            search_start = start_time - timedelta(hours=1)
            search_end = end_time + timedelta(hours=1)
            events = await self.get_events(search_start, search_end)
            matched = []
            for e in events:
                event_title = e.get('summary', '')
                # タイトルが指定されていない場合は全件対象
                if title:
                    # どちらかが短い場合は短い方で部分一致
                    if len(title) < len(event_title):
                        if title not in event_title:
                            continue
                    else:
                        if event_title not in title:
                            continue
                # 指定時刻に最も近いイベントを優先
                event_start_str = e['start'].get('dateTime') or e['start'].get('date')
                if not event_start_str:
                    continue
                event_start = datetime.fromisoformat(event_start_str.replace('Z', '+00:00'))
                # 1時間以内のイベントを対象
                if abs((event_start - start_time).total_seconds()) <= 3600:
                    matched.append(e)
            return matched
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