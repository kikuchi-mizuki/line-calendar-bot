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
from extractors.datetime_extractor import DateTimeExtractor
from extractors.title_extractor import TitleExtractor
from extractors.recurrence_extractor import RecurrenceExtractor
from extractors.person_extractor import PersonExtractor
from constants import (
    ADD_KEYWORDS, DELETE_KEYWORDS, UPDATE_KEYWORDS, READ_KEYWORDS,
    RELATIVE_DATES, WEEKDAYS, TIME_PATTERNS, DATE_PATTERNS
)

logger = logging.getLogger(__name__)

# DateTimeExtractorのインスタンスを作成
datetime_extractor = DateTimeExtractor()
# TitleExtractorのインスタンスを作成
title_extractor = TitleExtractor()
# RecurrenceExtractorのインスタンスを作成
recurrence_extractor = RecurrenceExtractor()

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
    # より自然な表現（追加）
    "予定を入れておいて", "予定を作っておいて", "予定を登録しておいて",
    "予定を設定しておいて", "予定を入れておいてください", "予定を作っておいてください",
    "予定を登録しておいてください", "予定を設定しておいてください",
    "予定を入れておいてほしい", "予定を作っておいてほしい", "予定を登録しておいてほしい",
    "予定を設定しておいてほしい", "予定を入れておいてお願い", "予定を作っておいてお願い",
    "予定を登録しておいてお願い", "予定を設定しておいてお願い",
    # より自然な短い表現（追加）
    "入れておいて", "作っておいて", "登録しておいて", "設定しておいて",
    "入れておいてください", "作っておいてください", "登録しておいてください", "設定しておいてください",
    "入れておいてほしい", "作っておいてほしい", "登録しておいてほしい", "設定しておいてほしい",
    "入れておいてお願い", "作っておいてお願い", "登録しておいてお願い", "設定しておいてお願い",
]

# 予定削除のキーワード（より自然な表現に対応）
DELETE_KEYWORDS = [
    "削除", "消す", "消して", "削除して", "削除してください", "消してください",
    "キャンセル", "キャンセルして", "キャンセルしてください",
    "きゃんせる", "きゃんせるして", "きゃんせるしてください",
    "ｷｬﾝｾﾙ", "ｷｬﾝｾﾙして", "ｷｬﾝｾﾙしてください",
    "予定削除", "予定キャンセル", "予定取り消し",
    "打ち合わせ削除", "打ち合わせキャンセル", "打ち合わせ取り消し",
    "会議削除", "会議キャンセル", "会議取り消し",
    "ミーティング削除", "ミーティングキャンセル", "ミーティング取り消し"
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
    "予定を更新してほしい", "予定を移動してほしい", "予定をずらしてほしい",
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
    "予定", "スケジュール",
    # より自然な表現（追加）
    "予定を教えてください", "予定を確認してください", "予定を教えてほしい", "予定を確認してほしい",
    "予定を教えてお願い", "予定を確認してお願い", "予定を教えておいて", "予定を確認しておいて",
    "予定を教えておいてください", "予定を確認しておいてください", "予定を教えておいてほしい", "予定を確認しておいてほしい",
    "予定を教えておいてお願い", "予定を確認しておいてお願い", "予定を教えておいてください", "予定を確認しておいてください",
    "予定を教えておいてほしい", "予定を確認しておいてほしい", "予定を教えておいてお願い", "予定を確認しておいてお願い",
    # より自然な短い表現（追加）
    "教えて", "確認して", "教えてください", "確認してください",
    "教えてほしい", "確認してほしい", "教えてお願い", "確認してお願い",
    "教えておいて", "確認しておいて", "教えておいてください", "確認しておいてください",
    "教えておいてほしい", "確認しておいてほしい", "教えておいてお願い", "確認しておいてお願い",
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
    # より自然な表現（追加）
    'time_range_with_duration': r'(?P<start_hour>\d{1,2})時(?:(?P<start_minute>\d{1,2})分)?から(?P<duration>\d{1,2})時間(?:(?P<minutes>\d{1,2})分)?',
    'time_range_with_duration_colon': r'(?P<start_hour>\d{1,2}):(?P<start_minute>\d{2})から(?P<duration>\d{1,2})時間(?:(?P<minutes>\d{1,2})分)?',
    'time_range_with_duration_am_pm': r'(?P<period>午前|午後|朝|夜|夕方|深夜)(?P<start_hour>\d{1,2})時(?:(?P<start_minute>\d{1,2})分)?から(?P<duration>\d{1,2})時間(?:(?P<minutes>\d{1,2})分)?',
    'time_range_with_duration_relative': r'(?P<relative>今|この|次の|前の)(?P<unit>時間|時間帯|時間枠)から(?P<duration>\d{1,2})時間(?:(?P<minutes>\d{1,2})分)?',
}

# 日付表現のパターンを拡充
DATE_PATTERNS = {
    'absolute_date': r'(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日',
    'relative_date': r'(?P<relative>今日|明日|明後日|昨日|一昨日|今週|来週|再来週|先週|今月|来月|先月|今年|来年|去年|一昨年)',
    'weekday': r'(?P<weekday>月|火|水|木|金|土|日)曜日?',
    'month_day': r'(?P<month>\d{1,2})月(?P<day>\d{1,2})日',
    'slash_date': r'(?P<month>\d{1,2})/(?P<day>\d{1,2})',
    # より自然な表現（追加）
    'relative_date_with_weekday': r'(?P<relative>今週|来週|再来週|先週)の(?P<weekday>月|火|水|木|金|土|日)曜日?',
    'relative_date_with_month': r'(?P<relative>今月|来月|先月)の(?P<day>\d{1,2})日',
    'relative_date_with_year': r'(?P<relative>今年|来年|去年|一昨年)の(?P<month>\d{1,2})月(?P<day>\d{1,2})日',
    'relative_date_with_weekday_and_time': r'(?P<relative>今週|来週|再来週|先週)の(?P<weekday>月|火|水|木|金|土|日)曜日?の(?P<hour>\d{1,2})時(?:(?P<minute>\d{1,2})分)?',
    'relative_date_with_month_and_time': r'(?P<relative>今月|来月|先月)の(?P<day>\d{1,2})日の(?P<hour>\d{1,2})時(?:(?P<minute>\d{1,2})分)?',
    'relative_date_with_year_and_time': r'(?P<relative>今年|来年|去年|一昨年)の(?P<month>\d{1,2})月(?P<day>\d{1,2})日の(?P<hour>\d{1,2})時(?:(?P<minute>\d{1,2})分)?',
}

# タイムゾーンの設定
JST = timezone(timedelta(hours=9))

def normalize_text(text: str) -> str:
    """
    テキストを正規化する
    """
    # 半角カタカナ→全角カタカナ
    text = jaconv.h2z(text, kana=True)
    # 全角カタカナ→ひらがな
    text = jaconv.kata2hira(text)
    # 全角数字・英字を半角に変換
    text = jaconv.z2h(text, ascii=True, digit=True)
    # 全角スペースを半角に変換
    text = text.replace('　', ' ')
    # 半角カタカナの「キャンセル」をひらがなに変換（複数のパターンに対応）
    text = text.replace('ｷｬﾝｾﾙ', 'きゃんせる')
    text = text.replace('ｷｬﾝｾﾙして', 'きゃんせるして')
    text = text.replace('ｷｬﾝｾﾙしてください', 'きゃんせるしてください')
    
    # 相対日付表現の正規化
    text = text.replace('あした', '明日')
    text = text.replace('あす', '明日')
    text = text.replace('みょうにち', '明日')
    text = text.replace('あさって', '明後日')
    text = text.replace('みょうごにち', '明後日')
    text = text.replace('きのう', '昨日')
    text = text.replace('さくじつ', '昨日')
    text = text.replace('おととい', '一昨日')
    text = text.replace('いっさくじつ', '一昨日')
    text = text.replace('こんしゅう', '今週')
    text = text.replace('らいしゅう', '来週')
    text = text.replace('さらいしゅう', '再来週')
    text = text.replace('こんげつ', '今月')
    text = text.replace('らいげつ', '来月')
    text = text.replace('さらいげつ', '再来月')
    
    # 助詞付きの表現も正規化
    text = text.replace('あしたの', '明日の')
    text = text.replace('あすの', '明日の')
    text = text.replace('みょうにちの', '明日の')
    text = text.replace('あさっての', '明後日の')
    text = text.replace('みょうごにちの', '明後日の')
    text = text.replace('きのうの', '昨日の')
    text = text.replace('さくじつの', '昨日の')
    text = text.replace('おとといの', '一昨日の')
    text = text.replace('いっさくじつの', '一昨日の')
    text = text.replace('こんしゅうの', '今週の')
    text = text.replace('らいしゅうの', '来週の')
    text = text.replace('さらいしゅうの', '再来週の')
    text = text.replace('こんげつの', '今月の')
    text = text.replace('らいげつの', '来月の')
    text = text.replace('さらいげつの', '再来月の')
    
    return text

def parse_message(text: str) -> Dict[str, Any]:
    """メッセージを解析して必要な情報を抽出する"""
    try:
        # 操作タイプを判定
        operation_type = extract_operation_type(text)
        logger.debug(f"メッセージ解析結果: {operation_type}")

        # 日時情報を抽出
        datetime_info = extract_datetime_from_message(text, operation_type)
        if not datetime_info:
            if operation_type in ['read', 'check']:
                # 日付情報がなくても今日の0:00〜23:59で返す
                now = datetime.now(JST)
                datetime_info = {
                    'start_time': datetime.combine(now.date(), time(0, 0), tzinfo=JST),
                    'end_time': datetime.combine(now.date(), time(23, 59), tzinfo=JST),
                    'date_only': True
                }
            elif operation_type == 'add':
                return {
                    'success': False,
                    'error': '日時情報が見つかりませんでした'
                }

        # タイトルを抽出
        title = extract_title(text, operation_type)

        # 場所を抽出
        location = extract_location(text)

        # 参加者を抽出
        person = extract_person(text)

        # 繰り返し情報を抽出
        recurrence = extract_recurrence(text)
        logger.debug(f"繰り返し情報を抽出: {text}")
        logger.debug(f"抽出された繰り返し情報: {recurrence}")

        result = {
            'success': True,
            'operation_type': operation_type,
            'title': title,
            'location': location,
            'person': person,
            'recurrence': recurrence
        }

        if datetime_info:
            result.update(datetime_info)

        logger.debug(f"メッセージ解析結果: {result}")
        return result

    except Exception as e:
        logger.error(f"メッセージ解析エラー: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            'success': False,
            'error': str(e)
        }

def extract_operation_type(text: str) -> Optional[str]:
    """
    メッセージから操作タイプを抽出する
    
    Args:
        text (str): メッセージテキスト
        
    Returns:
        Optional[str]: 操作タイプ（'add', 'delete', 'update', 'read'）またはNone
    """
    try:
        # テキストを正規化
        normalized_text = normalize_text(text)
        
        # 予定の追加を表すキーワードをチェック
        for keyword in ADD_KEYWORDS:
            if keyword in normalized_text:
                return 'add'
                
        # 予定の削除を表すキーワードをチェック
        for keyword in DELETE_KEYWORDS:
            if keyword in normalized_text:
                return 'delete'
                
        # 予定の変更を表すキーワードをチェック
        for keyword in UPDATE_KEYWORDS:
            if keyword in normalized_text:
                return 'update'
                
        # 予定の確認を表すキーワードをチェック
        for keyword in READ_KEYWORDS:
            if keyword in normalized_text:
                return 'read'
        
        # 日時とタイトルが含まれている場合は、自動的に予定の追加として扱う
        datetime_info = extract_datetime_from_message(text)
        title = extract_title(text)
        if datetime_info and title:
            return 'add'
            
        return None
    except Exception as e:
        logger.error(f"操作タイプの抽出中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def extract_title(text: str, operation_type: str = None) -> str:
    logger.debug(f"タイトル抽出開始: {text}")
    normalized_text = normalize_text(text)
    logger.debug(f"正規化後のメッセージ: {normalized_text}")

    # 操作タイプがreadの場合はタイトルをNoneにする
    if operation_type == 'read':
        logger.debug("操作タイプがreadのため、タイトルをNoneにします")
        return None

    # 日時表現を削除
    text_without_datetime = remove_datetime_expressions(normalized_text)
    logger.debug(f"日時表現削除後: {text_without_datetime}")

    # 場所情報を削除
    text_without_location = re.sub(r'。?場所は[^。]*|。?会場は[^。]*|。?(?:で|にて)[^。、]*(?:で|に|へ|と|は|が|を)?', '', text_without_datetime)
    logger.debug(f"場所情報削除後: {text_without_location}")

    # 参加者情報を削除
    text_without_participants = re.sub(r'。?参加者.*$', '', text_without_location)
    logger.debug(f"参加者情報削除後: {text_without_participants}")

    # 不要な語を除去
    patterns_to_remove = [
        r'^(?:から|を|に|で|へ|と|が|の)+',  # 先頭の助詞を除去
        r'(?:から|まで|翌日)+',  # 時間関連の表現を除去
        r'(?:を|に|で|へ|と|が|の)?追加して[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?追加[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?登録して[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?登録[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?入れて[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?入れる[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?作って[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?作る[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?設定して[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?設定[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?立てて[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?立てる[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?組んで[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?組む[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?決めて[。｡]?$',
        r'(?:を|に|で|へ|と|が|の)?決める[。｡]?$',
        r'[。｡]$',
        r'^[。｡]',
        r'ま$',  # 「まで」の残りを削除
    ]
    
    title = text_without_participants
    for pattern in patterns_to_remove:
        title = re.sub(pattern, '', title)

    # 空白を削除
    title = title.strip()

    # タイトルが空の場合はNone
    if not title:
        title = None

    logger.debug(f"最終的なタイトル: {title}")
    return title

def remove_datetime_expressions(text: str) -> str:
    """日時表現を削除する"""
    # 年月日
    text = re.sub(r'\d{1,4}年', '', text)  # 年を削除
    text = re.sub(r'\d{1,2}月', '', text)  # 月を削除
    text = re.sub(r'\d{1,2}日', '', text)  # 日を削除
    
    # 時刻（分を含む場合と含まない場合の両方に対応）
    text = re.sub(r'\d{1,2}時(?:\d{1,2}分)?', '', text)  # 分を含む時刻と含まない時刻の両方に対応
    
    # 相対日付表現を削除
    text = re.sub(r'(今日|明日|明後日|昨日|一昨日|今週|来週|再来週|先週|今月|来月|先月|今年|来年|去年|一昨年)', '', text)
    
    # 時間関連の表現を削除
    text = re.sub(r'(?:から|まで|翌日)', '', text)
    
    return text

def extract_location(text: str) -> Optional[str]:
    """メッセージから場所を抽出する"""
    try:
        normalized_message = normalize_text(text)
        
        # 場所を表すパターン
        location_patterns = [
            r'場所は(?P<location>[^。]+?)(?:。|$|から|まで|と|は|が|を|に|へ)',
            r'場所(?P<location>[^。]+?)(?:。|$|から|まで|と|は|が|を|に|へ)',
            r'会場は(?P<location>[^。]+?)(?:。|$|から|まで|と|は|が|を|に|へ)',
            r'会場(?P<location>[^。]+?)(?:。|$|から|まで|と|は|が|を|に|へ)',
            r'(?:で|にて)(?P<location>[^。、]+?)(?:で|に|へ|と|は|が|を)?(?:。|$|から|まで)',
        ]
        
        # タイトルと同じ文字列は場所として扱わない
        title = extract_title(text)
        if title and title in normalized_message:
            normalized_message = normalized_message.replace(title, '')
        
        for pattern in location_patterns:
            match = re.search(pattern, normalized_message)
            if match:
                location = match.group('location').strip()
                # 不要な語を除去
                patterns_to_remove = [
                    r'(?:を|に|で|へ|と|が|の)?追加して[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?追加[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?登録して[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?登録[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?入れて[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?入れる[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?作って[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?作る[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?設定して[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?設定[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?立てて[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?立てる[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?組んで[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?組む[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?決めて[。｡]?$',
                    r'(?:を|に|で|へ|と|が|の)?決める[。｡]?$',
                ]
                for remove_pattern in patterns_to_remove:
                    location = re.sub(remove_pattern, '', location)
                location = location.strip()
                # タイトルと同じ場合はNoneを返す
                return None if location == title else location
        
        return None
    except Exception as e:
        logger.error(f"場所抽出エラー: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def extract_person(text: str) -> str:
    """メッセージから人物情報を抽出する"""
    # 参加者情報を抽出
    person_match = re.search(r'参加者(?:は|が)?([^。、]+)', text)
    if person_match:
        person = person_match.group(1).strip()
        # 不要な文字を削除（末尾のみ）
        patterns_to_remove = [
            r'[をにでへとがの]?追加して$',
            r'[をにでへとがの]?追加$',
            r'[をにでへとがの]?削除して$',
            r'[をにでへとがの]?削除$',
            r'[をにでへとがの]?キャンセルして$',
            r'[をにでへとがの]?キャンセル$',
            r'[をにでへとがの]?して$'
        ]
        
        for pattern in patterns_to_remove:
            person = re.sub(pattern, '', person)
        
        # 空白を削除
        person = person.strip()
        
        logger.debug(f"抽出された参加者: {person}")
        return person
    
    # 参加者情報が見つからない場合はNoneを返す
    return None

def extract_recurrence(text: str) -> Optional[str]:
    """メッセージから繰り返し情報を抽出する"""
    try:
        logger.debug(f"繰り返し情報を抽出: {text}")
        
        normalized_message = normalize_text(text)
        
        # 繰り返しを表すパターン
        recurrence_patterns = [
            r'毎週(?P<weekday>月|火|水|木|金|土|日)曜日?',
            r'毎月(?P<day>\d{1,2})日',
            r'毎日',
            r'毎週',
            r'毎月',
            r'毎年'
        ]
        
        for pattern in recurrence_patterns:
            match = re.search(pattern, normalized_message)
            if match:
                if 'weekday' in match.groupdict():
                    weekday = WEEKDAYS[match.group('weekday')]
                    return f'FREQ=WEEKLY;BYDAY={weekday}'
                elif 'day' in match.groupdict():
                    day = match.group('day')
                    return f'FREQ=MONTHLY;BYMONTHDAY={day}'
                elif pattern == '毎日':
                    return 'FREQ=DAILY'
                elif pattern == '毎週':
                    return 'FREQ=WEEKLY'
                elif pattern == '毎月':
                    return 'FREQ=MONTHLY'
                elif pattern == '毎年':
                    return 'FREQ=YEARLY'
        
        logger.debug("抽出された繰り返し情報: None")
        return None
    except Exception as e:
        logger.error(f"繰り返し情報抽出エラー: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def extract_datetime_from_message(text: str, operation_type: str = None) -> Optional[Dict]:
    """メッセージから日時を抽出する"""
    try:
        logger.debug(f"時間抽出開始: {text}")
        
        # 正規化したメッセージを使用
        normalized_message = normalize_text(text)
        logger.debug(f"正規化後のメッセージ: {normalized_message}")
        
        # 現在時刻を一度だけ取得
        now = datetime.now(JST)
        logger.debug(f"現在時刻: {now}")
        
        # 相対日付表現をチェック
        if '今日' in normalized_message:
            # 今日の場合は0:00から23:59までを検索
            start_time = datetime.combine(now.date(), time(0, 0), tzinfo=JST)
            end_time = datetime.combine(now.date(), time(23, 59), tzinfo=JST)
            logger.debug(f"今日の予定を検索: {start_time} から {end_time}")
            return {
                'start_time': start_time,
                'end_time': end_time,
                'date_only': True
            }
        elif '明日' in normalized_message:
            # 明日の場合は0:00から23:59までを検索
            tomorrow = now.date() + timedelta(days=1)
            start_time = datetime.combine(tomorrow, time(0, 0), tzinfo=JST)
            end_time = datetime.combine(tomorrow, time(23, 59), tzinfo=JST)
            logger.debug(f"明日の予定を検索: {start_time} から {end_time}")
            return {
                'start_time': start_time,
                'end_time': end_time,
                'date_only': True
            }
        elif '今週' in normalized_message:
            # 今週の場合は月曜日から日曜日までを検索
            monday = now.date() - timedelta(days=now.weekday())
            start_time = datetime.combine(monday, time(0, 0), tzinfo=JST)
            end_time = datetime.combine(monday + timedelta(days=6), time(23, 59), tzinfo=JST)
            logger.debug(f"今週の予定を検索: {start_time} から {end_time}")
            return {
                'start_time': start_time,
                'end_time': end_time,
                'date_only': True
            }
        elif '来週' in normalized_message:
            next_monday = now.date() - timedelta(days=now.weekday()) + timedelta(days=7)
            start_time = datetime.combine(next_monday, time(0, 0), tzinfo=JST)
            end_time = datetime.combine(next_monday + timedelta(days=6), time(23, 59), tzinfo=JST)
            logger.debug(f"来週の予定を検索: {start_time} から {end_time}")
            return {
                'start_time': start_time,
                'end_time': end_time,
                'date_only': True
            }
        elif '今月' in normalized_message:
            start_time = datetime.combine(now.date().replace(day=1), time(0, 0), tzinfo=JST)
            next_month = start_time.replace(day=28) + timedelta(days=4)
            end_time = datetime.combine(next_month - timedelta(days=next_month.day), time(23, 59), tzinfo=JST)
            logger.debug(f"今月の予定を検索: {start_time} から {end_time}")
            return {
                'start_time': start_time,
                'end_time': end_time,
                'date_only': True
            }
        
        # 日付のみのパターンを先に確認
        date_pattern = r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
        date_match = re.search(date_pattern, normalized_message)
        logger.debug(f"日付パターン: {date_pattern}")
        logger.debug(f"日付パターンマッチ結果: {date_match.groupdict() if date_match else 'マッチなし'}")
        
        # 日付と時刻のパターンを抽出
        date_time_pattern = r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日(?P<hour>\d{1,2})時(?:(?P<minute>\d{1,2})分)?"
        datetime_match = re.search(date_time_pattern, normalized_message)
        logger.debug(f"日時パターン: {date_time_pattern}")
        logger.debug(f"日時パターンマッチ結果: {datetime_match.groupdict() if datetime_match else 'マッチなし'}")
        
        if datetime_match:
            # 日時指定がある場合の処理
            month = int(datetime_match.group('month'))
            day = int(datetime_match.group('day'))
            hour = int(datetime_match.group('hour'))
            minute = int(datetime_match.group('minute')) if datetime_match.group('minute') else 0
            logger.debug(f"抽出された日時: {month}月{day}日 {hour}時{minute}分")
            
            # 年を決定（未来の日付を優先）
            year = now.year
            # 指定された日付が現在より過去の場合、来年にする
            base_date = date(year, month, day)
            if base_date < now.date():
                year += 1
                base_date = date(year, month, day)
            logger.debug(f"決定された年: {year}")
            
            # 日時オブジェクトを作成
            start_time = datetime.combine(base_date, time(hour, minute), tzinfo=JST)
            logger.debug(f"作成された開始時刻: {start_time}")
            
            # 「から」の後の時刻を検索（翌日の場合も考慮）
            end_time_pattern = r'から(?:翌日)?(?P<end_hour>\d{1,2})時(?:(?P<end_minute>\d{1,2})分)?'
            end_match = re.search(end_time_pattern, normalized_message)
            logger.debug(f"終了時刻パターンマッチ結果: {end_match.groupdict() if end_match else 'マッチなし'}")
            
            if end_match:
                end_hour = int(end_match.group('end_hour'))
                end_minute = int(end_match.group('end_minute')) if end_match.group('end_minute') else 0
                # 翌日かどうかを確認
                is_next_day = '翌日' in normalized_message
                end_date = base_date + timedelta(days=1) if is_next_day else base_date
                end_time = datetime.combine(end_date, time(end_hour, end_minute), tzinfo=JST)
                if not is_next_day and end_time < start_time:  # 翌日指定がなく、終了時刻が開始時刻より前の場合
                    end_time = end_time + timedelta(days=1)
            else:
                # 終了時刻が指定されていない場合は1時間後をデフォルトとする
                end_time = start_time + timedelta(hours=1)
            
        elif date_match:
            # 日付のみの指定の場合
            month = int(date_match.group('month'))
            day = int(date_match.group('day'))
            logger.debug(f"抽出された日付: {month}月{day}日")
            
            # 年を決定（未来の日付を優先）
            year = now.year
            # 指定された日付が現在より過去の場合、来年にする
            base_date = date(year, month, day)
            if base_date < now.date():
                year += 1
                base_date = date(year, month, day)
            logger.debug(f"決定された年: {year}")
            
            # 開始時刻を0:00、終了時刻を23:59に設定
            start_time = datetime.combine(base_date, time(0, 0), tzinfo=JST)
            end_time = datetime.combine(base_date, time(23, 59), tzinfo=JST)
            logger.debug(f"日付のみの指定のため、一日全体を対象とします: {start_time} から {end_time}")
            return {
                'start_time': start_time,
                'end_time': end_time,
                'date_only': True
            }
            
        else:
            # 時刻のみのパターンを処理
            hour = now.hour
            minute = now.minute
            for pattern in [TIME_PATTERNS['basic_time'], TIME_PATTERNS['am_pm_time'], TIME_PATTERNS['colon_time']]:
                match = re.search(pattern, normalized_message)
                if match:
                    if 'period' in match.groupdict() and match.group('period'):
                        hour = int(match.group('hour'))
                        if match.group('period') in ['午後', '夜', '夕方', '深夜']:
                            hour += 12
                    else:
                        hour = int(match.group('hour'))
                    if 'minute' in match.groupdict() and match.group('minute'):
                        minute = int(match.group('minute'))
                    else:
                        minute = 0
                    break
            start_time = datetime.combine(now.date(), time(hour, minute), tzinfo=JST)
            end_time = datetime.combine(now.date(), time(23, 59), tzinfo=JST)
            logger.debug(f"時刻のみの指定: {start_time} から {end_time}")
        
        logger.debug(f"最終的な日時抽出結果: {start_time} から {end_time}")
        return {
            'start_time': start_time,
            'end_time': end_time
        }
        
    except Exception as e:
        logger.error(f"日時抽出エラー: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def extract_time(message: str) -> Dict:
    """
    メッセージから時間情報を抽出する
    
    Args:
        message (str): 入力メッセージ
        
    Returns:
        Dict: 時間情報を含む辞書
    """
    try:
        # 現在時刻を取得
        now = datetime.now(JST)
        
        # メッセージの正規化
        normalized_message = normalize_text(message)
        logger.debug(f"正規化後のメッセージ: {normalized_message}")
        logger.debug(f"現在時刻: {now}")
        
        # 時間パターンの定義（優先順位付き）
        time_patterns = [
            # 時間範囲のパターン
            (r'(\d{1,2})時から(\d{1,2})時', 'range'),  # "8時から10時" のようなパターン
            (r'(\d{1,2}):(\d{2})から(\d{1,2}):(\d{2})', 'range'),  # "8:30から10:30" のようなパターン
            
            # 開始時刻のパターン
            (r'(\d{1,2})時から', 'start'),  # "8時から" のようなパターン
            (r'(\d{1,2}):(\d{2})から', 'start'),  # "8:30から" のようなパターン
            (r'(\d{1,2})時', 'start'),     # "8時" のようなパターン
            (r'(\d{1,2}):(\d{2})', 'start'),      # "8:30" のようなパターン
            
            # 午前/午後のパターン
            (r'午前(\d{1,2})時', 'start'),  # "午前8時" のようなパターン
            (r'午後(\d{1,2})時', 'start'),  # "午後8時" のようなパターン
            (r'朝(\d{1,2})時', 'start'),    # "朝8時" のようなパターン
            (r'夜(\d{1,2})時', 'start'),    # "夜8時" のようなパターン
        ]
        
        # 時間情報の初期化
        time_info = {
            'start_time': None,
            'end_time': None,
            'date_only': False
        }
        
        # 時間パターンの検索
        for pattern, time_type in time_patterns:
            match = re.search(pattern, normalized_message)
            if match:
                if time_type == 'range':
                    # 時間範囲の処理
                    if ':' in pattern:
                        start_hour = int(match.group(1))
                        start_minute = int(match.group(2))
                        end_hour = int(match.group(3))
                        end_minute = int(match.group(4))
                    else:
                        start_hour = int(match.group(1))
                        start_minute = 0
                        end_hour = int(match.group(2))
                        end_minute = 0
                    
                    time_info['start_time'] = now.replace(
                        hour=start_hour,
                        minute=start_minute,
                        second=0,
                        microsecond=0
                    )
                    time_info['end_time'] = now.replace(
                        hour=end_hour,
                        minute=end_minute,
                        second=0,
                        microsecond=0
                    )
                    break
                else:
                    # 開始時刻の処理
                    if ':' in pattern:
                        hour = int(match.group(1))
                        minute = int(match.group(2))
                    else:
                        hour = int(match.group(1))
                        minute = 0
                    
                    # 午後や夜の時間を24時間形式に変換
                    if '午後' in pattern or '夜' in pattern:
                        if hour < 12:
                            hour += 12
                    
                    time_info['start_time'] = now.replace(
                        hour=hour,
                        minute=minute,
                        second=0,
                        microsecond=0
                    )
                    # 終了時間を1時間後に設定
                    time_info['end_time'] = time_info['start_time'] + timedelta(hours=1)
                    break
        
        # 時間が見つからない場合は日付のみとして扱う
        if time_info['start_time'] is None:
            time_info['date_only'] = True
            time_info['start_time'] = now.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0
            )
            time_info['end_time'] = now.replace(
                hour=23,
                minute=59,
                second=59,
                microsecond=999999
            )
        
        logger.debug(f"抽出された時間情報: {time_info}")
        return time_info
        
    except Exception as e:
        logger.error(f"時間の抽出中にエラーが発生: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            'start_time': None,
            'end_time': None,
            'date_only': True
        }