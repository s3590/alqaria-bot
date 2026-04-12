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

# --- 2. إعداد قاعدة البيانات (v12) ---
DB_FILE = "bot_database.v12.0.db"

def db_connect():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    try:
        with db_connect() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.execute("CREATE TABLE IF NOT EXISTS main_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, emoji TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS sub_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, main_category_id INTEGER, name TEXT NOT NULL, image_url TEXT, FOREIGN KEY (main_category_id) REFERENCES main_categories (id) ON DELETE CASCADE)")
            cursor.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, sub_category_id INTEGER, name TEXT NOT NULL, price REAL NOT NULL, delivery_fee REAL NOT NULL, FOREIGN KEY (sub_category_id) REFERENCES sub_categories (id) ON DELETE CASCADE)")
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, cart TEXT DEFAULT '{}')")
            cursor.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, user_name TEXT NOT NULL, products TEXT NOT NULL, total_price REAL NOT NULL, status TEXT DEFAULT 'قيد المراجعة', order_date TEXT NOT NULL, status_history TEXT DEFAULT '[]')")

            cursor.execute("PRAGMA table_info(orders)")
            columns = [info['name'] for info in cursor.fetchall()]
            if 'status_history' not in columns:
                cursor.execute("ALTER TABLE orders ADD COLUMN status_history TEXT DEFAULT '[]'")
                logger.info("Upgraded 'orders' table with 'status_history' column.")

            cursor.execute("SELECT COUNT(*) FROM main_categories")
            if cursor.fetchone()[0] == 0:
                logger.info("Populating database with initial data...")
                main_cats = [('قسم الدقيق', '🍚'), ('قسم السكر', '🍚'), ('قسم الارز', '🍛'), ('قسم البقوليات', '🫘'), ('قسم الزيت و السمن', '🧈'), (' قسم الحليب البودره ', '🥛')]
                cursor.executemany("INSERT INTO main_categories (name, emoji) VALUES (?, ?)", main_cats)
                sub_cats = [
                    (1, 'الدقيق الأبيض', None), (1, 'الدقيق الأسمر', None),
                    (2, 'السكر الأبيض', None),
                    (3, 'رز الربان', None),
                    (4, 'العدس الأحمر', None),
                    (5, 'زيت الطبخ', None),
                    (6, 'حليب البودرة', None)
                ]
                cursor.executemany("INSERT INTO sub_categories (main_category_id, name, image_url) VALUES (?, ?, ?)", sub_cats)
                

                cursor.executemany("INSERT INTO products (sub_category_id, name, price, delivery_fee) VALUES (?, ?, ?, ?)", products)
            conn.commit()
        logger.info("Database v12.0 setup successful.")
    except Exception as e:
        logger.error(f"DATABASE SETUP FAILED: {e}", exc_info=True)

# --- 3. دوال مساعدة (v12) ---
def get_product_details(prod_id):
    with db_connect() as conn:
        return conn.execute("SELECT p.*, sc.name as sub_cat_name, mc.name as main_cat_name FROM products p JOIN sub_categories sc ON p.sub_category_id = sc.id JOIN main_categories mc ON sc.main_category_id = mc.id WHERE p.id = ?", (prod_id,)).fetchone()

def escape_markdown(text: str) -> str:
    iproducts = [
    (1, 'كيس (50 كيلو)', 12700, 1000), (1, 'نص كيس (25 كيلو)', 6350, 500),
    (2, 'كيس (45 كيلو)', 12000, 1000), (2, 'نص كيس (22.5 كيلو)', 6000, 500),
    (3, 'كيس (10 كيلو)', 19000, 1000), (3, 'نص كيس (5 كيلو)', 9500, 500),
    (4, 'كيس (10 كيلو)', 7400, 300), (4, 'كيس (5 كيلو)', 3800, 200),
    (5, 'جالون (4 لتر)', 3750, 200),
    # --- منتجات حليب البودرة ---
    (6, 'كيس (25 كيلو)', 50000, 500), 
    (6, 'نص كيس (12.5 كيلو)', 25000, 250),
    (6, 'ربع كيس (6.25 كيلو)', 12500, 200),
    (6, '1 كيلو', 1900, 50)  # <-- تم نقل هذا السطر إلى الأخير
]
f not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def format_invoice(cart: dict) -> tuple[str, int, int]:
    if not cart: return "", 0, 0
    
    header = "الصنف".ljust(12) + "الكمية".ljust(10) + "السعر".ljust(9) + "الإجمالي".ljust(10)
    separator = "-" * 42
    invoice_text = f"```\n{header}\n{separator}\n"
    
    total_items_price, total_delivery_price = 0, 0
    
    for p_id, qty in cart.items():
        item = get_product_details(p_id)
        if item:
            item_total = item["price"] * qty
            total_items_price += item_total
            total_delivery_price += item["delivery_fee"] * qty
            
            col_cat = item['sub_cat_name'][:11].ljust(12)
            col_qty = f"{qty} {item['name']}"[:9].ljust(10)
            col_price = str(int(item['price'])).ljust(9)
            col_total = str(int(item_total)).ljust(10)
            
            invoice_text += f"{col_cat}{col_qty}{col_price}{col_total}\n{separator}\n"

    grand_total = total_items_price + total_delivery_price
    
    equal_separator = "=" * 42
    invoice_text += f"```\n*ملخص الفاتورة:*\n"
    invoice_text += f"🛍️ *إجمالي المشتريات:* {int(total_items_price)} ريال\n"
    invoice_text += f"🚚 *إجمالي التوصيل:* {int(total_delivery_price)} ريال\n"
    invoice_text += f"*{equal_separator}*\n"
    invoice_text += f"💰 *المبلغ الإجمالي: {int(grand_total)} ريال*"
    
    return invoice_text, grand_total, total_delivery_price

def get_user_cart(user_id: int) -> dict:
    with db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
        cart_json = cursor.execute("SELECT cart FROM users WHERE id = ?", (user_id,)).fetchone()['cart']
        return json.loads(cart_json)

def save_user_cart(user_id: int, cart: dict):
    with db_connect() as conn:
        cart_json = json.dumps(cart)
        conn.execute("UPDATE users SET cart = ? WHERE id = ?", (cart_json, user_id))
        conn.commit()

def update_order_status(order_id: int, new_status: str, actor: str = "النظام"):
    with db_connect() as conn:
        order = conn.execute("SELECT status_history FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order: return
        
        history = json.loads(order['status_history'])
        history.append({
            "status": new_status,
            "date": datetime.now(TIMEZONE).isoformat(),
            "actor": actor
        })
        
        conn.execute("UPDATE orders SET status = ?, status_history = ? WHERE id = ?", (new_status, json.dumps(history), order_id))
        conn.commit()

# --- 4. دوال الواجهة الرئيسية والفرعية ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_message = "🏪 أهلاً بك في بقالة القرية الذكية!\n\nاختر من القائمة أدناه، أو اكتب طلبك مباشرة (مثال: 2 كيس سكر)."
    keyboard = [
        [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse_main_cats")],
        [InlineKeyboardButton("🛍️ عرض سلتي", callback_data="view_cart")],
        [InlineKeyboardButton("📦 تتبع طلبي", callback_data="track_order_start")],
        [InlineKeyboardButton("📋 طلباتي السابقة", callback_data="my_orders")]
    ]
    if str(update.effective_user.id) == ADMIN_CHAT_ID:
        keyboard.append([InlineKeyboardButton("👑 لوحة تحكم المدير", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    cart = get_user_cart(user_id)

    if not cart:
        msg = "سلتك فارغة حالياً!"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("« تسوق الآن", callback_data="browse_main_cats")]])
        if query: await query.edit_message_text(msg, reply_markup=markup)
        else: await update.message.reply_text(msg, reply_markup=markup)
        return

    invoice_text, _, _ = format_invoice(cart)
    msg = "🛒 *فاتورتك الحالية:*\n" + invoice_text
    
    keyboard_buttons = [
        [InlineKeyboardButton("✅ إرسال الطلب للمراجعة", callback_data="confirm_order")],
        [InlineKeyboardButton("🗑️ تفريغ السلة", callback_data="clear_cart")],
        [InlineKeyboardButton("« متابعة التسوق", callback_data="browse_main_cats")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)
    try:
        if query: await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else: await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except TelegramError as e:
        if "message is not modified" not in str(e).lower(): logger.error(f"Error in view_cart: {e}")

async def show_products_for_main_category(query, context, main_cat_id):
    with db_connect() as conn:
        products = conn.execute("SELECT p.id, p.name as prod_name, p.price, sc.name as sub_cat_name, mc.name as main_cat_name FROM products p JOIN sub_categories sc ON p.sub_category_id = sc.id JOIN main_categories mc ON sc.main_category_id = mc.id WHERE mc.id = ? ORDER BY sc.name, p.price", (main_cat_id,)).fetchall()
        main_cat_name = products[0]['main_cat_name'] if products else "القسم"

    caption = f"اختر المنتج المطلوب من قسم *{escape_markdown(main_cat_name)}*:"
    
    if not products:
        await query.answer("لا توجد منتجات في هذا القسم بعد.", show_alert=True)
        return

    keyboard_buttons = [[InlineKeyboardButton(f"➕ {p['sub_cat_name']} {p['prod_name']} ({int(p['price'])} ريال)", callback_data=f"add_{p['id']}")] for p in products]
    keyboard_buttons.append([InlineKeyboardButton("« العودة للأقسام", callback_data="browse_main_cats")])
    keyboard = InlineKeyboardMarkup(keyboard_buttons)
    
    try:
        await query.edit_message_text(caption, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Error in show_products_for_main_category: {e}")

# --- 5. دوال لوحة تحكم المدير ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    with db_connect() as conn:
        total_sales = conn.execute("SELECT SUM(total_price) FROM orders WHERE status = 'تم التسليم'").fetchone()[0] or 0
        pending_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'قيد المراجعة'").fetchone()[0]
    msg = f"👑 *لوحة تحكم المدير*\n\n💰 *إجمالي المبيعات المكتملة:* {int(total_sales)} ريال\n⏳ *طلبات جديدة:* {pending_orders}\n\nاختر الإجراء:"
    keyboard = [
        [InlineKeyboardButton("➕ إدارة الإضافة", callback_data="admin_add_menu")],
        [InlineKeyboardButton("✏️ تعديل سعر", callback_data="admin_edit_price_start")],
        [InlineKeyboardButton("🗑️ إدارة الحذف", callback_data="admin_delete_menu")],
        [InlineKeyboardButton("📊 تقارير المبيعات", callback_data="admin_reports_menu")],
        [InlineKeyboardButton("« العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup(keyboard))

# --- 5.1 محادثات الإضافة ---
ADD_MAIN_CAT_NAME, ADD_MAIN_CAT_EMOJI = range(2)
ADD_SUB_CAT_CHOOSE_MAIN, ADD_SUB_CAT_NAME, ADD_SUB_CAT_IMAGE = range(3)
ADD_PROD_CHOOSE_SUB, ADD_PROD_NAME, ADD_PROD_PRICE, ADD_PROD_FEE = range(4)

async def admin_add_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("قسم رئيسي جديد", callback_data="add_main_cat_start")],
        [InlineKeyboardButton("نوع منتج جديد", callback_data="add_sub_cat_start")],
        [InlineKeyboardButton("حجم/منتج نهائي جديد", callback_data="add_prod_start")],
        [InlineKeyboardButton("« العودة للوحة التحكم", callback_data="admin_panel")]
    ]
    await update.callback_query.edit_message_text("ماذا تريد أن تضيف؟", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_add_main_cat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("أرسل اسم القسم الرئيسي الجديد (مثال: المعلبات).")
    return ADD_MAIN_CAT_NAME
async def admin_add_main_cat_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_main_cat_name'] = update.message.text
    await update.message.reply_text("الآن أرسل الإيموجي الخاص بهذا القسم (مثال: 🥫).")
    return ADD_MAIN_CAT_EMOJI
async def admin_add_main_cat_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data['new_main_cat_name']
    emoji = update.message.text
    try:
        with db_connect() as conn:
            conn.execute("INSERT INTO main_categories (name, emoji) VALUES (?, ?)", (name, emoji))
            conn.commit()
        await update.message.reply_text(f"✅ تم إضافة القسم الرئيسي '{name}' بنجاح.")
    except sqlite3.IntegrityError:
        await update.message.reply_text(f"❌ خطأ: القسم '{name}' موجود بالفعل.")
    del context.user_data['new_main_cat_name']
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_add_sub_cat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_connect() as conn:
        cats = conn.execute("SELECT * FROM main_categories").fetchall()
    keyboard = [[InlineKeyboardButton(c['name'], callback_data=f"addsub_main_{c['id']}")] for c in cats]
    keyboard.append([InlineKeyboardButton("إلغاء", callback_data="admin_panel")])
    await update.callback_query.edit_message_text("اختر القسم الرئيسي الذي ينتمي إليه النوع الجديد:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_SUB_CAT_CHOOSE_MAIN
async def admin_add_sub_cat_choose_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_sub_cat_main_id'] = update.callback_query.data.split("_")[2]
    await update.callback_query.edit_message_text("أرسل اسم النوع الجديد (مثال: الدقيق الأسمر).")
    return ADD_SUB_CAT_NAME
async def admin_add_sub_cat_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_sub_cat_name'] = update.message.text
    await update.message.reply_text("الآن أرسل رابط الصورة لهذا النوع، أو أرسل 'تخطي' إذا لم تكن هناك صورة.")
    return ADD_SUB_CAT_IMAGE
async def admin_add_sub_cat_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    main_id = context.user_data['new_sub_cat_main_id']
    name = context.user_data['new_sub_cat_name']
    image_url = update.message.text if update.message.text.lower() != 'تخطي' else None
    with db_connect() as conn:
        conn.execute("INSERT INTO sub_categories (main_category_id, name, image_url) VALUES (?, ?, ?)", (main_id, name, image_url))
        conn.commit()
    await update.message.reply_text(f"✅ تم إضافة النوع '{name}' بنجاح.")
    del context.user_data['new_sub_cat_main_id']
    del context.user_data['new_sub_cat_name']
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_add_prod_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_connect() as conn:
        sub_cats = conn.execute("SELECT * FROM sub_categories").fetchall()
    keyboard = [[InlineKeyboardButton(sc['name'], callback_data=f"addprod_sub_{sc['id']}")] for sc in sub_cats]
    keyboard.append([InlineKeyboardButton("إلغاء", callback_data="admin_panel")])
    await update.callback_query.edit_message_text("اختر النوع الذي ينتمي إليه المنتج النهائي:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_PROD_CHOOSE_SUB
async def admin_add_prod_choose_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_prod_sub_id'] = update.callback_query.data.split("_")[2]
    await update.callback_query.edit_message_text("أرسل اسم المنتج النهائي (مثال: كيس 50 كيلو).")
    return ADD_PROD_NAME
async def admin_add_prod_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_prod_name'] = update.message.text
    await update.message.reply_text("أرسل سعر المنتج (أرقام فقط).")
    return ADD_PROD_PRICE
async def admin_add_prod_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_prod_price'] = update.message.text
    await update.message.reply_text("أرسل رسوم توصيل المنتج (أرقام فقط).")
    return ADD_PROD_FEE
async def admin_add_prod_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sub_id = context.user_data['new_prod_sub_id']
    name = context.user_data['new_prod_name']
    price = context.user_data['new_prod_price']
    fee = update.message.text
    if not price.isdigit() or not fee.isdigit():
        await update.message.reply_text("خطأ: السعر ورسوم التوصيل يجب أن تكون أرقامًا. حاول مرة أخرى.")
        return ConversationHandler.END
    with db_connect() as conn:
        conn.execute("INSERT INTO products (sub_category_id, name, price, delivery_fee) VALUES (?, ?, ?, ?)", (sub_id, name, int(price), int(fee)))
        conn.commit()
    await update.message.reply_text(f"✅ تم إضافة المنتج '{name}' بنجاح.")
    del context.user_data['new_prod_sub_id']
    del context.user_data['new_prod_name']
    del context.user_data['new_prod_price']
    await admin_panel(update, context)
    return ConversationHandler.END

# --- 5.2 محادثات تعديل السعر ---
EDIT_PRICE_CHOOSE, EDIT_PRICE_SET = range(2)
async def admin_edit_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_connect() as conn:
        products = conn.execute("SELECT p.id, p.name, p.price, sc.name as sub_cat_name FROM products p JOIN sub_categories sc ON p.sub_category_id = sc.id ORDER BY sc.name, p.price").fetchall()
    keyboard = [[InlineKeyboardButton(f"{p['sub_cat_name']} {p['name']} ({int(p['price'])} ريال)", callback_data=f"editprice_{p['id']}")] for p in products]
    keyboard.append([InlineKeyboardButton("« العودة", callback_data="admin_panel")])
    await update.callback_query.edit_message_text("اختر المنتج الذي تريد تعديل سعره:", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_PRICE_CHOOSE
async def admin_edit_price_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    prod_id = query.data.split("_")[1]
    context.user_data['product_to_edit'] = prod_id
    item = get_product_details(prod_id)
    full_name = f"{item['sub_cat_name']} {item['name']}"
    msg = f"السعر الحالي لـ *{escape_markdown(full_name)}* هو {int(item['price'])} ريال. \n\nأرسل السعر الجديد الآن (أرقام فقط)."
    await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    return EDIT_PRICE_SET
async def admin_edit_price_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_price_text = update.message.text
    prod_id = context.user_data.get('product_to_edit')

    # التحقق من أن السعر المدخل هو رقم صالح
    if not new_price_text.isdigit():
        await update.message.reply_text("❌ خطأ: السعر يجب أن يكون أرقامًا فقط. الرجاء إرسال السعر الجديد مرة أخرى.")
        return EDIT_PRICE_SET # يبقى في نفس المرحلة ليسمح للمستخدم بإعادة المحاولة

    # التحقق من وجود معرّف المنتج في بيانات المستخدم المؤقتة
    if not prod_id:
        await update.message.reply_text("حدث خطأ ما، لم يتم العثور على المنتج المراد تعديله. الرجاء البدء من جديد.")
        if 'product_to_edit' in context.user_data:
            del context.user_data['product_to_edit']
        # بما أننا في محادثة، نحتاج إلى استدعاء دالة تعرض لوحة التحكم من جديد
        await admin_panel_from_message(update, context)
        return ConversationHandler.END

    # كل شيء سليم، قم بتحديث قاعدة البيانات
    try:
        new_price = int(new_price_text)
        with db_connect() as conn:
            conn.execute("UPDATE products SET price = ? WHERE id = ?", (new_price, prod_id))
            conn.commit()
        
        item = get_product_details(prod_id)
        full_name = f"{item['sub_cat_name']} {item['name']}"
        
        await update.message.reply_text(f"✅ تم تحديث سعر المنتج '{full_name}' إلى *{new_price} ريال* بنجاح.", parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Failed to update price for product {prod_id}: {e}")
        await update.message.reply_text("حدث خطأ أثناء تحديث السعر في قاعدة البيانات. الرجاء المحاولة مرة أخرى.")

    # تنظيف بيانات المستخدم المؤقتة والعودة إلى لوحة التحكم
    if 'product_to_edit' in context.user_data:
        del context.user_data['product_to_edit']
    
    await admin_panel_from_message(update, context)

    return ConversationHandler.END

# دالة مساعدة جديدة للعودة إلى لوحة التحكم من رسالة
async def admin_panel_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_connect() as conn:
        total_sales = conn.execute("SELECT SUM(total_price) FROM orders WHERE status = 'تم التسليم'").fetchone()[0] or 0
        pending_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'قيد المراجعة'").fetchone()[0]
    msg = f"👑 *لوحة تحكم المدير*\n\n💰 *إجمالي المبيعات المكتملة:* {int(total_sales)} ريال\n⏳ *طلبات جديدة:* {pending_orders}\n\nاختر الإجراء:"
    keyboard = [
        [InlineKeyboardButton("➕ إدارة الإضافة", callback_data="admin_add_menu")],
        [InlineKeyboardButton("✏️ تعديل سعر", callback_data="admin_edit_price_start")],
        [InlineKeyboardButton("🗑️ إدارة الحذف", callback_data="admin_delete_menu")],
        [InlineKeyboardButton("📊 تقارير المبيعات", callback_data="admin_reports_menu")],
        [InlineKeyboardButton("« العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup(keyboard))


# --- 5.3 محادثات الحذف ---
DELETE_CHOOSE_ITEM = range(1)
async def admin_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("حذف قسم رئيسي", callback_data="delete_type_main")],
        [InlineKeyboardButton("حذف نوع منتج", callback_data="delete_type_sub")],
        [InlineKeyboardButton("حذف منتج نهائي", callback_data="delete_type_prod")],
        [InlineKeyboardButton("« العودة للوحة التحكم", callback_data="admin_panel")]
    ]
    await update.callback_query.edit_message_text("ماذا تريد أن تحذف؟ (سيتم حذف كل ما يتبعه)", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_delete_item_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    item_type = query.data.split("_")[2]
    context.user_data['item_type_to_delete'] = item_type
    
    items = []
    message_text = ""
    with db_connect() as conn:
        if item_type == "main":
            items = conn.execute("SELECT id, name FROM main_categories").fetchall()
            message_text = "اختر القسم الرئيسي الذي تريد حذفه:"
        elif item_type == "sub":
            items = conn.execute("SELECT sc.id, sc.name, mc.name as main_cat_name FROM sub_categories sc JOIN main_categories mc ON sc.main_category_id = mc.id").fetchall()
            message_text = "اختر النوع الذي تريد حذفه:"
        elif item_type == "prod":
            items = conn.execute("SELECT p.id, p.name, sc.name as sub_cat_name FROM products p JOIN sub_categories sc ON p.sub_category_id = sc.id").fetchall()
            message_text = "اختر المنتج النهائي الذي تريد حذفه:"

    if not items:
        await query.edit_message_text("لا توجد عناصر للحذف.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="admin_delete_menu")]]))
        return ConversationHandler.END

    keyboard = []
    for item in items:
        if item_type == 'main':
            label = f"{item['name']}"
        elif item_type == 'sub':
            label = f"{item['main_cat_name']} -> {item['name']}"
        else: # prod
            label = f"{item['sub_cat_name']} -> {item['name']}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"delitem_{item['id']}")])
    
    keyboard.append([InlineKeyboardButton("« إلغاء", callback_data="admin_panel")])
    await query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return DELETE_CHOOSE_ITEM

async def admin_delete_item_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    item_id = query.data.split("_")[1]
    item_type = context.user_data.get('item_type_to_delete')

    table_map = {
        "main": "main_categories",
        "sub": "sub_categories",
        "prod": "products"
    }
    table_name = table_map.get(item_type)

    if not table_name:
        await query.edit_message_text("خطأ غير متوقع. حاول مرة أخرى.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="admin_panel")]]))
        return ConversationHandler.END

    with db_connect() as conn:
        conn.execute(f"DELETE FROM {table_name} WHERE id = ?", (item_id,))
        conn.commit()

    await query.edit_message_text("✅ تم حذف العنصر بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة للوحة التحكم", callback_data="admin_panel")]]))
    del context.user_data['item_type_to_delete']
    return ConversationHandler.END

# --- 5.4 تقارير المبيعات ---
async def admin_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("تقرير اليوم", callback_data="gen_report_today")],
        [InlineKeyboardButton("تقرير الأمس", callback_data="gen_report_yesterday")],
        [InlineKeyboardButton("تقرير آخر 7 أيام", callback_data="gen_report_week")],
        [InlineKeyboardButton("« العودة للوحة التحكم", callback_data="admin_panel")]
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
    
    start_date_str = start_date.isoformat()
    
    with db_connect() as conn:
        orders = conn.execute("SELECT * FROM orders WHERE status = 'تم التسليم' AND order_date >= ?", (start_date_str,)).fetchall()

    if not orders:
        await query.edit_message_text(f"لا توجد مبيعات مكتملة في الفترة المحددة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="admin_reports_menu")]]))
        return

    total_sales = sum(o['total_price'] for o in orders)
    num_orders = len(orders)
    product_sales = {}
    for order in orders:
        cart = json.loads(order['products'])
        for prod_id, qty in cart.items():
            prod_id_str = str(prod_id)
            if prod_id_str in product_sales:
                product_sales[prod_id_str] += qty
            else:
                product_sales[prod_id_str] = qty
    
    sorted_products = sorted(product_sales.items(), key=lambda item: item[1], reverse=True)
    
    report_text = f"📊 *{title}*\n"
    report_text += f"*{'='*20}*\n"
    report_text += f"💰 *إجمالي المبيعات:* {int(total_sales)} ريال\n"
    report_text += f"📦 *عدد الطلبات:* {num_orders}\n\n"
    report_text += "📈 *المنتجات الأكثر مبيعًا:*\n"
    
    for i, (prod_id, qty) in enumerate(sorted_products[:5]):
        details = get_product_details(prod_id)
        if details:
            full_name = f"{details['sub_cat_name']} {details['name']}"
            report_text += f"{i+1}. {escape_markdown(full_name)} - *(الكمية: {qty})*\n"
            
    await query.edit_message_text(report_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="admin_reports_menu")]]))


# --- 6. تتبع الطلب للعميل ---
TRACK_ORDER_ID = range(1)
async def track_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("الرجاء إرسال رقم الطلب الذي تريد تتبعه.")
    return TRACK_ORDER_ID

async def track_order_show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_id = update.message.text
    if not order_id.isdigit():
        await update.message.reply_text("رقم الطلب غير صالح. الرجاء إرسال أرقام فقط.")
        await start(update, context)
        return ConversationHandler.END

    with db_connect() as conn:
        order = conn.execute("SELECT * FROM orders WHERE id = ? AND user_id = ?", (order_id, update.effective_user.id)).fetchone()

    if not order:
        await update.message.reply_text(f"عذراً، لم يتم العثور على طلب بهذا الرقم `{order_id}`.", parse_mode=ParseMode.MARKDOWN)
        await start(update, context)
        return ConversationHandler.END

    history = json.loads(order['status_history'])
    status_text = f"🚦 *تتبع حالة الطلب رقم `{order_id}`*\n\n"
    for event in history:
        try:
            date_obj = datetime.fromisoformat(event['date']).astimezone(TIMEZONE).strftime('%Y-%m-%d %I:%M %p')
        except (ValueError, TypeError):
            date_obj = event['date'] # Fallback for old format
        status_text += f"🔹 *{escape_markdown(event['status'])}* - {escape_markdown(date_obj)}\n"
    
    await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN_V2)
    await start(update, context)
    return ConversationHandler.END

# --- 7. البحث الذكي (v13) ---
GREETING_KEYWORDS = ["كيف", "حالك", "السلام", "عليكم", "مرحبا", "بكم", "صباح", "مساء", "بقالة", "اهلًا", "هلا"]

def find_product_matches(text_line: str):
    words = text_line.split()
    with db_connect() as conn:
        all_products = conn.execute("SELECT p.id, p.name as prod_name, sc.name as sub_cat_name FROM products p JOIN sub_categories sc ON p.sub_category_id = sc.id").fetchall()
    
    candidates = []
    for product in all_products:
        full_name = f"{product['sub_cat_name']} {product['prod_name']}"
        score = 0
        for word in words:
            if word in full_name:
                score += 1
        if score > 0:
            candidates.append({'product': product, 'score': score})
    
    return sorted(candidates, key=lambda x: x['score'], reverse=True)

async def clarify_product_options(update: Update, context: ContextTypes.DEFAULT_TYPE, term: str, matches: list):
    keyboard = []
    for match in matches:
        prod = match['product']
        full_name = f"{prod['sub_cat_name']} {prod['prod_name']}"
        keyboard.append([InlineKeyboardButton(f"➕ {full_name}", callback_data=f"add_clarify_{prod['id']}")])
    
    await update.message.reply_text(f"وجدت عدة منتجات تطابق '{term}'، أيها تقصد؟", reply_markup=InlineKeyboardMarkup(keyboard))

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if any(keyword in text.lower() for keyword in GREETING_KEYWORDS):
        await update.message.reply_text("أهلاً بك! أنا بوت بقالة القرية الذكية. يمكنك تصفح المنتجات من الأزرار أو كتابة طلبك مباشرة.")
        return

    added_items, not_found_items, ambiguous_items = [], [], []

    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        
        quantity_match = re.match(r'^\d+', line)
        quantity = 1
        search_text = line
        if quantity_match:
            quantity = int(quantity_match.group(0))
            search_text = line[quantity_match.end():].strip()
        
        matches = find_product_matches(search_text)

        if not matches:
            not_found_items.append(line)
            continue

        if len(matches) == 1 or matches[0]['score'] > matches[1]['score']:
            best_match = matches[0]['product']
            cart = get_user_cart(user_id)
            cart[str(best_match['id'])] = cart.get(str(best_match['id']), 0) + quantity
            save_user_cart(user_id, cart)
            
            full_name = f"{best_match['sub_cat_name']} {best_match['prod_name']}"
            added_items.append(f"(x{quantity}) {full_name}")
        else:
            top_score = matches[0]['score']
            ambiguous_matches = [m for m in matches if m['score'] == top_score]
            ambiguous_items.append({'term': search_text, 'matches': ambiguous_matches})

    response_message = ""
    if added_items:
        response_message += "✅ *تمت إضافة المنتجات التالية للسلة:*\n" + "\n".join(f"- {item}" for item in added_items)
    
    if not_found_items:
        if response_message: response_message += "\n\n"
        response_message += "⚠️ *عذراً، لم أتمكن من العثور على:*\n" + "\n".join(f"- {item}" for item in not_found_items)

    if response_message:
        await update.message.reply_text(response_message, parse_mode=ParseMode.MARKDOWN)

    if ambiguous_items:
        for item in ambiguous_items:
            await clarify_product_options(update, context, item['term'], item['matches'])
    
    if added_items or ambiguous_items:
        await view_cart(update, context)
    elif not_found_items:
        user = update.effective_user
        forward_message = f"رسالة لم يفهمها البوت من العميل: {user.full_name} (@{user.username or 'لا يوجد'})\n\n---\n{text}\n---"
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=forward_message)
        await update.message.reply_text("شكراً لك، تم إرسال رسالتك إلى الإدارة للمراجعة والرد عليك في أقرب وقت.")

# --- 8. المعالج الموحد للأزرار ---
async def unified_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data == "ignore": return

    if data.startswith("add_clarify_"):
        prod_id = data.split("_")[2]
        cart = get_user_cart(user_id)
        cart[str(prod_id)] = cart.get(str(prod_id), 0) + 1
        save_user_cart(user_id, cart)
        item = get_product_details(prod_id)
        full_name = f"{item['sub_cat_name']} {item['name']}"
        await query.answer(f"✅ تمت إضافة: {full_name}", show_alert=True)
        await query.delete_message()
        await view_cart(update, context)
        return

    if data.startswith("add_"):
        prod_id = data.split("_")[1]
        cart = get_user_cart(user_id)
        cart[str(prod_id)] = cart.get(str(prod_id), 0) + 1
        save_user_cart(user_id, cart)
        item = get_product_details(prod_id)
        full_name = f"{item['sub_cat_name']} {item['name']}"
        await query.answer(f"✅ تمت إضافة: {full_name}", show_alert=True)
        return

    if data == "browse_main_cats":
        with db_connect() as conn:
            cats = conn.execute("SELECT * FROM main_categories ORDER BY id").fetchall()
        keyboard = [[InlineKeyboardButton(f"{cat['emoji']} {cat['name']}", callback_data=f"maincat_{cat['id']}")] for cat in cats]
        keyboard.append([InlineKeyboardButton("« العودة للقائمة الرئيسية", callback_data="main_menu")])
        await query.edit_message_text("اختر القسم الرئيسي:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("maincat_"):
        main_cat_id = data.split("_")[1]
        await show_products_for_main_category(query, context, main_cat_id)

    elif data == "main_menu": await start(update, context)
    elif data == "view_cart": await view_cart(update, context)
    elif data == "clear_cart":
        keyboard = [
            [InlineKeyboardButton("نعم، قم بالتفريغ", callback_data="clear_cart_confirm")],
            [InlineKeyboardButton("لا، تراجع", callback_data="view_cart")]
        ]
        await query.edit_message_text("⚠️ هل أنت متأكد أنك تريد تفريغ سلتك بالكامل؟", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "clear_cart_confirm":
        save_user_cart(user_id, {})
        await query.edit_message_text("🗑️ تم تفريغ سلتك بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة للقائمة", callback_data="main_menu")]]))
    elif data == "confirm_order":
        cart = get_user_cart(user_id)
        if not cart:
            await query.answer("سلتك فارغة!", show_alert=True)
            return
        user = query.from_user
        invoice_text, grand_total, _ = format_invoice(cart)
        order_date = datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M')
        
        with db_connect() as conn:
            cursor = conn.cursor()
            initial_history = json.dumps([{"status": "قيد المراجعة", "date": datetime.now(TIMEZONE).isoformat(), "actor": "النظام"}])
            cursor.execute("INSERT INTO orders (user_id, user_name, products, total_price, order_date, status_history) VALUES (?, ?, ?, ?, ?, ?)", (user_id, user.full_name, json.dumps(cart), grand_total, order_date, initial_history))
            order_id = cursor.lastrowid
            conn.commit()
        
        admin_approval_msg = f"🔔 *طلب جديد رقم* `{order_id}`\n*العميل:* {escape_markdown(user.full_name)}\n\n{invoice_text}"
        keyboard = [
            [InlineKeyboardButton("✅ موافقة", callback_data=f"order_approve_{order_id}")],
            [InlineKeyboardButton("❌ رفض", callback_data=f"order_reject_{order_id}")]
        ]
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_approval_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        
        await query.edit_message_text(f"✅ تم استلام طلبك بنجاح!\nرقم طلبك هو: `{order_id}`\n\nيمكنك استخدامه لتتبع حالة الطلب لاحقًا.", parse_mode=ParseMode.MARKDOWN)
        save_user_cart(user_id, {})

    elif data.startswith("order_approve_"):
        order_id = data.split("_")[2]
        with db_connect() as conn:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order or order['status'] != 'قيد المراجعة':
            await query.answer("خطأ: الطلب تمت معالجته.", show_alert=True)
            return
        update_order_status(order_id, "تم التأكيد", actor="المدير")
        await context.bot.send_message(chat_id=order['user_id'], text=f"✅ تم تأكيد طلبك رقم `{order_id}` وجاري تجهيزه الآن!", parse_mode=ParseMode.MARKDOWN)
        
        keyboard = [
            [InlineKeyboardButton("🚚 خرج للتوصيل", callback_data=f"order_out_{order_id}")],
            [InlineKeyboardButton("✅ تم التسليم", callback_data=f"order_delivered_{order_id}")],
            [InlineKeyboardButton("❌ إلغاء الطلب", callback_data=f"order_reject_{order_id}")]
        ]
        await query.edit_message_text(f"✅ تمت الموافقة على طلب رقم `{order_id}`. اختر الإجراء التالي:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("order_reject_"):
        order_id = data.split("_")[2]
        with db_connect() as conn:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order or order['status'] in ['ملغي', 'تم التسليم']:
            await query.answer("خطأ: لا يمكن تغيير حالة هذا الطلب.", show_alert=True)
            return
        update_order_status(order_id, "ملغي", actor="المدير")
        await context.bot.send_message(chat_id=order['user_id'], text=f"❌ نعتذر، تم إلغاء طلبك رقم `{order_id}`.", parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text(f"❌ تم إلغاء طلب رقم `{order_id}`.", parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("order_out_"):
        order_id = data.split("_")[2]
        update_order_status(order_id, "خرج للتوصيل", actor="المدير")
        with db_connect() as conn:
            user_id = conn.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)).fetchone()['user_id']
        await context.bot.send_message(chat_id=user_id, text=f"🚚 طلبك رقم `{order_id}` في طريقه إليك الآن!", parse_mode=ParseMode.MARKDOWN)
        keyboard = [[InlineKeyboardButton("✅ تم التسليم", callback_data=f"order_delivered_{order_id}")]]
        await query.edit_message_text(f"🚚 تم تحديث حالة الطلب `{order_id}` إلى 'خرج للتوصيل'.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("order_delivered_"):
        order_id = data.split("_")[2]
        update_order_status(order_id, "تم التسليم", actor="المدير")
        with db_connect() as conn:
            user_id = conn.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)).fetchone()['user_id']
        await context.bot.send_message(chat_id=user_id, text=f"🎉 نأمل أن تكون راضيًا عن الخدمة! تم تسليم طلبك رقم `{order_id}` بنجاح.", parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text(f"🎉 تم تحديث حالة الطلب `{order_id}` إلى 'تم التسليم'.", parse_mode=ParseMode.MARKDOWN)

    elif data == "my_orders":
        with db_connect() as conn:
            orders = conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,)).fetchall()
        if not orders:
            await query.edit_message_text("ليس لديك أي طلبات سابقة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="main_menu")]]))
            return
        msg = "*طلباتك الأخيرة:*\n\n"
        for order in orders:
            msg += f"📦 *طلب رقم:* `{order['id']}`\n"
            msg += f"📅 *التاريخ:* {escape_markdown(order['order_date'])}\n"
            msg += f"💰 *الإجمالي:* {int(order['total_price'])} ريال\n"
            msg += f"🚦 *الحالة:* {escape_markdown(order['status'])}\n--------------------\n"
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="main_menu")]]))
    
    elif data == "admin_panel": await admin_panel(update, context)
    elif data == "admin_add_menu": await admin_add_menu(update, context)
    elif data == "admin_delete_menu": await admin_delete_menu(update, context)
    elif data == "admin_reports_menu": await admin_reports_menu(update, context)
    elif data.startswith("gen_report_"): await generate_report(update, context)

# --- دالة الإلغاء العامة ---
async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keys_to_del = [k for k in context.user_data.keys() if k.startswith('new_') or k.startswith('product_to_') or k.startswith('item_type_to_')]
    for k in keys_to_del:
        del context.user_data[k]
    
    query = update.callback_query
    if query:
        await query.answer()
        if 'admin_panel' in query.data:
             await admin_panel(update, context)
        else:
             await start(update, context)
    else:
        await start(update, context)
    return ConversationHandler.END

# --- 9. الإعداد والتشغيل ---
def main() -> None:
    setup_database()
    application = Application.builder().token(TOKEN).build()
    
    add_main_cat_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_main_cat_start, pattern='^add_main_cat_start$')],
        states={
            ADD_MAIN_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_main_cat_name)],
            ADD_MAIN_CAT_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_main_cat_emoji)],
        },
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^admin_panel$')]
    )
    add_sub_cat_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_sub_cat_start, pattern='^add_sub_cat_start$')],
        states={
            ADD_SUB_CAT_CHOOSE_MAIN: [CallbackQueryHandler(admin_add_sub_cat_choose_main, pattern='^addsub_main_')],
            ADD_SUB_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_sub_cat_name)],
            ADD_SUB_CAT_IMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_sub_cat_image)],
        },
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^admin_panel$')]
    )
    add_prod_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_prod_start, pattern='^add_prod_start$')],
        states={
            ADD_PROD_CHOOSE_SUB: [CallbackQueryHandler(admin_add_prod_choose_sub, pattern='^addprod_sub_')],
            ADD_PROD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_prod_name)],
            ADD_PROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_prod_price)],
            ADD_PROD_FEE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_prod_fee)],
        },
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^admin_panel$')]
    )
    edit_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_price_start, pattern='^admin_edit_price_start$')],
        states={
            EDIT_PRICE_CHOOSE: [CallbackQueryHandler(admin_edit_price_choose, pattern='^editprice_')],
            EDIT_PRICE_SET: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_price_set)],
        },
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^admin_panel$')]
    )
    delete_item_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_delete_item_start, pattern='^delete_type_main$'),
            CallbackQueryHandler(admin_delete_item_start, pattern='^delete_type_sub$'),
            CallbackQueryHandler(admin_delete_item_start, pattern='^delete_type_prod$'),
        ],
        states={
            DELETE_CHOOSE_ITEM: [CallbackQueryHandler(admin_delete_item_confirm, pattern='^delitem_')]
        },
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^admin_panel$')]
    )
    track_order_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(track_order_start, pattern='^track_order_start$')],
        states={
            TRACK_ORDER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, track_order_show_status)]
        },
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^main_menu$')]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(add_main_cat_conv)
    application.add_handler(add_sub_cat_conv)
    application.add_handler(add_prod_conv)
    application.add_handler(edit_price_conv)
    application.add_handler(delete_item_conv)
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
