from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, abort, session, jsonify, render_template, redirect, url_for
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import MessagingApi, Configuration, ApiClient, ReplyMessageRequest, URIAction, TemplateMessage, ButtonsTemplate
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import TextMessage
import os
import logging
import traceback
from datetime import datetime, timedelta, timezone
import pytz
import json
import asyncio
import argparse
from functools import wraps
from message_parser import parse_message, extract_time
from calendar_operations import CalendarManager
from database import DatabaseManager
from typing import List, Dict
import warnings
import time
from tenacity import retry, stop_after_attempt, wait_exponential
import signal
from contextlib import contextmanager
from werkzeug.middleware.proxy_fix import ProxyFix
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery

# 警告の抑制
warnings.filterwarnings('ignore', category=DeprecationWarning)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('linebot').setLevel(logging.ERROR)

# コマンドライン引数の設定
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=3001, help='ポート番号')
args = parser.parse_args()

# ログ設定
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# タイムゾーンの設定
JST = pytz.timezone('Asia/Tokyo')

# Google Calendar APIの認証情報のパスを確認
credentials_path = os.getenv('GOOGLE_CREDENTIALS_PATH')
if not credentials_path:
    # 環境変数から直接認証情報を取得
    credentials_json = os.getenv('GOOGLE_CREDENTIALS')
    if not credentials_json:
        raise ValueError("GOOGLE_CREDENTIALS環境変数が設定されていません。")
    # 一時ファイルとして認証情報を保存
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(credentials_json)
        credentials_path = f.name

# CalendarManagerの初期化
calendar_manager = CalendarManager(credentials_path)

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-here')

# プロキシ設定
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1,
    x_prefix=1
)

# LINE Bot SDKの初期化
configuration = Configuration(
    access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
)
api_client = ApiClient(configuration)
messaging_api = MessagingApi(api_client)
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

db_manager = DatabaseManager()

# タイムアウト設定
TIMEOUT_SECONDS = 30  # タイムアウトを30秒に延長

@contextmanager
def timeout(seconds):
    def signal_handler(signum, frame):
        raise TimeoutError(f"処理が{seconds}秒でタイムアウトしました")
    
    # SIGALRMハンドラーを設定する前に現在のハンドラーを保存
    original_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        # 元のハンドラーを復元
        signal.signal(signal.SIGALRM, original_handler)

# リトライ設定
MAX_RETRIES = 5
RETRY_DELAY = 2
RETRY_BACKOFF = 1.5

def retry_on_error(func):
    """
    エラー発生時にリトライするデコレータ
    """
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=RETRY_DELAY, exp_base=RETRY_BACKOFF),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying {func.__name__} after {retry_state.attempt_number} attempts"
        )
    )
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}")
            logger.error(traceback.format_exc())
            raise
    return wrapper

def require_auth(f):
    """
    ユーザー認証を要求するデコレータ
    
    Args:
        f: デコレートする関数
        
    Returns:
        デコレートされた関数
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = request.args.get('user_id')
        if not user_id or not db_manager.is_authorized(user_id):
            logger.warning(f"未認証ユーザーからのアクセス: {user_id}")
            return "認証が必要です。", 401
        return f(*args, **kwargs)
    return decorated_function

def format_error_message(error: Exception, context: str = "") -> str:
    """
    エラーメッセージを整形する
    
    Args:
        error (Exception): エラーオブジェクト
        context (str): エラーのコンテキスト
        
    Returns:
        str: 整形されたエラーメッセージ
    """
    error_type = type(error).__name__
    error_message = str(error)
    
    if isinstance(error, InvalidSignatureError):
        return "署名の検証に失敗しました。不正なリクエストの可能性があります。"
    elif isinstance(error, ValueError):
        return f"入力値が不正です: {error_message}"
    elif isinstance(error, KeyError):
        return f"必要な情報が不足しています: {error_message}"
    else:
        return f"エラーが発生しました: {error_message}\n\n詳細: {context}"

def format_datetime(dt: datetime) -> str:
    """
    日時をフォーマットする
    
    Args:
        dt (datetime): フォーマットする日時
        
    Returns:
        str: フォーマットされた日時文字列
    """
    try:
        # タイムゾーンを日本時間に設定
        if dt.tzinfo is None:
            dt = JST.localize(dt)
        else:
            dt = dt.astimezone(JST)
            
        # 日時のフォーマット
        return dt.strftime('%Y年%m月%d日 %H:%M')
    except Exception as e:
        logger.error(f"日時のフォーマット中にエラーが発生: {str(e)}")
        return ""

def format_response_message(operation_type: str, result: Dict) -> str:
    """
    操作結果に基づいて応答メッセージをフォーマット
    
    Args:
        operation_type (str): 操作の種類
        result (Dict): 操作結果
        
    Returns:
        str: フォーマットされたメッセージ
    """
    try:
        if not result.get('success', False):
            return result.get('message', '操作に失敗しました。')
            
        if operation_type == 'add':
            event = result.get('event')
            if event:
                # execute()を呼び出して実際のレスポンスを取得
                event_data = event.execute()
                message = "予定を追加しました。\n\n"
                message += f"📝 {event_data.get('summary', '')}\n"
                if 'start' in event_data and 'dateTime' in event_data['start']:
                    message += f"🗓 {format_datetime(datetime.fromisoformat(event_data['start']['dateTime']))}\n"
                if 'location' in event_data:
                    message += f"📍 {event_data['location']}\n"
                if 'description' in event_data:
                    message += f"📋 {event_data['description']}\n"
                return message
            return "予定を追加しました。"
            
        elif operation_type == 'delete':
            deleted_count = result.get('deleted_count', 0)
            return f"{deleted_count}件の予定を削除しました。"
            
        elif operation_type == 'list':
            events = result.get('events', [])
            if not events:
                return "予定はありません。"
                
            message = "予定一覧:\n\n"
            for event in events:
                message += f"📝 {event.get('summary', '')}\n"
                if 'start' in event and 'dateTime' in event['start']:
                    message += f"🗓 {format_datetime(datetime.fromisoformat(event['start']['dateTime']))}\n"
                if 'location' in event:
                    message += f"📍 {event['location']}\n"
                if 'description' in event:
                    message += f"📋 {event['description']}\n"
                message += "\n"
            return message
            
        return "操作が完了しました。"
        
    except Exception as e:
        logger.error(f"メッセージのフォーマット中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return "申し訳ありません。\nメッセージの作成中にエラーが発生しました。\nもう一度お試しください。"

def format_event_details(event: dict) -> str:
    """
    イベントの詳細をフォーマットする
    
    Args:
        event (dict): イベント情報
        
    Returns:
        str: フォーマットされたイベント詳細
    """
    try:
        start_time = event.get('start', {}).get('dateTime')
        end_time = event.get('end', {}).get('dateTime')
        title = event.get('summary', '予定')
        location = event.get('location', '')
        description = event.get('description', '')
        
        message = f"🗓 {format_datetime(datetime.fromisoformat(start_time))}〜\n"
        if location:
            message += f"📍 {location}\n"
        message += f"📌 {title}\n"
        if description:
            message += f"👥 {description}\n"
            
        return message
        
    except Exception as e:
        logger.error(f"イベント詳細のフォーマット中にエラーが発生: {str(e)}")
        return ""

def format_event_list(events: List[Dict]) -> str:
    """
    予定のリストを表示用にフォーマットする

    Args:
        events (List[Dict]): 予定のリスト

    Returns:
        str: フォーマットされたメッセージ
    """
    if not events:
        return "予定はありません。"
        
    # 日付ごとに予定を整理
    events_by_date = {}
    for event in events:
        try:
            # 開始時刻の取得とタイムゾーン変換
            start = event['start'].get('dateTime', event['start'].get('date'))
            if start:
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                if start_dt.tzinfo is None:
                    start_dt = JST.localize(start_dt)
                else:
                    start_dt = start_dt.astimezone(JST)
                
                # 終了時刻の取得とタイムゾーン変換
                end = event['end'].get('dateTime', event['end'].get('date'))
                if end:
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    if end_dt.tzinfo is None:
                        end_dt = JST.localize(end_dt)
                    else:
                        end_dt = end_dt.astimezone(JST)
                
                # 日付をキーとして使用
                date_key = start_dt.strftime('%Y/%m/%d')
                
                # 曜日を取得
                weekday = ['月', '火', '水', '木', '金', '土', '日'][start_dt.weekday()]
                
                # 予定の詳細情報を整形
                event_details = []
                event_details.append(f"📌 {event.get('summary', '(タイトルなし)')}")
                
                # 時刻の表示形式を設定
                if 'dateTime' in event['start']:
                    event_details.append(f"⏰ {start_dt.strftime('%H:%M')}～{end_dt.strftime('%H:%M')}")
                else:
                    event_details.append("⏰ 終日")
                
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
        except Exception as e:
            logger.error(f"イベントの処理中にエラーが発生: {str(e)}")
            logger.error(f"イベントデータ: {event}")
            continue
        
    # 日付順に整形
    message = "📅 予定一覧\n"
    message += "=" * 20 + "\n\n"
    
    for date_key in sorted(events_by_date.keys()):
        date_info = events_by_date[date_key]
        message += f"🗓 {date_key} ({date_info['weekday']})\n"
        message += "-" * 15 + "\n"
        
        for i, event_str in enumerate(date_info['events'], 1):
            message += f"{i}. {event_str}\n"
            
        message += "\n"
        
    return message

def process_webhook(body, signature):
    """
    Webhookの処理を実行する
    """
    try:
        # 署名を検証
        handler.handle(body, signature)
        logger.info("署名の検証に成功")
        return True
    except InvalidSignatureError as e:
        logger.error("署名の検証に失敗しました。")
        logger.error(traceback.format_exc())
        return False
    except Exception as e:
        logger.error(f"コールバック処理中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return False

@app.route("/callback", methods=['POST'])
@retry_on_error
def callback():
    """
    LINE Messaging APIからのコールバックを処理する
    """
    start_time = time.time()
    logger.info("コールバック処理開始")
    
    try:
        # リクエストヘッダーから署名を取得
        if 'X-Line-Signature' not in request.headers:
            logger.error("X-Line-Signatureヘッダーが見つかりません")
            return 'OK', 200
        
        signature = request.headers['X-Line-Signature']
        
        # リクエストボディを取得
        body = request.get_data(as_text=True)
        logger.debug(f"リクエストボディ: {body}")
        
        # ThreadPoolExecutorを使用してタイムアウトを実装
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(process_webhook, body, signature)
            try:
                result = future.result(timeout=TIMEOUT_SECONDS)
                if not result:
                    return 'OK', 200
            except TimeoutError:
                logger.error(f"処理が{TIMEOUT_SECONDS}秒でタイムアウトしました")
                return 'OK', 200
        
        processing_time = time.time() - start_time
        logger.info(f"コールバック処理完了 (処理時間: {processing_time:.2f}秒)")
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"予期せぬエラー: {str(e)}")
        logger.error(traceback.format_exc())
        return 'OK', 200

# user_tokens.jsonからユーザーごとのGoogle認証情報を取得

def get_user_credentials(line_user_id):
    try:
        with open('user_tokens.json', 'r') as f:
            tokens = json.load(f)
    except FileNotFoundError:
        tokens = {}
    user_token = tokens.get(line_user_id)
    if not user_token:
        return None
    credentials = google.oauth2.credentials.Credentials(
        token=user_token['token'],
        refresh_token=user_token['refresh_token'],
        token_uri=user_token['token_uri'],
        client_id=user_token['client_id'],
        client_secret=user_token['client_secret'],
        scopes=user_token['scopes']
    )
    return credentials

# Googleカレンダー予定一覧を取得

def get_user_events(line_user_id):
    credentials = get_user_credentials(line_user_id)
    if not credentials:
        return None
    service = googleapiclient.discovery.build('calendar', 'v3', credentials=credentials)
    events_result = service.events().list(calendarId='primary', maxResults=10).execute()
    events = events_result.get('items', [])
    if not events:
        return "予定はありません。"
    return "\n".join([event['summary'] for event in events if 'summary' in event])

@handler.add(MessageEvent)
def handle_message(event):
    """
    LINEメッセージを処理する
    
    Args:
        event (MessageEvent): LINEイベント
    """
    if not isinstance(event.message, TextMessageContent):
        return

    reply_message = "申し訳ありません。メッセージの処理中にエラーが発生しました。もう一度試してください。"  # デフォルトのエラーメッセージ
    
    try:
        # メッセージの取得
        text = event.message.text
        
        # メッセージの解析
        result = parse_message(text)
        
        # 日時抽出の結果を確認
        if result.get('type') == 'error':
            # 日付のみの場合はエラーとしない
            if '日時情報を抽出できませんでした' in result.get('message', ''):
                # 今日の日付で0:00〜23:59を設定
                now = datetime.now(JST)
                start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_time = now.replace(hour=23, minute=59, second=59, microsecond=999999)
                result = {
                    'type': 'read',
                    'start_time': start_time,
                    'end_time': end_time,
                    'date_only': True
                }
            else:
                raise ValueError(result.get('message', 'メッセージの解析に失敗しました'))
        
        # 操作タイプの取得
        operation_type = result.get('operation_type')
        
        # 日時情報のチェック
        datetime_info = result.get('datetime', {})
        if operation_type == 'update':
            if not all(key in datetime_info for key in ['start_time', 'end_time', 'new_start_time', 'new_end_time']):
                reply_message = "予定の変更に必要な日時情報が不足しています。以下のような形式で入力してください：\n・5月5日10時から12時に変更\n・明日の予定を来週月曜日に変更"
                messaging_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_message)]
                    )
                )
                return
                
        # カレンダー操作の実行
        if operation_type == 'update':
            success = calendar_manager.update_event(
                start_time=datetime_info['start_time'],
                end_time=datetime_info['end_time'],
                new_start_time=datetime_info['new_start_time'],
                new_end_time=datetime_info['new_end_time'],
                title=result.get('title'),
                location=result.get('location'),
                person=result.get('person')
            )
            if success:
                reply_message = "予定を更新しました。"
            else:
                reply_message = "予定の更新に失敗しました。もう一度試してください。"
                
        elif operation_type in ['read', 'check']:
            try:
                start = result.get('start_time')
                end = result.get('end_time')
                # 日付のみの場合は0:00〜23:59に補正
                if result.get('date_only') and start and end:
                    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
                    end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
                    # タイムゾーンを設定
                    if start.tzinfo is None:
                        start = JST.localize(start)
                    if end.tzinfo is None:
                        end = JST.localize(end)
                events = asyncio.run(calendar_manager.get_events(
                    start_time=start,
                    end_time=end
                ))
                reply_message = format_event_list(events)
            except Exception as e:
                logger.error(f"予定の確認中にエラーが発生: {str(e)}")
                reply_message = "予定の確認に失敗しました。もう一度試してください。"
                
        elif operation_type == 'add':
            try:
                # 時間情報の抽出
                time_info = extract_time(text)
                if not time_info['date_only']:
                    result['start_time'] = time_info['start_time']
                    result['end_time'] = time_info['end_time']
                
                # 予定の追加を試みる
                add_result = asyncio.run(calendar_manager.add_event(
                    title=result['title'],
                    start_time=result['start_time'],
                    end_time=result['end_time'],
                    location=result.get('location'),
                    person=result.get('person'),
                    description=None
                ))
                
                # 結果に基づいてメッセージを設定
                if add_result.get('success', True):
                    reply_message = format_response_message('add', add_result)
                else:
                    # 重複する予定がある場合
                    if add_result.get('overlapping_events'):
                        reply_message = format_response_message('add', {
                            'success': False,
                            'overlapping_events': add_result['overlapping_events']
                        })
                    else:
                        reply_message = "予定の追加に失敗しました。もう一度試してください。"
                        
            except Exception as e:
                logger.error(f"予定の追加中にエラーが発生: {str(e)}")
                logger.error(traceback.format_exc())
                reply_message = "予定の追加に失敗しました。もう一度試してください。"
                
        elif operation_type == 'delete':
            try:
                result = asyncio.run(calendar_manager.delete_event(
                    start_time=result['start_time'],
                    end_time=result['end_time'],
                    title=result.get('title')
                ))
                reply_message = format_response_message('delete', result)
            except Exception as e:
                logger.error(f"予定の削除中にエラーが発生: {str(e)}")
                reply_message = format_response_message('delete', {
                    'success': False
                })
        
        # 応答メッセージの送信
        try:
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_message)]
                )
            )
            logger.info(f"LINEへの返信を送信しました: {reply_message}")
        except Exception as e:
            logger.error(f"LINEへの返信送信中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
        
    except Exception as e:
        logger.error(f"メッセージ処理中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        try:
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_message)]
                )
            )
            logger.info(f"エラーメッセージを送信しました: {reply_message}")
        except Exception as e:
            logger.error(f"エラーメッセージの送信中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())

    # handle_messageで「今日の予定を教えて」に対応
    if text == "今日の予定を教えて":
        events_message = get_user_events(event.source.user_id)
        if events_message is None:
            send_google_auth_link(event.source.user_id)
            reply_message = "Googleカレンダー連携が必要です。上のボタンから連携してください。"
        else:
            reply_message = events_message
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_message)]
            )
        )
        return

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        message = data.get('message', '')
        
        # メッセージを解析
        result = parse_message(message)
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/', methods=['GET'])
def home():
    return render_template('base.html')

@app.before_request
def before_request():
    # リクエストの開始時刻を記録
    request.start_time = time.time()
    # リクエストの詳細をログに記録
    logger.debug(f"Request: {request.method} {request.url}")
    logger.debug(f"Headers: {dict(request.headers)}")
    logger.debug(f"Body: {request.get_data(as_text=True)}")

@app.after_request
def after_request(response):
    # リクエストの処理時間を計算してログに記録
    if hasattr(request, 'start_time'):
        elapsed = time.time() - request.start_time
        logger.info(f"Request processed in {elapsed:.2f} seconds")
        logger.debug(f"Response status: {response.status}")
        logger.debug(f"Response headers: {dict(response.headers)}")
    return response

@app.errorhandler(502)
def bad_gateway_error(error):
    logger.error(f"502 Bad Gateway Error: {str(error)}")
    logger.error(f"Request Headers: {dict(request.headers)}")
    logger.error(f"Request Data: {request.get_data()}")
    return jsonify({
        'error': 'Bad Gateway',
        'message': 'サーバー間の通信に問題が発生しました。',
        'status_code': 502
    }), 502

@app.errorhandler(504)
def gateway_timeout_error(error):
    logger.error(f"504 Gateway Timeout Error: {str(error)}")
    logger.error(f"Request Headers: {dict(request.headers)}")
    logger.error(f"Request Data: {request.get_data()}")
    return jsonify({
        'error': 'Gateway Timeout',
        'message': 'サーバーからの応答がタイムアウトしました。',
        'status_code': 504
    }), 504

@app.errorhandler(Exception)
def handle_exception(error):
    logger.error(f"Unhandled Exception: {str(error)}")
    logger.error(f"Request Headers: {dict(request.headers)}")
    logger.error(f"Request Data: {request.get_data()}")
    logger.error(traceback.format_exc())
    return jsonify({
        'error': 'Internal Server Error',
        'message': '予期せぬエラーが発生しました。',
        'status_code': 500
    }), 500

# Google連携ボタンをLINEユーザーに送信する関数
def send_google_auth_link(user_id):
    auth_url = f"https://line-calendar-bot-q8d3.onrender.com/authorize?user_id={user_id}"
    message = TemplateMessage(
        alt_text="Google連携はこちらから",
        template=ButtonsTemplate(
            text="Googleカレンダーと連携するには下のボタンを押してください。",
            actions=[
                URIAction(label="Google連携", uri=auth_url)
            ]
        )
    )
    messaging_api.push_message(to=user_id, messages=[message])

# /authorizeでuser_idを受け取ってセッションに保存
@app.route('/authorize')
def authorize():
    user_id = request.args.get('user_id')
    if user_id:
        session['line_user_id'] = user_id
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES
    )
    flow.redirect_uri = url_for('oauth2callback', _external=True)
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)

# /oauth2callbackでuser_idとトークンをuser_tokens.jsonに保存
@app.route('/oauth2callback')
def oauth2callback():
    state = session['state']
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state
    )
    flow.redirect_uri = url_for('oauth2callback', _external=True)
    authorization_response = request.url
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    line_user_id = session.get('line_user_id')
    # トークンをファイルに保存（本番はDB推奨）
    if line_user_id:
        try:
            with open('user_tokens.json', 'r') as f:
                tokens = json.load(f)
        except FileNotFoundError:
            tokens = {}
        tokens[line_user_id] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        with open('user_tokens.json', 'w') as f:
            json.dump(tokens, f)
    return 'Google連携が完了しました！このウィンドウを閉じてLINEに戻ってください。'

SCOPES = ['https://www.googleapis.com/auth/calendar']
CLIENT_SECRETS_FILE = "/etc/secrets/client_secret.json"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port) 