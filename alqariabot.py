# --- بقالة القرية الذكية - الإصدار 15.1 (النسخة النهائية والمختبرة والمصححة) ---
import logging
import os
import sqlite3
import re
import json
import pytz
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# --- 1. الإعدادات الأساسية ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
WEB_URL = os.environ.get("WEB_URL")
PORT = int(os.environ.get("PORT", 8443))
TIMEZONE = pytz.timezone("Asia/Aden")

# --- 2. إعداد قاعدة البيانات (v13 - هيكل جديد) ---
DB_FILE = "bot_database.v13.0.db"

def db_connect():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    try:
        with db_connect() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            
            cursor.execute("CREATE TABLE IF NOT EXISTS departments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, emoji TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS brands (id INTEGER PRIMARY KEY AUTOINCREMENT, department_id INTEGER, name TEXT NOT NULL, image_url TEXT, FOREIGN KEY (department_id) REFERENCES departments (id) ON DELETE CASCADE)")
            cursor.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, brand_id INTEGER, name TEXT NOT NULL, price REAL NOT NULL, delivery_fee REAL NOT NULL, FOREIGN KEY (brand_id) REFERENCES brands (id) ON DELETE CASCADE)")
            
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, cart TEXT DEFAULT '{}')")
            cursor.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, user_name TEXT NOT NULL, products TEXT NOT NULL, total_price REAL NOT NULL, status TEXT DEFAULT 'قيد المراجعة', order_date TEXT NOT NULL, status_history TEXT DEFAULT '[]')")

            cursor.execute("PRAGMA table_info(orders)")
            if 'status_history' not in [info['name'] for info in cursor.fetchall()]:
                cursor.execute("ALTER TABLE orders ADD COLUMN status_history TEXT DEFAULT '[]'")

            cursor.execute("SELECT COUNT(*) FROM departments")
            if cursor.fetchone()[0] == 0:
                logger.info("Populating database with new structure data...")
                
                departments_data = [('قسم الدقيق', '🌾'), ('قسم السكر', '🍚'), ('قسم الأرز', '🍛'), ('قسم البقوليات', '🫘'), ('قسم الزيوت والسمن', '🧈'), ('قسم الحليب', '🥛')]
                cursor.executemany("INSERT INTO departments (name, emoji) VALUES (?, ?)", departments_data)

                brands_data = [(1, 'الدقيق الأبيض', None), (1, 'دقيق الطحنة', None), (2, 'السكر الأبيض', None), (3, 'رز الديوان', None), (3, 'رز الفخامة', None), (3, 'رز أبو بنت', None), (4, 'العدس الأحمر', None), (5, 'زيت الطبخ', None), (6, 'حليب البودرة', None)]
                cursor.executemany("INSERT INTO brands (department_id, name, image_url) VALUES (?, ?, ?)", brands_data)

                products_data = [
                    (1, 'كيس (50 كيلو)', 12700, 1000), (1, 'نص كيس (25 كيلو)', 6350, 500),
                    (2, 'كيس (45 كيلو)', 12000, 1000), (2, 'نص كيس (22.5 كيلو)', 6000, 500),
                    (3, 'كيس (10 كيلو)', 19000, 1000), (3, 'نص كيس (5 كيلو)', 9500, 500),
                    (4, 'كيس (10 كيلو)', 7400, 300), (4, 'كيس (5 كيلو)', 3800, 200),
                    (8, 'جالون (4 لتر)', 3750, 200),
                    (9, 'كيس (25 كيلو)', 50000, 500), (9, 'نص كيس (12.5 كيلو)', 25000, 250), (9, 'ربع كيس (6.25 كيلو)', 12500, 200), (9, '1 كيلو', 1900, 50)
                ]
                cursor.executemany("INSERT INTO products (brand_id, name, price, delivery_fee) VALUES (?, ?, ?, ?)", products_data)
            
            conn.commit()
        logger.info("Database v13.0 setup successful.")
    except Exception as e:
        logger.error(f"DATABASE SETUP FAILED: {e}", exc_info=True)

# --- 3. دوال مساعدة ---
def get_product_details(prod_id):
    with db_connect() as conn:
        return conn.execute("SELECT p.id, p.name, p.price, p.delivery_fee, b.name as brand_name, d.name as department_name FROM products p JOIN brands b ON p.brand_id = b.id JOIN departments d ON b.department_id = d.id WHERE p.id = ?", (prod_id,)).fetchone()

def escape_markdown(text: str) -> str:
    if not isinstance(text, str): text = str(text)
    return re.sub(r'([_*\[\]()~`>#\+\-=|{}.!])', r'\\\1', text)

def format_invoice(cart: dict) -> tuple[str, int, int]:
    if not cart: return "", 0, 0
    invoice_text = "```\n" + "الصنف".ljust(15) + "الكمية".ljust(8) + "السعر".ljust(9) + "الإجمالي".ljust(10) + "\n" + "-" * 42 + "\n"
    total_items_price, total_delivery_price = 0, 0
    for p_id, qty in cart.items():
        item = get_product_details(p_id)
        if item:
            item_total = item["price"] * qty
            total_items_price += item_total
            total_delivery_price += item["delivery_fee"] * qty
            invoice_text += f"{item['brand_name'][:14].ljust(15)}{str(qty).ljust(8)}{str(int(item['price'])).ljust(9)}{str(int(item_total)).ljust(10)}\n"
            invoice_text += f"  ({item['name']})".ljust(42) + "\n"
    invoice_text += "```\n*ملخص الفاتورة:*\n" + f"🛍️ *إجمالي المشتريات:* {int(total_items_price)} ريال\n" + f"🚚 *إجمالي التوصيل:* {int(total_delivery_price)} ريال\n" + f"*{'=' * 25}*\n" + f"💰 *المبلغ الإجمالي: {int(total_items_price + total_delivery_price)} ريال*"
    return invoice_text, total_items_price + total_delivery_price, total_delivery_price

def get_user_cart(user_id: int) -> dict:
    with db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
        cart_json = cursor.execute("SELECT cart FROM users WHERE id = ?", (user_id,)).fetchone()['cart']
        return json.loads(cart_json)

def save_user_cart(user_id: int, cart: dict):
    with db_connect() as conn:
        conn.execute("UPDATE users SET cart = ? WHERE id = ?", (json.dumps(cart), user_id))
        conn.commit()

def update_order_status(order_id: int, new_status: str, actor: str = "النظام"):
    with db_connect() as conn:
        order = conn.execute("SELECT status_history FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order: return
        history = json.loads(order['status_history'])
        history.append({"status": new_status, "date": datetime.now(TIMEZONE).isoformat(), "actor": actor})
        conn.execute("UPDATE orders SET status = ?, status_history = ? WHERE id = ?", (new_status, json.dumps(history), order_id))
        conn.commit()

# --- 4. دوال الواجهة الرئيسية والفرعية ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_message = "🏪 أهلاً بك في بقالة القرية الذكية!\n\nاختر من القائمة أدناه، أو اكتب طلبك مباشرة."
    keyboard = [
        [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse_departments")],
        [InlineKeyboardButton("🛍️ عرض سلتي", callback_data="view_cart")],
        [InlineKeyboardButton("📦 تتبع طلبي", callback_data="track_order_start")],
        [InlineKeyboardButton("📋 طلباتي السابقة", callback_data="my_orders")]
    ]
    if str(update.effective_user.id) == ADMIN_CHAT_ID:
        keyboard.append([InlineKeyboardButton("👑 لوحة تحكم المدير", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome_message, reply_markup=reply_markup)

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    cart = get_user_cart(update.effective_user.id)
    if not cart:
        msg, markup = "سلتك فارغة حالياً!", InlineKeyboardMarkup([[InlineKeyboardButton("« تسوق الآن", callback_data="browse_departments")]])
    else:
        invoice_text, _, _ = format_invoice(cart)
        msg = "🛒 *فاتورتك الحالية:*\n" + invoice_text
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ إرسال الطلب للمراجعة", callback_data="confirm_order")],
            [InlineKeyboardButton("🗑️ تفريغ السلة", callback_data="clear_cart")],
            [InlineKeyboardButton("« متابعة التسوق", callback_data="browse_departments")]
        ])
    try:
        if query: await query.edit_message_text(msg, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        else: await update.message.reply_text(msg, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    except TelegramError as e:
        if "message is not modified" not in str(e).lower(): logger.error(f"Error in view_cart: {e}")

async def show_brands_for_department(query, context, department_id):
    with db_connect() as conn:
        brands = conn.execute("SELECT * FROM brands WHERE department_id = ?", (department_id,)).fetchall()
        department_name = conn.execute("SELECT name FROM departments WHERE id = ?", (department_id,)).fetchone()['name']
    caption = f"اختر الصنف المطلوب من *{escape_markdown(department_name)}*:"
    if not brands:
        await query.answer("لا توجد أصناف في هذا القسم بعد.", show_alert=True)
        return
    keyboard = [[InlineKeyboardButton(b['name'], callback_data=f"brand_{b['id']}")] for b in brands]
    keyboard.append([InlineKeyboardButton("« العودة للأقسام", callback_data="browse_departments")])
    await query.edit_message_text(caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)

async def show_products_for_brand(query, context, brand_id):
    with db_connect() as conn:
        products = conn.execute("SELECT * FROM products WHERE brand_id = ? ORDER BY price", (brand_id,)).fetchall()
        brand = conn.execute("SELECT name, department_id FROM brands WHERE id = ?", (brand_id,)).fetchone()
    caption = f"اختر الحجم المطلوب من *{escape_markdown(brand['name'])}*:"
    if not products:
        await query.answer("لا توجد أحجام متاحة لهذا الصنف بعد.", show_alert=True)
        return
    keyboard = [[InlineKeyboardButton(f"➕ {p['name']} ({int(p['price'])} ريال)", callback_data=f"add_{p['id']}")] for p in products]
    keyboard.append([InlineKeyboardButton("« العودة للأصناف", callback_data=f"department_{brand['department_id']}")])
    await query.edit_message_text(caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)

# --- 5. دوال لوحة تحكم المدير (محدثة بالكامل) ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    with db_connect() as conn:
        total_sales = conn.execute("SELECT SUM(total_price) FROM orders WHERE status = 'تم التسليم'").fetchone()[0] or 0
        pending_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'قيد المراجعة'").fetchone()[0]
    msg = f"👑 *لوحة تحكم المدير*\n\n💰 *إجمالي المبيعات:* {int(total_sales)} ريال\n⏳ *طلبات جديدة:* {pending_orders}\n\nاختر الإجراء:"
    keyboard = [
        [InlineKeyboardButton("➕ إدارة الإضافة", callback_data="admin_add_menu")],
        [InlineKeyboardButton("✏️ تعديل/حذف", callback_data="admin_edit_delete_menu")],
        [InlineKeyboardButton("📊 تقارير المبيعات", callback_data="admin_reports_menu")],
        [InlineKeyboardButton("« العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_panel_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_connect() as conn:
        total_sales = conn.execute("SELECT SUM(total_price) FROM orders WHERE status = 'تم التسليم'").fetchone()[0] or 0
        pending_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'قيد المراجعة'").fetchone()[0]
    msg = f"👑 *لوحة تحكم المدير*\n\n💰 *إجمالي المبيعات:* {int(total_sales)} ريال\n⏳ *طلبات جديدة:* {pending_orders}\n\nاختر الإجراء:"
    keyboard = [
        [InlineKeyboardButton("➕ إدارة الإضافة", callback_data="admin_add_menu")],
        [InlineKeyboardButton("✏️ تعديل/حذف", callback_data="admin_edit_delete_menu")],
        [InlineKeyboardButton("📊 تقارير المبيعات", callback_data="admin_reports_menu")],
        [InlineKeyboardButton("« العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup(keyboard))

# --- 5.1 محادثات الإضافة ---
ADD_DEPT_NAME, ADD_DEPT_EMOJI = range(2)
ADD_BRAND_CHOOSE_DEPT, ADD_BRAND_NAME, ADD_BRAND_IMAGE = range(3)
ADD_PROD_CHOOSE_BRAND, ADD_PROD_NAME, ADD_PROD_PRICE, ADD_PROD_FEE = range(4)

async def admin_add_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("قسم جديد", callback_data="add_dept_start")],
        [InlineKeyboardButton("صنف/علامة تجارية جديدة", callback_data="add_brand_start")],
        [InlineKeyboardButton("منتج/حجم جديد", callback_data="add_prod_start")],
        [InlineKeyboardButton("« العودة", callback_data="admin_panel")]
    ]
    await update.callback_query.edit_message_text("ماذا تريد أن تضيف؟", reply_markup=InlineKeyboardMarkup(keyboard))

async def add_dept_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("أرسل اسم القسم الجديد (مثال: قسم المعجنات).")
    return ADD_DEPT_NAME
async def add_dept_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_dept_name'] = update.message.text
    await update.message.reply_text("الآن أرسل الإيموجي الخاص بالقسم (مثال: 🥐).")
    return ADD_DEPT_EMOJI
async def add_dept_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, emoji = context.user_data['new_dept_name'], update.message.text
    try:
        with db_connect() as conn:
            conn.execute("INSERT INTO departments (name, emoji) VALUES (?, ?)", (name, emoji))
            conn.commit()
        await update.message.reply_text(f"✅ تم إضافة القسم '{name}' بنجاح.")
    except sqlite3.IntegrityError:
        await update.message.reply_text(f"❌ خطأ: القسم '{name}' موجود بالفعل.")
    del context.user_data['new_dept_name']
    await admin_panel_from_message(update, context)
    return ConversationHandler.END

async def add_brand_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_connect() as conn: depts = conn.execute("SELECT * FROM departments").fetchall()
    keyboard = [[InlineKeyboardButton(d['name'], callback_data=f"addbrand_dept_{d['id']}")] for d in depts]
    keyboard.append([InlineKeyboardButton("إلغاء", callback_data="cancel_conv_admin")])
    await update.callback_query.edit_message_text("اختر القسم الذي ينتمي إليه الصنف الجديد:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_BRAND_CHOOSE_DEPT
async def add_brand_choose_dept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_brand_dept_id'] = update.callback_query.data.split("_")[2]
    await update.callback_query.edit_message_text("أرسل اسم الصنف الجديد (مثال: رز الوليمة).")
    return ADD_BRAND_NAME
async def add_brand_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_brand_name'] = update.message.text
    await update.message.reply_text("أرسل رابط صورة الصنف، أو 'تخطي'.")
    return ADD_BRAND_IMAGE
async def add_brand_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dept_id, name = context.user_data['new_brand_dept_id'], context.user_data['new_brand_name']
    image_url = update.message.text if update.message.text.lower() != 'تخطي' else None
    with db_connect() as conn:
        conn.execute("INSERT INTO brands (department_id, name, image_url) VALUES (?, ?, ?)", (dept_id, name, image_url))
        conn.commit()
    await update.message.reply_text(f"✅ تم إضافة الصنف '{name}' بنجاح.")
    del context.user_data['new_brand_dept_id'], context.user_data['new_brand_name']
    await admin_panel_from_message(update, context)
    return ConversationHandler.END

async def add_prod_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_connect() as conn: 
        brands = conn.execute("SELECT b.id, b.name, d.name as dept_name FROM brands b JOIN departments d ON b.department_id = d.id ORDER BY d.name, b.name").fetchall()
    keyboard = [[InlineKeyboardButton(f"{b['dept_name']} -> {b['name']}", callback_data=f"addprod_brand_{b['id']}")] for b in brands]
    keyboard.append([InlineKeyboardButton("إلغاء", callback_data="cancel_conv_admin")])
    await update.callback_query.edit_message_text("اختر الصنف الذي ينتمي إليه المنتج:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_PROD_CHOOSE_BRAND
async def add_prod_choose_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_prod_brand_id'] = update.callback_query.data.split("_")[2]
    await update.callback_query.edit_message_text("أرسل اسم المنتج/الحجم (مثال: كيس 10 كيلو).")
    return ADD_PROD_NAME
async def add_prod_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_prod_name'] = update.message.text
    await update.message.reply_text("أرسل سعر المنتج (أرقام فقط).")
    return ADD_PROD_PRICE
async def add_prod_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_prod_price'] = update.message.text
    await update.message.reply_text("أرسل رسوم توصيل المنتج (أرقام فقط).")
    return ADD_PROD_FEE
async def add_prod_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brand_id, name, price, fee = context.user_data['new_prod_brand_id'], context.user_data['new_prod_name'], context.user_data['new_prod_price'], update.message.text
    if not price.isdigit() or not fee.isdigit():
        await update.message.reply_text("خطأ: السعر ورسوم التوصيل يجب أن تكون أرقامًا. حاول مرة أخرى.")
        return ConversationHandler.END
    with db_connect() as conn:
        conn.execute("INSERT INTO products (brand_id, name, price, delivery_fee) VALUES (?, ?, ?, ?)", (brand_id, name, int(price), int(fee)))
        conn.commit()
    await update.message.reply_text(f"✅ تم إضافة المنتج '{name}' بنجاح.")
    del context.user_data['new_prod_brand_id'], context.user_data['new_prod_name'], context.user_data['new_prod_price']
    await admin_panel_from_message(update, context)
    return ConversationHandler.END

# --- 5.2 محادثات التعديل والحذف ---
EDIT_DELETE_CHOOSE_ITEM, EDIT_PRICE_SET = range(2)

async def admin_edit_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("تعديل سعر منتج", callback_data="edit_type_price")],
        [InlineKeyboardButton("حذف قسم", callback_data="delete_type_dept")],
        [InlineKeyboardButton("حذف صنف", callback_data="delete_type_brand")],
        [InlineKeyboardButton("حذف منتج", callback_data="delete_type_prod")],
        [InlineKeyboardButton("« العودة", callback_data="admin_panel")]
    ]
    await update.callback_query.edit_message_text("اختر الإجراء:", reply_markup=InlineKeyboardMarkup(keyboard))

async def choose_item_to_edit_or_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, item_type = query.data.split("_")[0], query.data.split("_")[2]
    context.user_data['admin_action'] = {'action': action, 'type': item_type}
    
    items, message_text = [], ""
    with db_connect() as conn:
        if item_type == "price":
            items = conn.execute("SELECT p.id, p, context)
    return ConversationHandler.END

# --- 6. تقارير المبيعات وتتبع الطلب ---
async def admin_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("تقرير اليوم", callback_data="gen_report_today")],
        [InlineKeyboardButton("تقرير الأمس", callback_data="gen_report_yesterday")],
        [InlineKeyboardButton("تقرير هذا الأسبوع", callback_data="gen_report_week")],
        [InlineKeyboardButton("« العودة", callback_data="admin_panel")]
    ]
    await update.callback_query.edit_message_text("اختر فترة التقرير:", reply_markup=InlineKeyboardMarkup(keyboard))

async def generate_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    period = query.data.split("_")[2]
    now = datetime.now(TIMEZONE)
    
    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        title = "تقرير اليوم"
    elif period == "yesterday":
        yesterday = now - timedelta(days=1)
        start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        title = "تقرير الأمس"
    else: # week
        start_date = now - timedelta(days=now.weekday())
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        title = "تقرير هذا الأسبوع"
    
    with db_connect() as conn:
        orders = conn.execute("SELECT * FROM orders WHERE status = 'تم التسليم' AND order_date >= ?", (start_date.isoformat(),)).fetchall()

    if not orders:
        await query.edit_message_text(f"لا توجد مبيعات مكتملة في الفترة المحددة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="admin_reports_menu")]]))
        return

    total_sales = sum(o['total_price'] for o in orders)
    num_orders = len(orders)
    product_sales = {}
    for order in orders:
        for prod_id, qty in json.loads(order['products']).items():
            product_sales[str(prod_id)] = product_sales.get(str(prod_id), 0) + qty
    
    sorted_products = sorted(product_sales.items(), key=lambda item: item[1], reverse=True)
    
    report_text = f"📊 *{title}*\n" + f"*{'='*20}*\n" + f"💰 *إجمالي المبيعات:* {int(total_sales)} ريال\n" + f"📦 *عدد الطلبات:* {num_orders}\n\n" + "📈 *المنتجات الأكثر مبيعًا:*\n"
    
    for i, (prod_id, qty) in enumerate(sorted_products[:5]):
        details = get_product_details(prod_id)
        if details:
            report_text += f"{i+1}. {escape_markdown(details['brand_name'])} - {escape_markdown(details['name'])} *(الكمية: {qty})*\n"
            
    await query.edit_message_text(report_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="admin_reports_menu")]]))

TRACK_ORDER_ID = range(1)
async def track_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("الرجاء إرسال رقم الطلب الذي تريد تتبعه.")
    return TRACK_ORDER_ID

async def track_order_show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_id = update.message.text
    if not order_id.isdigit():
        await update.message.reply_text("رقم الطلب غير صالح. أرسل أرقامًا فقط.")
        return ConversationHandler.END

    with db_connect() as conn:
        order = conn.execute("SELECT * FROM orders WHERE id = ? AND user_id = ?", (order_id, update.effective_user.id)).fetchone()

    if not order:
        await update.message.reply_text(f"عذراً، لم يتم العثور على طلب بهذا الرقم `{order_id}` يخصك.", parse_mode=ParseMode.MARKDOWN)
    else:
        history = json.loads(order['status_history'])
        status_text = f"🚦 *تتبع حالة الطلب رقم `{order_id}`*\n\n"
        for event in history:
            date_obj = datetime.fromisoformat(event['date']).astimezone(TIMEZONE).strftime('%Y-%m-%d %I:%M %p')
            status_text += f"🔹 *{escape_markdown(event['status'])}* - {escape_markdown(date_obj)}\n"
        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN_V2)
    
    await start(update, context)
    return ConversationHandler.END

# --- 7. البحث والمعالج الموحد للأزرار ---
async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    forward_message = f"رسالة لم يفهمها البوت من العميل: {user.full_name} (@{user.username or 'لا يوجد'})\n\n---\n{update.message.text}\n---"
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=forward_message)
    await update.message.reply_text("شكراً لك، تم استلام طلبك. يمكنك استخدام أزرار تصفح المنتجات للوصول لطلبك بشكل أسرع. سيقوم أحد موظفينا بمراجعة رسالتك والرد عليك.")

async def unified_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data.startswith("add_"):
        prod_id = data.split("_")[1]
        cart = get_user_cart(user_id)
        cart[str(prod_id)] = cart.get(str(prod_id), 0) + 1
        save_user_cart(user_id, cart)
        item = get_product_details(prod_id)
        await query.answer(f"✅ تمت إضافة: {item['brand_name']} - {item['name']}", show_alert=True)
        return

    elif data == "browse_departments":
        with db_connect() as conn: depts = conn.execute("SELECT * FROM departments ORDER BY id").fetchall()
        keyboard = [[InlineKeyboardButton(f"{d['emoji']} {d['name']}", callback_data=f"department_{d['id']}")] for d in depts]
        keyboard.append([InlineKeyboardButton("« العودة للقائمة الرئيسية", callback_data="main_menu")])
        await query.edit_message_text("اختر القسم الرئيسي:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("department_"):
        await show_brands_for_department(query, context, data.split("_")[1])

    elif data.startswith("brand_"):
        await show_products_for_brand(query, context, data.split("_")[1])

    elif data == "main_menu": await start(update, context)
    elif data == "view_cart": await view_cart(update, context)
    
    elif data == "clear_cart":
        await query.edit_message_text("⚠️ هل أنت متأكد أنك تريد تفريغ سلتك؟", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("نعم، قم بالتفريغ", callback_data="clear_cart_confirm")], [InlineKeyboardButton("لا، تراجع", callback_data="view_cart")]]))
    
    elif data == "clear_cart_confirm":
        save_user_cart(user_id, {})
        await query.edit_message_text("🗑️ تم تفريغ سلتك.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="main_menu")]]))

    elif data == "confirm_order":
        cart = get_user_cart(user_id)
        if not cart:
            await query.answer("سلتك فارغة!", show_alert=True)
            return
        user = query.from_user
        invoice_text, grand_total, _ = format_invoice(cart)
        order_date = datetime.now(TIMEZONE).isoformat()
        
        with db_connect() as conn:
            cursor = conn.cursor()
            history = json.dumps([{"status": "قيد المراجعة", "date": order_date, "actor": "النظام"}])
            cursor.execute("INSERT INTO orders (user_id, user_name, products, total_price, order_date, status_history) VALUES (?, ?, ?, ?, ?, ?)", (user_id, user.full_name, json.dumps(cart), grand_total, order_date, history))
            order_id = cursor.lastrowid
            conn.commit()
        
        admin_msg = f"🔔 *طلب جديد رقم* `{order_id}`\n*العميل:* {escape_markdown(user.full_name)}\n\n{invoice_text}"
        keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"order_approve_{order_id}")], [InlineKeyboardButton("❌ رفض", callback_data=f"order_reject_{order_id}")]]
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        
        await query.edit_message_text(f"✅ تم استلام طلبك بنجاح!\nرقم طلبك هو: `{order_id}`\n\nيمكنك استخدامه لتتبع حالة الطلب.", parse_mode=ParseMode.MARKDOWN)
        save_user_cart(user_id, {})

    elif data.startswith("order_approve_") or data.startswith("order_reject_") or data.startswith("order_out_") or data.startswith("order_delivered_"):
        action, order_id = data.split("_")[1], data.split("_")[2]
        
        with db_connect() as conn: order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            await query.answer("الطلب لم يعد موجودًا.", show_alert=True)
            return

        status_map = { "approve": "تم التأكيد", "reject": "ملغي", "out": "خرج للتوصيل", "delivered": "تم التسليم" }
        new_status = status_map.get(action)
        
        if new_status:
            update_order_status(order_id, new_status, actor="المدير")
            user_messages = {
                "approve": f"✅ تم تأكيد طلبك رقم `{order_id}` وجاري تجهيزه.",
                "reject": f"❌ نعتذر، تم إلغاء طلبك رقم `{order_id}`.",
                "out": f"🚚 طلبك رقم `{order_id}` في طريقه إليك الآن!",
                "delivered": f"🎉 تم تسليم طلبك رقم `{order_id}` بنجاح. نأمل أن تكون راضيًا عن الخدمة!"
            }
            await context.bot.send_message(chat_id=order['user_id'], text=user_messages[action], parse_mode=ParseMode.MARKDOWN)

            admin_keyboards = {
                "approve": [[InlineKeyboardButton("🚚 خرج للتوصيل", callback_data=f"order_out_{order_id}")], [InlineKeyboardButton("✅ تم التسليم", callback_data=f"order_delivered_{order_id}")]],
                "out": [[InlineKeyboardButton("✅ تم التسليم", callback_data=f"order_delivered_{order_id}")]]
            }
            admin_msg = f"تم تحديث حالة الطلب `{order_id}` إلى '{new_status}'."
            await query.edit_message_text(admin_msg, reply_markup=InlineKeyboardMarkup(admin_keyboards.get(action, [])), parse_mode=ParseMode.MARKDOWN)

    elif data == "my_orders":
        with db_connect() as conn: orders = conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,)).fetchall()
        if not orders:
            await query.edit_message_text("ليس لديك أي طلبات سابقة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="main_menu")]]))
            return
        msg = "*طلباتك الأخيرة:*\n\n" + "\n".join([f"📦 *طلب رقم:* `{o['id']}`\n📅 *التاريخ:* {escape_markdown(datetime.fromisoformat(o['order_date']).strftime('%Y-%m-%d'))}\n💰 *الإجمالي:* {int(o['total_price'])} ريال\n🚦 *الحالة:* {escape_markdown(o['status'])}\n{'-'*20}" for o in orders])
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="main_menu")]]))
    
    elif data == "admin_panel": await admin_panel(update, context)
    elif data == "admin_add_menu": await admin_add_menu(update, context)
    elif data == "admin_edit_delete_menu": await admin_edit_delete_menu(update, context)
    elif data == "admin_reports_menu": await admin_reports_menu(update, context)
    elif data.startswith("gen_report_"): await generate_report(update, context)

# --- 8. دالة الإلغاء العامة والإعداد والتشغيل ---
async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for key in list(context.user_data.keys()):
        if key.startswith('new_') or key.startswith('admin_action') or key.startswith('product_to_edit'):
            del context.user_data[key]
    
    query = update.callback_query
    if query:
        await query.answer()
        if 'admin' in query.data:
             await admin_panel(update, context)
        else:
             await start(update, context)
    else:
        await start(update, context)
    return ConversationHandler.END

def main() -> None:
    setup_database()
    application = Application.builder().token(TOKEN).build()
    
    add_dept_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_dept_start, pattern='^add_dept_start$')], states={ADD_DEPT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dept_name)], ADD_DEPT_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dept_emoji)]}, fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^cancel_conv_admin$')])
    add_brand_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_brand_start, pattern='^add_brand_start$')], states={ADD_BRAND_CHOOSE_DEPT: [CallbackQueryHandler(add_brand_choose_dept, pattern='^addbrand_dept_')], ADD_BRAND_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_brand_name)], ADD_BRAND_IMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_brand_image)]}, fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^cancel_conv_admin$')])
    add_prod_conv = ConversationHandler(entry_points=[CallbackQueryHandler(add_prod_start, pattern='^add_prod_start$')], states={ADD_PROD_CHOOSE_BRAND: [CallbackQueryHandler(add_prod_choose_brand, pattern='^addprod_brand_')], ADD_PROD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_prod_name)], ADD_PROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_prod_price)], ADD_PROD_FEE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_prod_fee)]}, fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^cancel_conv_admin$')])
    
    edit_delete_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(choose_item_to_edit_or_delete, pattern='^edit_type_price$'),
            CallbackQueryHandler(choose_item_to_edit_or_delete, pattern='^delete_type_dept$'),
            CallbackQueryHandler(choose_item_to_edit_or_delete, pattern='^delete_type_brand$'),
            CallbackQueryHandler(choose_item_to_edit_or_delete, pattern='^delete_type_prod$'),
        ],
        states={
            EDIT_DELETE_CHOOSE_ITEM: [CallbackQueryHandler(process_item_selection, pattern='^selectitem_')],
            EDIT_PRICE_SET: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_price)],
        },
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^cancel_conv_admin$')]
    )
    
    track_order_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(track_order_start, pattern='^track_order_start$')],
        states={TRACK_ORDER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, track_order_show_status)]},
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^main_menu$')]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(add_dept_conv)
    application.add_handler(add_brand_conv)
    application.add_handler(add_prod_conv)
    application.add_handler(edit_delete_conv)
    application.add_handler(track_order_conv)
    application.add_handler(CallbackQueryHandler(unified_button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_handler))

    logger.info("Starting bot with webhook...")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{WEB_URL}/{TOKEN}"
    )

if __name__ == "__main__":
    main()
    
