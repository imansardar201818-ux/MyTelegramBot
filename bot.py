# ============================================================
# 📦 ایمپورت‌ها
# ============================================================
from builtins import int
import os
import re
import time
import json
import logging
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

import telebot
from telebot import types

load_dotenv()

# ============================================================
# ⚙️ تنظیمات اولیه (از محیط)
# ============================================================
ADMIN_ID = int(os.getenv("ADMIN_ID", 8915086212))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@StoreSardaarApple")
BONUS_PERCENT = int(os.getenv("BONUS_PERCENT", 5))
BANK_CARD = os.getenv("BANK_CARD", "5022291331447233")
BANK_OWNER = os.getenv("BANK_OWNER", "ایمان سردار راد")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8904951204:AAFS8Ae27-xuBSfarkDLyTm1nMbNB2v6dQo").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN در Environment Variables تنظیم نشده است.")

bot = telebot.TeleBot(BOT_TOKEN)
bot.delete_webhook()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# 💾 دیتابیس SQLite (با ساختار اصلاح‌شده)
# ============================================================
DB_PATH = "sardar_app_store.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS apple_ids (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            apple_id TEXT UNIQUE,
            password TEXT,
            birth_date TEXT,
            school TEXT,
            job TEXT,
            parentsmeet TEXT,
            security_q1 TEXT,
            security_a1 TEXT,
            security_q2 TEXT,
            security_a2 TEXT,
            security_q3 TEXT,
            security_a3 TEXT,
            product_type TEXT DEFAULT 'ready',
            icloud_status TEXT DEFAULT 'with_icloud',
            warranty_type TEXT DEFAULT '31days',
            used INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT NULL,
            date_used TEXT DEFAULT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password TEXT,
            used INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT NULL,
            date_used TEXT DEFAULT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            join_date TEXT,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            email TEXT,
            birth_date TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            order_id INTEGER UNIQUE,
            product_type TEXT,
            product_detail TEXT,
            password TEXT,
            purchase_date TEXT,
            status TEXT DEFAULT 'pending'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS failed_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_type TEXT,
            price INTEGER,
            reason TEXT,
            date TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS temp_orders (
            order_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            product_name TEXT,
            price INTEGER,
            email TEXT,
            email_option TEXT,
            is_for_apple INTEGER DEFAULT 0,
            photo_id TEXT,
            status TEXT DEFAULT 'waiting_payment',
            created_at TEXT,
            updated_at TEXT,
            icloud_status TEXT,
            warranty_type TEXT,
            order_type TEXT DEFAULT 'product'
        )
    ''')

    # مهاجرت دیتابیس برای نسخه‌های قدیمی
    # سفارش افزایش موجودی با order_type=balance از سفارش محصول کاملاً جدا می‌شود.
    try:
        cursor.execute("ALTER TABLE temp_orders ADD COLUMN order_type TEXT DEFAULT 'product'")
    except sqlite3.OperationalError:
        pass  # ستون از قبل وجود دارد

    # سفارش‌های قدیمی که نامشان افزایش موجودی است نیز به‌عنوان balance علامت‌گذاری شوند.
    try:
        cursor.execute("UPDATE temp_orders SET order_type = 'balance' WHERE TRIM(product_name) = 'افزایش موجودی' AND (order_type IS NULL OR order_type = 'product')")
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS warranty_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            apple_id TEXT,
            request_date TEXT,
            status TEXT DEFAULT 'pending'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS unlock_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            apple_id TEXT,
            password TEXT,
            email TEXT,
            email_password TEXT,
            request_date TEXT,
            status TEXT DEFAULT 'pending'
        )
    ''')

    cursor.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)", ("card_number", BANK_CARD))
    cursor.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)", ("card_owner", BANK_OWNER))
    cursor.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)", ("bonus_percent", str(BONUS_PERCENT)))
    cursor.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)", ("last_order_id", "1000"))

    conn.commit()
    return conn

# ============================================================
# 📊 توابع مدیریت تنظیمات
# ============================================================
def get_setting(key):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT setting_value FROM bot_settings WHERE setting_key = ?", (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def update_setting(key, value):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE bot_settings SET setting_value = ? WHERE setting_key = ?", (value, key))
    conn.commit()
    conn.close()

# ============================================================
# 📦 توابع مدیریت سفارش‌ها
# ============================================================
def get_next_order_id():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT setting_value FROM bot_settings WHERE setting_key = 'last_order_id'")
    result = cursor.fetchone()
    if result:
        current_id = int(result[0])
        new_id = current_id + 1
        cursor.execute("UPDATE bot_settings SET setting_value = ? WHERE setting_key = 'last_order_id'", (str(new_id),))
        conn.commit()
        conn.close()
        return new_id
    else:
        cursor.execute("INSERT INTO bot_settings (setting_key, setting_value) VALUES (?, ?)", ("last_order_id", "1001"))
        conn.commit()
        conn.close()
        return 1001

def payment_markup(order_id):
    """روش‌های پرداخت بانکی؛ برای شارژ کیف پول استفاده می‌شود."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💳 درگاه پرداخت", callback_data=f"gateway_{order_id}"),
        types.InlineKeyboardButton("🏦 کارت به کارت", callback_data=f"card_to_card_{order_id}")
    )
    markup.add(types.InlineKeyboardButton("❌ لغو سفارش", callback_data=f"cancel_order_{order_id}"))
    return markup

def payment_options_markup(order_id):
    """
    برای خرید محصول: اگر موجودی کیف پول کافی باشد، فقط پرداخت از موجودی را نشان می‌دهد.
    اگر کافی نباشد، روش‌های بانکی نمایش داده می‌شوند.
    """
    temp = get_temp_order(order_id)
    if not temp:
        return payment_markup(order_id)

    price = int(temp.get("price") or 0)
    balance = int(get_user_balance(temp["user_id"]) or 0)
    markup = types.InlineKeyboardMarkup(row_width=1)

    if price > 0 and balance >= price and not is_balance_order(temp):
        markup.add(types.InlineKeyboardButton(
            f"💰 پرداخت از موجودی ({price:,} تومان)",
            callback_data=f"balance_pay_{order_id}"
        ))
    else:
        markup.add(
            types.InlineKeyboardButton("💳 درگاه پرداخت", callback_data=f"gateway_{order_id}"),
            types.InlineKeyboardButton("🏦 کارت به کارت", callback_data=f"card_to_card_{order_id}")
        )

    markup.add(types.InlineKeyboardButton("❌ لغو سفارش", callback_data=f"cancel_order_{order_id}"))
    return markup

def pay_order_with_balance(order_id, user_id):
    """پرداخت کامل یک محصول از کیف پول با کسر اتمیک موجودی؛ از دوبار کسر جلوگیری می‌کند."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT * FROM temp_orders WHERE order_id = ? AND user_id = ?", (order_id, user_id))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return False, "not_found", None, None

        temp = dict(row)
        if temp["status"] != "waiting_payment":
            conn.rollback()
            return False, "not_payable", temp, None
        if is_balance_order(temp):
            conn.rollback()
            return False, "invalid_order_type", temp, None

        price = int(temp["price"] or 0)
        if price <= 0:
            conn.rollback()
            return False, "invalid_price", temp, None

        cursor.execute("""
            UPDATE users
            SET balance = balance - ?
            WHERE user_id = ? AND balance >= ?
        """, (price, user_id, price))
        if cursor.rowcount != 1:
            conn.rollback()
            return False, "insufficient_balance", temp, None

        cursor.execute("""
            UPDATE temp_orders
            SET status = 'confirmed', updated_at = ?
            WHERE order_id = ? AND user_id = ? AND status = 'waiting_payment'
        """, (time.strftime("%Y-%m-%d %H:%M:%S"), order_id, user_id))
        if cursor.rowcount != 1:
            conn.rollback()
            return False, "already_processed", temp, None

        cursor.execute("UPDATE user_purchases SET status = 'confirmed' WHERE order_id = ? AND user_id = ?", (order_id, user_id))
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        new_balance = int(result[0]) if result else 0
        conn.commit()
        return True, "success", temp, new_balance
    except Exception:
        conn.rollback()
        logger.exception(f"خطا در پرداخت از موجودی سفارش #{order_id}")
        return False, "error", None, None
    finally:
        conn.close()

def get_active_order(user_id):
    """فقط سفارش‌های باز کاربر را برمی‌گرداند؛ این کار مانع قاطی شدن رسیدها می‌شود."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM temp_orders
        WHERE user_id = ?
        AND status IN ('waiting_payment', 'waiting_receipt', 'receipt_received', 'confirmed', 'delivering')
        ORDER BY created_at DESC
        LIMIT 1
    """, (user_id,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None

def cancel_order_by_id(order_id, user_id, reason="لغو توسط کاربر"):
    """لغو اتمیک سفارش و ثبت آن در تاریخچه."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM temp_orders WHERE order_id = ? AND user_id = ?", (order_id, user_id))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "not_found", None

    status = row["status"]
    cancellable = status in ("waiting_payment", "waiting_receipt")
    if not cancellable:
        conn.close()
        return False, "not_cancellable", dict(row)

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE temp_orders SET status = ?, updated_at = ? WHERE order_id = ? AND user_id = ? AND status IN ('waiting_payment','waiting_receipt')",
                ("cancelled", now, order_id, user_id))
    changed = cursor.rowcount == 1
    if changed:
        cursor.execute("UPDATE user_purchases SET status = ? WHERE order_id = ? AND user_id = ?",
                    ("cancelled", order_id, user_id))
        cursor.execute("INSERT INTO failed_purchases (user_id, product_type, price, reason, date) VALUES (?, ?, ?, ?, ?)",
                    (user_id, row["product_name"], row["price"], reason, now))
    conn.commit()
    conn.close()
    return changed, ("cancelled" if changed else "race"), dict(row)

def create_temp_order(user_id, product_name, price, email="", email_option="", is_for_apple=0, icloud_status=None, warranty_type=None, order_type="product"):
    order_id = get_next_order_id()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO temp_orders 
        (order_id, user_id, product_name, price, email, email_option, is_for_apple, status, created_at, updated_at, icloud_status, warranty_type, order_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_id, user_id, product_name, price, email, email_option, is_for_apple, 'waiting_payment',
        time.strftime("%Y-%m-%d %H:%M:%S"), time.strftime("%Y-%m-%d %H:%M:%S"), icloud_status, warranty_type, order_type))
    conn.commit()
    conn.close()

    # ثبت سفارش در تاریخچه از همان ابتدا تا وضعیت پرداخت/تحویل
    # بتواند روی همان رکورد به‌روزرسانی شود.
    create_purchase_record(user_id, order_id, product_name, "", "")
    return order_id

def update_temp_order(order_id, **kwargs):
    if not kwargs:
        return False

    conn = get_db()
    cursor = conn.cursor()
    fields = []
    values = []

    for key, value in kwargs.items():
        fields.append(f"{key} = ?")
        values.append(value)

    fields.append("updated_at = ?")
    values.append(time.strftime("%Y-%m-%d %H:%M:%S"))
    values.append(order_id)

    query = f"UPDATE temp_orders SET {', '.join(fields)} WHERE order_id = ?"
    cursor.execute(query, tuple(values))
    changed = cursor.rowcount
    conn.commit()
    conn.close()

    logger.info(f"🗄️ ORDER UPDATE | order={order_id} | changed={changed} | data={kwargs}")
    return changed == 1

def get_temp_order(order_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM temp_orders WHERE order_id = ?", (order_id,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None

def is_balance_order(temp):
    """تشخیص قطعی سفارش شارژ کیف پول؛ هرگز بر اساس مسیر تحویل محصول تصمیم نمی‌گیریم."""
    if not temp:
        return False
    order_type = (temp.get("order_type") or "").strip().lower()
    product_name = (temp.get("product_name") or "").strip()
    return order_type == "balance" or product_name == "افزایش موجودی"

def delete_temp_order(order_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM temp_orders WHERE order_id = ?", (order_id,))
    conn.commit()
    conn.close()

# ============================================================
# 👤 توابع مدیریت کاربران
# ============================================================
def get_user_balance(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0]
    else:
        add_new_user(user_id)
        return 0

def add_new_user(user_id, first_name="", last_name="", phone="", email="", birth_date=""):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT OR IGNORE INTO users 
        (user_id, balance, join_date, first_name, last_name, phone, email, birth_date) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, 0, time.strftime("%Y-%m-%d %H:%M:%S"), first_name, last_name, phone, email, birth_date)
    )
    conn.commit()
    conn.close()

def update_user_balance(user_id, new_balance):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    conn.close()

def get_user_info(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, balance, join_date, first_name, last_name, phone, email, birth_date FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {
            "user_id": result[0],
            "balance": result[1],
            "join_date": result[2],
            "first_name": result[3] or "نامشخص",
            "last_name": result[4] or "نامشخص",
            "phone": result[5] or "نامشخص",
            "email": result[6] or "نامشخص",
            "birth_date": result[7] or "نامشخص"
        }
    return None

def get_all_users():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, balance, join_date, first_name, last_name, phone, email, birth_date FROM users")
    users = cursor.fetchall()
    conn.close()
    return users

# ============================================================
# 📦 توابع ذخیره‌سازی خریدها
# ============================================================
def create_purchase_record(user_id, order_id, product_type, product_detail, password):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT OR IGNORE INTO user_purchases 
        (user_id, order_id, product_type, product_detail, password, purchase_date, status) 
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, order_id, product_type, product_detail, password, time.strftime("%Y-%m-%d %H:%M:%S"), "pending")
    )
    conn.commit()
    conn.close()

def update_purchase_status(order_id, new_status, product_detail="", password=""):
    conn = get_db()
    cursor = conn.cursor()
    if product_detail or password:
        cursor.execute("UPDATE user_purchases SET status = ?, product_detail = ?, password = ? WHERE order_id = ?", 
                    (new_status, product_detail, password, order_id))
    else:
        cursor.execute("UPDATE user_purchases SET status = ? WHERE order_id = ?", (new_status, order_id))
    conn.commit()
    conn.close()

def save_failed_purchase(user_id, product_type, price, reason="لغو توسط کاربر"):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO failed_purchases (user_id, product_type, price, reason, date) VALUES (?, ?, ?, ?, ?)",
        (user_id, product_type, price, reason, time.strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

def get_user_purchase_stats(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM user_purchases WHERE user_id = ? AND status = 'completed'", (user_id,))
    success_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM failed_purchases WHERE user_id = ?", (user_id,))
    failed_count = cursor.fetchone()[0]
    conn.close()
    return success_count, failed_count

# ============================================================
# 📊 توابع آمار و موجودی
# ============================================================
def get_inventory_stats():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM apple_ids WHERE used = 0")
    apple_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM emails WHERE used = 0")
    email_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    conn.close()
    return apple_count, email_count, user_count

def check_inventory_and_notify():
    try:
        apple_count, email_count, _ = get_inventory_stats()
        if apple_count < 5:
            bot.send_message(ADMIN_ID, f"⚠️ هشدار: تعداد اپل‌آیدی‌های موجود کمتر از ۵ است (تعداد: {apple_count})")
        if email_count < 5:
            bot.send_message(ADMIN_ID, f"⚠️ هشدار: تعداد ایمیل‌های موجود کمتر از ۵ است (تعداد: {email_count})")
    except Exception as e:
        logger.error(f"خطا در ارسال نوتیفیکیشن به ادمین: {e}")

# ============================================================
# 💾 توابع مدیریت اپل‌آیدی و ایمیل
# ============================================================
def get_unused_apple_id(product_type='ready', icloud_status='with_icloud', warranty_type='31days'):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            id, apple_id, password, birth_date, school, job, parentsmeet,
            security_q1, security_a1, security_q2, security_a2, security_q3, security_a3
        FROM apple_ids 
        WHERE used = 0 AND product_type = ? AND icloud_status = ? AND warranty_type = ?
        LIMIT 1
    ''', (product_type, icloud_status, warranty_type))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {
            "id": result[0],
            "apple_id": result[1],
            "password": result[2],
            "birth_date": result[3] or "ندارد",
            "school": result[4] or "ندارد",
            "job": result[5] or "ندارد",
            "parentsmeet": result[6] or "ندارد",
            "security_q1": result[7] or "ندارد",
            "security_a1": result[8] or "ندارد",
            "security_q2": result[9] or "ندارد",
            "security_a2": result[10] or "ندارد",
            "security_q3": result[11] or "ندارد",
            "security_a3": result[12] or "ندارد"
        }
    return None

def get_unused_email():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, password FROM emails WHERE used = 0 LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    if result:
        return {"id": result[0], "email": result[1], "password": result[2]}
    return None

def mark_apple_id_used(item_id, user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE apple_ids SET used = 1, user_id = ?, date_used = ? WHERE id = ?",
        (user_id, time.strftime("%Y-%m-%d %H:%M:%S"), item_id)
    )
    conn.commit()
    conn.close()
    check_inventory_and_notify()

def mark_email_used(item_id, user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE emails SET used = 1, user_id = ?, date_used = ? WHERE id = ?",
        (user_id, time.strftime("%Y-%m-%d %H:%M:%S"), item_id)
    )
    conn.commit()
    conn.close()
    check_inventory_and_notify()

def add_apple_id(apple_id, password, birth_date="", school="", job="", parentsmeet="", 
                security_q1="", security_a1="", security_q2="", security_a2="", 
                security_q3="", security_a3="", product_type='ready', icloud_status='with_icloud', warranty_type='31days'):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO apple_ids 
            (apple_id, password, birth_date, school, job, parentsmeet, 
            security_q1, security_a1, security_q2, security_a2, security_q3, security_a3,
            product_type, icloud_status, warranty_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (apple_id, password, birth_date, school, job, parentsmeet, 
            security_q1, security_a1, security_q2, security_a2, security_q3, security_a3,
            product_type, icloud_status, warranty_type))
        conn.commit()
        conn.close()
        check_inventory_and_notify()
        return True
    except Exception as e:
        logger.error(f"خطا در افزودن اپل‌آیدی: {e}")
        conn.close()
        return False

def get_all_apple_ids():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, apple_id, password, birth_date, school, job, parentsmeet, used, user_id, product_type, icloud_status, warranty_type FROM apple_ids")
    result = cursor.fetchall()
    conn.close()
    return result

def get_all_emails():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, password, used, user_id FROM emails")
    result = cursor.fetchall()
    conn.close()
    return result

def add_email(email, password):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO emails (email, password) VALUES (?, ?)", (email, password))
        conn.commit()
        conn.close()
        check_inventory_and_notify()
        return True
    except Exception as e:
        logger.error(f"خطا در افزودن ایمیل: {e}")
        conn.close()
        return False

# ============================================================
# 🔒 توابع بررسی عضویت در کانال
# ============================================================
def is_member(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

def join_channel_button():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🔗 عضویت در کانال", url="https://t.me/StoreSardaarApple"))
    markup.add(types.InlineKeyboardButton("✅ عضویت دارم", callback_data="check_membership"))
    return markup

# ============================================================
# 🏠 منوی اصلی
# ============================================================
def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("تعرفه خدمات 💎")
    btn2 = types.KeyboardButton("Apple ID ساخت 🍏")
    btn3 = types.KeyboardButton("Apple ID آماده 📦")
    btn4 = types.KeyboardButton("ایمیل آماده 📧")
    btn5 = types.KeyboardButton("ساخت ایمیل 📧")
    btn6 = types.KeyboardButton("گارانتی 🛡️")
    btn7 = types.KeyboardButton("پشتیبانی 👨‍💻")
    btn8 = types.KeyboardButton("افزایش موجودی 💰")
    btn9 = types.KeyboardButton("خریدهای من 🛒")
    btn10 = types.KeyboardButton("آنلاک ایل آیدی 🔄")
    btn11 = types.KeyboardButton("پنل ادمین 🌻") if user_id == ADMIN_ID else None
    
    markup.row(btn1)
    markup.row(btn2, btn3)
    markup.row(btn4, btn5)
    markup.row(btn6, btn7)
    markup.row(btn8)
    markup.row(btn9, btn10)
    if btn11:
        markup.row(btn11)
    return markup

# ============================================================
# 📞 check_membership
# ============================================================
@bot.callback_query_handler(func=lambda call: call.data == "check_membership")
def check_membership(call):
    user_id = call.message.chat.id
    if is_member(user_id):
        bot.answer_callback_query(call.id, "✅ شما عضو کانال هستید.")
        bot.send_message(user_id, "✅ عضویت شما تأیید شد. به منوی اصلی خوش آمدید!", reply_markup=main_menu(user_id))
    else:
        bot.answer_callback_query(call.id, "❌ شما هنوز عضو کانال نشده‌اید.")
        bot.send_message(user_id, "❌ لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())

# ============================================================
# 🚀 شروع
# ============================================================
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id
    add_new_user(user_id, first_name=message.from_user.first_name, last_name=message.from_user.last_name or "")
    if is_member(user_id):
        balance = get_user_balance(user_id)
        bot.send_message(
            user_id,
            f"👋 سلام {message.from_user.first_name} عزیز!\nبه ربات فروشگاه SARDAR VIP خوش آمدید.\n💰 موجودی شما: {balance:,} تومان",
            reply_markup=main_menu(user_id)
        )
    else:
        bot.send_message(
            user_id,
            "🔒 لطفاً ابتدا در کانال عضو شوید تا بتوانید از خدمات استفاده کنید.",
            reply_markup=join_channel_button()
        )

# ============================================================
# 💎 تعرفه خدمات
# ============================================================
@bot.message_handler(func=lambda message: message.text == "تعرفه خدمات 💎")
def pricing(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🔙 بازگشت"))
    
    text = (
        "╔══════════════════════════════╗\n"
        "          💎 تعرفه خدمات          \n"
        "          SARDAR VIP              \n"
        "╚══════════════════════════════╝\n\n"
        "🍏 **ساخت Apple ID**\n"
        "   ──────────────\n"
        "   💰 ۷۱۰,۰۰۰ تومان\n\n"
        "📦 **Apple ID آماده**\n"
        "   ──────────────\n"
        "   🗓️ گارانتی ۳۱ روزه  → ۴۱۰,۰۰۰ تومان\n"
        "   ♾️ گارانتی دائمی    → ۴۵۰,۰۰۰ تومان\n"
        "   ❌ بدون iCloud      → ۳۵۰,۰۰۰ تومان\n\n"
        "📧 **ایمیل**\n"
        "   ──────────────\n"
        "   📧 ایمیل آماده        → ۲۴۵,۰۰۰ تومان\n"
        "   📧 ساخت ایمیل سفارشی  → ۲۵۰,۰۰۰ تومان\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💳 **پرداخت آسان با کارت به کارت**\n"
        "📞 **پشتیبانی ۲۴ ساعته**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💙 **موفق و پیروز باشید**"
    )
    
    bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=markup)

# ============================================================
# 📦 Apple ID آماده
# ============================================================
@bot.message_handler(func=lambda message: message.text == "Apple ID آماده 📦")
def apple_id_ready(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(
        types.KeyboardButton("☁️🗓️ گارانتی 31 روزه iCloud"),
        types.KeyboardButton("☁️♾️ گارانتی دائمی iCloud"),
        types.KeyboardButton("❌ بدون iCloud"),
        types.KeyboardButton("🔙 بازگشت")
    )
    bot.send_message(user_id, "📦 Apple ID آماده\n\n☁️🗓️ گارانتی 31 روزه - 410,000 تومان\n☁️♾️ گارانتی دائمی - 450,000 تومان\n❌ بدون iCloud - 350,000 تومان", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "☁️🗓️ گارانتی 31 روزه iCloud")
def apple31(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🛒 خرید | 410.000 تومان (31 روزه)"), types.KeyboardButton("🔙 بازگشت"))
    bot.send_message(user_id, "☁️ Apple ID 31 روزه\n💰 قیمت: 410,000 تومان\n✅ دارای iCloud\n✅ گارانتی 31 روزه", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "☁️♾️ گارانتی دائمی iCloud")
def apple_infinite(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🛒 خرید | 450.000 تومان (دائمی)"), types.KeyboardButton("🔙 بازگشت"))
    bot.send_message(user_id, "☁️ Apple ID دائمی\n💰 قیمت: 450,000 تومان\n✅ دارای iCloud\n✅ گارانتی دائمی", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "❌ بدون iCloud")
def apple_noicloud(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🛒 خرید | 350.000 تومان (بدون iCloud)"), types.KeyboardButton("🔙 بازگشت"))
    bot.send_message(user_id, "❌ Apple ID بدون iCloud\n💰 قیمت: 350,000 تومان", reply_markup=markup)

# ============================================================
# 🛒 خرید محصولات آماده
# ============================================================
@bot.message_handler(func=lambda message: message.text.startswith("🛒 خرید |"))
def buy_product(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    
    text = message.text
    if "410.000" in text:
        product_name = "Apple ID 31 روزه"
        price = 410000
        icloud_status = 'with_icloud'
        warranty_type = '31days'
    elif "450.000" in text:
        product_name = "Apple ID دائمی"
        price = 450000
        icloud_status = 'with_icloud'
        warranty_type = 'infinite'
    elif "350.000" in text:
        product_name = "Apple ID بدون iCloud"
        price = 350000
        icloud_status = 'without_icloud'
        warranty_type = 'none'
    else:
        bot.send_message(user_id, "❌ محصول نامعتبر!")
        return
    
    order_id = create_temp_order(user_id, product_name, price, icloud_status=icloud_status, warranty_type=warranty_type)
    
    markup = payment_options_markup(order_id)
    bot.send_message(
        user_id,
        f"📦 محصول: **{product_name}**\n💰 مبلغ: **{price:,}** تومان\n🆔 سفارش: #{order_id}\n\nلطفاً روش پرداخت را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=markup
    )

# ============================================================
# 🍏 ساخت Apple ID (با اصلاح منطق)
# ============================================================
@bot.message_handler(func=lambda message: message.text == "Apple ID ساخت 🍏")
def apple_id_create(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📧 با ایمیل شما", callback_data=f"apple_email_self_{user_id}"),
        types.InlineKeyboardButton("✍️ ساخت ایمیل با ما", callback_data=f"apple_email_our_{user_id}")
    )
    bot.send_message(
        user_id,
        "🍏 **ساخت Apple ID**\n\n"
        "💰 قیمت: **۷۱۰,۰۰۰** تومان\n\n"
        "📧 لطفاً گزینه مورد نظر را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=markup
    )

# ----- گزینه ۱: با ایمیل خود کاربر -----
@bot.callback_query_handler(func=lambda call: call.data.startswith("apple_email_self_"))
def apple_email_self(call):
    user_id = int(call.data.split("_")[3])
    if user_id != call.message.chat.id:
        bot.answer_callback_query(call.id, "❌ این بخش برای شما نیست.")
        return
    
    bot.answer_callback_query(call.id, "✅ با ایمیل خودم")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    
    order_id = create_temp_order(user_id, "ساخت Apple ID (با ایمیل شما)", 710000, email_option='self')
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🔙 بازگشت"))
    msg = bot.send_message(
        user_id,
        "📧 لطفاً **ایمیل** خود را وارد کنید:\n(این ایمیل برای ساخت اپل آیدی استفاده می‌شود)",
        reply_markup=markup
    )
    bot.register_next_step_handler(msg, get_apple_email, order_id)

def get_apple_email(message, order_id):
    user_id = message.chat.id
    email = (message.text or "").strip()

    if email == "🔙 بازگشت":
        bot.send_message(user_id, "✅ عملیات لغو شد.", reply_markup=main_menu(user_id))
        delete_temp_order(order_id)
        return

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        retry = bot.send_message(user_id, "❌ ایمیل واردشده معتبر نیست. لطفاً ایمیل معتبر وارد کنید:")
        bot.register_next_step_handler(retry, get_apple_email, order_id)
        return

    update_temp_order(order_id, email=email)
    
    markup = payment_options_markup(order_id)
    bot.send_message(user_id, "✅ ایمیل دریافت شد. لطفاً روش پرداخت را انتخاب کنید:", reply_markup=markup)

# ----- گزینه ۲: ساخت ایمیل با ما (یک‌جا با قیمت ۷۱۰,۰۰۰) -----
@bot.callback_query_handler(func=lambda call: call.data.startswith("apple_email_our_"))
def apple_email_our(call):
    user_id = int(call.data.split("_")[3])
    if user_id != call.message.chat.id:
        bot.answer_callback_query(call.id, "❌ این بخش برای شما نیست.")
        return
    
    bot.answer_callback_query(call.id, "✍️ ساخت ایمیل با ما")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    
    order_id = create_temp_order(user_id, "ساخت Apple ID (با ایمیل ما)", 710000, email_option='our', is_for_apple=1)
    
    markup = payment_options_markup(order_id)
    bot.send_message(
        user_id,
        f"📦 محصول: **ساخت Apple ID با ایمیل ما**\n💰 مبلغ: **۷۱۰,۰۰۰** تومان\n🆔 سفارش: #{order_id}\n\nلطفاً روش پرداخت را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=markup
    )

# ============================================================
# 📞 پرداخت، رسید و تحویل — مدیریت بر اساس order_id
# ============================================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("balance_pay_"))
def balance_payment(call):
    try:
        order_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "❌ سفارش نامعتبر است.")
        return

    user_id = call.message.chat.id
    ok, state, temp, new_balance = pay_order_with_balance(order_id, user_id)

    if not ok:
        if state == "insufficient_balance":
            bot.answer_callback_query(call.id, "❌ موجودی کافی نیست.")
            bot.edit_message_reply_markup(
                user_id, call.message.message_id,
                reply_markup=payment_options_markup(order_id)
            )
        elif state == "not_payable":
            bot.answer_callback_query(call.id, "⚠️ این سفارش دیگر قابل پرداخت نیست.")
        else:
            bot.answer_callback_query(call.id, "❌ پرداخت انجام نشد. دوباره تلاش کنید.")
        return

    bot.answer_callback_query(call.id, "✅ پرداخت از موجودی انجام شد.")
    try:
        bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    # پرداخت موفق محصول؛ از اینجا به بعد دقیقاً مثل پرداخت تأییدشده بانکی،
    # ادمین دکمه «ارسال محصول» را دریافت می‌کند.
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(
        "📦 ارسال محصول",
        callback_data=f"admin_deliver_{order_id}"
    ))

    bot.send_message(
        ADMIN_ID,
        f"💰 **پرداخت از موجودی انجام شد**\n\n"
        f"🆔 سفارش: #{order_id}\n"
        f"👤 کاربر: `{user_id}`\n"
        f"📦 محصول: **{temp['product_name']}**\n"
        f"💸 مبلغ کسرشده: **{int(temp['price']):,} تومان**\n"
        f"💳 موجودی باقی‌مانده: **{new_balance:,} تومان**\n\n"
        "⬇️ برای ارسال محصول روی دکمه زیر بزنید:",
        parse_mode="Markdown",
        reply_markup=markup
    )
    bot.send_message(
        user_id,
        f"✅ خرید شما با موفقیت انجام شد.\n\n"
        f"📦 محصول: **{temp['product_name']}**\n"
        f"💸 مبلغ کسرشده از موجودی: **{int(temp['price']):,} تومان**\n"
        f"💳 موجودی باقی‌مانده: **{new_balance:,} تومان**\n\n"
        "⏳ محصول پس از تأیید نهایی برای شما ارسال می‌شود.",
        parse_mode="Markdown",
        reply_markup=main_menu(user_id)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("gateway_"))
def gateway_payment(call):
    try:
        order_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "❌ سفارش نامعتبر است.")
        return

    user_id = call.message.chat.id
    temp = get_temp_order(order_id)
    if not temp or temp["user_id"] != user_id:
        bot.answer_callback_query(call.id, "❌ این سفارش متعلق به شما نیست.")
        return
    if temp["status"] != "waiting_payment":
        bot.answer_callback_query(call.id, "⚠️ این سفارش دیگر قابل پرداخت نیست.")
        return

    bot.answer_callback_query(call.id, "💳 درگاه انتخاب شد.")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    update_temp_order(order_id, status="waiting_receipt")

    bot.send_message(
        user_id,
        f"💳 **پرداخت سفارش #{order_id}**\n\n"
        f"📦 محصول: **{temp['product_name']}**\n"
        f"💰 مبلغ: **{temp['price']:,} تومان**\n\n"
        "🔗 لینک پرداخت:\n"
        "https://your-payment-gateway.com/pay/order\n\n"
        "📸 پس از پرداخت، رسید همین سفارش را ارسال کنید.\n"
        "⚠️ رسید شما فقط به سفارش درج‌شده در بالا متصل می‌شود.",
        parse_mode="Markdown",
        reply_markup=main_menu(user_id)
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("card_to_card_"))
def card_to_card_payment(call):
    try:
        order_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "❌ شماره سفارش نامعتبر است.")
        return

    user_id = call.message.chat.id

    temp = get_temp_order(order_id)
    if not temp or temp["user_id"] != user_id:
        bot.answer_callback_query(call.id, "❌ سفارش نامعتبر است.")
        return
    if temp["status"] != "waiting_payment":
        bot.answer_callback_query(call.id, "⚠️ این سفارش دیگر قابل پرداخت نیست.")
        return

    # به‌روزرسانی وضعیت به waiting_receipt
    update_temp_order(order_id, status="waiting_receipt")

    bot.answer_callback_query(call.id, "🏦 کارت به کارت انتخاب شد.")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)

    card_number = get_setting("card_number")
    card_owner = get_setting("card_owner")
    price = temp["price"]

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("❌ لغو سفارش", callback_data=f"cancel_order_{order_id}"))

    bot.send_message(
        user_id,
        f"🏦 **کارت به کارت — سفارش #{order_id}**\n\n"
        f"📦 محصول: **{temp['product_name']}**\n"
        f"💳 شماره کارت: `{card_number}`\n"
        f"👤 نام صاحب کارت: {card_owner}\n\n"
        f"💰 مبلغ: **{price:,} تومان**\n\n"
        "📸 لطفاً عکس رسید همین پرداخت را ارسال کنید.\n"
        "⚠️ رسید به سفارش بالا متصل خواهد شد.",
        parse_mode="Markdown",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_order_"))
def cancel_order_callback(call):
    try:
        order_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "❌ سفارش نامعتبر است.")
        return

    user_id = call.message.chat.id
    ok, state, temp = cancel_order_by_id(order_id, user_id)
    if not ok:
        if state == "not_cancellable":
            bot.answer_callback_query(call.id, "⚠️ این سفارش دیگر قابل لغو نیست.")
        else:
            bot.answer_callback_query(call.id, "❌ سفارش پیدا نشد.")
        return

    bot.answer_callback_query(call.id, "✅ سفارش لغو شد.")
    try:
        bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    bot.send_message(
        user_id,
        f"✅ سفارش **#{order_id}** با موفقیت لغو شد.\n\n"
        f"📦 {temp['product_name']}\n"
        "اگر خواستید می‌توانید خرید جدیدی ثبت کنید.",
        parse_mode="Markdown",
        reply_markup=main_menu(user_id)
    )
    bot.send_message(ADMIN_ID, f"🚫 سفارش #{order_id} توسط کاربر {user_id} لغو شد.")

# ---------- رسید ----------
@bot.message_handler(content_types=["photo", "document"])
def handle_receipt(message):
    user_id = message.chat.id

    print(f"📸 RECEIPT RECEIVED | user={user_id} | "
        f"photo={bool(message.photo)} | document={bool(message.document)}")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM temp_orders
        WHERE user_id = ?
        AND status = 'waiting_receipt'
        ORDER BY created_at DESC
        LIMIT 1
    """, (user_id,))

    result = cursor.fetchone()
    conn.close()

    if not result:
        # بررسی وجود سفارش در مرحله انتظار پرداخت
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM temp_orders WHERE user_id = ? AND status = 'waiting_payment'", (user_id,))
        count = cursor.fetchone()[0]
        conn.close()
        if count > 0:
            bot.send_message(
                user_id,
                "❌ شما یک سفارش در انتظار پرداخت دارید.\n"
                "لطفاً ابتدا روش پرداخت را انتخاب کنید، سپس رسید را ارسال کنید.",
                reply_markup=main_menu(user_id)
            )
        else:
            bot.send_message(
                user_id,
                "❌ هیچ سفارش فعالی در مرحله دریافت رسید یافت نشد.\n"
                "لطفاً ابتدا یک سفارش جدید ثبت کنید و روش پرداخت را انتخاب کنید.",
                reply_markup=main_menu(user_id)
            )
        return

    temp = dict(result)
    order_id = temp["order_id"]

    # دریافت file_id چه به صورت عکس چه فایل
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id
    else:
        bot.send_message(user_id, "❌ فایل رسید قابل شناسایی نیست.")
        return

    # تغییر وضعیت سفارش
    update_temp_order(
        order_id,
        status="receipt_received",
        photo_id=file_id
    )

    # نوع سفارش از همین‌جا داخل callback مشخص می‌شود.
    # بنابراین سفارش شارژ هرگز وارد callback ارسال محصول نمی‌شود.
    confirm_prefix = "admin_confirm_balance_" if is_balance_order(temp) else "admin_confirm_product_"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "✅ تأیید",
            callback_data=f"{confirm_prefix}{order_id}"
        ),
        types.InlineKeyboardButton(
            "❌ رد",
            callback_data=f"admin_reject_{order_id}"
        )
    )

    user_info = get_user_info(user_id) or {
        "first_name": "نامشخص",
        "last_name": "نامشخص"
    }

    admin_msg = (
        "📸 **رسید جدید دریافت شد**\n\n"
        f"👤 کاربر: {user_id}\n"
        f"👤 نام: {user_info['first_name']} {user_info['last_name']}\n"
        f"📦 محصول: {temp['product_name']}\n"
        f"💰 مبلغ: {temp['price']:,} تومان\n"
        f"🆔 سفارش: **#{order_id}**\n\n"
        "⬇️ رسید را بررسی کنید:"
    )

    try:
        # اگر عکس باشد
        if message.photo:
            bot.send_photo(
                ADMIN_ID,
                file_id,
                caption=admin_msg,
                reply_markup=markup,
                parse_mode="Markdown"
            )
        # اگر به صورت فایل ارسال شده باشد
        else:
            bot.send_document(
                ADMIN_ID,
                file_id,
                caption=admin_msg,
                reply_markup=markup,
                parse_mode="Markdown"
            )

        bot.send_message(
            user_id,
            f"✅ رسید سفارش **#{order_id}** برای ادمین ارسال شد.\n\n"
            "⏳ لطفاً منتظر تأیید بمانید.",
            parse_mode="Markdown",
            reply_markup=main_menu(user_id)
        )

        print(f"✅ RECEIPT SENT TO ADMIN | order={order_id}")

    except Exception as e:
        print(f"❌ RECEIPT SEND ERROR | order={order_id} | {repr(e)}")

        logger.exception(
            f"خطا در ارسال رسید سفارش #{order_id}"
        )

        update_temp_order(
            order_id,
            status="waiting_receipt"
        )

        bot.send_message(
            user_id,
            "❌ ارسال رسید به ادمین ناموفق بود.\n"
            "لطفاً دوباره رسید را ارسال کنید.",
            reply_markup=main_menu(user_id)
        )

# ---------- CALLBACK های تأیید و رد توسط ادمین ----------
def _remove_admin_buttons(call):
    try:
        bot.edit_message_reply_markup(
            chat_id=ADMIN_ID,
            message_id=call.message.message_id,
            reply_markup=None
        )
    except Exception as e:
        logger.warning(f"خطا در حذف دکمه‌های ادمین: {e}")


def _confirm_balance_order(call, order_id, temp):
    """تأیید شارژ کیف پول؛ این تابع هیچ‌وقت دکمه ارسال محصول نمی‌سازد."""
    user_id = temp["user_id"]
    amount = int(temp["price"])

    # عملیات نهایی داخل یک تراکنش انجام می‌شود تا با دوبار کلیک، شارژ دوباره نشود.
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM temp_orders WHERE order_id = ?", (order_id,))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            bot.answer_callback_query(call.id, "❌ سفارش پیدا نشد.")
            return

        current = dict(row)
        if current["status"] != "receipt_received":
            conn.rollback()
            bot.answer_callback_query(call.id, "⚠️ این رسید قبلاً بررسی شده است.")
            return

        if not is_balance_order(current):
            conn.rollback()
            bot.answer_callback_query(call.id, "❌ نوع سفارش با این دکمه سازگار نیست.")
            logger.error(f"BALANCE CALLBACK MISMATCH | order={order_id} | product={current.get('product_name')} | type={current.get('order_type')}")
            return

        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        old_balance = int(result[0]) if result else 0
        if not result:
            cursor.execute("INSERT INTO users (user_id, balance, join_date) VALUES (?, ?, ?)",
                           (user_id, 0, time.strftime("%Y-%m-%d %H:%M:%S")))

        new_balance = old_balance + amount
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        cursor.execute("UPDATE temp_orders SET status = 'delivered', updated_at = ? WHERE order_id = ? AND status = 'receipt_received'",
                       (time.strftime("%Y-%m-%d %H:%M:%S"), order_id))
        if cursor.rowcount != 1:
            conn.rollback()
            bot.answer_callback_query(call.id, "⚠️ این سفارش قبلاً پردازش شده است.")
            return

        cursor.execute("UPDATE user_purchases SET status = 'delivered', product_detail = ? WHERE order_id = ?",
                       (f"افزایش موجودی به {new_balance}", order_id))
        conn.commit()

    except Exception as e:
        conn.rollback()
        logger.exception(f"خطا در شارژ کیف پول سفارش #{order_id}: {e}")
        bot.answer_callback_query(call.id, "❌ خطا در ثبت شارژ کیف پول.")
        return
    finally:
        conn.close()

    _remove_admin_buttons(call)
    delete_temp_order(order_id)

    bot.send_message(
        user_id,
        f"✅ پرداخت سفارش #{order_id} تأیید شد.\n\n"
        f"💰 مبلغ شارژ: **{amount:,} تومان**\n"
        f"💳 موجودی جدید شما: **{new_balance:,} تومان**",
        parse_mode="Markdown",
        reply_markup=main_menu(user_id)
    )
    bot.send_message(
        ADMIN_ID,
        f"✅ شارژ کیف پول انجام شد.\n"
        f"🆔 سفارش: #{order_id}\n"
        f"👤 کاربر: `{user_id}`\n"
        f"💰 مبلغ شارژ: **{amount:,} تومان**\n"
        f"💳 موجودی جدید: **{new_balance:,} تومان**",
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id, "✅ موجودی کاربر با موفقیت افزایش یافت.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_confirm_balance_"))
def admin_confirm_balance(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ شما اجازه این کار را ندارید.")
        return
    try:
        order_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "❌ سفارش نامعتبر است.")
        return
    temp = get_temp_order(order_id)
    if not temp:
        bot.answer_callback_query(call.id, "❌ سفارش پیدا نشد.")
        return
    _confirm_balance_order(call, order_id, temp)


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_confirm_product_"))
def admin_confirm_product(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ شما اجازه این کار را ندارید.")
        return

    try:
        order_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "❌ سفارش نامعتبر است.")
        return

    temp = get_temp_order(order_id)
    if not temp:
        bot.answer_callback_query(call.id, "❌ سفارش پیدا نشد.")
        return

    if temp["status"] != "receipt_received":
        bot.answer_callback_query(call.id, "⚠️ این سفارش قبلاً بررسی شده است.")
        return

    # این callback مخصوص محصول است؛ اگر دیتابیس گفت balance، اجازه ساخت دکمه ارسال نمی‌دهیم.
    if is_balance_order(temp):
        logger.warning(f"PRODUCT CALLBACK BLOCKED BALANCE ORDER | order={order_id}")
        _confirm_balance_order(call, order_id, temp)
        return

    if not update_temp_order(order_id, status="confirmed"):
        bot.answer_callback_query(call.id, "❌ تغییر وضعیت سفارش انجام نشد.")
        return
    update_purchase_status(order_id, "confirmed")

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(
        "📦 ارسال محصول",
        callback_data=f"admin_deliver_{order_id}"
    ))

    _remove_admin_buttons(call)
    try:
        bot.send_message(
            ADMIN_ID,
            f"✅ **پرداخت سفارش #{order_id} تأیید شد.**\n\n"
            f"📦 محصول: **{temp['product_name']}**\n"
            f"💰 مبلغ: **{temp['price']:,} تومان**\n\n"
            "⬇️ برای تکمیل سفارش روی دکمه زیر بزنید:",
            parse_mode="Markdown",
            reply_markup=markup
        )
        bot.send_message(
            temp["user_id"],
            f"✅ پرداخت شما برای سفارش #{order_id} تأیید شد.\n"
            "📦 به زودی محصول شما ارسال خواهد شد.",
            reply_markup=main_menu(temp["user_id"])
        )
        bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد. دکمه ارسال محصول نمایش داده شد.")
    except Exception as e:
        logger.exception(f"خطا در نمایش دکمه ارسال سفارش #{order_id}: {e}")
        bot.answer_callback_query(call.id, "❌ خطا در نمایش دکمه ارسال محصول.")


# سازگاری با رسیدهای قدیمی: اگر callback قدیمی admin_confirm_123 هنوز وجود داشت،
# نوع واقعی سفارش از دیتابیس خوانده می‌شود؛ شارژ هرگز به ارسال محصول نمی‌رود.
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_confirm_") and not call.data.startswith("admin_confirm_balance_") and not call.data.startswith("admin_confirm_product_"))
def admin_confirm_legacy(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ شما اجازه این کار را ندارید.")
        return
    try:
        order_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "❌ سفارش نامعتبر است.")
        return
    temp = get_temp_order(order_id)
    if not temp:
        bot.answer_callback_query(call.id, "❌ سفارش پیدا نشد.")
        return
    if temp["status"] != "receipt_received":
        bot.answer_callback_query(call.id, "⚠️ این سفارش قبلاً بررسی شده است.")
        return
    if is_balance_order(temp):
        _confirm_balance_order(call, order_id, temp)
    else:
        # رفتار قدیمی برای محصولات عادی، ولی با تشخیص قطعی نوع سفارش.
        if not update_temp_order(order_id, status="confirmed"):
            bot.answer_callback_query(call.id, "❌ تغییر وضعیت سفارش انجام نشد.")
            return
        update_purchase_status(order_id, "confirmed")
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("📦 ارسال محصول", callback_data=f"admin_deliver_{order_id}"))
        _remove_admin_buttons(call)
        bot.send_message(ADMIN_ID, f"✅ پرداخت سفارش #{order_id} تأیید شد.\n📦 محصول: **{temp['product_name']}**\n💰 مبلغ: **{temp['price']:,} تومان**", parse_mode="Markdown", reply_markup=markup)
        bot.send_message(temp["user_id"], f"✅ پرداخت شما برای سفارش #{order_id} تأیید شد.\n📦 به زودی محصول شما ارسال خواهد شد.", reply_markup=main_menu(temp["user_id"]))
        bot.answer_callback_query(call.id, "✅ پرداخت تأیید شد.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_reject_"))
def admin_reject(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ شما اجازه این کار را ندارید.")
        return

    order_id = int(call.data.split("_")[2])
    temp = get_temp_order(order_id)
    if not temp:
        bot.answer_callback_query(call.id, "❌ سفارش پیدا نشد.")
        return

    if temp["status"] not in ("receipt_received", "confirmed"):
        bot.answer_callback_query(call.id, "⚠️ این سفارش قابل رد نیست.")
        return

    # بروزرسانی وضعیت به rejected
    update_temp_order(order_id, status="rejected")
    update_purchase_status(order_id, "rejected")
    save_failed_purchase(temp["user_id"], temp["product_name"], temp["price"], "رسید رد شد")

    # حذف دکمه‌ها
    try:
        bot.edit_message_reply_markup(
            chat_id=ADMIN_ID,
            message_id=call.message.message_id,
            reply_markup=None
        )
        bot.answer_callback_query(call.id, "❌ رسید رد شد.")
        # اطلاع به کاربر
        bot.send_message(
            temp["user_id"],
            f"❌ متأسفانه رسید شما برای سفارش #{order_id} رد شد.\n"
            "لطفاً با پشتیبانی تماس بگیرید.",
            reply_markup=main_menu(temp["user_id"])
        )
        # حذف سفارش موقت
        delete_temp_order(order_id)
    except Exception as e:
        logger.error(f"خطا در ویرایش پیام ادمین: {e}")
        bot.answer_callback_query(call.id, "❌ خطا در ویرایش پیام.")

# ---------- CALLBACK ارسال محصول توسط ادمین ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_deliver_"))
def admin_deliver(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ شما اجازه این کار را ندارید.")
        return

    order_id = int(call.data.split("_")[2])
    temp = get_temp_order(order_id)
    if not temp:
        bot.answer_callback_query(call.id, "❌ سفارش پیدا نشد.")
        return

    if temp["status"] != "confirmed":
        bot.answer_callback_query(call.id, "⚠️ سفارش تأیید نشده است.")
        return

    user_id = temp["user_id"]
    product_name = temp["product_name"]

    # ⛔ افزایش موجودی هرگز نباید از مسیر «ارسال محصول» عبور کند.
    if is_balance_order(temp):
        logger.warning(f"⛔ BALANCE ORDER SENT TO DELIVERY | order={order_id} | user={user_id}")
        bot.answer_callback_query(call.id, "⚠️ این سفارش افزایش موجودی است و نیازی به ارسال محصول ندارد.")
        try:
            bot.edit_message_reply_markup(
                chat_id=ADMIN_ID,
                message_id=call.message.message_id,
                reply_markup=None
            )
        except Exception as e:
            logger.warning(f"خطا در حذف دکمه ارسال محصول برای سفارش شارژ: {e}")
        return

    # بررسی نوع محصول و ارسال
    # ۱. اپل آیدی آماده
    if product_name in ["Apple ID 31 روزه", "Apple ID دائمی", "Apple ID بدون iCloud"]:
        # دریافت از انبار
        icloud_status = temp.get("icloud_status", "with_icloud")
        warranty_type = temp.get("warranty_type", "31days")
        apple = get_unused_apple_id(product_type='ready', icloud_status=icloud_status, warranty_type=warranty_type)
        if not apple:
            bot.send_message(ADMIN_ID, f"❌ اپل آیدی برای سفارش #{order_id} در انبار موجود نیست.")
            return
        # ارسال به کاربر
        msg = (
            f"🍏 **اپل آیدی شما**\n\n"
            f"📧 اپل آیدی: `{apple['apple_id']}`\n"
            f"🔑 رمز: `{apple['password']}`\n"
            f"📅 تاریخ تولد: {apple['birth_date']}\n"
            f"🏫 مدرسه: {apple['school']}\n"
            f"💼 شغل: {apple['job']}\n"
            f"👨‍👩‍👧 ملاقات والدین: {apple['parentsmeet']}\n"
            f"❓ سوال امنیتی ۱: {apple['security_q1']}\n"
            f"🔐 پاسخ ۱: {apple['security_a1']}\n"
            f"❓ سوال امنیتی ۲: {apple['security_q2']}\n"
            f"🔐 پاسخ ۲: {apple['security_a2']}\n"
            f"❓ سوال امنیتی ۳: {apple['security_q3']}\n"
            f"🔐 پاسخ ۳: {apple['security_a3']}\n\n"
            f"💡 لطفاً رمز را تغییر دهید و اطلاعات را ذخیره کنید."
        )
        bot.send_message(user_id, msg, parse_mode="Markdown", reply_markup=main_menu(user_id))
        # مارک استفاده شده
        mark_apple_id_used(apple["id"], user_id)
        # ثبت در تاریخچه
        detail = f"{apple['apple_id']} | {apple['password']}"
        update_purchase_status(order_id, "delivered", product_detail=detail, password=apple['password'])
        create_purchase_record(user_id, order_id, product_name, detail, apple['password'])
        # پیام به ادمین
        bot.send_message(ADMIN_ID, f"✅ اپل آیدی برای سفارش #{order_id} به کاربر ارسال شد.")

    # ۲. ایمیل آماده
    elif product_name == "ایمیل آماده":
        email_item = get_unused_email()
        if not email_item:
            bot.send_message(ADMIN_ID, f"❌ ایمیل برای سفارش #{order_id} در انبار موجود نیست.")
            return
        msg = f"📧 **ایمیل شما**\n\n📧 ایمیل: `{email_item['email']}`\n🔑 رمز: `{email_item['password']}`"
        bot.send_message(user_id, msg, parse_mode="Markdown", reply_markup=main_menu(user_id))
        mark_email_used(email_item["id"], user_id)
        detail = f"{email_item['email']} | {email_item['password']}"
        update_purchase_status(order_id, "delivered", product_detail=detail, password=email_item['password'])
        create_purchase_record(user_id, order_id, product_name, detail, email_item['password'])
        bot.send_message(ADMIN_ID, f"✅ ایمیل برای سفارش #{order_id} به کاربر ارسال شد.")

    # ۳. ساخت Apple ID (با ایمیل خود کاربر یا با ایمیل ما) -> نیاز به ورود دستی ادمین
    elif product_name in ["ساخت Apple ID (با ایمیل شما)", "ساخت Apple ID (با ایمیل ما)"]:
        # از ادمین بخواهید اطلاعات اپل آیدی ساخته‌شده را وارد کند
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
        markup.add(types.KeyboardButton("🔙 بازگشت به پنل ادمین"))
        msg = bot.send_message(
            ADMIN_ID,
            f"📝 **سفارش #{order_id} - {product_name}**\n\n"
            "لطفاً اطلاعات اپل آیدی ساخته‌شده را به فرمت زیر وارد کنید:\n"
            "`apple_id, password, birth_date, school, job, parentsmeet, security_q1, security_a1, security_q2, security_a2, security_q3, security_a3`\n\n"
            "فیلدهای اختیاری را با 'ندارد' پر کنید.\n"
            "مثال:\n"
            "`example@icloud.com, 123456, 1990-01-01, مدرسه, شغل, محل ملاقات, سوال1, پاسخ1, سوال2, پاسخ2, سوال3, پاسخ3`",
            parse_mode="Markdown",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_custom_apple_delivery, order_id, user_id, product_name)

    # ۴. ساخت ایمیل سفارشی
    elif product_name == "ایمیل سفارشی":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
        markup.add(types.KeyboardButton("🔙 بازگشت به پنل ادمین"))
        msg = bot.send_message(
            ADMIN_ID,
            f"📝 **سفارش #{order_id} - ایمیل سفارشی**\n\n"
            "لطفاً اطلاعات ایمیل ساخته‌شده را به فرمت زیر وارد کنید:\n"
            "`email, password`",
            parse_mode="Markdown",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_custom_email_delivery, order_id, user_id, product_name)

    else:
        bot.send_message(ADMIN_ID, f"❌ نوع محصول ناشناخته: {product_name}")

    # حذف دکمه ارسال محصول از پیام ادمین
    try:
        bot.edit_message_reply_markup(
            chat_id=ADMIN_ID,
            message_id=call.message.message_id,
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"خطا در ویرایش پیام ادمین: {e}")

    bot.answer_callback_query(call.id, "✅ محصول در حال ارسال...")

# ---------- توابع کمکی برای ارسال محصولات سفارشی ----------
def process_custom_apple_delivery(message, order_id, user_id, product_name):
    if message.text == "🔙 بازگشت به پنل ادمین":
        bot.send_message(ADMIN_ID, "✅ عملیات لغو شد.", reply_markup=admin_panel_reply())
        return

    data = message.text.split(',')
    if len(data) != 12:
        bot.send_message(ADMIN_ID, "❌ تعداد فیلدها صحیح نیست. لطفاً دقیقاً ۱۲ فیلد وارد کنید.")
        # دوباره بپرس
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
        markup.add(types.KeyboardButton("🔙 بازگشت به پنل ادمین"))
        msg = bot.send_message(
            ADMIN_ID,
            "لطفاً اطلاعات را دوباره به فرمت صحیح وارد کنید:\n"
            "`apple_id, password, birth_date, school, job, parentsmeet, security_q1, security_a1, security_q2, security_a2, security_q3, security_a3`",
            parse_mode="Markdown",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_custom_apple_delivery, order_id, user_id, product_name)
        return

    apple_id = data[0].strip()
    password = data[1].strip()
    birth_date = data[2].strip()
    school = data[3].strip()
    job = data[4].strip()
    parentsmeet = data[5].strip()
    q1 = data[6].strip()
    a1 = data[7].strip()
    q2 = data[8].strip()
    a2 = data[9].strip()
    q3 = data[10].strip()
    a3 = data[11].strip()

    # ارسال به کاربر
    msg = (
        f"🍏 **اپل آیدی شما**\n\n"
        f"📧 اپل آیدی: `{apple_id}`\n"
        f"🔑 رمز: `{password}`\n"
        f"📅 تاریخ تولد: {birth_date}\n"
        f"🏫 مدرسه: {school}\n"
        f"💼 شغل: {job}\n"
        f"👨‍👩‍👧 ملاقات والدین: {parentsmeet}\n"
        f"❓ سوال امنیتی ۱: {q1}\n"
        f"🔐 پاسخ ۱: {a1}\n"
        f"❓ سوال امنیتی ۲: {q2}\n"
        f"🔐 پاسخ ۲: {a2}\n"
        f"❓ سوال امنیتی ۳: {q3}\n"
        f"🔐 پاسخ ۳: {a3}\n\n"
        f"💡 لطفاً رمز را تغییر دهید و اطلاعات را ذخیره کنید."
    )
    bot.send_message(user_id, msg, parse_mode="Markdown", reply_markup=main_menu(user_id))
    # ثبت در تاریخچه
    detail = f"{apple_id} | {password}"
    update_purchase_status(order_id, "delivered", product_detail=detail, password=password)
    create_purchase_record(user_id, order_id, product_name, detail, password)
    bot.send_message(ADMIN_ID, f"✅ اپل آیدی سفارشی برای سفارش #{order_id} به کاربر ارسال شد.")
    delete_temp_order(order_id)

def process_custom_email_delivery(message, order_id, user_id, product_name):
    if message.text == "🔙 بازگشت به پنل ادمین":
        bot.send_message(ADMIN_ID, "✅ عملیات لغو شد.", reply_markup=admin_panel_reply())
        return

    data = message.text.split(',')
    if len(data) != 2:
        bot.send_message(ADMIN_ID, "❌ فرمت نامعتبر. لطفاً به صورت `email, password` وارد کنید.")
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
        markup.add(types.KeyboardButton("🔙 بازگشت به پنل ادمین"))
        msg = bot.send_message(
            ADMIN_ID,
            "لطفاً اطلاعات را دوباره به فرمت صحیح وارد کنید:\n`email, password`",
            parse_mode="Markdown",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_custom_email_delivery, order_id, user_id, product_name)
        return

    email = data[0].strip()
    password = data[1].strip()
    msg = f"📧 **ایمیل شما**\n\n📧 ایمیل: `{email}`\n🔑 رمز: `{password}`"
    bot.send_message(user_id, msg, parse_mode="Markdown", reply_markup=main_menu(user_id))
    detail = f"{email} | {password}"
    update_purchase_status(order_id, "delivered", product_detail=detail, password=password)
    create_purchase_record(user_id, order_id, product_name, detail, password)
    bot.send_message(ADMIN_ID, f"✅ ایمیل سفارشی برای سفارش #{order_id} به کاربر ارسال شد.")
    delete_temp_order(order_id)

# ============================================================
# 📧 ساخت ایمیل سفارشی
# ============================================================
@bot.message_handler(func=lambda message: message.text == "ساخت ایمیل 📧")
def create_email(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🛒 خرید ساخت ایمیل | 250,000 تومان (سفارشی)"), types.KeyboardButton("🔙 بازگشت"))
    bot.send_message(user_id, "📧 ساخت ایمیل\n💰 قیمت: 250,000 تومان\n✅ ساخت اختصاصی", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🛒 خرید ساخت ایمیل | 250,000 تومان (سفارشی)")
def buy_custom_email(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    
    order_id = create_temp_order(user_id, "ایمیل سفارشی", 250000, is_for_apple=0)
    
    markup = payment_options_markup(order_id)
    bot.send_message(
        user_id,
        f"📦 محصول: **ایمیل سفارشی**\n💰 مبلغ: **۲۵۰,۰۰۰** تومان\n🆔 سفارش: #{order_id}\n\nلطفاً روش پرداخت را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=markup
    )

# ============================================================
# 📧 ایمیل آماده
# ============================================================
@bot.message_handler(func=lambda message: message.text == "ایمیل آماده 📧")
def email_ready(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🛒 خرید ایمیل آماده | 245,000 تومان"), types.KeyboardButton("🔙 بازگشت"))
    bot.send_message(user_id, "📧 ایمیل آماده\n💰 قیمت: 245,000 تومان\n✅ تحویل فوری", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🛒 خرید ایمیل آماده | 245,000 تومان")
def buy_ready_email(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    
    order_id = create_temp_order(user_id, "ایمیل آماده", 245000)
    
    markup = payment_options_markup(order_id)
    bot.send_message(
        user_id,
        f"📦 محصول: **ایمیل آماده**\n💰 مبلغ: **۲۴۵,۰۰۰** تومان\n🆔 سفارش: #{order_id}\n\nلطفاً روش پرداخت را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=markup
    )

# ============================================================
# 🛒 خریدهای من — تاریخچه واقعی سفارش‌ها
# ============================================================
@bot.message_handler(func=lambda message: message.text == "خریدهای من 🛒")
def my_purchases(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT order_id, product_type, purchase_date, status, product_detail
        FROM user_purchases
        WHERE user_id = ?
        ORDER BY purchase_date DESC, id DESC
        LIMIT 20
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        bot.send_message(user_id, "🛒 هنوز سفارشی ثبت نکرده‌اید.", reply_markup=main_menu(user_id))
        return

    status_map = {
        "pending": "⏳ در انتظار پرداخت",
        "rejected": "❌ پرداخت رد شد",
        "cancelled": "🚫 لغو شده",
        "completed": "✅ تکمیل شده",
        "delivered": "📦 تحویل شده"
    }
    text = "🛒 **خریدهای من**\n\n"
    for row in rows:
        status = status_map.get(row["status"], row["status"])
        text += (
            f"🆔 **سفارش #{row['order_id']}**\n"
            f"📦 {row['product_type']}\n"
            f"📅 {row['purchase_date']}\n"
            f"📌 وضعیت: {status}\n"
        )
        if row["status"] in ("completed", "delivered") and row["product_detail"]:
            text += "🔐 اطلاعات تحویل‌شده در سابقه سفارش ثبت شده است.\n"
        text += "──────────────\n"

    bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=main_menu(user_id))

# ============================================================
# 🛡️ گارانتی
# ============================================================
@bot.message_handler(func=lambda message: message.text == "گارانتی 🛡️")
def warranty_menu(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🔙 بازگشت"))
    
    msg = bot.send_message(
        user_id,
        "🛡️ **بررسی گارانتی اپل آیدی**\n\n"
        "لطفاً **اپل آیدی** خود را وارد کنید تا وضعیت گارانتی آن را بررسی کنیم.\n\n"
        "(مثال: example@icloud.com)",
        reply_markup=markup
    )
    bot.register_next_step_handler(msg, check_warranty)

def check_warranty(message):
    user_id = message.chat.id
    if message.text == "🔙 بازگشت":
        back_to_main(message)
        return
    
    apple_id = message.text.strip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO warranty_requests (user_id, apple_id, request_date) VALUES (?, ?, ?)", 
                   (user_id, apple_id, time.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    bot.send_message(
        user_id,
        f"🛡️ **نتیجه بررسی گارانتی**\n\n"
        f"📱 اپل آیدی: {apple_id}\n"
        f"✅ وضعیت: **فعال**\n"
        f"📅 تاریخ انقضا: ۱۴۰۵/۱۲/۰۱\n\n"
        f"⚠️ این اطلاعات صرفاً جنبه نمایشی دارد.",
        reply_markup=main_menu(user_id)
    )

# ============================================================
# 💰 افزایش موجودی
# ============================================================
@bot.message_handler(func=lambda message: message.text == "افزایش موجودی 💰")
def increase_balance_menu(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🔙 بازگشت"))
    
    msg = bot.send_message(
        user_id,
        f"💳 **افزایش موجودی کیف پول**\n\n"
        f"💰 موجودی فعلی شما: {get_user_balance(user_id):,} تومان\n\n"
        f"مبلغ مورد نظر را به تومان وارد کنید:\n"
        f"(مثال: 50000)\n\n"
        f"⚠️ پس از تأیید ادمین، موجودی شما افزایش می‌یابد.",
        reply_markup=markup
    )
    bot.register_next_step_handler(msg, process_balance_increase)

def process_balance_increase(message):
    user_id = message.chat.id
    if message.text == "🔙 بازگشت":
        back_to_main(message)
        return
    
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            bot.send_message(user_id, "❌ مبلغ باید بزرگتر از صفر باشد.", reply_markup=main_menu(user_id))
            return
    except:
        bot.send_message(user_id, "❌ لطفاً یک عدد معتبر وارد کنید.", reply_markup=main_menu(user_id))
        return
    
    order_id = create_temp_order(user_id, "افزایش موجودی", amount, order_type="balance")
    
    markup = payment_markup(order_id)
    bot.send_message(
        user_id,
        f"💰 مبلغ: **{amount:,}** تومان\n🆔 سفارش: #{order_id}\n\nلطفاً روش پرداخت را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=markup
    )

# ============================================================
# 👨‍💻 پشتیبانی
# ============================================================
@bot.message_handler(func=lambda message: message.text == "پشتیبانی 👨‍💻")
def support(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 پشتیبان 1", url="https://t.me/iman_sardaar"),
        types.InlineKeyboardButton("👤 پشتیبان 2", url="https://t.me/mobile_sardaar")
    )
    
    text = (
        "👨‍💻 **پشتیبانی SARDAR VIP**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📞 برای ارتباط با پشتیبان‌ها، روی یکی از دکمه‌های زیر کلیک کنید:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🕐 **ساعات پاسخگویی:**\n"
        "   ۲۴ ساعته، ۷ روز هفته\n\n"
        "💙 **ما همیشه در کنار شما هستیم.**"
    )
    
    bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=markup)

# ============================================================
# 🔄 آنلاک ایل آیدی (با اصلاح امنیتی)
# ============================================================
unlock_temp = {}

@bot.message_handler(func=lambda message: message.text == "آنلاک ایل آیدی 🔄")
def unlock_apple_id(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🔙 بازگشت"))
    msg = bot.send_message(
        user_id,
        "🔓 **آنلاک اپل آیدی**\n\n"
        "لطفاً **اپل آیدی** خود را وارد کنید:",
        reply_markup=markup
    )
    bot.register_next_step_handler(msg, unlock_get_apple_id)

def unlock_get_apple_id(message):
    user_id = message.chat.id
    if message.text == "🔙 بازگشت":
        back_to_main(message)
        return
    
    apple_id = message.text.strip()
    if not apple_id:
        bot.send_message(user_id, "❌ اپل آیدی نمی‌تواند خالی باشد.")
        unlock_apple_id(message)
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🔙 بازگشت"))
    msg = bot.send_message(
        user_id,
        f"🔓 **آنلاک اپل آیدی**\n\n"
        f"اپل آیدی: `{apple_id}`\n\n"
        "لطفاً **رمز اپل آیدی** را وارد کنید:",
        parse_mode="Markdown",
        reply_markup=markup
    )
    bot.register_next_step_handler(msg, unlock_get_password, apple_id)

def unlock_get_password(message, apple_id):
    user_id = message.chat.id
    if message.text == "🔙 بازگشت":
        back_to_main(message)
        return
    
    password = message.text.strip()
    if not password:
        bot.send_message(user_id, "❌ رمز نمی‌تواند خالی باشد.")
        unlock_get_apple_id(message)
        return
    
    unlock_temp[user_id] = {"apple_id": apple_id, "password": password}
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📧 وارد کردن ایمیل", callback_data=f"unlock_has_email_{user_id}"),
        types.InlineKeyboardButton("❌ ندارم", callback_data=f"unlock_no_email_{user_id}")
    )
    bot.send_message(
        user_id,
        "🔓 **آنلاک اپل آیدی**\n\n"
        "آیا **ایمیل چنج شده** دارید؟\n"
        "اگر دارید، روی **وارد کردن ایمیل** کلیک کنید.\n"
        "اگر ندارید، روی **ندارم** کلیک کنید.",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("unlock_has_email_"))
def unlock_has_email(call):
    user_id = int(call.data.split("_")[3])
    if user_id != call.message.chat.id:
        bot.answer_callback_query(call.id, "❌ این بخش برای شما نیست.")
        return
    
    bot.answer_callback_query(call.id, "📧 وارد کردن ایمیل")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🔙 بازگشت"))
    msg = bot.send_message(
        user_id,
        "🔓 **آنلاک اپل آیدی**\n\n"
        "لطفاً **ایمیل چنج شده** را وارد کنید:",
        reply_markup=markup
    )
    bot.register_next_step_handler(msg, unlock_get_email, user_id)

def unlock_get_email(message, user_id):
    if message.text == "🔙 بازگشت":
        back_to_main(message)
        return
    
    email = message.text.strip()
    if not email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        bot.send_message(user_id, "❌ ایمیل نامعتبر! لطفاً یک ایمیل معتبر وارد کنید.")
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
        markup.add(types.KeyboardButton("🔙 بازگشت"))
        msg = bot.send_message(
            user_id,
            "🔓 لطفاً ایمیل چنج شده را دوباره وارد کنید:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, unlock_get_email, user_id)
        return
    
    unlock_temp[user_id]["email"] = email
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🔙 بازگشت"))
    msg = bot.send_message(
        user_id,
        "🔓 **آنلاک اپل آیدی**\n\n"
        f"ایمیل: `{email}`\n\n"
        "لطفاً **رمز ایمیل** را وارد کنید.\n"
        "⚠️ در صورت نداشتن رمز ایمیل، درخواست شما رد می‌شود.\n\n"
        "اگر رمز ندارید، روی **🔙 بازگشت** کلیک کنید.",
        parse_mode="Markdown",
        reply_markup=markup
    )
    bot.register_next_step_handler(msg, unlock_get_email_password, user_id)

def unlock_get_email_password(message, user_id):
    if message.text == "🔙 بازگشت":
        back_to_main(message)
        return
    
    email_password = message.text.strip()
    if not email_password:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
        markup.add(types.KeyboardButton("🔙 بازگشت"))
        msg = bot.send_message(
            user_id,
            "❌ رمز ایمیل نمی‌تواند خالی باشد. دوباره وارد کنید یا روی «🔙 بازگشت» بزنید.",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, unlock_get_email_password, user_id)
        return
    
    data = unlock_temp.get(user_id)
    if not data:
        bot.send_message(user_id, "❌ خطا! لطفاً دوباره از اول شروع کنید.", reply_markup=main_menu(user_id))
        return
    
    apple_id = data["apple_id"]
    password = data["password"]
    email = data.get("email", "")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO unlock_requests (user_id, apple_id, password, email, email_password, request_date) VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, apple_id, password, email, email_password, time.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    if user_id in unlock_temp:
        del unlock_temp[user_id]
    
    admin_msg = (
        f"🔓 **درخواست آنلاک اپل آیدی**\n\n"
        f"👤 کاربر: {user_id}\n"
        f"📱 اپل آیدی: `{apple_id}`\n"
        f"🔑 رمز اپل آیدی: `{password}`\n"
        f"📧 ایمیل چنج شده: `{email}`\n"
        f"🔑 رمز ایمیل: `{email_password}`\n\n"
        f"📅 تاریخ درخواست: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    bot.send_message(ADMIN_ID, admin_msg, parse_mode="Markdown")
    
    bot.send_message(
        user_id,
        "✅ درخواست شما با موفقیت ثبت شد.\n\n"
        "📞 برای اطلاع از نتیجه درخواست خود، با پشتیبان در تماس باشید.\n"
        "💙 از تماس شما متشکریم.",
        reply_markup=main_menu(user_id)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("unlock_no_email_"))
def unlock_no_email(call):
    user_id = int(call.data.split("_")[3])
    if user_id != call.message.chat.id:
        bot.answer_callback_query(call.id, "❌ این بخش برای شما نیست.")
        return
    
    bot.answer_callback_query(call.id, "❌ ندارم")
    bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=None)
    
    data = unlock_temp.get(user_id)
    if not data:
        bot.send_message(user_id, "❌ خطا! لطفاً دوباره از اول شروع کنید.", reply_markup=main_menu(user_id))
        return
    
    apple_id = data["apple_id"]
    password = data["password"]
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO unlock_requests (user_id, apple_id, password, email, email_password, request_date) VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, apple_id, password, "", "", time.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    
    if user_id in unlock_temp:
        del unlock_temp[user_id]
    
    admin_msg = (
        f"🔓 **درخواست آنلاک اپل آیدی** (بدون ایمیل)\n\n"
        f"👤 کاربر: {user_id}\n"
        f"📱 اپل آیدی: `{apple_id}`\n"
        f"🔑 رمز اپل آیدی: `{password}`\n"
        f"📧 ایمیل چنج شده: **ندارد**\n\n"
        f"📅 تاریخ درخواست: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    bot.send_message(ADMIN_ID, admin_msg, parse_mode="Markdown")
    
    bot.send_message(
        user_id,
        "✅ درخواست شما با موفقیت ثبت شد.\n\n"
        "📞 برای اطلاع از نتیجه درخواست خود، با پشتیبان در تماس باشید.\n"
        "💙 از تماس شما متشکریم.",
        reply_markup=main_menu(user_id)
    )

# ============================================================
# 🔙 بازگشت به منو
# ============================================================
def back_to_main(message):
    user_id = message.chat.id

    # اگر کاربر وسط یک register_next_step_handler باشد، آن مرحله را پاک کن
    # تا پیام‌های بعدی دوباره توسط مرحله قبلی گرفته نشوند.
    try:
        bot.clear_step_handler_by_chat_id(user_id)
    except Exception as e:
        logger.warning(f"خطا در پاک کردن step handler برای {user_id}: {e}")

    if user_id == ADMIN_ID:
        # اگر ادمین هست، به پنل ادمین برگرد
        bot.send_message(user_id, "🏠 بازگشت به پنل ادمین", reply_markup=admin_panel_reply())
    else:
        balance = get_user_balance(user_id)
        bot.send_message(
            user_id,
            f"🏠 به منوی اصلی برگشتید.\n💰 موجودی: {balance:,} تومان",
            reply_markup=main_menu(user_id)
        )

# ============================================================
# 📚 راهنما
# ============================================================
@bot.message_handler(commands=["help"])
def help_command(message):
    user_id = message.chat.id
    if not is_member(user_id):
        bot.send_message(user_id, "🔒 لطفاً ابتدا در کانال عضو شوید.", reply_markup=join_channel_button())
        return
    
    help_text = (
        "📚 **راهنمای ربات SARDAR VIP**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🍏 **ساخت Apple ID:**\n"
        "   ساخت اختصاصی با ایمیل خودتان یا ایمیل ما\n\n"
        "📦 **Apple ID آماده:**\n"
        "   ☁️ گارانتی ۳۱ روزه - ۴۱۰,۰۰۰ تومان\n"
        "   ☁️ گارانتی دائمی - ۴۵۰,۰۰۰ تومان\n"
        "   ❌ بدون iCloud - ۳۵۰,۰۰۰ تومان\n\n"
        "📧 **ایمیل:**\n"
        "   📧 ایمیل آماده - ۲۴۵,۰۰۰ تومان\n"
        "   📧 ساخت ایمیل سفارشی - ۲۵۰,۰۰۰ تومان\n\n"
        "🛡️ **گارانتی:**\n"
        "   برای بررسی گارانتی اپل آیدی خود از این بخش استفاده کنید\n\n"
        "🔄 **آنلاک اپل آیدی:**\n"
        "   برای رفع قفل اپل آیدی های غیرفعال\n\n"
        "💳 **افزایش موجودی:**\n"
        "   با کارت به کارت یا پرداخت مستقیم موجودی کیف پول را شارژ کنید\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👨‍💻 **پشتیبانی:**\n"
        "   در صورت هرگونه مشکل، از بخش پشتیبانی استفاده کنید.\n\n"
        "💙 **موفق و پیروز باشید!**"
    )
    bot.send_message(user_id, help_text, parse_mode="Markdown", reply_markup=main_menu(user_id))

# ============================================================
# ⚙️ پنل ادمین
# ============================================================
@bot.message_handler(func=lambda message: message.text == "پنل ادمین 🌻" and message.from_user.id == ADMIN_ID)
def admin_panel(message):
    user_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("📊 آمار"),
        types.KeyboardButton("➕ افزودن اپل آیدی"),
        types.KeyboardButton("➕ افزودن ایمیل"),
        types.KeyboardButton("📋 لیست اپل آیدی‌ها"),
        types.KeyboardButton("📋 لیست ایمیل‌ها"),
        types.KeyboardButton("✏️ ویرایش تنظیمات"),
        types.KeyboardButton("📤 ارسال پیام همگانی"),
        types.KeyboardButton("🔙 بازگشت به منو")
    )
    bot.send_message(user_id, "⚙️ پنل مدیریت", reply_markup=markup)

def admin_panel_reply():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("📊 آمار"),
        types.KeyboardButton("➕ افزودن اپل آیدی"),
        types.KeyboardButton("➕ افزودن ایمیل"),
        types.KeyboardButton("📋 لیست اپل آیدی‌ها"),
        types.KeyboardButton("📋 لیست ایمیل‌ها"),
        types.KeyboardButton("✏️ ویرایش تنظیمات"),
        types.KeyboardButton("📤 ارسال پیام همگانی"),
        types.KeyboardButton("🔙 بازگشت به منو")
    )
    return markup

# ============================================================
# 📊 آمار
# ============================================================
@bot.message_handler(func=lambda message: message.text == "📊 آمار" and message.from_user.id == ADMIN_ID)
def stats(message):
    apple_count, email_count, user_count = get_inventory_stats()
    total_apple = len(get_all_apple_ids())
    total_email = len(get_all_emails())
    text = f"📊 **آمار کلی ربات**\n\n👥 کاربران: {user_count}\n🍏 اپل آیدی‌های موجود: {apple_count}\n📧 ایمیل‌های موجود: {email_count}\n📦 کل اپل آیدی‌ها: {total_apple}\n📧 کل ایمیل‌ها: {total_email}"
    bot.send_message(ADMIN_ID, text, parse_mode="Markdown", reply_markup=admin_panel_reply())

# ============================================================
# ➕ افزودن اپل آیدی
# ============================================================
@bot.message_handler(func=lambda message: message.text == "➕ افزودن اپل آیدی" and message.from_user.id == ADMIN_ID)
def add_apple_id_admin(message):
    bot.send_message(
        ADMIN_ID,
        "لطفاً اطلاعات اپل آیدی را به صورت زیر وارد کنید:\n\n"
        "`apple_id, password, birth_date, school, job, parentsmeet, security_q1, security_a1, security_q2, security_a2, security_q3, security_a3, product_type, icloud_status, warranty_type`\n\n"
        "فیلدهای اختیاری را با 'ندارد' پر کنید.\n"
        "product_type: ready یا custom\n"
        "icloud_status: with_icloud یا without_icloud\n"
        "warranty_type: 31days یا infinite یا none\n\n"
        "مثال:\n"
        "`test@icloud.com, 123456, 1990-01-01, مدرسه, شغل, محل ملاقات, سوال1, پاسخ1, سوال2, پاسخ2, سوال3, پاسخ3, ready, with_icloud, 31days`",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(message, process_add_apple)

def process_add_apple(message):
    data = message.text.split(',')
    if len(data) != 15:
        bot.send_message(ADMIN_ID, "❌ تعداد فیلدها صحیح نیست. لطفاً دقیقاً ۱۵ فیلد وارد کنید.")
        return
    apple_id = data[0].strip()
    password = data[1].strip()
    birth_date = data[2].strip()
    school = data[3].strip()
    job = data[4].strip()
    parentsmeet = data[5].strip()
    q1 = data[6].strip()
    a1 = data[7].strip()
    q2 = data[8].strip()
    a2 = data[9].strip()
    q3 = data[10].strip()
    a3 = data[11].strip()
    product_type = data[12].strip()
    icloud_status = data[13].strip()
    warranty_type = data[14].strip()
    if add_apple_id(apple_id, password, birth_date, school, job, parentsmeet, q1, a1, q2, a2, q3, a3, product_type, icloud_status, warranty_type):
        bot.send_message(ADMIN_ID, f"✅ اپل آیدی {apple_id} با موفقیت اضافه شد.", reply_markup=admin_panel_reply())
    else:
        bot.send_message(ADMIN_ID, "❌ خطا در افزودن! احتمالاً اپل آیدی تکراری است.", reply_markup=admin_panel_reply())

# ============================================================
# ➕ افزودن ایمیل
# ============================================================
@bot.message_handler(func=lambda message: message.text == "➕ افزودن ایمیل" and message.from_user.id == ADMIN_ID)
def add_email_admin(message):
    bot.send_message(ADMIN_ID, "لطفاً ایمیل و رمز را به صورت `email, password` وارد کنید:")
    bot.register_next_step_handler(message, process_add_email)

def process_add_email(message):
    data = message.text.split(',')
    if len(data) < 2:
        bot.send_message(ADMIN_ID, "❌ فرمت نامعتبر! لطفاً به صورت `email, password` وارد کنید.")
        return
    email = data[0].strip()
    password = data[1].strip()
    if add_email(email, password):
        bot.send_message(ADMIN_ID, f"✅ ایمیل {email} با موفقیت اضافه شد.", reply_markup=admin_panel_reply())
    else:
        bot.send_message(ADMIN_ID, "❌ خطا در افزودن! احتمالاً ایمیل تکراری است.", reply_markup=admin_panel_reply())

# ============================================================
# 📋 لیست‌ها (با Pagination)
# ============================================================
@bot.message_handler(func=lambda message: message.text == "📋 لیست اپل آیدی‌ها" and message.from_user.id == ADMIN_ID)
def list_apple_ids(message):
    apples = get_all_apple_ids()
    if not apples:
        bot.send_message(ADMIN_ID, "📭 هیچ اپل آیدی در دیتابیس وجود ندارد.", reply_markup=admin_panel_reply())
        return
    chunk_size = 10
    for i in range(0, len(apples), chunk_size):
        chunk = apples[i:i+chunk_size]
        text = "📋 لیست اپل آیدی‌ها:\n\n"
        for a in chunk:
            text += f"ID: {a[0]} | {a[1]} | رمز: {a[2]} | نوع: {a[9] or 'ready'} | iCloud: {a[10] or 'with'} | گارانتی: {a[11] or 'none'} | وضعیت: {'استفاده شده' if a[7] else 'موجود'} | کاربر: {a[8] or 'ندارد'}\n"
        bot.send_message(ADMIN_ID, text, reply_markup=admin_panel_reply() if i+chunk_size >= len(apples) else None)
        time.sleep(0.5)

@bot.message_handler(func=lambda message: message.text == "📋 لیست ایمیل‌ها" and message.from_user.id == ADMIN_ID)
def list_emails(message):
    emails = get_all_emails()
    if not emails:
        bot.send_message(ADMIN_ID, "📭 هیچ ایمیلی در دیتابیس وجود ندارد.", reply_markup=admin_panel_reply())
        return
    chunk_size = 10
    for i in range(0, len(emails), chunk_size):
        chunk = emails[i:i+chunk_size]
        text = "📋 لیست ایمیل‌ها:\n\n"
        for e in chunk:
            text += f"ID: {e[0]} | {e[1]} | رمز: {e[2]} | وضعیت: {'استفاده شده' if e[3] else 'موجود'} | کاربر: {e[4] or 'ندارد'}\n"
        bot.send_message(ADMIN_ID, text, reply_markup=admin_panel_reply() if i+chunk_size >= len(emails) else None)
        time.sleep(0.5)

# ============================================================
# ✏️ ویرایش تنظیمات
# ============================================================
@bot.message_handler(func=lambda message: message.text == "✏️ ویرایش تنظیمات" and message.from_user.id == ADMIN_ID)
def edit_settings(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔄 تغییر شماره کارت", callback_data="edit_card_number"),
        types.InlineKeyboardButton("🔄 تغییر نام صاحب کارت", callback_data="edit_card_owner"),
        types.InlineKeyboardButton("🔄 تغییر درصد پاداش", callback_data="edit_bonus")
    )
    bot.send_message(
        ADMIN_ID,
        "✏️ تنظیمات فعلی:\n\n"
        "شماره کارت: " + get_setting("card_number") + "\n"
        "نام صاحب کارت: " + get_setting("card_owner") + "\n"
        "درصد پاداش: " + get_setting("bonus_percent") + "%",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "edit_card_number" and call.from_user.id == ADMIN_ID)
def edit_card_number(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "لطفاً شماره کارت جدید را وارد کنید:")
    bot.register_next_step_handler(msg, lambda m: update_setting_and_reply(m, "card_number", "شماره کارت"))

@bot.callback_query_handler(func=lambda call: call.data == "edit_card_owner" and call.from_user.id == ADMIN_ID)
def edit_card_owner(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "لطفاً نام جدید صاحب کارت را وارد کنید:")
    bot.register_next_step_handler(msg, lambda m: update_setting_and_reply(m, "card_owner", "نام صاحب کارت"))

@bot.callback_query_handler(func=lambda call: call.data == "edit_bonus" and call.from_user.id == ADMIN_ID)
def edit_bonus(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "لطفاً درصد پاداش جدید را وارد کنید (فقط عدد):")
    bot.register_next_step_handler(msg, lambda m: update_setting_and_reply(m, "bonus_percent", "درصد پاداش"))

def update_setting_and_reply(message, key, label):
    if message.from_user.id != ADMIN_ID:
        return
    value = message.text.strip()
    if key == "bonus_percent" and not value.isdigit():
        bot.send_message(ADMIN_ID, "❌ درصد باید عدد باشد.", reply_markup=admin_panel_reply())
        return
    update_setting(key, value)
    bot.send_message(ADMIN_ID, f"✅ {label} با موفقیت به {value} تغییر یافت.", reply_markup=admin_panel_reply())

# ============================================================
# 📤 ارسال پیام همگانی
# ============================================================
@bot.message_handler(func=lambda message: message.text == "📤 ارسال پیام همگانی" and message.from_user.id == ADMIN_ID)
def broadcast(message):
    bot.send_message(ADMIN_ID, "✉️ لطفاً پیام خود را برای ارسال به همه کاربران وارد کنید (برای لغو /cancel):")
    bot.register_next_step_handler(message, process_broadcast)

def process_broadcast(message):
    if message.text == "/cancel":
        bot.send_message(ADMIN_ID, "❌ ارسال همگانی لغو شد.", reply_markup=admin_panel_reply())
        return
    users = get_all_users()
    if not users:
        bot.send_message(ADMIN_ID, "❌ هیچ کاربری در دیتابیس وجود ندارد.", reply_markup=admin_panel_reply())
        return
    success = 0
    fail = 0
    for user in users:
        try:
            bot.send_message(user[0], message.text)
            success += 1
            time.sleep(0.05)
        except Exception as e:
            logger.error(f"خطا در ارسال به {user[0]}: {e}")
            fail += 1
    bot.send_message(ADMIN_ID, f"✅ پیام همگانی ارسال شد.\nموفق: {success}\nناموفق: {fail}", reply_markup=admin_panel_reply())

# ============================================================
# 🔙 بازگشت به منو (ادمین)
# ============================================================
@bot.message_handler(func=lambda message: message.text == "🔙 بازگشت به منو" and message.from_user.id == ADMIN_ID)
def back_to_main_from_admin(message):
    user_id = message.chat.id
    balance = get_user_balance(user_id)
    bot.send_message(user_id, f"🏠 به منوی اصلی برگشتید.\n💰 موجودی: {balance:,} تومان", reply_markup=main_menu(user_id))

# ============================================================
# 🔙 بازگشت عمومی
# ============================================================
@bot.message_handler(func=lambda message: message.text == "🔙 بازگشت")
def back_button(message):
    back_to_main(message)

# ============================================================
# 🏃 اجرای ربات
# ============================================================
if __name__ == "__main__":
    print("\n========================================")
    print("✅ SARDAR VIP - FIXED ORDER ROUTING v2")
    print("========================================\n")
    logger.info("🤖 ربات SARDAR  در حال راه‌اندازی...")
    logger.info("🤖 @SilverMobilStore_Bot")
    check_inventory_and_notify()
    try:
        bot.delete_webhook()
        logger.info("✅ وب‌هوک حذف شد.")
    except Exception as e:
        logger.warning(f"⚠️ خطا در حذف وب‌هوک: {e}")
    logger.info("✅ شروع به دریافت پیام‌ها...")
    try:
        bot.polling(non_stop=True, interval=0, timeout=20)
    except Exception as e:
        logger.error(f"❌ خطای اصلی: {e}")
        time.sleep(5)
