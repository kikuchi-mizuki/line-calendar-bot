from typing import Dict, Optional
from datetime import datetime
from dateutil.parser import parse
import traceback

class CalendarManager:
    def update_event(self, event_id: str, datetime_info: Dict[str, datetime]) -> Optional[Dict]:
        """
        指定されたイベントの時間を更新する
        
        Args:
            event_id (str): 更新するイベントのID
            datetime_info (Dict[str, datetime]): 更新する日時情報
            
        Returns:
            Optional[Dict]: 更新されたイベント情報
        """
        try:
            # イベントを取得
            event = self.service.events().get(calendarId='mmms.dy.23@gmail.com', eventId=event_id).execute()
            
            # 新しい開始時刻が指定されている場合
            if 'new_start_time' in datetime_info:
                new_start_time = datetime_info['new_start_time']
                duration = parse(event['end']['dateTime']) - parse(event['start']['dateTime'])
                new_end_time = new_start_time + duration
                
                event['start']['dateTime'] = new_start_time.isoformat()
                event['end']['dateTime'] = new_end_time.isoformat()
            
            # 新しい時間の長さが指定されている場合
            elif 'new_duration' in datetime_info:
                start_time = parse(event['start']['dateTime'])
                new_end_time = start_time + datetime_info['new_duration']
                event['end']['dateTime'] = new_end_time.isoformat()
            
            # イベントを更新
            updated_event = self.service.events().update(
                calendarId='mmms.dy.23@gmail.com',
                eventId=event_id,
                body=event
            ).execute()
            
            return updated_event
            
        except Exception as e:
            logger.error(f"イベントの更新中にエラーが発生: {str(e)}")
            logger.error(traceback.format_exc())
            return None 