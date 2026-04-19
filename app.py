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

BOT_NAME = os.getenv('BOT_NAME', 'LineBot')  # 你的 Bot 顯示名稱

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


def clean_mention(text, bot_name):
    """移除開頭的 @BotName 前綴"""
    pattern = rf'^@{re.escape(bot_name)}\s*'
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
    return response.status_code == 200


def extract_url(text):
    match = re.search(r'https?://[^\s]+', text)
    return match.group(0) if match else None


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info(f"[Webhook received] body: {body}")  # 診斷用
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    raw_text = event.message.text

    # 只處理有 @mention Bot 的訊息（群組中必須 @mention 才會觸發）
    if not raw_text.startswith(f'@{BOT_NAME}'):
        return  # 靜默忽略非 @mention 訊息

    # 清除 @mention 前綴，取得實際內容
    msg_text = clean_mention(raw_text, BOT_NAME)

    if not msg_text:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請在 @mention 後面加上要儲存的內容。\n例如：@Bot #創意 今天想到一個好點子")
        )
        return

    # 取得發送者名稱
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

    # 用 hashtag 判斷要存入哪個資料庫
    if "#創意" in msg_text:
        properties = {
            "標題":  {"title":     [{"text": {"content": title}}]},
            "內容":  {"rich_text": [{"text": {"content": msg_text}}]},
            "提出者": {"rich_text": [{"text": {"content": sender_name}}]},
        }
        success = add_to_notion(NOTION_DB_IDEA, properties)
        reply_msg = f"✅ 已將創意整理至 Notion 創意池！\n提出者：{sender_name}"

    elif "#設計" in msg_text or "#功能" in msg_text:
        category = "未分類"
        if "#設計" in msg_text:       category = "設計參考"
        elif "#要的功能" in msg_text:  category = "要的功能"
        elif "#不要的功能" in msg_text: category = "不要的功能"

        properties = {
            "標題":  {"title":     [{"text": {"content": title}}]},
            "內容":  {"rich_text": [{"text": {"content": msg_text}}]},
            "分類":  {"select":    {"name": category}},
            "提出者": {"rich_text": [{"text": {"content": sender_name}}]},
        }
        success = add_to_notion(NOTION_DB_DESIGN, properties)
        reply_msg = f"✅ 已存入設計池（分類：{category}）\n提出者：{sender_name}"

    elif "#資源" in msg_text or extract_url(msg_text):
        url = extract_url(msg_text)
        properties = {
            "標題":  {"title":     [{"text": {"content": title}}]},
            "說明":  {"rich_text": [{"text": {"content": msg_text}}]},
            "連結":  {"url": url} if url else {"url": None},
            "提出者": {"rich_text": [{"text": {"content": sender_name}}]},
        }
        success = add_to_notion(NOTION_DB_RESOURCE, properties)
        reply_msg = f"✅ 已將資源整理至 Notion 資源池！\n提出者：{sender_name}"

    else:
        # 沒有對應指令，回傳使用說明
        reply_msg = (
            "❓ 請加上分類標籤：\n"
            "  #創意 → 創意池\n"
            "  #設計 / #要的功能 / #不要的功能 → 設計池\n"
            "  #資源（或直接貼網址）→ 資源池\n\n"
            "範例：@Bot #創意 想做一個自動存 Notion 的機器人"
        )
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text=reply_msg)
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
