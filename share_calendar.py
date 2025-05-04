from googleapiclient.discovery import build
from google.oauth2 import service_account

SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'credentials.json'
USER_EMAIL = 'aimiamano@gmail.com'  # ここをあなたのGmailアドレスに変更

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

service = build('calendar', 'v3', credentials=credentials)

rule = {
    'scope': {
        'type': 'user',
        'value': USER_EMAIL,
    },
    'role': 'writer'  # 'reader' でもOK
}

calendar_id = 'mmms.dy.23@gmail.com'
created_rule = service.acl().insert(calendarId=calendar_id, body=rule).execute()
print(f"Created rule: {created_rule['id']}") 