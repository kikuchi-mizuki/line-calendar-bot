# LINE Bot with Flask

このプロジェクトは、LINE Messaging APIを使用してメッセージを受信し、Flaskで処理するシンプルなボットアプリケーションです。

## セットアップ

1. 必要なパッケージをインストール:
```bash
pip install -r requirements.txt
```

2. LINE Developersでチャネルを作成し、以下の情報を取得:
   - チャネルアクセストークン
   - チャネルシークレット

3. `.env`ファイルに以下の情報を設定:
```
LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token
LINE_CHANNEL_SECRET=your_channel_secret
```

4. アプリケーションを実行:
```bash
python app.py
```

5. ngrokなどのツールを使用してローカルサーバーを公開:
```bash
ngrok http 5000
```

6. LINE DevelopersコンソールでWebhook URLを設定:
   - `https://あなたのドメイン/callback`

## 機能

- LINEから送信されたメッセージを受信
- 受信したメッセージをそのまま返信 