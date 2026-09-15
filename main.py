import os
import re
import sqlite3
import threading
import requests
from flask import Flask
from telebot import TeleBot, types

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 7958546546  # آيدي المالك الخاص بك

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

bot = TeleBot(BOT_TOKEN)

# --- Flask Keep-Alive Server ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running 24/7!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- Database Setup ---
DB_NAME = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Users table
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)''')
    # Channels table
    cursor.execute('''CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY, channel_link TEXT)''')
    # Settings table
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute('''INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance', 'off')''')
    conn.commit()
    conn.close()

init_db()

def is_maintenance():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key='maintenance'")
    res = cursor.fetchone()
    conn.close()
    return res[0] == 'on' if res else False

def add_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def get_channels():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_link FROM channels")
    rows = cursor.fetchall()
    conn.close()
    return rows

# --- Mandatory Subscription Check ---
def check_sub(user_id):
    if user_id == ADMIN_ID:
        return True, []
    
    channels = get_channels()
    if not channels:
        return True, []
    
    unsubbed = []
    for ch_id, ch_link in channels:
        try:
            member = bot.get_chat_member(ch_id, user_id)
            if member.status in ['left', 'kicked']:
                unsubbed.append((ch_id, ch_link))
        except Exception:
            # If bot can't check, assume unsubscribed or handle error
            unsubbed.append((ch_id, ch_link))
            
    return (len(unsubbed) == 0), unsubbed

# --- TikTok Downloader Core ---
def download_tiktok(url):
    try:
        # Resolve short URLs
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
        final_url = res.url

        # API Request
        api_url = f"https://api.tiklydown.eu.org/api/download?url={final_url}"
        api_res = requests.get(api_url, timeout=15)
        if api_res.status_code == 200:
            data = api_res.json()
            # Try getting video stream URL
            video_url = data.get('video', {}).get('noWatermark') or data.get('video', {}).get('watermark')
            if video_url:
                return video_url
    except Exception as e:
        print(f"Download Error: {e}")
    return None

# --- Command Handlers ---

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    add_user(user_id)
    
    # Check maintenance
    if is_maintenance() and user_id != ADMIN_ID:
        bot.reply_to(message, "⚠️ البوت حالياً في وضع الصيانة، يرجى المحاولة لاحقاً.")
        return

    # Check Subscription
    is_ok, unsubbed = check_sub(user_id)
    if not is_ok:
        markup = types.InlineKeyboardMarkup()
        for i, (ch_id, ch_link) in enumerate(unsubbed, start=1):
            btn = types.InlineKeyboardButton(f"قناة الاشتراك {i}", url=ch_link)
            markup.add(btn)
        markup.add(types.InlineKeyboardButton("تحقق من الاشتراك 🔄", callback_data="check_sub"))
        bot.reply_to(message, "⚠️ اشترك في القنوات التالية لاستخدام البوت:", reply_markup=markup)
        return

    bot.reply_to(message, "أهلاً بك! أرسل لي رابط فيديو من تيك توك لتحميله بدون علامة مائية.")

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def callback_check_sub(call):
    is_ok, _ = check_sub(call.from_user.id)
    if is_ok:
        bot.answer_callback_query(call.id, "تم التحقق بنجاح! يمكنك استخدام البوت الآن.")
        bot.send_message(call.message.chat.id, "أرسل لي رابط فيديو من تيك توك الآن.")
    else:
        bot.answer_callback_query(call.id, "لم تشترك في جميع القنوات بعد!", show_alert=True)

# --- Admin Commands ---

@bot.message_handler(commands=['admin', 'panel'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "الأمر غير معروف. استخدم /start للبدء.")
        return
    
    msg = (
        "لوحة تحكم الأدمن 🛠️:\n\n"
        "/addch @username link - إضافة قناة اشتراك إجباري\n"
        "/delch @username - حذف قناة اشتراك\n"
        "/channels - عرض القنوات\n"
        "/maintenance - تفعيل/تعطيل وضع الصيانة\n"
        "/bc النص - إذاعة لجميع المستخدمين"
    )
    bot.reply_to(message, msg)

@bot.message_handler(commands=['channels'])
def list_channels(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "الأمر غير معروف. استخدم /start للبدء.")
        return
    
    channels = get_channels()
    if not channels:
        bot.reply_to(message, "لا توجد قنوات اشتراك إزامية حالياً.")
        return
    
    res = "القنوات المضافة حالياً:\n"
    for ch_id, ch_link in channels:
        res += f"- {ch_id} ({ch_link})\n"
    bot.reply_to(message, res)

@bot.message_handler(commands=['addch'])
def add_channel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "الأمر غير معروف. استخدم /start للبدء.")
        return
    
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "الاستخدام الصحيح:\n/addch @channel_id https://t.me/channel_link")
        return
    
    ch_id, ch_link = parts[1], parts[2]
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO channels VALUES (?, ?)", (ch_id, ch_link))
    conn.commit()
    conn.close()
    bot.reply_to(message, f"تمت إضافة القناة {ch_id} بنجاح!")

@bot.message_handler(commands=['delch'])
def del_channel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "الأمر غير معروف. استخدم /start للبدء.")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "الاستخدام الصحيح:\n/delch @channel_id")
        return
    
    ch_id = parts[1]
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id=?", (ch_id,))
    conn.commit()
    conn.close()
    bot.reply_to(message, f"تمت إزالة القناة {ch_id} بنجاح.")

@bot.message_handler(commands=['maintenance'])
def toggle_maintenance(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "الأمر غير معروف. استخدم /start للبدء.")
        return
    
    current = is_maintenance()
    new_status = 'off' if current else 'on'
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value=? WHERE key='maintenance'", (new_status,))
    conn.commit()
    conn.close()
    
    status_text = "تم تفعيل وضع الصيانة 🛑" if new_status == 'on' else "تم تعطيل وضع الصيانة وإعادة تشغيل البوت 🟢"
    bot.reply_to(message, status_text)

# --- Message Handler for TikTok Links ---

@bot.message_handler(func=lambda m: True)
def handle_messages(message):
    user_id = message.from_user.id
    
    if is_maintenance() and user_id != ADMIN_ID:
        bot.reply_to(message, "⚠️ البوت حالياً في وضع الصيانة.")
        return

    text = message.text or ""
    
    # Check if text contains TikTok link
    tiktok_regex = r'(https?://(?:www\.|vt\.|vm\.)?tiktok\.com/[^\s]+)'
    match = re.search(tiktok_regex, text)
    
    if match:
        is_ok, unsubbed = check_sub(user_id)
        if not is_ok:
            bot.reply_to(message, "⚠️ يجب عليك الاشتراك بالقنوات أولاً لطلب الفيديو. أرسل /start للإكمال.")
            return
            
        url = match.group(0)
        wait_msg = bot.reply_to(message, "جاري تحميل الفيديو، يرجى الانتظار... ⏳")
        
        video_stream = download_tiktok(url)
        if video_stream:
            try:
                bot.send_video(message.chat.id, video_stream, reply_to_message_id=message.message_id)
                bot.delete_message(message.chat.id, wait_msg.message_id)
            except Exception as e:
                bot.edit_message_text("حدث خطأ أثناء إرسال الفيديو.", message.chat.id, wait_msg.message_id)
        else:
            bot.edit_message_text("حدث خطأ أثناء تحميل الفيديو. تأكد من صحة الرابط وحاول مجدداً.", message.chat.id, wait_msg.message_id)
    else:
        if text.startswith('/'):
            bot.reply_to(message, "الأمر غير معروف. استخدم /start للبدء.")
        else:
            bot.reply_to(message, "يرجى إرسال رابط تيك توك صحيح.")

# --- Start Threads and Polling ---
if __name__ == '__main__':
    # Start Flask Web Server
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start Telegram Bot
    print("Bot is running...")
    bot.infinity_polling(skip_pending=True)
