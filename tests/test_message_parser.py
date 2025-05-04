import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from message_parser import parse_message, extract_title_from_message, extract_datetime_from_message

class TestMessageParser(unittest.TestCase):
    """
    メッセージパーサーのテスト
    """
    @patch('message_parser.extract_datetime_from_message')
    @patch('message_parser.extract_title_from_message')
    def test_parse_message_add(self, mock_title, mock_datetime):
        """
        イベント追加メッセージの解析テスト
        """
        # モックの設定
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=1)
        mock_datetime.return_value = {'start_time': start_time, 'end_time': end_time}
        mock_title.return_value = ('会議', None, None)
        
        message = "明日の10時から11時まで会議を追加してください"
        result = parse_message(message)
        
        # 結果の確認
        self.assertTrue(result['success'])
        self.assertEqual(result['operation_type'], 'add')
        self.assertEqual(result['title'], '会議')
        self.assertIsNotNone(result['start_time'])
        self.assertIsNotNone(result['end_time'])
        
    @patch('message_parser.extract_datetime_from_message')
    @patch('message_parser.extract_title_from_message')
    def test_parse_message_delete(self, mock_title, mock_datetime):
        """
        イベント削除メッセージの解析テスト
        """
        # モックの設定
        start_time = datetime.now()
        mock_datetime.return_value = {'start_time': start_time, 'end_time': None}
        mock_title.return_value = ('会議', None, None)
        
        message = "明日の会議を削除してください"
        result = parse_message(message)
        
        # 結果の確認
        self.assertTrue(result['success'])
        self.assertEqual(result['operation_type'], 'delete')
        self.assertEqual(result['title'], '会議')
        self.assertIsNotNone(result['start_time'])
        
    @patch('message_parser.extract_datetime_from_message')
    @patch('message_parser.extract_title_from_message')
    def test_parse_message_update(self, mock_title, mock_datetime):
        """
        イベント更新メッセージの解析テスト
        """
        # モックの設定
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=1)
        mock_datetime.return_value = {'start_time': start_time, 'end_time': end_time}
        mock_title.return_value = ('会議', None, None)
        
        message = "明日の会議を12時から13時に変更してください"
        result = parse_message(message)
        
        # 結果の確認
        self.assertTrue(result['success'])
        self.assertEqual(result['operation_type'], 'update')
        self.assertEqual(result['title'], '会議')
        self.assertIsNotNone(result['start_time'])
        self.assertIsNotNone(result['end_time'])
        
    @patch('message_parser.extract_datetime_from_message')
    def test_parse_message_read(self, mock_datetime):
        """
        イベント確認メッセージの解析テスト
        """
        # モックの設定
        start_time = datetime.now()
        end_time = start_time + timedelta(days=1)
        mock_datetime.return_value = {'start_time': start_time, 'end_time': end_time}
        
        message = "明日の予定を教えてください"
        result = parse_message(message)
        
        # 結果の確認
        self.assertTrue(result['success'])
        self.assertEqual(result['operation_type'], 'read')
        self.assertIsNotNone(result['start_time'])
        self.assertIsNotNone(result['end_time'])
        
    @patch('message_parser.nlp')
    def test_extract_title_from_message(self, mock_nlp):
        """
        タイトル抽出のテスト
        """
        # モックの設定
        mock_doc = MagicMock()
        mock_nlp.return_value = mock_doc
        
        # 通常のケース
        mock_doc.noun_chunks = [
            MagicMock(text='会議', root=MagicMock(children=[]))
        ]
        message = "会議を追加してください"
        title, location, person = extract_title_from_message(message)
        self.assertEqual(title, "会議")
        self.assertIsNone(location)
        self.assertIsNone(person)
        
        # 場所を含むケース
        mock_doc.noun_chunks = [
            MagicMock(text='会議', root=MagicMock(children=[])),
            MagicMock(text='会議室Aで', root=MagicMock(children=[
                MagicMock(text='で', pos_='ADP')
            ]))
        ]
        message = "会議を会議室Aで追加してください"
        title, location, person = extract_title_from_message(message)
        self.assertEqual(title, "会議")
        self.assertEqual(location, "会議室A")
        self.assertIsNone(person)
        
        # 人物を含むケース
        mock_doc.noun_chunks = [
            MagicMock(text='会議', root=MagicMock(children=[])),
            MagicMock(text='山田さんと', root=MagicMock(children=[
                MagicMock(text='と', pos_='ADP')
            ]))
        ]
        message = "会議を山田さんと追加してください"
        title, location, person = extract_title_from_message(message)
        self.assertEqual(title, "会議")
        self.assertIsNone(location)
        self.assertEqual(person, "山田さん")

        # 時間表現を含むケース
        message = "明後日9時から9時半まで片さんとMTG"
        title, location, person = extract_title_from_message(message)
        self.assertEqual(title, "片さんとMTG")
        self.assertIsNone(location)
        self.assertEqual(person, "片さん")

        # 時間表現と場所を含むケース
        message = "明日10時から11時まで会議室Aで山田さんと打ち合わせ"
        title, location, person = extract_title_from_message(message)
        self.assertEqual(title, "山田さんと打ち合わせ")
        self.assertEqual(location, "会議室A")
        self.assertEqual(person, "山田さん")
        
    @patch('message_parser.dateparser.parse')
    def test_extract_datetime_from_message(self, mock_parse):
        """
        日時抽出のテスト
        """
        # モックの設定
        base_time = datetime(2023, 1, 1, 10, 0)
        mock_parse.side_effect = [
            base_time,  # start_time
            base_time + timedelta(hours=1)  # end_time
        ]
        
        # 絶対時刻のケース
        message = "10時から11時まで"
        result = extract_datetime_from_message(message)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.get('start_time'))
        self.assertIsNotNone(result.get('end_time'))
        
        # 相対時刻のケース
        mock_parse.side_effect = [
            base_time + timedelta(hours=1),  # start_time
            base_time + timedelta(hours=2)  # end_time
        ]
        message = "1時間後から2時間後まで"
        result = extract_datetime_from_message(message)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.get('start_time'))
        self.assertIsNotNone(result.get('end_time'))
        
        # 曜日のケース
        mock_parse.side_effect = [
            base_time + timedelta(days=7),  # start_time
            base_time + timedelta(days=7, hours=1)  # end_time
        ]
        message = "来週の月曜日の10時から11時まで"
        result = extract_datetime_from_message(message)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.get('start_time'))
        self.assertIsNotNone(result.get('end_time'))
        
        # 期間のケース
        mock_parse.side_effect = [
            base_time + timedelta(days=7),  # start_time
            base_time + timedelta(days=11)  # end_time
        ]
        message = "来週の月曜日から金曜日まで"
        result = extract_datetime_from_message(message)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.get('start_time'))
        self.assertIsNotNone(result.get('end_time'))
        
if __name__ == '__main__':
    unittest.main() 