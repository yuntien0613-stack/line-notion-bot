import os
import re
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

NOTION_DB_IDEA     = os.getenv('NOTION_DB_IDEA')
NOTION_DB_DESIGN   = os.getenv('NOTION_DB_DESIGN')
NOTION_DB_RESOURCE = os.getenv('NOTION_DB_RESOURCE')

BOT_NAME = os.getenv('BOT_NAME', 'AI小幫手')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


def clean_mention(text, bot_name):
    pattern = rf'^@{re.escape(bot_name)}[\s\u3000]*'
    return re.sub(pattern, '', text).strip()


def call_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    response = requests.post(url, json=payload)
    print(f"[Gemini] Status: {response.status_code}", flush=True)
    print(f"[Gemini] Response: {response.text}", flush=True)
    if response.status_code == 200:
        data = response.json()
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    return None


def ai_classify_idea(msg_text):
    prompt = f"""你是一個創意整理助手。根據以下訊息內容，請回傳 JSON 格式：
{{
  "title": "簡短標題（15字以內）",
  "summary": "整理後的內容摘要（50字以內）",
  "status": "To Do"
}}
status 固定填 "To Do"。
只回傳 JSON，不要其他文字。

訊息內容：{msg_text}"""
    result = call_gemini(prompt)
    if result:
        result = result.replace('```json', '').replace('```', '').strip()
        return json.loads(result)
    return None


def ai_classify_design(msg_text):
    prompt = f"""你是一個設計分類助手。根據以下訊息內容，請回傳 JSON 格式：
{{
  "title": "簡短標題（15字以內）",
  "summary": "整理後的內容摘要（50字以內）",
  "category": "分類名稱"
}}
category 只能從以下選項選一個：設計參考、要的功能、不要的功能、未分類
只回傳 JSON，不要其他文字。

訊息內容：{msg_text}"""
    result = call_gemini(prompt)
    if result:
        result = result.replace('```json', '').replace('```', '').strip()
        return json.loads(result)
    return None


def ai_classify_resource(msg_text):
    prompt = f"""你是一個文化資源分類助手。根據以下訊息內容，請回傳 JSON 格式：
{{
  "title": "單位或資源名稱（15字以內）",
  "summary": "整理後的說明（50字以內）",
  "theme": "主題類別"
}}
theme 只能從以下選項選一個：工藝 & 職人、聚落 & 社區、文化館所、生活美學、當代藝術 & 設計
只回傳 JSON，不要其他文字。

訊息內容：{msg_text}"""
    result = call_gemini(prompt)
    if result:
        result = result.replace('```json', '').replace('```', '').strip()
        return json.loads(result)
    return None


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
    print(f"[Notion] Sending to DB: {database_id}", flush=True)
    print(f"[Notion] Properties: {properties}", flush=True)
    response = requests.post(url, json=payload, headers=headers)
    print(f"[Notion] Status: {response.status_code}", flush=True)
    print(f"[Notion] Response: {response.text}", flush=True)
    return response.status_code == 200


def extract_url(text):
    match = re.search(r'https?://[^\s]+', text)
    return match.group(0) if match else None


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    print(f"[Webhook] Received: {body}", flush=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    raw_text = event.message.text
    print(f"[MSG] raw_text: {raw_text}", flush=True)

    if not raw_text.startswith(f'@{BOT_NAME}'):
        return

    msg_text = clean_mention(raw_text, BOT_NAME)
    print(f"[MSG] cleaned: {msg_text}", flush=True)

    if not msg_text:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=(
                "請在 @AI小幫手 後面加上內容。\n\n"
                "📌 使用方式：\n"
                "  創意想法 → 直接說內容\n"
                "  設計相關 → #設計 / #要的功能 / #不要的功能\n"
                "  資源連結 → 貼網址或說明資源單位"
            ))
        )
        return

    try:
        profile = line_bot_api.get_group_member_profile(
            event.source.group_id, event.source.user_id
        )
        sender_name = profile.display_name
    except Exception as e:
        print(f"[MSG] get_profile error: {e}", flush=True)
        sender_name = "未知使用者"

    success = False
    reply_msg = ""

    # 設計池（有 hashtag 的）
    if "#設計" in msg_text or "#要的功能" in msg_text or "#不要的功能" in msg_text:
        ai = ai_classify_design(msg_text)
        if ai:
            title = ai.get('title', msg_text[:30])
            summary = ai.get('summary', msg_text)
            category = ai.get('category', '未分類')
        else:
            title = msg_text[:30]
            summary = msg_text
            category = "未分類"

        properties = {
            "標題 (Title)": {"title": [{"text": {"content": title}}]},
            "內容 (Content)": {"rich_text": [{"text": {"content": summary}}]},
            "分類 (Category)": {"select": {"name": category}},
            "提出者 (Sender)": {"rich_text": [{"text": {"content": sender_name}}]},
        }
        success = add_to_notion(NOTION_DB_DESIGN, properties)
        reply_msg = f"✅ 已存入設計池\n分類：{category}\n標題：{title}\n提出者：{sender_name}"

    # 資源池（有網址的）
    elif extract_url(msg_text):
        url = extract_url(msg_text)
        ai = ai_classify_resource(msg_text)
        if ai:
            title = ai.get('title', msg_text[:30])
            summary = ai.get('summary', msg_text)
            theme = ai.get('theme', '未分類')
        else:
            title = msg_text[:30]
            summary = msg_text
            theme = "未分類"

        properties = {
            "名稱": {"title": [{"text": {"content": title}}]},
            "網站": {"url": url},
            "主題類別": {"select": {"name": theme}},
            "聯絡人": {"rich_text": [{"text": {"content": sender_name}}]},
        }
        success = add_to_notion(NOTION_DB_RESOURCE, properties)
        reply_msg = f"✅ 已存入資源池\n主題：{theme}\n標題：{title}\n提出者：{sender_name}"

    # 創意池（其他所有訊息）
    else:
        ai = ai_classify_idea(msg_text)
        if ai:
            title = ai.get('title', msg_text[:30])
            summary = ai.get('summary', msg_text)
            status = ai.get('status', 'To Do')
        else:
            title = msg_text[:30]
            summary = msg_text
            status = "To Do"

        properties = {
            "標題 (Title)": {"title": [{"text": {"content": title}}]},
            "內容 (Content)": {"rich_text": [{"text": {"content": summary}}]},
            "狀態 (Status)": {"status": {"name": status}},
            "提出者 (Sender)": {"rich_text": [{"text": {"content": sender_name}}]},
        }
        success = add_to_notion(NOTION_DB_IDEA, properties)
        reply_msg = f"✅ 已存入創意池\n標題：{title}\n提出者：{sender_name}"

    if success:
        line_bot_api.reply_message(
            event.reply_token, TextSendMessage(text=reply_msg)
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⚠️ 寫入 Notion 失敗，請確認設定正確。")
        )


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
