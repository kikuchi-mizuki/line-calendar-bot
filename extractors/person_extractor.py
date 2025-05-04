import re
import logging

logger = logging.getLogger(__name__)

class PersonExtractor:
    def __init__(self):
        # 敬称のパターン
        self.honorifics = r'さん|君|様|氏'
        
        # 時間表現のパターン
        self.time_patterns = [
            r'\d{1,2}時(?:\d{1,2}分)?(?:から|まで)?',
            r'午前|午後|朝|昼|夕方|夜',
            r'\d{1,2}:\d{2}',
            r'今日|明日|明後日',
        ]
        
    def extract(self, text: str) -> str:
        """
        テキストから人名を抽出する
        
        Args:
            text (str): 入力テキスト
            
        Returns:
            str: 抽出された人名（見つからない場合はNone）
        """
        try:
            # 参加者情報の抽出パターン
            patterns = [
                r'参加者は(.+?)と(.+?)と',
                r'参加者は(.+?)と',
                r'参加者は(.+?)さんと(.+?)さんと',
                r'参加者は(.+?)さんと',
                r'参加者は(.+?)ちゃんと(.+?)ちゃんと',
                r'参加者は(.+?)ちゃんと',
                r'参加者は(.+?)くんと(.+?)くんと',
                r'参加者は(.+?)くんと',
                r'参加者は(.+?)君と(.+?)君と',
                r'参加者は(.+?)君と',
                r'参加者は(.+?)様と(.+?)様と',
                r'参加者は(.+?)様と'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    participants = []
                    for group in match.groups():
                        if group:
                            # 敬称を除去
                            person = re.sub(r'さん|ちゃん|くん|君|様', '', group)
                            # 余分な空白を除去
                            person = person.strip()
                            if person:
                                participants.append(person)
                    
                    if participants:
                        return 'と'.join(participants)
            
            return None
            
        except Exception as e:
            logger.error(f"人名の抽出中にエラーが発生: {str(e)}")
            return None 