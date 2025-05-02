from flask import Flask, request, abort, jsonify
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)
from linebot.v3.exceptions import InvalidSignatureError
import os
import logging
import traceback
from datetime import datetime, timedelta, timezone
import pytz
from message_parser import (
    parse_message,
    extract_title,
    extract_location,
    extract_person
)
from calendar_chat import CalendarChat
from typing import Dict, Tuple, Any, Optional
import spacy
import threading

app = Flask(__name__)

# ロギングの設定をより詳細に
logging.basicConfig(
    level=logging.DEBUG,  # INFOからDEBUGに変更してより詳細なログを取得
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s\n    %(pathname)s:%(lineno)d',
    handlers=[
        logging.StreamHandler()  # 標準出力のみを使用
    ]
)
logger = logging.getLogger(__name__)

# LINE APIの設定
configuration = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# LINE Messaging APIクライアントの初期化
line_bot_api = MessagingApi(ApiClient(configuration))

# カレンダー操作クラスのインスタンス化
calendar_chat = CalendarChat()

# タイムゾーンの設定
JST = pytz.timezone('Asia/Tokyo')

# spaCyモデルの初期化
nlp = spacy.load("ja_core_news_sm")

def format_response_message(operation_type: str, success: bool, data: Dict[str, Any] = None) -> str:
    """
    レスポンスメッセージをフォーマットする
    
    Args:
        operation_type (str): 操作タイプ
        success (bool): 成功したかどうか
        data (Dict[str, Any], optional): レスポンスデータ
        
    Returns:
        str: フォーマットされたメッセージ
    """
    if not data:
        return "申し訳ありません。エラーが発生しました。"

    if not success:
        return data.get('message', 'エラーが発生しました。')

    if operation_type == 'read':
        events = data.get('events', [])
        if not events:
            return "📅 指定された期間に予定はありません。"

        response = "📅 予定一覧:\n\n"
        current_date = None

        for event in events:
            start_time = event['start_time']
            end_time = event['end_time']
            
            # 日付が変わったら日付を表示
            event_date = start_time.date()
            if current_date != event_date:
                current_date = event_date
                response += f"■ {current_date.strftime('%Y年%m月%d日')}（{['月', '火', '水', '木', '金', '土', '日'][current_date.weekday()]}）\n"

            # イベントの詳細を追加
            response += f"• {event['title']}\n"
            response += f"  ⏰ {start_time.strftime('%H:%M')} 〜 {end_time.strftime('%H:%M')}\n"
            
            if event.get('location'):
                response += f"  📍 {event['location']}\n"
            if event.get('description'):
                response += f"  📝 {event['description']}\n"
            
            response += "\n"

        return response.strip()

    elif operation_type == 'add':
        if data.get('event'):
            event = data['event']
            response = "✅ 予定を追加しました！\n\n"
            response += f"📅 タイトル: {event.get('summary', '予定なし')}\n"
            
            start_time = event.get('start', {}).get('dateTime')
            end_time = event.get('end', {}).get('dateTime')
            
            if start_time:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00')).astimezone(JST)
                response += f"⏰ 開始: {start_dt.strftime('%Y年%m月%d日 %H:%M')}\n"
            if end_time:
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00')).astimezone(JST)
                response += f"⌛️ 終了: {end_dt.strftime('%Y年%m月%d日 %H:%M')}\n"
            
            if event.get('location'):
                response += f"📍 場所: {event['location']}\n"
                
            return response.strip()
        return "✅ 予定を追加しました！"

    elif operation_type == 'delete':
        return "🗑️ 予定を削除しました！"

    elif operation_type == 'update':
        return "📝 予定を更新しました！"

    return data.get('message', 'エラーが発生しました。')

def try_delete_event(start_time: datetime, end_time: datetime, title: str = None) -> bool:
    """
    予定を削除する
    
    Args:
        start_time (datetime): 予定の開始時刻
        end_time (datetime): 予定の終了時刻
        title (str, optional): 予定のタイトル（削除時は使用しない）
        
    Returns:
        bool: 削除に成功したかどうか
    """
    try:
        # タイムゾーン情報を確実に設定
        if start_time.tzinfo is None:
            start_time = JST.localize(start_time)
        if end_time.tzinfo is None:
            end_time = JST.localize(end_time)
        
        # 予定を削除（タイトルは無視して日時のみで検索）
        success = calendar_chat.delete_event(start_time=start_time, end_time=end_time)
        
        if success:
            logger.info(f"予定を削除しました")
            return True
        else:
            logger.error(f"予定の削除に失敗しました")
            return False
            
    except Exception as e:
        logger.error(f"予定の削除中にエラーが発生: {str(e)}")
        return False

def try_add_event(start_time: datetime, end_time: datetime, title: Optional[str] = None,
                 location: Optional[str] = None, person: Optional[str] = None,
                 message: Optional[str] = None) -> Dict[str, Any]:
    """
    イベントの追加を試みる
    """
    try:
        logger.debug(f"""イベント追加の試行:
            開始時刻: {start_time}
            終了時刻: {end_time}
            タイトル: {title}
            場所: {location}
            人物: {person}
            メッセージ: {message}
        """)
        
        # 必須パラメータのチェック
        if not start_time or not end_time:
            logger.error("開始時刻または終了時刻が指定されていません")
            return {
                'success': False,
                'message': '開始時間と終了時間は必須です。'
            }
            
        # タイトルが指定されていない場合、メッセージから抽出を試みる
        if not title and message:
            title = extract_title(message)
            logger.debug(f"メッセージからタイトルを抽出: {title}")
            if not title:
                title = "予定"
                logger.debug("デフォルトのタイトルを使用: 予定")
                
        # 場所が指定されていない場合、メッセージから抽出を試みる
        if not location and message:
            location = extract_location(message)
            logger.debug(f"メッセージから場所を抽出: {location}")
            
        # 人物が指定されていない場合、メッセージから抽出を試みる
        if not person and message:
            person = extract_person(message)
            logger.debug(f"メッセージから人物を抽出: {person}")
            
        # 重複チェック
        existing_events = calendar_chat.get_events(start_time, end_time)
        if existing_events:
            logger.debug(f"既存のイベントを検出: {len(existing_events)}件")
            # イベントの重複をチェック
            overlapping_events = []
            for event in existing_events:
                event_start = event['start'].get('dateTime')
                event_end = event['end'].get('dateTime')
                
                if event_start and event_end:
                    event_start = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                    event_end = datetime.fromisoformat(event_end.replace('Z', '+00:00'))
                    
                    # タイムゾーンを考慮
                    event_start = event_start.astimezone(JST)
                    event_end = event_end.astimezone(JST)
                    
                    # 重複チェック
                    if (event_start < end_time and event_end > start_time):
                        overlap_info = {
                            'summary': event.get('summary', '予定なし'),
                            'start': event_start.strftime('%Y-%m-%d %H:%M'),
                            'end': event_end.strftime('%Y-%m-%d %H:%M'),
                            'location': event.get('location', ''),
                            'description': event.get('description', '')
                        }
                        logger.debug(f"重複するイベントを検出: {overlap_info}")
                        overlapping_events.append(overlap_info)
            
            if overlapping_events:
                logger.warning(f"重複する予定が{len(overlapping_events)}件見つかりました")
                return {
                    'success': False,
                    'message': '指定された時間帯に既に予定が存在します。',
                    'existing_events': overlapping_events
                }
            
        # イベントの追加
        logger.debug("イベントを追加します")
        event = calendar_chat.add_event(
            start_time=start_time,
            end_time=end_time,
            title=title,
            location=location,
            person=person
        )
        
        if event:
            logger.info(f"イベントが正常に追加されました: {event.get('summary', '予定なし')}")
            return {
                'success': True,
                'message': '予定を追加しました。',
                'event': event
            }
        else:
            logger.error("イベントの追加に失敗しました")
            return {
                'success': False,
                'message': '予定の追加に失敗しました。'
            }
            
    except Exception as e:
        logger.error("予定の追加中に予期せぬエラーが発生:")
        logger.error(f"エラータイプ: {type(e).__name__}")
        logger.error(f"エラーメッセージ: {str(e)}")
        logger.error("スタックトレース:")
        logger.error(traceback.format_exc())
        return {
            'success': False,
            'message': f'予定の追加中にエラーが発生しました: {str(e)}'
        }

def try_read_event(parsed_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    予定を読み取る
    
    Args:
        parsed_data (Dict[str, Any]): パースされたデータ
        
    Returns:
        Tuple[bool, Dict[str, Any]]: (成功したかどうか, 結果を含む辞書)
    """
    try:
        # 現在の日付を取得
        now = datetime.now(JST)
        start_time = parsed_data.get('start_time')
        end_time = parsed_data.get('end_time')
        
        # start_timeがNoneの場合、今日の0時を設定
        if start_time is None:
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # end_timeがNoneの場合、今日の23:59:59を設定
        if end_time is None:
            end_time = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # タイムゾーン情報を確実に設定
        if start_time.tzinfo is None:
            start_time = JST.localize(start_time)
        if end_time.tzinfo is None:
            end_time = JST.localize(end_time)
            
        # 予定を取得
        events = calendar_chat.get_events(time_min=start_time, time_max=end_time)
        
        if not events:
            return True, {
                'success': True,
                'message': '指定された期間に予定はありません。',
                'events': []
            }
            
        # イベントを整形
        formatted_events = []
        for event in events:
            event_start = event['start'].get('dateTime')
            event_end = event['end'].get('dateTime')
            
            if event_start and event_end:
                event_start = datetime.fromisoformat(event_start.replace('Z', '+00:00')).astimezone(JST)
                event_end = datetime.fromisoformat(event_end.replace('Z', '+00:00')).astimezone(JST)
                
                formatted_events.append({
                    'title': event.get('summary', '予定なし'),
                    'start_time': event_start,
                    'end_time': event_end,
                    'location': event.get('location', ''),
                    'description': event.get('description', '')
                })
        
        return True, {
            'success': True,
            'message': '予定を取得しました。',
            'events': formatted_events
        }
        
    except Exception as e:
        logger.error(f"予定の取得中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return False, {
            'success': False,
            'message': '予定の取得中にエラーが発生しました。',
            'events': []
        }

def try_update_event(message: str) -> str:
    """
    イベントの更新を試みる
    
    Args:
        message (str): ユーザーからのメッセージ
        
    Returns:
        str: 応答メッセージ
    """
    try:
        # メッセージを解析
        parsed_info = parse_message(message)
        if not parsed_info or parsed_info.get('operation_type') != 'update':
            return "申し訳ありません。イベントの更新に必要な情報を取得できませんでした。"
        
        start_time = parsed_info.get('start_time')
        end_time = parsed_info.get('end_time')
        new_start_time = parsed_info.get('new_start_time')
        new_duration = parsed_info.get('new_duration')
        
        if not start_time or not end_time or (not new_start_time and not new_duration):
            return "申し訳ありません。イベントの更新に必要な時間情報を取得できませんでした。"
        
        # 指定された時間帯のイベントを検索
        events = calendar_chat.get_events(time_min=start_time, time_max=end_time)
        if not events:
            return "指定された時間帯にイベントが見つかりませんでした。"
        
        # 最初のイベントを更新
        event = events[0]
        event_id = event['id']
        
        # 新しい終了時刻を計算
        if new_start_time:
            # 元のイベントの時間の長さを維持
            original_duration = end_time - start_time
            new_end_time = new_start_time + original_duration
            update_start_time = new_start_time
        elif new_duration:
            # 開始時刻は維持し、新しい時間の長さを適用
            update_start_time = start_time
            new_end_time = start_time + new_duration
            
        updated_event = calendar_chat.update_event(
            event_id=event_id,
            start_time=update_start_time,
            end_time=new_end_time,
            title=event.get('summary'),
            location=event.get('location')
        )
        
        if not updated_event:
            return "イベントの更新に失敗しました。"
            
        # 成功メッセージの生成
        if new_start_time:
            return f"予定の開始時刻を{new_start_time.strftime('%H:%M')}に更新しました。"
        elif new_duration:
            duration_minutes = int(new_duration.total_seconds() / 60)
            if duration_minutes >= 60:
                hours = duration_minutes // 60
                minutes = duration_minutes % 60
                if minutes == 0:
                    return f"予定の時間の長さを{hours}時間に更新しました。"
                else:
                    return f"予定の時間の長さを{hours}時間{minutes}分に更新しました。"
            else:
                return f"予定の時間の長さを{duration_minutes}分に更新しました。"
            
    except Exception as e:
        logger.error(f"イベントの更新中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return "予定の更新中にエラーが発生しました。"

def handle_calendar_operation(operation_type: str, parsed_data: dict) -> Tuple[bool, Dict[str, Any]]:
    """
    カレンダー操作を実行する
    
    Args:
        operation_type (str): 操作タイプ
        parsed_data (dict): 解析されたデータ
        
    Returns:
        Tuple[bool, Dict[str, Any]]: 成功したかどうかと結果データ
    """
    try:
        if operation_type == 'add':
            result = try_add_event(
                start_time=parsed_data['start_time'],
                end_time=parsed_data['end_time'],
                title=parsed_data.get('title'),
                location=parsed_data.get('location'),
                person=parsed_data.get('person'),
                message=parsed_data.get('message')
            )
            return result['success'], result
            
        elif operation_type == 'delete':
            success = try_delete_event(
                start_time=parsed_data['start_time'],
                end_time=parsed_data['end_time']
            )
            return success, {'success': success, 'message': '予定を削除しました' if success else '予定の削除に失敗しました'}
            
        elif operation_type == 'update':
            response = try_update_event(parsed_data['message'])
            return True, {'success': True, 'message': response}
            
        elif operation_type == 'read':
            success, result = try_read_event(parsed_data)
            return success, result
            
        else:
            return False, {'message': '不明な操作タイプです'}
            
    except Exception as e:
        logger.error(f"カレンダー操作中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return False, {'message': f'カレンダー操作中にエラーが発生しました: {str(e)}'}

def process_message_async(event):
    """
    メッセージを非同期で処理する
    """
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try:
            # 受信メッセージのログ
            logger.debug(f"受信メッセージ: {event.message.text}")
            
            # メッセージの解析
            parsed_data = parse_message(event.message.text)
            logger.debug(f"解析結果: {parsed_data}")
            
            if not parsed_data:
                logger.error("メッセージの解析に失敗しました")
                raise ValueError("メッセージの解析に失敗しました")

            # カレンダー操作の処理
            success, result = handle_calendar_operation(parsed_data.get('operation_type', 'read'), parsed_data)
            logger.debug(f"カレンダー操作結果: success={success}, result={result}")
            
            # レスポンスメッセージの作成
            response_message = format_response_message(
                parsed_data.get('operation_type', 'read'),
                success,
                result
            )
            logger.debug(f"レスポンスメッセージ: {response_message}")
            
            # メッセージの送信
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response_message)]
                )
            )
            
        except Exception as e:
            logger.error("エラーの詳細情報:")
            logger.error(f"エラータイプ: {type(e).__name__}")
            logger.error(f"エラーメッセージ: {str(e)}")
            logger.error("スタックトレース:")
            logger.error(traceback.format_exc())
            
            try:
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="申し訳ありません。エラーが発生しました。\nエラー内容: " + str(e))]
                    )
                )
            except Exception as reply_error:
                logger.error(f"エラーメッセージの送信にも失敗しました: {str(reply_error)}")

@app.route("/callback", methods=['POST'])
def callback():
    # リクエストヘッダーからX-Line-Signatureを取得
    signature = request.headers['X-Line-Signature']

    # リクエストボディを取得
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    # 非同期でメッセージを処理
    thread = threading.Thread(target=process_message_async, args=(event,))
    thread.start()

if __name__ == "__main__":
    logger.info("アプリケーションを起動します")
    app.run(port=5051) 