import spacy
import re
from datetime import datetime, timedelta, timezone, date, time
import logging
import calendar
from typing import Optional, Dict, Any, Tuple, List
import dateparser
from dateparser.conf import Settings
import traceback
import pytz
import jaconv

logger = logging.getLogger(__name__)

# spaCyモデルの読み込み
try:
    nlp = spacy.load("ja_core_news_sm")
except OSError:
    logger.info("Downloading spaCy model...")
    spacy.cli.download("ja_core_news_sm")
    nlp = spacy.load("ja_core_news_sm")

# dateparserの設定
settings = Settings()
settings.PREFER_DATES_FROM = 'future'
settings.TIMEZONE = 'Asia/Tokyo'
settings.RETURN_AS_TIMEZONE_AWARE = True
settings.RELATIVE_BASE = datetime.now()
settings.LANGUAGES = ['ja']

# 日本語の助詞とその役割のマッピングを拡充
PARTICLE_ROLES = {
    'の': ['possession', 'modification', 'topic', 'nominalization', 'apposition'],
    'と': ['with', 'and', 'comparison', 'quotation', 'conjunction'],
    'は': ['topic', 'contrast', 'emphasis', 'focus'],
    'を': ['object', 'target', 'passive', 'direction'],
    'に': ['target', 'time', 'location', 'purpose', 'cause', 'passive', 'agent'],
    'で': ['location', 'means', 'time_range', 'scope', 'cause', 'state', 'limit'],
    'から': ['start', 'source', 'reason', 'material', 'origin', 'basis'],
    'まで': ['end', 'destination', 'limit', 'extent', 'range'],
    'へ': ['direction', 'target', 'purpose', 'destination'],
    'が': ['subject', 'object', 'desire', 'ability', 'focus', 'emphasis'],
    'も': ['also', 'even', 'emphasis', 'addition', 'inclusion'],
    'や': ['and', 'example', 'listing', 'selection'],
    'か': ['question', 'choice', 'uncertainty', 'doubt'],
    'ね': ['confirmation', 'emphasis', 'agreement', 'appeal'],
    'よ': ['emphasis', 'attention', 'assertion', 'notification'],
    'な': ['emphasis', 'request', 'prohibition', 'emotion'],
    'わ': ['emphasis', 'feminine', 'realization', 'emotion'],
    'ぞ': ['emphasis', 'masculine', 'assertion', 'warning'],
    'ぜ': ['emphasis', 'masculine', 'invitation', 'encouragement'],
    'だ': ['assertion', 'declaration', 'state'],
    'です': ['polite_assertion', 'declaration', 'state'],
    'ます': ['polite_verb', 'declaration', 'state'],
    'けど': ['contrast', 'concession', 'background'],
    'から': ['reason', 'cause', 'basis', 'start'],
    'ので': ['reason', 'cause', 'basis'],
    'のに': ['contrast', 'expectation', 'purpose'],
    'ば': ['condition', 'hypothesis', 'assumption'],
    'たら': ['condition', 'hypothesis', 'assumption'],
    'なら': ['condition', 'hypothesis', 'assumption'],
    'て': ['connection', 'sequence', 'cause', 'state'],
    'で': ['connection', 'sequence', 'cause', 'state'],
}

# 日本語の日時表現を英語に変換するマッピング
JP_TO_EN_MAPPING = {
    '今日': 'today',
    '明日': 'tomorrow',
    '明後日': 'day after tomorrow',
    '昨日': 'yesterday',
    '一昨日': 'day before yesterday',
    '来週': 'next week',
    '先週': 'last week',
    '今週': 'this week',
    '再来週': 'week after next',
    '月曜': 'monday',
    '火曜': 'tuesday',
    '水曜': 'wednesday',
    '木曜': 'thursday',
    '金曜': 'friday',
    '土曜': 'saturday',
    '日曜': 'sunday',
    '月曜日': 'monday',
    '火曜日': 'tuesday',
    '水曜日': 'wednesday',
    '木曜日': 'thursday',
    '金曜日': 'friday',
    '土曜日': 'saturday',
    '日曜日': 'sunday',
    '今月': 'this month',
    '来月': 'next month',
    '先月': 'last month',
    '今年': 'this year',
    '来年': 'next year',
    '去年': 'last year',
    '一昨年': 'year before last',
}

# 予定追加のキーワード（より自然な表現に対応）
ADD_KEYWORDS = [
    "追加", "登録", "入れる", "予定にする", "作る", "お願い", "入れと", "入れて", 
    "スケジュールに入れる", "予定に入れる", "予定に追加", "予定に登録",
    "予定を入れる", "予定を作る", "予定を登録", "予定を設定",
    "予定を立てる", "予定を組む", "予定を決める", "予定を設定する",
    "予定を入れて", "予定を作って", "予定を登録して", "予定を設定して",
    "予定を入れてください", "予定を作ってください", "予定を登録してください",
    "予定を設定してください", "予定を入れておいて", "予定を作っておいて",
    "予定を登録しておいて", "予定を設定しておいて",
    "予定を入れてほしい", "予定を作ってほしい", "予定を登録してほしい",
    "予定を設定してほしい", "予定を入れてください", "予定を作ってください",
    "予定を登録してください", "予定を設定してください",
    # より自然な表現
    "入れて", "入れてください", "入れてほしい", "入れてお願い",
    "作って", "作ってください", "作ってほしい", "作ってお願い",
    "登録して", "登録してください", "登録してほしい", "登録してお願い",
    "設定して", "設定してください", "設定してほしい", "設定してお願い",
    "立てて", "立ててください", "立ててほしい", "立ててお願い",
    "組んで", "組んでください", "組んでほしい", "組んでお願い",
    "決めて", "決めてください", "決めてほしい", "決めてお願い",
    # 短い表現
    "追加", "登録", "入れる", "作る", "設定", "立てる", "組む", "決める",
    # より自然な短い表現
    "入れて", "作って", "登録して", "設定して", "立てて", "組んで", "決めて",
    # 追加の自然な表現
    "を追加", "を登録", "を入れて", "を作って",
    "追加して", "追加してください", "追加してほしい", "追加してお願い",
    "予定追加", "予定登録", "予定作成", "予定設定",
    "打ち合わせ追加", "打ち合わせ登録", "打ち合わせ設定",
    "会議追加", "会議登録", "会議設定",
    "ミーティング追加", "ミーティング登録", "ミーティング設定",
]

# 予定削除のキーワード（より自然な表現に対応）
DELETE_KEYWORDS = [
    "削除", "消す", "キャンセル", "取り消す", "なくす", "いらない", "決しておいて",
    "予定を消す", "予定を取り消す", "予定をキャンセル", "予定を削除して",
    "予定を削除", "予定を取りやめる", "予定を中止", "予定を無効にする",
    "予定を破棄", "予定を無効化", "予定をキャンセルする",
    "予定を消してください", "予定を取り消してください", "予定をキャンセルしてください",
    "予定を削除してください", "予定を取りやめてください", "予定を中止してください",
    "予定を無効にしてください", "予定を破棄してください", "予定を無効化してください",
    "予定をキャンセルしてください", "予定を消して", "予定を取り消して",
    "予定をキャンセルして", "予定を削除して", "予定を取りやめて",
    "予定を中止して", "予定を無効にして", "予定を破棄して",
    "予定を無効化して", "予定をキャンセルして",
    "予定を消してほしい", "予定を取り消してほしい", "予定をキャンセルしてほしい",
    "予定を削除してほしい", "予定を取りやめてほしい", "予定を中止してほしい",
    "予定を無効にしてほしい", "予定を破棄してほしい", "予定を無効化してほしい",
    "予定をキャンセルしてほしい", "予定を消してお願い", "予定を取り消してお願い",
    "予定をキャンセルしてお願い", "予定を削除してお願い", "予定を取りやめてお願い",
    "予定を中止してお願い", "予定を無効にしてお願い", "予定を破棄してお願い",
    "予定を無効化してお願い", "予定をキャンセルしてお願い",
    # 追加: 命令形・依頼形バリエーション
    "削除して", "削除してください", "削除してお願い", "削除してほしい",
    "消して", "消してください", "消してお願い", "消してほしい",
    "キャンセルして", "キャンセルしてください", "キャンセルしてお願い", "キャンセルしてほしい",
    "取り消して", "取り消してください", "取り消してお願い", "取り消してほしい",
    "中止して", "中止してください", "中止してお願い", "中止してほしい",
    "破棄して", "破棄してください", "破棄してお願い", "破棄してほしい",
    "無効にして", "無効にしてください", "無効にしてお願い", "無効にしてほしい",
    "無効化して", "無効化してください", "無効化してお願い", "無効化してほしい",
    # より自然な表現
    "やめとく", "やめときます", "やめときましょう", "やめときましょうか",
    "やめとこう", "やめときましょう", "やめときましょうか",
    "やめときます", "やめときましょう", "やめときましょうか",
    "やめときましょう", "やめときましょうか",
    "やめときましょうか", "やめときましょうか？",
    "やめときます", "やめときましょう", "やめときましょうか",
    "やめときましょう", "やめときましょうか",
    "やめときましょうか", "やめときましょうか？",
    # 短い表現
    "キャンセル", "取り消し", "削除", "消去", "消す", "取り消す",
    "取りやめ", "中止", "無効", "破棄", "無効化",
    # より自然な短い表現
    "やめとく", "やめとこう", "やめときます", "やめときましょう",
    "やめときましょうか", "やめときましょうか？"
]

# 予定変更のキーワード（より自然な表現に対応）
UPDATE_KEYWORDS = [
    "変更", "リスケ", "ずらす", "後ろ倒し", "前倒し", "時間変更", "予定をずらす",
    "予定を後ろ倒し", "予定を前倒し", "予定をリスケジュール",
    "予定を変更", "予定を修正", "予定を調整", "予定を更新",
    "予定を移動", "予定をずらす", "予定を変更する", "予定を修正する",
    "予定を変更してください", "予定を修正してください", "予定を調整してください",
    "予定を更新してください", "予定を移動してください", "予定をずらしてください",
    "予定を変更して", "予定を修正して", "予定を調整して", "予定を更新して",
    "予定を移動して", "予定をずらして", "予定を変更して", "予定を修正して",
    "予定を変更してほしい", "予定を修正してほしい", "予定を調整してほしい",
    "予定を更新してほしい", "予定を移動してほしい", "予定をずらしてほしい",
    "予定を変更してお願い", "予定を修正してお願い", "予定を調整してお願い",
    "予定を更新してお願い", "予定を移動してお願い", "予定をずらしてお願い",
    "予定を変更してください", "予定を修正してください", "予定を調整してください",
    "予定を更新してください", "予定を移動してください", "予定をずらしてください"
]

# 予定確認のキーワード（より自然な表現に対応）
READ_KEYWORDS = [
    "予定を教えて", "予定を確認", "予定は？", "予定は?",
    "スケジュールを教えて", "スケジュールを確認",
    "何がある", "何が入ってる", "空いてる",
    "予定ある", "予定入ってる", "予定は何",
    "予定を見せて", "予定を表示", "予定一覧",
    "スケジュール一覧", "スケジュールを見せて",
    "予定を見る", "スケジュールを見る",
    "予定確認", "スケジュール確認",
    "予定は", "スケジュールは",
    "予定を", "スケジュールを",
    "予定", "スケジュール"
]

# 時間表現のパターンを拡充
TIME_PATTERNS = {
    'basic_time': r'(?P<hour>\d{1,2})時(?:(?P<minute>\d{1,2})分)?',
    'am_pm_time': r'(?P<period>午前|午後|朝|夜|夕方|深夜)(?P<hour>\d{1,2})時(?:(?P<minute>\d{1,2})分)?',
    'colon_time': r'(?P<hour>\d{1,2}):(?P<minute>\d{2})',
    'relative_time': r'(?P<relative>今|この|次の|前の)(?P<unit>時間|時間帯|時間枠)',
    'duration': r'(?P<duration>\d{1,2})時間(?:(?P<minutes>\d{1,2})分)?',
    'time_range': r'(?P<start_hour>\d{1,2})時(?:(?P<start_minute>\d{1,2})分)?(?:から|〜)(?P<end_hour>\d{1,2})時(?:(?P<end_minute>\d{1,2})分)?',
    'time_range_colon': r'(?P<start_hour>\d{1,2}):(?P<start_minute>\d{2})(?:から|〜)(?P<end_hour>\d{1,2}):(?P<end_minute>\d{2})',
    'time_range_am_pm': r'(?P<start_period>午前|午後|朝|夜|夕方|深夜)(?P<start_hour>\d{1,2})時(?:(?P<start_minute>\d{1,2})分)?(?:から|〜)(?P<end_period>午前|午後|朝|夜|夕方|深夜)?(?P<end_hour>\d{1,2})時(?:(?P<end_minute>\d{1,2})分)?',
}

# 日付表現のパターンを拡充
DATE_PATTERNS = {
    'absolute_date': r'(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日',
    'relative_date': r'(?P<relative>今日|明日|明後日|昨日|一昨日|今週|来週|再来週|先週|今月|来月|先月|今年|来年|去年|一昨年)',
    'weekday': r'(?P<weekday>月|火|水|木|金|土|日)曜日?',
    'month_day': r'(?P<month>\d{1,2})月(?P<day>\d{1,2})日',
    'slash_date': r'(?P<month>\d{1,2})/(?P<day>\d{1,2})',
}

# タイムゾーンの設定
JST = pytz.timezone('Asia/Tokyo')

# 操作タイプの定義
OPERATION_TYPES = {
    'add': ['追加', '入れる', '入れて', '予定', '予約', 'スケジュール'],
    'delete': ['削除', '消す', '消して', '取り消し', 'キャンセル'],
    'update': ['変更', '修正', '更新', '変更して', '修正して'],
    'read': ['確認', '見る', '見せて', '教えて', '予定は', 'スケジュールは']
}

# 相対的な日付表現の定義
RELATIVE_DATES = {
    '今日': 0,
    '明日': 1,
    '明後日': 2,
    '昨日': -1,
    '一昨日': -2,
    '今週': 0,
    '来週': 7,
    '再来週': 14,
    '今月': 0,
    '来月': 30,
    '再来月': 60
}

# 曜日の定義
WEEKDAYS = {
    '月曜日': 0, '月曜': 0, '月': 0,
    '火曜日': 1, '火曜': 1, '火': 1,
    '水曜日': 2, '水曜': 2, '水': 2,
    '木曜日': 3, '木曜': 3, '木': 3,
    '金曜日': 4, '金曜': 4, '金': 4,
    '土曜日': 5, '土曜': 5, '土': 5,
    '日曜日': 6, '日曜': 6, '日': 6
}

def normalize_text(text: str) -> str:
    """
    テキストを正規化する
    
    Args:
        text (str): 入力テキスト
        
    Returns:
        str: 正規化されたテキスト
    """
    # 全角数字を半角に変換
    text = jaconv.z2h(text, ascii=True, digit=True)
    # 全角スペースを半角に変換
    text = text.replace('　', ' ')
    # 小文字を大文字に変換
    text = text.upper()
    return text

def parse_message(message: str) -> Dict[str, Any]:
    """
    メッセージを解析して予定の操作タイプと必要な情報を抽出する
    
    Args:
        message (str): ユーザーからのメッセージ
        
    Returns:
        Dict[str, Any]: 解析結果
    """
    # 操作タイプの判定
    operation_type = None
    
    # 更新操作の判定（より具体的なキーワードを優先）
    for keyword in UPDATE_KEYWORDS:
        if keyword in message and ('変更' in message or 'に変更' in message):
            operation_type = 'update'
            break
    
    # 削除操作の判定
    if not operation_type:
        for keyword in DELETE_KEYWORDS:
            if keyword in message:
                operation_type = 'delete'
                break
    
    # 追加操作の判定
    if not operation_type:
        for keyword in ADD_KEYWORDS:
            if keyword in message:
                operation_type = 'add'
                break
    
    # 予定確認の判定（最も一般的なキーワードなので最後にチェック）
    if not operation_type:
        for keyword in READ_KEYWORDS:
            # 更新や変更を示す文字列が含まれていない場合のみ確認操作と判定
            if keyword in message and not any(update_word in message for update_word in ['変更', 'に変更', 'リスケ', 'ずらす']):
                operation_type = 'read'
                break
    
    # 操作タイプが不明な場合、日時情報が含まれていれば追加操作と判断
    if not operation_type:
        datetime_info = extract_datetime_from_message(message)
        if datetime_info:
            operation_type = 'add'
    
    if not operation_type:
        return {'error': '予定の操作タイプが不明です'}
    
    # 日時情報の抽出
    datetime_info = extract_datetime_from_message(message, is_update=(operation_type == 'update'))
    if not datetime_info:
        return {'error': '日時情報が見つかりませんでした'}
    
    # タイトル、場所、人物の抽出（read操作の場合は不要）
    title = None
    location = None
    person = None
    if operation_type != 'read':
        title = extract_title(message)
        location = extract_location(message)
        person = extract_person(message)
    
    result = {
        'operation_type': operation_type,
        'start_time': datetime_info['start_time'],
        'end_time': datetime_info['end_time'],
        'title': title,
        'location': location,
        'person': person,
        'message': message
    }
    
    # 更新操作の場合の追加情報
    if operation_type == 'update':
        if 'new_start_time' in datetime_info:
            result['new_start_time'] = datetime_info['new_start_time']
        if 'new_duration' in datetime_info:
            result['new_duration'] = datetime_info['new_duration']
    
    return result

def extract_title_from_message(message: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    メッセージからタイトル、場所、人物を抽出する
    
    Args:
        message (str): メッセージ
        
    Returns:
        Tuple[str, Optional[str], Optional[str]]: (タイトル, 場所, 人物)
    """
    try:
        # メッセージを正規化
        message = normalize_text(message)
        
        # spaCyで解析
        doc = nlp(message)
        
        # 場所を示す助詞
        location_particles = ['で', 'に', 'へ']
        # 人物を示す助詞
        person_particles = ['と', 'とともに']
        
        # 場所と人物を抽出
        location = None
        person = None
        
        for i, token in enumerate(doc):
            # 場所の抽出
            if token.dep_ in ['nmod'] and token.text in location_particles:
                for child in token.children:
                    if child.pos_ in ['NOUN', 'PROPN']:
                        location = child.text
                        break
            
            # 人物の抽出
            if token.dep_ in ['nmod'] and token.text in person_particles:
                for child in token.children:
                    if child.pos_ in ['NOUN', 'PROPN']:
                        person = child.text
                        break
        
        # タイトルの抽出
        title = None
        
        # 1. 動詞を含む文節を探す
        for token in doc:
            if token.pos_ == 'VERB':
                # 動詞の文節を取得
                for child in token.children:
                    if child.dep_ in ['nsubj', 'obj'] and child.pos_ in ['NOUN', 'PROPN']:
                        if child.text != location and child.text != person:
                            title = child.text
                            break
                if title:
                    break
        
        # 2. 名詞を含む文節を探す
        if not title:
            for token in doc:
                if token.pos_ in ['NOUN', 'PROPN']:
                    if token.text != location and token.text != person:
                        title = token.text
                        break
        
        # 3. タイトルが見つからない場合は「予定」を使用
        if not title:
            title = "予定"
        
        logger.info(f"抽出結果 - タイトル: {title}, 場所: {location}, 人物: {person}")
        
        return title, location, person
        
    except Exception as e:
        logger.error(f"タイトル抽出中にエラーが発生しました: {str(e)}")
        logger.error(traceback.format_exc())
        return "予定", None, None

def extract_duration_from_message(message: str) -> Optional[int]:
    """
    メッセージから予定の長さ（分）を抽出する
    
    Args:
        message (str): ユーザーからのメッセージ
        
    Returns:
        Optional[int]: 予定の長さ（分）。見つからない場合はNone
    """
    # 時間を表す表現を検索
    hour_patterns = [
        r'(\d+)時間',
        r'(\d+)時間半',
        r'(\d+)時間に',  # 2時間に
        r'(\d+)時間で',  # 2時間で
        r'(\d+)時間分',  # 2時間分
        r'(\d+)時間の',  # 2時間の
    ]
    minute_patterns = [
        r'(\d+)分',
        r'(\d+)分に',  # 30分に
        r'(\d+)分で',  # 30分で
        r'(\d+)分の',  # 30分の
    ]
    
    # 時間を分に変換
    for pattern in hour_patterns:
        match = re.search(pattern, message)
        if match:
            hours = int(match.group(1))
            if '半' in pattern:
                return hours * 60 + 30
            return hours * 60
    
    # 分を抽出
    for pattern in minute_patterns:
        match = re.search(pattern, message)
        if match:
            return int(match.group(1))
    
    # 数字のみの場合は時間として解釈
    number_match = re.search(r'(\d+)に', message)  # 2に
    if number_match:
        hours = int(number_match.group(1))
        return hours * 60
    
    return None

def extract_datetime_from_message(message: str, is_update: bool = False) -> Optional[Dict[str, Optional[datetime]]]:
    try:
        # 日本時間のタイムゾーンを設定
        JST = pytz.timezone('Asia/Tokyo')
        now = datetime.now(JST)
        
        # 日付パターンの定義
        date_patterns = [
            r'(\d+)月(\d+)日',
            r'(\d+)日',
            r'今日',
            r'明日',
            r'明後日',
            r'来週の?[月火水木金土日]曜日?',
        ]

        # 日付の抽出
        target_date = None
        for pattern in date_patterns:
            match = re.search(pattern, message)
            if match:
                if pattern == r'今日':
                    target_date = now.date()
                elif pattern == r'明日':
                    target_date = (now + timedelta(days=1)).date()
                elif pattern == r'明後日':
                    target_date = (now + timedelta(days=2)).date()
                elif pattern.startswith(r'来週'):
                    weekday_str = re.search(r'[月火水木金土日]', match.group(0)).group(0)
                    target_date = get_next_weekday(weekday_str).date()
                else:
                    if len(match.groups()) == 2:  # 月日が指定されている場合
                        month, day = map(int, match.groups())
                        year = now.year
                        target_date = datetime(year, month, day).date()
                    else:  # 日のみ指定されている場合
                        day = int(match.group(1))
                        target_date = now.replace(day=day).date()
                        if target_date < now.date():
                            target_date = target_date.replace(year=now.year + 1)
                break

        if not target_date:
            target_date = now.date()

        if is_update:
            # 元の時間を抽出するパターンを拡充
            original_time_patterns = [
                r'(\d+)時半?(?:(\d+)分)?(?:から|より|の|を|に|の予定|から始まる)',
                r'(\d+)時半(?:から|より|の|を|に|の予定|から始まる)',
                r'(\d+)時(?:(\d+)分)?(?:から|より|の|を|に|の予定|から始まる)',
            ]
            
            # 新しい時間を抽出するパターンを拡充
            new_time_patterns = [
                r'(?:(\d+)時半?(?:(\d+)分)?(?:から|より|の|を|に))(?:変更|移動|ずらす|する)',
                r'(?:(\d+)時半(?:から|より|の|を|に))(?:変更|移動|ずらす|する)',
                r'(\d+)時(?:(\d+)分)?(?:から|より|の|を|に)(?:変更|移動|ずらす|する)',
                r'(\d+)時(?:(\d+)分)?から(?:に変更|に)',
                r'(\d+)時(?:(\d+)分)?に(?:変更|移動|ずらす|する)',
                r'(\d+)時(?:(\d+)分)?からに変更',  # 新しいパターン
                r'(\d+)時(?:(\d+)分)?に変更して',  # 新しいパターン
                r'(\d+)時(?:(\d+)分)?からに変更して'  # 新しいパターン
            ]

            # 時間の長さを変更するパターン
            duration_patterns = [
                r'(\d+)時間(?:(\d+)分)?に(?:変更|する)',
                r'(\d+)時間に',
                r'(\d+)分に(?:変更|する)',
                r'(\d+)分間に(?:変更|する)',
            ]
            
            # 元の時間を探す
            original_time = None
            for pattern in original_time_patterns:
                match = re.search(pattern, message)
                if match:
                    hour = int(match.group(1))
                    # '半'が含まれている場合は30分として処理
                    if '半' in match.group(0):
                        minute = 30
                    else:
                        minute = int(match.group(2)) if match.group(2) else 0
                    original_time = datetime.combine(target_date, time(hour, minute))
                    original_time = JST.localize(original_time)
                    logger.debug(f"元の時間を抽出: {original_time}")
                    break
                    
            if not original_time:
                logger.error("元の時間の抽出に失敗")
                return None

            # まず時間の長さの変更をチェック
            for pattern in duration_patterns:
                match = re.search(pattern, message)
                if match:
                    if '時間' in pattern:
                        hours = int(match.group(1))
                        minutes = int(match.group(2)) if len(match.groups()) > 1 and match.group(2) else 0
                        new_duration = timedelta(hours=hours, minutes=minutes)
                        logger.debug(f"時間の長さの変更を検出: {new_duration}")
                        return {
                            'start_time': original_time,
                            'end_time': original_time + new_duration,
                            'new_duration': new_duration
                        }
                    else:
                        minutes = int(match.group(1))
                        new_duration = timedelta(minutes=minutes)
                        logger.debug(f"時間の長さの変更を検出: {new_duration}")
                        return {
                            'start_time': original_time,
                            'end_time': original_time + new_duration,
                            'new_duration': new_duration
                        }
                    
            # 開始時刻の変更をチェック
            for pattern in new_time_patterns:
                match = re.search(pattern, message)
                if match:
                    hour = int(match.group(1))
                    # '半'が含まれている場合は30分として処理
                    if '半' in match.group(0):
                        minute = 30
                    else:
                        minute = int(match.group(2)) if match.group(2) else 0
                    new_time = datetime.combine(target_date, time(hour, minute))
                    new_time = JST.localize(new_time)
                    logger.debug(f"新しい時間を抽出: {new_time}")
                    return {
                        'start_time': original_time,
                        'end_time': original_time + timedelta(hours=1),
                        'new_start_time': new_time
                    }
                
            logger.error("新しい時間の抽出に失敗")
            return None

        # 通常の時刻抽出（更新以外の場合）
        time_patterns = [
            (r'(\d+)時(\d+)分から(\d+)時(\d+)分まで', 4),  # HH:MM-HH:MM
            (r'(\d+)時から(\d+)時まで', 2),  # HH-HH
            (r'(\d+)時(\d+)分から', 2),  # HH:MM-
            (r'(\d+)時から', 1),  # HH-
            (r'(\d+)時(\d+)分', 2),  # HH:MM
            (r'(\d+)時', 1),  # HH
        ]

        start_time = None
        end_time = None

        for pattern, group_count in time_patterns:
            match = re.search(pattern, message)
            if match:
                if group_count == 4:  # HH:MM-HH:MM
                    start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
                    start_time = datetime.combine(target_date, time(start_hour, start_minute))
                    end_time = datetime.combine(target_date, time(end_hour, end_minute))
                elif group_count == 2:
                    if 'まで' in pattern:  # HH-HH
                        start_hour, end_hour = map(int, match.groups())
                        start_time = datetime.combine(target_date, time(start_hour, 0))
                        end_time = datetime.combine(target_date, time(end_hour, 0))
                    else:  # HH:MM
                        hour, minute = map(int, match.groups())
                        start_time = datetime.combine(target_date, time(hour, minute))
                        end_time = start_time + timedelta(hours=1)
                elif group_count == 1:  # HH
                    hour = int(match.group(1))
                    start_time = datetime.combine(target_date, time(hour, 0))
                    end_time = start_time + timedelta(hours=1)
                break

        # 時刻が指定されていない場合は、その日の全日を範囲とする
        if not start_time:
            start_time = datetime.combine(target_date, time(0, 0))
            end_time = datetime.combine(target_date, time(23, 59))

        # タイムゾーンを設定
        start_time = JST.localize(start_time)
        end_time = JST.localize(end_time)

        return {'start_time': start_time, 'end_time': end_time}

    except Exception as e:
        logger.error(f"日時の抽出中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def get_next_weekday(weekday_str: str) -> datetime:
    """
    次の指定された曜日の日付を取得する
    
    Args:
        weekday_str (str): 曜日の文字列（月、火、水、木、金、土、日）
        
    Returns:
        datetime: 次の指定された曜日の日付
    """
    weekday_map = {
        "月": 0, "火": 1, "水": 2, "木": 3,
        "金": 4, "土": 5, "日": 6
    }
    
    if weekday_str not in weekday_map:
        raise ValueError(f"無効な曜日: {weekday_str}")
    
    target_weekday = weekday_map[weekday_str]
    now = datetime.now()
    days_ahead = target_weekday - now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return now + timedelta(days=days_ahead)

def get_this_weekday(weekday_str: str) -> datetime:
    """
    今週の指定された曜日の日付を取得する
    
    Args:
        weekday_str (str): 曜日の文字列（月、火、水、木、金、土、日）
        
    Returns:
        datetime: 今週の指定された曜日の日付
    """
    weekday_map = {
        "月": 0, "火": 1, "水": 2, "木": 3,
        "金": 4, "土": 5, "日": 6
    }
    
    if weekday_str not in weekday_map:
        raise ValueError(f"無効な曜日: {weekday_str}")
    
    target_weekday = weekday_map[weekday_str]
    now = datetime.now()
    days_ahead = target_weekday - now.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return now + timedelta(days=days_ahead)

def extract_recurrence_from_message(message: str) -> Optional[Dict[str, Any]]:
    """
    メッセージから繰り返し情報を抽出する
    
    Args:
        message (str): ユーザーからのメッセージ
        
    Returns:
        Optional[Dict[str, Any]]: 繰り返し情報
    """
    # 繰り返しパターン
    recurrence_patterns = [
        # 毎日
        (r"毎日", {"freq": "DAILY"}),
        (r"(\d+)日ごと", {"freq": "DAILY", "interval": lambda m: int(m.group(1))}),
        
        # 毎週
        (r"毎週(\w+)曜日", {"freq": "WEEKLY", "byday": lambda m: get_weekday_code(m.group(1))}),
        (r"(\d+)週間ごと", {"freq": "WEEKLY", "interval": lambda m: int(m.group(1))}),
        
        # 毎月
        (r"毎月(\d+)日", {"freq": "MONTHLY", "bymonthday": lambda m: int(m.group(1))}),
        (r"(\d+)ヶ月ごと", {"freq": "MONTHLY", "interval": lambda m: int(m.group(1))}),
        
        # 毎年
        (r"毎年(\d+)月(\d+)日", {"freq": "YEARLY", "bymonth": lambda m: int(m.group(1)), "bymonthday": lambda m: int(m.group(2))}),
    ]
    
    # 繰り返し回数
    count_patterns = [
        (r"(\d+)回", {"count": lambda m: int(m.group(1))}),
    ]
    
    # 終了日
    until_patterns = [
        (r"(\d{4})年(\d+)月(\d+)日まで", {"until": lambda m: datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))}),
        (r"(\d+)月(\d+)日まで", {"until": lambda m: datetime(datetime.now().year, int(m.group(1)), int(m.group(2)))}),
    ]
    
    # 繰り返し情報を抽出
    recurrence = {}
    
    # 繰り返しパターンをチェック
    for pattern, info in recurrence_patterns:
        match = re.search(pattern, message)
        if match:
            for key, value in info.items():
                if callable(value):
                    recurrence[key] = value(match)
                else:
                    recurrence[key] = value
            break
    
    # 繰り返し回数をチェック
    for pattern, info in count_patterns:
        match = re.search(pattern, message)
        if match:
            for key, value in info.items():
                if callable(value):
                    recurrence[key] = value(match)
                else:
                    recurrence[key] = value
            break
    
    # 終了日をチェック
    for pattern, info in until_patterns:
        match = re.search(pattern, message)
        if match:
            for key, value in info.items():
                if callable(value):
                    recurrence[key] = value(match)
                else:
                    recurrence[key] = value
            break
    
    return recurrence if recurrence else None

def get_weekday_code(weekday_str: str) -> str:
    """
    日本語の曜日をiCalendarの曜日コードに変換する
    
    Args:
        weekday_str (str): 日本語の曜日（月、火、水、木、金、土、日）
        
    Returns:
        str: iCalendarの曜日コード（MO, TU, WE, TH, FR, SA, SU）
    """
    weekday_map = {
        "月": "MO",
        "火": "TU",
        "水": "WE",
        "木": "TH",
        "金": "FR",
        "土": "SA",
        "日": "SU"
    }
    
    return weekday_map.get(weekday_str, "")

def extract_title(message: str) -> Optional[str]:
    """
    メッセージからタイトルを抽出する
    
    Args:
        message (str): 解析するメッセージ
        
    Returns:
        Optional[str]: 抽出されたタイトル、見つからない場合はNone
    """
    doc = nlp(message)
    
    # 動詞を探してタイトルを生成
    for token in doc:
        if token.pos_ == 'VERB':
            return f"{token.text}予定"
            
    return None

def extract_location(message: str) -> Optional[str]:
    """
    メッセージから場所を抽出する
    
    Args:
        message (str): 解析するメッセージ
        
    Returns:
        Optional[str]: 抽出された場所、見つからない場合はNone
    """
    doc = nlp(message)
    
    # 場所を示す可能性のある固有名詞を探す
    for ent in doc.ents:
        if ent.label_ in ['GPE', 'LOC']:
            return ent.text
            
    return None

def extract_person(message: str) -> Optional[str]:
    """
    メッセージから人物を抽出する
    
    Args:
        message (str): 解析するメッセージ
        
    Returns:
        Optional[str]: 抽出された人物、見つからない場合はNone
    """
    doc = nlp(message)
    
    # 人物を示す可能性のある固有名詞を探す
    for ent in doc.ents:
        if ent.label_ == 'PERSON':
            return ent.text
            
    return None 