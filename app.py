import os
import re
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
NOTION_TOKEN = os.getenv('NOTION_TOKEN')

NOTION_DB_IDEA     = os.getenv('NOTION_DB_IDEA')
NOTION_DB_DESIGN   = os.getenv('NOTION_DB_DESIGN')
NOTION_DB_RESOURCE = os.getenv('NOTION_DB_RESOURCE')

BOT_NAME = os.getenv('BOT_NAME', 'AI小幫手')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


def clean_mention(text, bot_name):
    pattern = rf'^@{re.escape(bot_name)}[\s\u3000]*'
    return re.sub(pattern, '', text).strip()


def add_to_notion(database_id, properties):
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
    response = requests.post(url, json=payload, headers=headers)
    app.logger.info(f"[Notion] status={response.status_code} body={response.text}")
    return response.status_code == 200


def extract_url(text):
    match = re.search(r'https?://[^\s]+', text)
    return match.group(0) if match else None


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info(f"[Webhook] body: {body}")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    raw_text = event.message.text

    if not raw_text.startswith(f'@{BOT_NAME}'):
        return

    msg_text = clean_mention(raw_text, BOT_NAME)

    if not msg_text:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請在 @AI小幫手 後面加上內容。\n例如：@AI小幫手 #創意 今天想到一個好點子")
        )
        return

    try:
        profile = line_bot_api.get_group_member_profile(
            event.source.group_id, event.source.user_id
        )
        sender_name = profile.display_name
    except Exception:
        sender_name = "未知使用者"

    title = msg_text[:30] + ("..." if len(msg_text) > 30 else "")
    success = False
    reply_msg = ""

    if "#創意" in msg_text:
        properties = {
            "標題": {"title": [{"text": {"content": title}}]},
            "內容 (Content)": {"rich_text": [{"text": {"content": msg_text}}]},
            "提出者 (Sender)": {"rich_text": [{"text": {"content": sender_name}}]},
        }
        success = add_to_notion(NOTION_DB_IDEA, properties)
        reply_msg = f"✅ 已將創意整理至 Notion 創意池！\n提出者：{sender_name}"

    elif "#設計" in msg_text or "#要的功能" in msg_text or "#不要的功能" in msg_text:
        category = "未分類"
        if "#設計" in msg_text:         category = "設計參考"
        elif "#要的功能" in msg_text:    category = "要的功能"
        elif "#不要的功能" in msg_text:  category = "不要的功能"

        properties = {
            "標題": {"title": [{"text": {"content": title}}]},
            "內容 (Content)": {"rich_text": [{"text": {"content": msg_text}}]},
            "分類 (Category)": {"select": {"name": category}},
            "提出者 (Sender)": {"rich_text": [{"text": {"content": sender_name}}]},
        }
        success = add_to_notion(NOTION_DB_DESIGN, properties)
        reply_msg = f"✅ 已存入設計池（分類：{category}）\n提出者：{sender_name}"

    elif "#資源" in msg_text or extract_url(msg_text):
        url = extract_url(msg_text)
        properties = {
            "名稱": {"title": [{"text": {"content": title}}]},
            "網站": {"url": url} if url else {"url": None},
            "聯絡人": {"rich_text": [{"text": {"content": sender_name}}]},
        }
        success = add_to_notion(NOTION_DB_RESOURCE, properties)
        reply_msg = f"✅ 已將資源整理至 Notion 資源池！\n提出者：{sender_name}"

    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=(
                "❓ 請加上分類標籤：\n"
                "  #創意 → 創意池\n"
                "  #設計 → 設計池\n"
                "  #要的功能 → 設計池\n"
                "  #不要的功能 → 設計池\n"
                "  #資源（或直接貼網址）→ 資源池\n\n"
                "範例：@AI小幫手 #創意 想做一個自動存 Notion 的機器人"
            ))
        )
        return

    if success:
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text=reply_msg)
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ 寫入 Notion 失敗，請確認 Token 與 Database ID 設定正確。")
        )


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
