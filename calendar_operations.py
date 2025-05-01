def check_schedule_overlap(service, calendar_id: str, start_time: datetime, end_time: datetime, exclude_event_id: str = None) -> tuple[bool, list]:
    """
    指定された時間帯に重複する予定があるかチェックする
    
    Args:
        service: Google Calendar API サービス
        calendar_id (str): カレンダーID
        start_time (datetime): 開始時間
        end_time (datetime): 終了時間
        exclude_event_id (str, optional): チェックから除外する予定のID
        
    Returns:
        tuple[bool, list]: (重複があるかどうか, 重複している予定のリスト)
    """
    try:
        # タイムゾーンを設定
        start_time = start_time.astimezone(JST)
        end_time = end_time.astimezone(JST)
        
        # 予定を取得
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_time.isoformat(),
            timeMax=end_time.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # 除外する予定をフィルタリング
        if exclude_event_id:
            events = [event for event in events if event['id'] != exclude_event_id]
        
        # 重複チェック
        overlapping_events = []
        for event in events:
            event_start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')).replace('Z', '+00:00'))
            event_end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')).replace('Z', '+00:00'))
            
            # 時間が重複しているかチェック
            if (start_time < event_end and end_time > event_start):
                overlapping_events.append({
                    'id': event['id'],
                    'title': event.get('summary', '予定なし'),
                    'start': event_start,
                    'end': event_end,
                    'location': event.get('location', '')
                })
        
        return len(overlapping_events) > 0, overlapping_events
        
    except Exception as e:
        logger.error(f"予定の重複チェック中にエラーが発生: {str(e)}")
        logger.error("詳細なエラー情報:", exc_info=True)
        raise

def add_event(service, calendar_id: str, event_data: dict) -> dict:
    """
    予定を追加する
    
    Args:
        service: Google Calendar API サービス
        calendar_id (str): カレンダーID
        event_data (dict): 予定データ
        
    Returns:
        dict: 操作結果
    """
    try:
        # 必須パラメータのチェック
        if not event_data.get('title'):
            return {'success': False, 'error': '予定のタイトルが指定されていません'}
        
        start_time = event_data.get('start_datetime')
        end_time = event_data.get('end_datetime')
        
        if not start_time or not end_time:
            return {'success': False, 'error': '開始時間または終了時間が指定されていません'}
        
        # 過去の時間チェック
        now = datetime.now(JST)
        if start_time < now:
            return {'success': False, 'error': '開始時間が過去の時間を指定しています'}
        
        # 終了時間のチェック
        if end_time <= start_time:
            return {'success': False, 'error': '終了時間が開始時間より前になっています'}
        
        # 重複チェック
        has_overlap, overlapping_events = check_schedule_overlap(service, calendar_id, start_time, end_time)
        if has_overlap:
            overlap_message = "以下の予定と時間が重複しています：\n"
            for event in overlapping_events:
                overlap_message += f"• {event['title']} ({event['start'].strftime('%H:%M')}〜{event['end'].strftime('%H:%M')})\n"
            return {'success': False, 'error': overlap_message}
        
        # 予定を作成
        event = {
            'summary': event_data['title'],
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Tokyo',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Tokyo',
            },
        }
        
        if event_data.get('location'):
            event['location'] = event_data['location']
        
        # 予定を追加
        event = service.events().insert(calendarId=calendar_id, body=event).execute()
        
        return {
            'success': True,
            'event': {
                'id': event['id'],
                'title': event['summary'],
                'start_datetime': start_time,
                'end_datetime': end_time,
                'location': event.get('location', '')
            }
        }
        
    except Exception as e:
        logger.error(f"予定の追加中にエラーが発生: {str(e)}")
        logger.error("詳細なエラー情報:", exc_info=True)
        return {'success': False, 'error': str(e)}

def update_event(service, calendar_id: str, event_id: str, event_data: dict) -> dict:
    """
    予定を更新する
    
    Args:
        service: Google Calendar API サービス
        calendar_id (str): カレンダーID
        event_id (str): 予定ID
        event_data (dict): 更新する予定データ
        
    Returns:
        dict: 操作結果
    """
    try:
        # 必須パラメータのチェック
        if not event_data.get('title'):
            return {'success': False, 'error': '予定のタイトルが指定されていません'}
        
        start_time = event_data.get('start_datetime')
        end_time = event_data.get('end_datetime')
        
        if not start_time or not end_time:
            return {'success': False, 'error': '開始時間または終了時間が指定されていません'}
        
        # 過去の時間チェック
        now = datetime.now(JST)
        if start_time < now:
            return {'success': False, 'error': '開始時間が過去の時間を指定しています'}
        
        # 終了時間のチェック
        if end_time <= start_time:
            return {'success': False, 'error': '終了時間が開始時間より前になっています'}
        
        # 重複チェック（自分自身は除外）
        has_overlap, overlapping_events = check_schedule_overlap(service, calendar_id, start_time, end_time, event_id)
        if has_overlap:
            overlap_message = "以下の予定と時間が重複しています：\n"
            for event in overlapping_events:
                overlap_message += f"• {event['title']} ({event['start'].strftime('%H:%M')}〜{event['end'].strftime('%H:%M')})\n"
            return {'success': False, 'error': overlap_message}
        
        # 既存の予定を取得
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        
        # 予定を更新
        event['summary'] = event_data['title']
        event['start'] = {
            'dateTime': start_time.isoformat(),
            'timeZone': 'Asia/Tokyo',
        }
        event['end'] = {
            'dateTime': end_time.isoformat(),
            'timeZone': 'Asia/Tokyo',
        }
        
        if event_data.get('location'):
            event['location'] = event_data['location']
        
        # 予定を更新
        updated_event = service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
        
        return {
            'success': True,
            'event': {
                'id': updated_event['id'],
                'title': updated_event['summary'],
                'start_datetime': start_time,
                'end_datetime': end_time,
                'location': updated_event.get('location', '')
            }
        }
        
    except Exception as e:
        logger.error(f"予定の更新中にエラーが発生: {str(e)}")
        logger.error("詳細なエラー情報:", exc_info=True)
        return {'success': False, 'error': str(e)}

def delete_event(service, calendar_id: str, event_id: str) -> dict:
    """
    予定を削除する
    
    Args:
        service: Google Calendar API サービス
        calendar_id (str): カレンダーID
        event_id (str): 予定ID
        
    Returns:
        dict: 操作結果
    """
    try:
        # 予定を取得
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        
        # 予定を削除
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        
        return {
            'success': True,
            'event': {
                'id': event['id'],
                'title': event.get('summary', '予定なし'),
                'start_datetime': datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')).replace('Z', '+00:00')),
                'end_datetime': datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')).replace('Z', '+00:00')),
                'location': event.get('location', '')
            }
        }
        
    except Exception as e:
        logger.error(f"予定の削除中にエラーが発生: {str(e)}")
        logger.error("詳細なエラー情報:", exc_info=True)
        return {'success': False, 'error': str(e)}

def get_events(service, calendar_id: str, start_time: datetime, end_time: datetime) -> dict:
    """
    予定を取得する
    
    Args:
        service: Google Calendar API サービス
        calendar_id (str): カレンダーID
        start_time (datetime): 開始時間
        end_time (datetime): 終了時間
        
    Returns:
        dict: 操作結果
    """
    try:
        # タイムゾーンを設定
        start_time = start_time.astimezone(JST)
        end_time = end_time.astimezone(JST)
        
        # 予定を取得
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_time.isoformat(),
            timeMax=end_time.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # 予定を整形
        formatted_events = []
        for event in events:
            start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')).replace('Z', '+00:00'))
            end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')).replace('Z', '+00:00'))
            
            formatted_events.append({
                'id': event['id'],
                'title': event.get('summary', '予定なし'),
                'start_datetime': start,
                'end_datetime': end,
                'location': event.get('location', '')
            })
        
        return {
            'success': True,
            'events': formatted_events
        }
        
    except Exception as e:
        logger.error(f"予定の取得中にエラーが発生: {str(e)}")
        logger.error("詳細なエラー情報:", exc_info=True)
        return {'success': False, 'error': str(e)} 