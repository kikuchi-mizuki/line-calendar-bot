from flask import Flask, request, abort, session, jsonify, render_template
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import MessagingApi, Configuration, ApiClient, ReplyMessageRequest
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
from message_parser import parse_message
from calendar_operations import CalendarManager
from database import DatabaseManager
from typing import List, Dict
import warnings
import time
from tenacity import retry, stop_after_attempt, wait_exponential
import signal
from contextlib import contextmanager
from werkzeug.middleware.proxy_fix import ProxyFix

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

def format_response_message(result: dict) -> str:
    """
    レスポンスメッセージをフォーマットする
    
    Args:
        result (dict): 操作結果
        
    Returns:
        str: フォーマットされたメッセージ
    """
    try:
        operation_type = result.get('operation_type')
        
        # 予定の追加
        if operation_type == 'add':
            if not result.get('success', True):
                overlapping_events = result.get('overlapping_events', [])
                if overlapping_events:
                    message = "⚠️ 以下の予定と重複しています：\n\n"
                    for event in overlapping_events:
                        message += f"・{event['start']}〜{event['end']} {event['summary']}\n"
                        if event.get('location'):
                            message += f"  📍 {event['location']}\n"
                        if event.get('description'):
                            message += f"  👥 {event['description']}\n"
                        message += "\n"
                    message += "別の時間を指定してくださいね！"
                    return message
                return "予定の追加に失敗しました。もう一度お試しください。"
            
            event = result.get('event', {})
            message = "予定を登録しました！\n\n"
            message += f"🗓 {format_datetime(datetime.fromisoformat(event.get('start', {}).get('dateTime', '')))}\n"
            message += f"📌 {event.get('summary', '予定')}\n"
            if event.get('location'):
                message += f"📍 {event['location']}\n"
            if event.get('description'):
                message += f"👥 {event['description']}\n"
            message += "\n何か変更があれば、また教えてくださいね！"
            return message
            
        # 予定の削除
        elif operation_type == 'delete':
            if not result.get('success', True):
                return "予定の削除に失敗しました。もう一度お試しください。"
            
            event = result.get('event', {})
            if not event:
                return "予定を削除しました。\n\nまた必要になったら、いつでも追加してくださいね！"
            
            start_time = event.get('start', {}).get('dateTime')
            if not start_time:
                return "予定を削除しました。\n\nまた必要になったら、いつでも追加してくださいね！"
                
            message = "以下の予定を削除しました。\n\n"
            message += f"🗓 {format_datetime(datetime.fromisoformat(start_time))}\n"
            message += f"📌 {event.get('summary', '予定')}\n"
            if event.get('location'):
                message += f"📍 {event['location']}\n"
            if event.get('description'):
                message += f"👥 {event['description']}\n"
            message += "\nまた必要になったら、いつでも追加してくださいね！"
            return message
            
        # 予定の確認
        elif operation_type in ['read', 'check']:
            events = result.get('events', [])
            if not events:
                return "予定はありません。\n\n新しい予定を追加してみましょう！"
                
            message = "登録中の予定はこちらです👇\n\n"
            for i, event in enumerate(events, 1):
                start_time = event.get('start', {}).get('dateTime')
                title = event.get('summary', '予定')
                location = event.get('location', '')
                description = event.get('description', '')
                
                message += f"{i}. 🗓 {format_datetime(datetime.fromisoformat(start_time))}\n"
                if location:
                    message += f"   📍 {location}\n"
                message += f"   📌 {title}\n"
                if description:
                    message += f"   👥 {description}\n"
                message += "\n"
                
            message += "他にも確認したい日があれば教えてください！"
            return message
            
        else:
            return "申し訳ありません。\n操作を認識できませんでした。\nもう一度お試しください。"
            
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
        start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')))
        end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')))
        
        # 日本時間に変換
        jst = timezone(timedelta(hours=9))
        start = start.astimezone(jst)
        end = end.astimezone(jst)
        
        # 日付をキーとして使用
        date_key = start.strftime('%Y/%m/%d')
        
        # 曜日を取得
        weekday = ['月', '火', '水', '木', '金', '土', '日'][start.weekday()]
        
        # 予定の詳細情報を整形
        event_details = []
        event_details.append(f"📌 {event.get('summary', '(タイトルなし)')}")
        event_details.append(f"⏰ {start.strftime('%H:%M')}～{end.strftime('%H:%M')}")
        
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

@app.route("/callback", methods=['POST'])
@retry_on_error
def callback():
    """
    LINE Messaging APIからのコールバックを処理する
    """
    start_time = time.time()
    logger.info("コールバック処理開始")
    
    try:
        with timeout(TIMEOUT_SECONDS):
            # リクエストヘッダーから署名を取得
            if 'X-Line-Signature' not in request.headers:
                logger.error("X-Line-Signatureヘッダーが見つかりません")
                return 'OK', 200
            
            signature = request.headers['X-Line-Signature']
            
            # リクエストボディを取得
            body = request.get_data(as_text=True)
            logger.debug(f"リクエストボディ: {body}")
            
            try:
                # 署名を検証
                handler.handle(body, signature)
                logger.info("署名の検証に成功")
            except InvalidSignatureError as e:
                logger.error("署名の検証に失敗しました。")
                logger.error(traceback.format_exc())
                return 'OK', 200
            except Exception as e:
                logger.error(f"コールバック処理中にエラーが発生: {str(e)}")
                logger.error(traceback.format_exc())
                return 'OK', 200
            
            processing_time = time.time() - start_time
            logger.info(f"コールバック処理完了 (処理時間: {processing_time:.2f}秒)")
            return 'OK', 200
            
    except TimeoutError as e:
        logger.error(f"タイムアウトエラー: {str(e)}")
        return 'OK', 200
    except Exception as e:
        logger.error(f"予期せぬエラー: {str(e)}")
        logger.error(traceback.format_exc())
        return 'OK', 200

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
                    start = datetime.combine(start.date(), datetime.min.time()).astimezone(JST)
                    end = datetime.combine(start.date(), datetime.max.time()).astimezone(JST)
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
                    reply_message = format_response_message({
                        'operation_type': 'add',
                        'success': True,
                        'event': add_result.get('event', {})
                    })
                else:
                    # 重複する予定がある場合
                    if add_result.get('overlapping_events'):
                        reply_message = format_response_message({
                            'operation_type': 'add',
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
                reply_message = format_response_message(result)
            except Exception as e:
                logger.error(f"予定の削除中にエラーが発生: {str(e)}")
                reply_message = format_response_message({
                    'operation_type': 'delete',
                    'success': False
                })
                
        # 応答メッセージの送信
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_message)]
            )
        )
        
    except Exception as e:
        logger.error(f"メッセージ処理中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_message)]
            )
        )

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3001))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False) 