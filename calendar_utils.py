import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime

# ロギングの設定
logger = logging.getLogger(__name__)

# スコープの設定
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_calendar_service():
    """Googleカレンダーのサービスを取得する（サービスアカウント使用）"""
    # サービスアカウントの認証情報を読み込む
    credentials = service_account.Credentials.from_service_account_file(
        'service-account.json', scopes=SCOPES)
    
    # カレンダーサービスを構築
    service = build('calendar', 'v3', credentials=credentials)
    return service

def add_event(summary, start_time, end_time, description=None, calendar_id='primary'):
    """カレンダーにイベントを追加する"""
    try:
        logger.info("📅 カレンダー登録開始:")
        logger.info(f"  タイトル: {summary}")
        logger.info(f"  開始時間: {start_time}")
        logger.info(f"  終了時間: {end_time}")
        logger.info(f"  説明: {description if description else '(なし)'}")
        logger.info(f"  カレンダーID: {calendar_id}")
        
        service = get_calendar_service()
        
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Tokyo',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Tokyo',
            },
        }
        
        result = service.events().insert(calendarId=calendar_id, body=event).execute()
        logger.info(f"✅ イベント追加成功: {result.get('htmlLink')}")
        return result
        
    except Exception as e:
        logger.error(f"❌ イベント追加失敗: {str(e)}")
        raise e

def parse_datetime(date_str, time_str):
    """日付と時間の文字列をdatetimeオブジェクトに変換する"""
    # 日付のパース（例: "2024/03/20"）
    year, month, day = map(int, date_str.split('/'))
    
    # 時間のパース（例: "14:30"）
    hour, minute = map(int, time_str.split(':'))
    
    return datetime.datetime(year, month, day, hour, minute) 