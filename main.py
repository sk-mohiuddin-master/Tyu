import sys
import os
import re
import requests
import json
import time
import threading
from flask import Flask, request, jsonify

# === CONFIG ===
GOOGLE_SHEET_URL = 'https://docs.google.com/spreadsheets/d/1NxgIRZlDh_vPM3ae2pXcpff6igk0z2sJEQh2mNSCrt0/gviz/tq?tqx=out:json'
BOT_TOKEN = '7659077268:AAG7wxW9U9PBzDx4PWAefKRmPJbyDQWwO9I'
CHAT_ID = -1002358978701
ALLOWED_CHAT_IDS = [CHAT_ID]

COL = {
    'UID': 2,
    'Package': 3,
    'Price': 4,
    'Quantity': 8,
    'Order Confirmation': 6,
    'Order ID': 7,
    'Payment Method': 10,
    'Transaction ID': 11
}

previous_order_ids = set()
last_update_id = None
guid_public_status = False

# === UTILS ===
def clean(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()

def fetch_nickname(uid: str) -> str:
    regions = ["sg", "bd"]
    for region in regions:
        try:
            url = f"https://glob-info2.vercel.app/info?uid={uid}"
            response = requests.get(url, timeout=10)
            data = response.json()
            nickname = data.get("basicInfo", {}).get("nickname")
            if nickname and nickname != "Unknown":
                return nickname
        except Exception:
            continue
    return "❌ Error"

def _fetch_sheet_raw():
    try:
        res = requests.get(GOOGLE_SHEET_URL, timeout=15)
        res.raise_for_status()
        json_text = res.text[res.text.find('{'):-2]
        return json.loads(json_text)
    except Exception as e:
        print("❌ Error fetching sheet raw:", e)
        return None

def get_full_sheet():
    data = _fetch_sheet_raw()
    if not data:
        return []
    rows = data['table']['rows']
    return [[cell['v'] if cell else '' for cell in row['c']] for row in rows]

def get_recent_rows(limit=5):
    data = _fetch_sheet_raw()
    if not data:
        return []
    rows = data['table']['rows'][-limit:]
    return [[cell['v'] if cell else '' for cell in row['c']] for row in rows]

def send_message(text, chat_id=CHAT_ID, reply_to=None):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown'
    }
    if reply_to:
        payload['reply_to_message_id'] = reply_to
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print("❌ Telegram send error:", e)

# === ORDER DETAILS ===
def send_order_details(row, is_new=True, chat_id=CHAT_ID):
    order_id = clean(row[COL['Order ID']])
    uid = clean(row[COL['UID']])
    nickname = fetch_nickname(uid)
    package = clean(row[COL['Package']])
    quantity = clean(row[COL['Quantity']])
    price = clean(row[COL['Price']])
    payment_method = clean(row[COL['Payment Method']])
    txn_id = clean(row[COL['Transaction ID']])
    confirmation = clean(row[COL['Order Confirmation']])
    include_txn = payment_method.lower() not in ["cash", "etc", "", "n/a", "none"]

    if is_new:
        send_message(f"📢 *New order found:* `{order_id}`", chat_id)

    msg = (
        "```gameflexbd Order Details\n"
        "▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔\n"
        f"🆔 ORDER NUMBER: {order_id}\n"
        f"🔰 NAME: {nickname}\n"
        f"👤 UID: {uid}\n\n"
        f"📦 PACKAGE: {package}\n"
        f"🔢 QUANTITY: {quantity}\n\n"
        f"💰 PRICE: ৳{price}\n"
        f"💳 PAYMENT METHOD: {payment_method}\n"
        + (f"🧾 TRANSACTION ID: {txn_id}\n" if include_txn and txn_id else "") +
        "▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔\n"
        "```"
    )
    send_message(msg, chat_id)

    if confirmation and confirmation.lower() != "none":
        confirmation_msg = (
            f"✅ *Confirmation for Order ID:* `{order_id}`\n"
            f"🔰 Name: {nickname}\n"
            f"🔗 {confirmation}"
        )
        send_message(confirmation_msg, chat_id)

def process_new_orders(rows):
    global previous_order_ids
    for row in rows:
        if len(row) <= COL['Order ID']:
            continue
        order_id = row[COL['Order ID']]
        if not order_id or order_id in previous_order_ids:
            continue
        send_order_details(row, is_new=True)
        previous_order_ids.add(order_id)

def normalize_id(val):
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        val = str(val)
    s = str(val).strip()
    m = re.search(r'\d+', s)
    return m.group(0) if m else ""

def handle_gcheck_command(order_id=None, chat_id=None, reply_to_msg_id=None):
    print(f"[DEBUG] handle_gcheck_command(order_id={order_id})")
    rows = get_full_sheet()
    if not rows:
        send_message("❌ Could not fetch order sheet.", chat_id=chat_id, reply_to=reply_to_msg_id)
        return

    if order_id:
        normalized_input = normalize_id(order_id)
        print(f"[DEBUG] normalized_input='{normalized_input}'")
        for row in rows:
            if len(row) <= COL['Order ID']:
                continue
            sheet_order_id = normalize_id(row[COL['Order ID']])
            if sheet_order_id == normalized_input:
                send_message(
                    f"📝 *Here's the order information for ID:* `{normalized_input}`",
                    chat_id=chat_id, reply_to=reply_to_msg_id)
                send_order_details(row, is_new=False, chat_id=chat_id)
                return
        send_message(f"❌ Order ID `{order_id}` not found.", chat_id=chat_id, reply_to=reply_to_msg_id)
    else:
        row = rows[-1]
        last_id = clean(row[COL['Order ID']])
        send_message(f"📝 *Showing the latest order ID:* `{last_id}`", chat_id=chat_id, reply_to=reply_to_msg_id)
        send_order_details(row, is_new=False, chat_id=chat_id)

def check_for_commands():
    global last_update_id, guid_public_status
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/getUpdates'
    if last_update_id is not None:
        url += f'?offset={last_update_id + 1}'

    try:
        res = requests.get(url, timeout=20)
        res.raise_for_status()
        updates = res.json().get("result", [])
    except Exception as e:
        print("❌ Error getting updates:", e)
        return

    if not updates:
        return

    for update in updates:
        last_update_id = update['update_id']
        message = update.get('message', {})
        if not message:
            continue
        text = message.get('text', '')
        if not text:
            continue
        user_chat_id = message.get('chat', {}).get('id')
        msg_id = message.get('message_id')
        lower = text.strip().lower()
        lower_noslash = lower.lstrip('/')

        if lower_noslash == "start":
            status = "✅ Guid is PUBLIC" if guid_public_status else "❌ Guid is PRIVATE"
            send_message(f"Hello!\n{status}", chat_id=user_chat_id, reply_to=msg_id)
            continue

        if user_chat_id in ALLOWED_CHAT_IDS:
            if lower_noslash == "guid onpublic":
                guid_public_status = True
                send_message("✅ Guid is now PUBLIC", chat_id=user_chat_id, reply_to=msg_id)
                continue
            if lower_noslash == "guid offpublic":
                guid_public_status = False
                send_message("❌ Guid is now PRIVATE", chat_id=user_chat_id, reply_to=msg_id)
                continue

        if lower_noslash.startswith("guid"):
            if (user_chat_id in ALLOWED_CHAT_IDS) or guid_public_status:
                parts = text.strip().split()
                if len(parts) == 2:
                    uid = parts[1]
                    nickname = fetch_nickname(uid)
                    msg = (
                        "```Account-Information\n"
                        f"🔰 Nickname: {nickname}\n"
                        f"👤 UID: {uid}\n```"
                    )
                    send_message(msg, chat_id=user_chat_id, reply_to=msg_id)
                else:
                    send_message("⚠️ Usage:\nGuid <UID>\nExample:\nGuid 1438204739", chat_id=user_chat_id, reply_to=msg_id)
            else:
                send_message("❌ Guid is PRIVATE", chat_id=user_chat_id, reply_to=msg_id)
            continue

        if lower_noslash.startswith("gcheck"):
            if user_chat_id in ALLOWED_CHAT_IDS:
                parts = text.strip().split(maxsplit=1)
                order_id = parts[1] if len(parts) == 2 else None
                handle_gcheck_command(order_id=order_id, chat_id=user_chat_id, reply_to_msg_id=msg_id)
            else:
                send_message("❌ You are not allowed to use this command.", chat_id=user_chat_id, reply_to=msg_id)
            continue

# === PLAYER REGION API ===
def get_player_info(uid):
    url = "https://shop2game.com/api/auth/player_id_login"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://shop2game.com",
        "Referer": "https://shop2game.com/app",
        "User-Agent": "Mozilla/5.0",
    }
    payload = {
        "app_id": 100067,
        "login_id": uid,
        "app_server_id": 0,
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response.json() if response.status_code == 200 else None
    except:
        return None

# === BOT LOOP ===
def bot_loop():
    print("🤖 Bot started and monitoring orders...")
    while True:
        try:
            rows = get_recent_rows(limit=5)
            if rows:
                process_new_orders(rows)
            check_for_commands()
        except Exception as e:
            print("❌ Bot loop error:", e)
        time.sleep(2)

# === FLASK APP ===
app = Flask(__name__)

@app.route('/')
def home():
    return '✅ Bot is live!'

@app.route('/region', methods=['GET'])
def region():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"message": "Please provide a UID"}), 400

    player_info = get_player_info(uid)
    if player_info and player_info.get("nickname") and player_info.get("region"):
        # Dummy data
        likes = 1234
        level = 60
        return jsonify({
            "uid": uid,
            "nickname": player_info["nickname"],
            "region": player_info["region"],
            "likes": likes,
            "level": level
        }), 200
    else:
        return jsonify({"message": "UID not found, please check the UID"}), 404

# === ENTRY POINT ===
if __name__ == '__main__':
    threading.Thread(target=bot_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=3000)
