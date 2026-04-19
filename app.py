import os
import re
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 從環境變數讀取設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
NOTION_TOKEN = os.getenv('NOTION_TOKEN')

# 三個群組的 Notion Database ID
NOTION_DB_IDEA = os.getenv('NOTION_DB_IDEA')
NOTION_DB_DESIGN = os.getenv('NOTION_DB_DESIGN')
NOTION_DB_RESOURCE = os.getenv('NOTION_DB_RESOURCE')

# 三個 LINE 群組的 ID (部署後再補填)
GROUP_ID_IDEA = os.getenv('GROUP_ID_IDEA')
GROUP_ID_DESIGN = os.getenv('GROUP_ID_DESIGN')
GROUP_ID_RESOURCE = os.getenv('GROUP_ID_RESOURCE')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

def add_to_notion(database_id, properties):
    """將資料寫入 Notion 資料庫"""
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    payload = {
        "parent": {"database_id": database_id},
        "properties": properties
    }
    response = requests.post(url, json=payload, headers=headers )
    return response.status_code == 200

def extract_url(text):
    """從文字中萃取第一個 URL"""
    url_pattern = r'https?://[^\s]+'
    match = re.search(url_pattern, text )
    return match.group(0) if match else None

@app.route("/callback", methods=['POST'])
def callback():
    # 取得 LINE Webhook 簽名並驗證
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg_text = event.message.text
    source_id = event.source.group_id if hasattr(event.source, 'group_id') else event.source.user_id
    
    # 取得發送者名稱
    try:
        profile = line_bot_api.get_group_member_profile(event.source.group_id, event.source.user_id)
        sender_name = profile.display_name
    except:
        sender_name = "未知使用者"

    # 準備 Notion 資料屬性
    title = msg_text[:20] + ("..." if len(msg_text) > 20 else "")
    
    success = False
    reply_msg = ""

    # 根據 Group ID 判斷要存入哪個資料庫
    if source_id == GROUP_ID_IDEA:
        properties = {
            "標題": {"title": [{"text": {"content": title}}]},
            "內容": {"rich_text": [{"text": {"content": msg_text}}]},
            "提出者": {"rich_text": [{"text": {"content": sender_name}}]}
        }
        success = add_to_notion(NOTION_DB_IDEA, properties)
        reply_msg = "✅ 已將創意整理至 Notion 創意池！"

    elif source_id == GROUP_ID_DESIGN:
        # 簡單分類邏輯
        category = "未分類"
        if "#設計" in msg_text: category = "設計參考"
        elif "#要的功能" in msg_text: category = "要的功能"
        elif "#不要的功能" in msg_text: category = "不要的功能"

        properties = {
            "標題": {"title": [{"text": {"content": title}}]},
            "內容": {"rich_text": [{"text": {"content": msg_text}}]},
            "分類": {"select": {"name": category}},
            "提出者": {"rich_text": [{"text": {"content": sender_name}}]}
        }
        success = add_to_notion(NOTION_DB_DESIGN, properties)
        reply_msg = f"✅ 已將設計/功能整理至 Notion 平台設計池（分類：{category}）！"

    elif source_id == GROUP_ID_RESOURCE:
        url = extract_url(msg_text)
        properties = {
            "標題": {"title": [{"text": {"content": title}}]},
            "說明": {"rich_text": [{"text": {"content": msg_text}}]},
            "連結": {"url": url} if url else {"url": None},
            "提出者": {"rich_text": [{"text": {"content": sender_name}}]}
        }
        success = add_to_notion(NOTION_DB_RESOURCE, properties)
        reply_msg = "✅ 已將資源連結整理至 Notion 資源池！"

    # 如果不在預設群組內，回傳 Group ID 供使用者設定
    else:
        reply_msg = f"目前群組 ID 為：{source_id}\n請將此 ID 設定至環境變數中以啟用自動整理功能。"

    if success or "目前群組 ID" in reply_msg:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
