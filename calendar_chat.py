from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone, time
import logging
import os
import warnings
import re
from dateutil import parser
from typing import List, Dict, Any, Optional, Tuple
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import pytz
import traceback
import json
import tempfile

# 警告メッセージを抑制
warnings.filterwarnings('ignore', message='file_cache is only supported with oauth2client<4.0.0')

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_credentials():
    """環境変数から認証情報を取得し、一時ファイルとして保存する"""
    credentials_json = os.getenv('GOOGLE_CREDENTIALS')
    if not credentials_json:
        raise ValueError("GOOGLE_CREDENTIALS環境変数が設定されていません")
    
    try:
        # JSONの形式を確認
        json.loads(credentials_json)
    except json.JSONDecodeError:
        raise ValueError("GOOGLE_CREDENTIALSの形式が正しくありません")
    
    # 一時ファイルとして保存
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
        temp_file.write(credentials_json)
        return temp_file.name

class CalendarChat:
    def __init__(self):
        """初期化"""
        self.SCOPES = ['https://www.googleapis.com/auth/calendar']
        self.creds = None
        self.service = None
        self.timezone = pytz.timezone('Asia/Tokyo')
        self.credentials_file = None
        self.initialize_service()

    def initialize_service(self):
        """Google Calendar APIのサービスを初期化する"""
        try:
            # 環境変数から認証情報を取得
            self.credentials_file = get_credentials()
            logger.info("認証情報を一時ファイルとして保存しました")

            # サービスアカウントの認証情報を使用してサービスを初期化
            self.creds = service_account.Credentials.from_service_account_file(
                self.credentials_file,
                scopes=self.SCOPES
            )
            
            # サービスを構築
            logger.info("Google Calendar APIサービスを初期化します")
            self.service = build('calendar', 'v3', credentials=self.creds)
            logger.info("Google Calendar API service initialized successfully")
            
        except Exception as e:
            logger.error(f"Google Calendar APIサービスの初期化に失敗: {str(e)}")
            logger.error("詳細なエラー情報:", exc_info=True)
            raise
        finally:
            # 一時ファイルを削除
            if self.credentials_file and os.path.exists(self.credentials_file):
                try:
                    os.unlink(self.credentials_file)
                    logger.info("一時ファイルを削除しました")
                except Exception as e:
                    logger.warning(f"一時ファイルの削除に失敗: {str(e)}")

    def get_events(self, time_min: datetime = None, time_max: datetime = None) -> list:
        """Get calendar events for the specified time range."""
        try:
            # サービスの初期化を確認
            if not self.service:
                logger.error("Google Calendar APIサービスが初期化されていません")
                return []

            # デフォルト値の設定
            if time_min is None:
                time_min = datetime.now(self.timezone).replace(hour=0, minute=0, second=0, microsecond=0)
            if time_max is None:
                time_max = time_min.replace(hour=23, minute=59, second=59)

            # タイムゾーンの設定
            if time_min.tzinfo is None:
                time_min = self.timezone.localize(time_min)
            if time_max.tzinfo is None:
                time_max = self.timezone.localize(time_max)

            logger.info(f"イベント取得開始 - 検索範囲: {time_min.isoformat()} 〜 {time_max.isoformat()}")

            try:
                events_result = self.service.events().list(
                    calendarId='primary',
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    singleEvents=True,
                    orderBy='startTime',
                    timeZone='Asia/Tokyo'
                ).execute()
            except Exception as api_error:
                logger.error(f"Google Calendar API呼び出しエラー: {str(api_error)}")
                logger.error("詳細なエラー情報:", exc_info=True)
                return []

            if not isinstance(events_result, dict):
                logger.error(f"予期しない形式のレスポンス: {type(events_result)}")
                return []

            events = events_result.get('items', [])
            if not isinstance(events, list):
                logger.error(f"予期しない形式のイベントリスト: {type(events)}")
                return []

            logger.info(f"取得したイベント数: {len(events)}")

            # イベントの詳細をログに出力
            for event in events:
                if not isinstance(event, dict):
                    logger.error(f"予期しない形式のイベント: {type(event)}")
                    continue
                logger.debug(f"イベント: {event.get('summary')} - {event.get('start')} 〜 {event.get('end')}")

            return events

        except Exception as e:
            logger.error(f"イベント取得中にエラーが発生: {str(e)}")
            logger.error("詳細なエラー情報:", exc_info=True)
            return []  # エラー時は空のリストを返す

    def format_events(self, events: list) -> str:
        """
        予定一覧を整形して返す（改善版）
        
        Args:
            events (list): 予定のリスト
            
        Returns:
            str: 整形された予定一覧
        """
        if not events:
            today = datetime.now(self.timezone)
            date_str = today.strftime('%Y年%m月%d日')
            return (
                f"📅 {date_str}の予定は特にありません。\n\n"
                f"新しい予定を追加する場合は、以下のような形式でメッセージを送ってください：\n"
                f"・「明日の15時に会議を追加して」\n"
                f"・「来週の月曜日、10時から12時まで打ち合わせを入れて」\n"
                f"・「今週の金曜日、14時からカフェで打ち合わせ」"
            )

        # 日付ごとに予定を整理
        events_by_date = {}
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            
            # 日付と時間を整形
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            
            # 日本時間に変換
            start_dt = start_dt.astimezone(self.timezone)
            end_dt = end_dt.astimezone(self.timezone)
            
            # 日付をキーとして使用
            date_key = start_dt.strftime('%Y/%m/%d')
            
            # 曜日を取得
            weekday = ['月', '火', '水', '木', '金', '土', '日'][start_dt.weekday()]
            
            # 時間のフォーマット
            time_str = f"{start_dt.strftime('%H:%M')}〜{end_dt.strftime('%H:%M')}"
            
            # 予定の詳細情報を整形
            event_details = []
            event_details.append(f"📌 {event.get('summary', '予定なし')}")
            event_details.append(f"⏰ {time_str}")
            
            if event.get('location'):
                event_details.append(f"📍 {event['location']}")
            
            if event.get('description'):
                event_details.append(f"📝 {event['description']}")
            
            event_str = "\n".join(event_details)
            
            if date_key not in events_by_date:
                events_by_date[date_key] = {
                    'weekday': weekday,
                    'events': []
                }
            events_by_date[date_key]['events'].append(event_str)

        # 日付順に整形
        formatted_events = []
        formatted_events.append("📅 予定一覧")
        formatted_events.append("=" * 20)
        
        for date in sorted(events_by_date.keys()):
            date_info = events_by_date[date]
            formatted_events.append(f"\n■ {date}（{date_info['weekday']}）")
            formatted_events.extend([f"  {event}" for event in date_info['events']])
            formatted_events.append("-" * 20)

        # 空き時間の情報を追加
        free_slots = self.get_free_time_slots(
            datetime.now(self.timezone).replace(hour=0, minute=0, second=0, microsecond=0),
            30
        )
        
        if free_slots:
            formatted_events.append("\n⏰ 空き時間")
            formatted_events.append("=" * 20)
            formatted_events.extend([f"  {slot}" for slot in self.format_free_time_slots(free_slots)])
        else:
            formatted_events.append("\n⏰ 空き時間はありません")

        return "\n".join(formatted_events)

    def check_availability(self, start_time: datetime, end_time: datetime) -> List[Dict]:
        """
        指定された時間帯の予定の重複をチェックする（改善版）
        
        Args:
            start_time: 開始時間
            end_time: 終了時間
            
        Returns:
            List[Dict]: 重複する予定のリスト
        """
        try:
            # タイムゾーンを考慮
            start_time = start_time.astimezone(self.timezone)
            end_time = end_time.astimezone(self.timezone)
            
            logger.info(f"Checking availability from {start_time} to {end_time}")
            
            # 予定を取得
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_time.isoformat(),
                timeMax=end_time.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            overlapping_events = []
            for event in events_result.get('items', []):
                event_start = event['start'].get('dateTime')
                event_end = event['end'].get('dateTime')
                
                if event_start and event_end:
                    event_start = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                    event_end = datetime.fromisoformat(event_end.replace('Z', '+00:00'))
                    
                    # タイムゾーンを考慮
                    event_start = event_start.astimezone(self.timezone)
                    event_end = event_end.astimezone(self.timezone)
                    
                    # 重複チェック
                    if (event_start < end_time and event_end > start_time):
                        overlapping_events.append({
                            'summary': event.get('summary', '予定なし'),
                            'start': event_start,
                            'end': event_end,
                            'location': event.get('location', ''),
                            'description': event.get('description', '')
                        })
            
            return overlapping_events
        
        except Exception as e:
            logger.error(f"Error checking availability: {str(e)}")
            raise

    def delete_event(self, start_time: datetime, end_time: datetime) -> bool:
        """
        指定された時間帯の予定を削除する
        
        Args:
            start_time (datetime): 予定の開始時刻
            end_time (datetime): 予定の終了時刻
            
        Returns:
            bool: 削除に成功したかどうか
        """
        try:
            # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
            
            # 指定された時間帯の予定を検索
            events = self.get_events(time_min=start_time, time_max=end_time)
            
            if not events:
                logger.warning(f"指定された時間（{start_time.isoformat()}〜{end_time.isoformat()}）に予定が見つかりません")
                return False
            
            # 予定を削除
            for event in events:
                event_id = event['id']
                try:
                    self.service.events().delete(
                        calendarId='primary',
                        eventId=event_id
                    ).execute()
                    logger.info(f"予定を削除しました: {event.get('summary')} ({event.get('start')} - {event.get('end')})")
                except Exception as e:
                    logger.error(f"予定の削除中にエラーが発生: {str(e)}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"予定の削除中にエラーが発生: {str(e)}")
            return False

    def update_event(self, event_id: str, start_time: datetime, end_time: datetime, title: str = None, location: str = None) -> Dict[str, Any]:
        """
        予定を更新する
        
        Args:
            event_id (str): 更新する予定のID
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            title (str, optional): 予定のタイトル
            location (str, optional): 場所
            
        Returns:
            Dict[str, Any]: 更新された予定の情報
        """
        try:
            # タイムゾーン情報を確実に設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)
            
            # 予定の詳細を取得
            event = self.service.events().get(calendarId='primary', eventId=event_id).execute()
            
            # 更新する情報を設定
            event['start'] = {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Tokyo'
            }
            event['end'] = {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Tokyo'
            }
            
            if title:
                event['summary'] = title
            
            if location:
                event['location'] = location
            
            # 予定を更新
            updated_event = self.service.events().update(
                calendarId='primary',
                eventId=event_id,
                body=event
            ).execute()
            
            logger.info(f"予定を更新しました: {updated_event.get('summary')} ({start_time} - {end_time})")
            return updated_event
            
        except Exception as e:
            logger.error(f"予定の更新中にエラーが発生しました: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def create_event(self, summary: str, start_time: datetime, end_time: datetime,
                    location: Optional[str] = None, description: Optional[str] = None,
                    recurrence: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        予定を作成する
        
        Args:
            summary (str): 予定のタイトル
            start_time (datetime): 開始日時
            end_time (datetime): 終了日時
            location (Optional[str]): 場所
            description (Optional[str]): 説明
            recurrence (Optional[Dict[str, Any]]): 繰り返し情報
            
        Returns:
            Optional[str]: 作成された予定のID。失敗した場合はNone
        """
        try:
            # タイムゾーンを設定
            start_time = self.timezone.localize(start_time)
            end_time = self.timezone.localize(end_time)
            
            # 予定の詳細を構築
            event = {
                'summary': summary,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
            }
            
            # オプションの情報を追加
            if location:
                event['location'] = location
            if description:
                event['description'] = description
            if recurrence:
                event['recurrence'] = [self._format_recurrence_rule(recurrence)]
            
            # 予定を作成
            created_event = self.service.events().insert(
                calendarId='primary',
                body=event
            ).execute()
            
            logger.info(f"Event created successfully: {created_event['id']}")
            return created_event['id']
            
        except Exception as e:
            logger.error(f"Failed to create event: {str(e)}")
            return None

    def list_events(self, time_min: Optional[datetime] = None,
                   time_max: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        予定の一覧を取得する
        
        Args:
            time_min (Optional[datetime]): 開始日時
            time_max (Optional[datetime]): 終了日時
            
        Returns:
            List[Dict[str, Any]]: 予定の一覧
        """
        try:
            # デフォルトの期間を設定
            if not time_min:
                time_min = datetime.now()
            if not time_max:
                time_max = time_min + timedelta(days=7)
            
            # タイムゾーンを設定
            time_min = self.timezone.localize(time_min)
            time_max = self.timezone.localize(time_max)
            
            # 予定を取得
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            logger.info(f"Retrieved {len(events)} events")
            return events
            
        except Exception as e:
            logger.error(f"Failed to list events: {str(e)}")
            return []

    def _format_recurrence_rule(self, recurrence: Dict[str, Any]) -> str:
        """
        繰り返し情報をiCalendar形式の文字列に変換する
        
        Args:
            recurrence (Dict[str, Any]): 繰り返し情報
                - freq: 頻度（daily, weekly, monthly, yearly）
                - interval: 間隔
                - count: 繰り返し回数
                - until: 終了日
                - byday: 曜日
                - bymonthday: 日付
            
        Returns:
            str: iCalendar形式の繰り返しルール
        """
        try:
            rule = f"RRULE:FREQ={recurrence['freq'].upper()}"
            
            if recurrence.get('interval'):
                rule += f";INTERVAL={recurrence['interval']}"
            
            if recurrence.get('count'):
                rule += f";COUNT={recurrence['count']}"
            
            if recurrence.get('until'):
                rule += f";UNTIL={recurrence['until'].strftime('%Y%m%dT%H%M%SZ')}"
            
            if recurrence.get('byday'):
                rule += f";BYDAY={recurrence['byday']}"
            
            if recurrence.get('bymonthday'):
                rule += f";BYMONTHDAY={recurrence['bymonthday']}"
            
            return rule
            
        except Exception as e:
            logger.error(f"Failed to format recurrence rule: {str(e)}")
            return ""

    def find_events_by_date_and_title(self, target_date: datetime, title_keyword: str = None) -> list:
        """
        指定された日付とタイトルのキーワードに一致する予定を検索する
        
        Args:
            target_date (datetime): 検索する日時
            title_keyword (str, optional): タイトルのキーワード
            
        Returns:
            list: 見つかった予定のリスト
        """
        try:
            # タイムゾーンを日本時間に設定
            jst = timezone(timedelta(hours=9))
            if target_date.tzinfo is None:
                target_date = target_date.replace(tzinfo=jst)
            
            # 指定された時刻の前後1時間を検索範囲とする
            search_start = target_date - timedelta(hours=1)
            search_end = target_date + timedelta(hours=1)
            
            logger.info(f"Searching for events between {search_start.isoformat()} and {search_end.isoformat()}")
            if title_keyword:
                logger.info(f"With title keyword: {title_keyword}")
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=search_start.isoformat(),
                timeMax=search_end.isoformat(),
                singleEvents=True,
                orderBy='startTime',
                timeZone='Asia/Tokyo'
            ).execute()
            
            events = events_result.get('items', [])
            matching_events = []
            
            for event in events:
                event_summary = event.get('summary', '').lower()
                # タイトルキーワードが指定されていない場合は、時間のみで検索
                if title_keyword is None or any(keyword.lower() in event_summary for keyword in title_keyword.split()):
                    # 開始・終了時刻をJSTに変換
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    end = event['end'].get('dateTime', event['end'].get('date'))
                    
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(jst)
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00')).astimezone(jst)
                    
                    # 指定された時刻に最も近い予定を対象とする
                    time_diff = abs((start_dt - target_date).total_seconds())
                    if time_diff <= 3600:  # 1時間以内
                        matching_events.append({
                            'id': event['id'],
                            'summary': event.get('summary', '予定なし'),
                            'start': start_dt,
                            'end': end_dt,
                            'original_event': event
                        })
            
            # 時間差でソート
            matching_events.sort(key=lambda x: abs((x['start'] - target_date).total_seconds()))
            return matching_events
            
        except Exception as e:
            logger.error(f"Error finding events: {str(e)}")
            logger.error("Full error details:", exc_info=True)
            return []

    def reschedule_event(self, target_date: datetime, title_keyword: str, new_start_time: datetime, new_duration: int = None) -> tuple[bool, str]:
        """
        指定された日付とタイトルの予定を新しい時間に変更する
        
        Args:
            target_date (datetime): 対象の予定の日付
            title_keyword (str): 予定のタイトルのキーワード
            new_start_time (datetime): 新しい開始時間
            new_duration (int, optional): 新しい予定の長さ（分）
            
        Returns:
            tuple[bool, str]: (成功したかどうか, メッセージ)
        """
        try:
            # タイムゾーンを日本時間に設定
            jst = timezone(timedelta(hours=9))
            if target_date.tzinfo is None:
                target_date = target_date.replace(tzinfo=jst)
            if new_start_time.tzinfo is None:
                new_start_time = new_start_time.replace(tzinfo=jst)
            
            # 対象の予定を検索
            events = self.find_events_by_date_and_title(target_date, title_keyword)
            
            if not events:
                return False, f"{target_date.strftime('%Y/%m/%d')}の「{title_keyword}」という予定は見つかりませんでした。"
     
            if len(events) > 1:
                # 複数の予定が見つかった場合は、時間を含めて表示
                events_info = "\n".join([
                    f"・{event['summary']} ({event['start'].strftime('%H:%M')}〜{event['end'].strftime('%H:%M')})"
                    for event in events
                ])
                return False, f"複数の予定が見つかりました。どの予定を変更するか、時間を指定してください：\n{events_info}"
            
            target_event = events[0]
            
            # 新しい終了時間を設定
            if new_duration is not None:
                new_end_time = new_start_time + timedelta(minutes=new_duration)
            else:
                # 元の予定の長さを維持
                original_duration = (target_event['end'] - target_event['start']).total_seconds() / 60
                new_end_time = new_start_time + timedelta(minutes=int(original_duration))
            
            # 予定の重複をチェック（自分自身は除外）
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=new_start_time.isoformat(),
                timeMax=new_end_time.isoformat(),
                singleEvents=True,
                orderBy='startTime',
                timeZone='Asia/Tokyo'
            ).execute()
            
            conflicts = []
            for event in events_result.get('items', []):
                # 自分自身の予定はスキップ
                if event['id'] == target_event['id']:
                    continue
                    
                event_start = event['start'].get('dateTime', event['start'].get('date'))
                event_end = event['end'].get('dateTime', event['end'].get('date'))
                
                # 日時をdatetimeオブジェクトに変換
                event_start_dt = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                event_end_dt = datetime.fromisoformat(event_end.replace('Z', '+00:00'))
                
                # JSTに変換
                event_start_dt = event_start_dt.astimezone(jst)
                event_end_dt = event_end_dt.astimezone(jst)
                
                conflicts.append({
                    'summary': event.get('summary', '予定なし'),
                    'start': event_start_dt.strftime('%H:%M'),
                    'end': event_end_dt.strftime('%H:%M')
                })
            
            if conflicts:
                conflict_info = "\n".join([
                    f"・{conflict['start']}〜{conflict['end']} {conflict['summary']}"
                    for conflict in conflicts
                ])
                return False, f"新しい時間に既に以下の予定が入っています：\n{conflict_info}"
            
            # 予定を更新
            event_body = target_event['original_event']
            event_body['start']['dateTime'] = new_start_time.isoformat()
            event_body['end']['dateTime'] = new_end_time.isoformat()
            
            updated_event = self.service.events().update(
                calendarId='primary',
                eventId=target_event['id'],
                body=event_body
            ).execute()
            
            # レスポンスメッセージを作成
            old_time = target_event['start'].strftime('%H:%M')
            new_time = new_start_time.strftime('%H:%M')
            new_end = new_end_time.strftime('%H:%M')
            duration_mins = int((new_end_time - new_start_time).total_seconds() / 60)
            
            return True, f"予定を変更しました：\n{target_event['summary']}\n{old_time} → {new_time}〜{new_end}（{duration_mins}分）"
         
        except Exception as e:
            logger.error(f"Error rescheduling event: {str(e)}")
            logger.error("Full error details:", exc_info=True)
            return False, "予定の変更中にエラーが発生しました。"

    def _format_event_time(self, event):
        """
        イベントの時間を文字列にフォーマットする
        
        Args:
            event (dict): イベントデータ
            
        Returns:
            str: フォーマットされた時間文字列
        """
        start_time = parser.parse(event['start'].get('dateTime'))
        end_time = parser.parse(event['end'].get('dateTime'))
        return f"{start_time.strftime('%H:%M')}〜{end_time.strftime('%H:%M')}"

    def update_event_duration(self, target_date, title_keyword, duration_minutes):
        """
        指定された予定の時間の長さを変更する
        
        Args:
            target_date (datetime): 対象の日時
            title_keyword (str): 予定のタイトルのキーワード
            duration_minutes (int): 新しい予定の長さ（分）
            
        Returns:
            tuple: (成功したかどうか, メッセージ)
        """
        try:
            logger.info(f"Searching for events - Date: {target_date}, Title: {title_keyword}")
            
            # タイムゾーンを日本時間に設定
            jst = timezone(timedelta(hours=9))
            if target_date.tzinfo is None:
                target_date = target_date.replace(tzinfo=jst)
            
            # 指定された日付の予定を取得
            search_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            search_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=search_start.isoformat(),
                timeMax=search_end.isoformat(),
                singleEvents=True,
                orderBy='startTime',
                timeZone='Asia/Tokyo'
            ).execute()
            
            events = events_result.get('items', [])
            logger.info(f"Found {len(events)} events for the day")
            
            # タイトルキーワードで予定を絞り込む
            matched_events = []
            for event in events:
                event_start = parser.parse(event['start'].get('dateTime'))
                if title_keyword in event.get('summary', '') and abs((event_start - target_date).total_seconds()) <= 3600:
                    matched_events.append(event)
            
            if not matched_events:
                return False, f"{target_date.strftime('%m/%d %H:%M')}の「{title_keyword}」という予定は見つかりませんでした。"
            
            if len(matched_events) > 1:
                event_list = "\n".join([
                    f"{i+1}. {event.get('summary')} ({self._format_event_time(event)})"
                    for i, event in enumerate(matched_events)
                ])
                return False, f"複数の予定が見つかりました。番号を指定して変更してください：\n{event_list}"
            
            target_event = matched_events[0]
            start_time = parser.parse(target_event['start'].get('dateTime'))
            new_end_time = start_time + timedelta(minutes=duration_minutes)
            
            # 他の予定との重複をチェック
            for event in events:
                if event['id'] == target_event['id']:
                    continue
                    
                event_start = parser.parse(event['start'].get('dateTime'))
                event_end = parser.parse(event['end'].get('dateTime'))
                
                if (start_time < event_end and new_end_time > event_start):
                    return False, f"指定された時間に他の予定「{event.get('summary')}」が入っています。"
            
            # 予定を更新
            target_event['end']['dateTime'] = new_end_time.isoformat()
            self.service.events().update(
                calendarId='primary',
                eventId=target_event['id'],
                body=target_event
            ).execute()
            
            formatted_time = self._format_event_time(target_event)
            return True, f"予定「{target_event.get('summary')}」の時間を{duration_minutes}分に変更しました。\n{formatted_time}"
            
        except Exception as e:
            logger.error(f"Error updating event duration: {str(e)}")
            logger.error("Full error details:", exc_info=True)
            return False, "予定の時間変更中にエラーが発生しました。"

    def add_event(self, start_time: datetime, end_time: datetime, title: str, 
                 location: Optional[str] = None, person: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        イベントを追加する
        
        Args:
            start_time (datetime): 開始時間
            end_time (datetime): 終了時間
            title (str): タイトル
            location (Optional[str]): 場所
            person (Optional[str]): 人物
            
        Returns:
            Optional[Dict[str, Any]]: 追加されたイベントの情報
        """
        try:
            # イベントの作成
            event = {
                'summary': title,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
            }
            
            # 場所が指定されている場合、追加
            if location:
                event['location'] = location
            
            # 人物が指定されている場合、説明として追加
            if person:
                event['description'] = f"参加者: {person}"
            
            # イベントを追加
            event = self.service.events().insert(
                calendarId='primary',
                body=event
            ).execute()
            
            logger.info(f"イベントを追加しました: {event.get('htmlLink')}")
            return event
            
        except Exception as e:
            logger.error(f"イベントの追加中にエラーが発生しました: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def get_free_time_slots(self, date: datetime, min_duration: int = 30) -> List[Dict]:
        """
        指定された日付の空き時間を取得する（改善版）
        
        Args:
            date (datetime): 対象日付
            min_duration (int): 最小空き時間（分）
            
        Returns:
            List[Dict]: 空き時間のリスト
        """
        try:
            # その日の予定を取得
            time_min = date.replace(hour=0, minute=0, second=0, microsecond=0)
            time_max = date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            events = self.get_events(time_min, time_max)
            
            # 予定を時系列順にソート
            sorted_events = sorted(events, key=lambda x: x['start'].get('dateTime', x['start'].get('date')))
            
            # 空き時間を計算
            free_slots = []
            current_time = time_min
            
            for event in sorted_events:
                event_start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')).replace('Z', '+00:00'))
                event_start = event_start.astimezone(self.timezone)
                
                # 現在時刻と予定開始時刻の間に空き時間がある場合
                if (event_start - current_time).total_seconds() / 60 >= min_duration:
                    free_slots.append({
                        'start': current_time,
                        'end': event_start,
                        'duration': int((event_start - current_time).total_seconds() / 60)
                    })
                
                # 予定の終了時刻を次の開始時刻として設定
                event_end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')).replace('Z', '+00:00'))
                event_end = event_end.astimezone(self.timezone)
                current_time = event_end
            
            # 最後の予定から23:59までの空き時間を追加
            if (time_max - current_time).total_seconds() / 60 >= min_duration:
                free_slots.append({
                    'start': current_time,
                    'end': time_max,
                    'duration': int((time_max - current_time).total_seconds() / 60)
                })
            
            return free_slots
        
        except Exception as e:
            logger.error(f"空き時間の取得中にエラーが発生: {str(e)}")
            logger.error("詳細なエラー情報:", exc_info=True)
            return []

    def format_free_time_slots(self, free_slots: List[Dict]) -> str:
        """
        空き時間を整形して返す（改善版）
        
        Args:
            free_slots (List[Dict]): 空き時間のリスト
            
        Returns:
            str: 整形された空き時間情報
        """
        if not free_slots:
            return "空き時間はありません。"
        
        message = "🕒 空き時間\n\n"
        
        for slot in free_slots:
            start_time = slot['start'].strftime('%H:%M')
            end_time = slot['end'].strftime('%H:%M')
            duration = slot['duration']
            
            message += f"⏰ {start_time}〜{end_time}（{duration}分）\n"
        
        return message

    def format_calendar_response(self, events: list, start_time: datetime, end_time: datetime) -> str:
        """
        カレンダーのレスポンスを整形する（改善版）
        
        Args:
            events (list): 予定のリスト
            start_time (datetime): 開始時刻
            end_time (datetime): 終了時刻
            
        Returns:
            str: 整形されたレスポンス
        """
        if not events:
            return (
                "📅 予定はありません。\n\n"
                "新しい予定を追加する場合は、以下のような形式でメッセージを送ってください：\n"
                "・「明日の15時に会議を追加して」\n"
                "・「来週の月曜日、10時から12時まで打ち合わせを入れて」\n"
                "・「今週の金曜日、14時からカフェで打ち合わせ」"
            )
        
        # 予定を日付ごとにグループ化
        events_by_date = {}
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            date = datetime.fromisoformat(start.replace('Z', '+00:00')).strftime('%Y年%m月%d日')
            if date not in events_by_date:
                events_by_date[date] = []
            events_by_date[date].append(event)
        
        # メッセージを構築
        message = "📅 予定一覧\n\n"
        
        for date in sorted(events_by_date.keys()):
            message += f"■ {date}\n"
            for event in events_by_date[date]:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                
                message += (
                    f"  📌 {event.get('summary', '予定なし')}\n"
                    f"  ⏰ {start_dt.strftime('%H:%M')}〜{end_dt.strftime('%H:%M')}\n"
                )
                if event.get('location'):
                    message += f"  📍 {event['location']}\n"
                message += "\n"
        
        # 空き時間情報を追加
        free_slots = self.get_free_time_slots(start_time)
        message += "\n" + self.format_free_time_slots(free_slots)
        
        message += "\n予定の追加、変更、削除が必要な場合は、お気軽にお申し付けください。"
        return message

    def check_overlapping_events(self, start_time: datetime, end_time: datetime) -> List[Dict]:
        """
        指定された時間帯に重複する予定があるかチェックする
        
        Args:
            start_time (datetime): 開始時刻
            end_time (datetime): 終了時刻
            
        Returns:
            List[Dict]: 重複する予定のリスト
        """
        try:
            # タイムゾーンの設定
            if start_time.tzinfo is None:
                start_time = self.timezone.localize(start_time)
            if end_time.tzinfo is None:
                end_time = self.timezone.localize(end_time)

            # 既存の予定を取得
            events = self.get_events(start_time, end_time)
            
            # 重複する予定を抽出
            overlapping_events = []
            for event in events:
                event_start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')).replace('Z', '+00:00'))
                event_end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')).replace('Z', '+00:00'))
                
                # 日本時間に変換
                event_start = event_start.astimezone(self.timezone)
                event_end = event_end.astimezone(self.timezone)
                
                # 時間が重複しているかチェック
                if (event_start < end_time and event_end > start_time):
                    overlapping_events.append({
                        'summary': event.get('summary', '予定なし'),
                        'start': event_start,
                        'end': event_end,
                        'location': event.get('location', ''),
                        'description': event.get('description', '')
                    })
            
            return overlapping_events
            
        except Exception as e:
            logger.error(f"予定の重複チェック中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return []
