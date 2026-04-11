# --- بقالة القرية الذكية - الإصدار 10.0 (النسخة المستقرة) ---
import logging
import os
import sqlite3
import re
import json
import pytz
from datetime import datetime
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

# --- 2. إعداد قاعدة البيانات ---
DB_FILE = "bot_database.v4.0.db"

def db_connect():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    try:
        with db_connect() as conn:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS main_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, emoji TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS sub_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, main_category_id INTEGER, name TEXT NOT NULL, image_url TEXT, FOREIGN KEY (main_category_id) REFERENCES main_categories (id))")
            cursor.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, sub_category_id INTEGER, name TEXT NOT NULL, price REAL NOT NULL, delivery_fee REAL NOT NULL, FOREIGN KEY (sub_category_id) REFERENCES sub_categories (id))")
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, cart TEXT DEFAULT '{}')")
            cursor.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, user_name TEXT NOT NULL, products TEXT NOT NULL, total_price REAL NOT NULL, status TEXT DEFAULT 'قيد المراجعة', order_date TEXT NOT NULL)")

            cursor.execute("SELECT COUNT(*) FROM main_categories")
            if cursor.fetchone()[0] == 0:
                logger.info("Populating database with initial data (v4.0)...")
                main_cats = [('الدقيق', '🍚'), ('السكر', '🍚'), ('الأرز', '🍛'), ('البقوليات', '🫘'), ('الزيوت والسمن', '🧈'), ('الحليب', '🥛')]
                cursor.executemany("INSERT INTO main_categories (name, emoji) VALUES (?, ?)", main_cats)
                sub_cats = [
                    (1, 'الدقيق الأبيض', 'https://i.ibb.co/9hCFM5C/flour.png'), (1, 'الدقيق الأسمر (طحنة)', 'https://i.ibb.co/9hCFM5C/flour.png'),
                    (2, 'السكر الأبيض', 'https://i.ibb.co/yQd9y5H/sugar.png'),
                    (3, 'رز الربان', 'https://i.ibb.co/b3vY2W3/rice.png'),
                    (4, 'العدس الأحمر', None),
                    (5, 'زيت الطبخ', 'https://i.ibb.co/hRk1V2g/oil.png'),
                    (6, 'حليب البودرة', None)
                ]
                cursor.executemany("INSERT INTO sub_categories (main_category_id, name, image_url) VALUES (?, ?, ?)", sub_cats)
                products = [
                    (1, 'كيس (50 كيلو)', 12700, 1000), (1, 'نص كيس (25 كيلو)', 6350, 500),
                    (2, 'كيس (45 كيلو)', 12000, 1000), (2, 'نص كيس (22.5 كيلو)', 6000, 500),
                    (3, 'كيس (50 كيلو)', 19000, 1000), (3, 'نص كيس (25 كيلو)', 9500, 500), (3, 'قطمة (10 كيلو)', 3800, 200),
                    (4, 'كيس (10 كيلو)', 7400, 300), (4, 'كيس (5 كيلو)', 3800, 200),
                    (5, '1 كيلو', 800, 50), (5, 'نص كيلو', 400, 25),
                    (6, 'جالون (4 لتر)', 3750, 200),
                    (7, '1 كيلو', 1900, 50)
                ]
                cursor.executemany("INSERT INTO products (sub_category_id, name, price, delivery_fee) VALUES (?, ?, ?, ?)", products)
            conn.commit()
        logger.info("Database v4.0 setup successful.")
    except Exception as e:
        logger.error(f"DATABASE SETUP FAILED: {e}", exc_info=True)

# --- 3. دوال مساعدة ---
def get_product_details(prod_id):
    with db_connect() as conn:
        return conn.execute("SELECT p.*, sc.name as sub_cat_name FROM products p JOIN sub_categories sc ON p.sub_category_id = sc.id WHERE p.id = ?", (prod_id,)).fetchone()

def escape_markdown(text: str) -> str:
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def format_invoice(cart: dict) -> tuple[str, int, int]:
    if not cart: return "", 0, 0
    invoice_text = "```\n"
    invoice_text += "الصنف           الكمية  السعر  الإجمالي\n"
    invoice_text += "--------------------------------------\n"
    total_items_price, total_delivery_price = 0, 0
    for p_id, qty in cart.items():
        item = get_product_details(p_id)
        if item:
            full_name = f"{item['sub_cat_name']} {item['name']}"
            item_total = item["price"] * qty
            total_items_price += item_total
            total_delivery_price += item["delivery_fee"] * qty
            name = full_name[:14].ljust(14)
            quantity = f"x{qty}".ljust(6)
            price = str(int(item['price'])).ljust(6)
            total = str(int(item_total))
            invoice_text += f"{name}{quantity}{price}{total}\n"
    invoice_text += "--------------------------------------\n"
    invoice_text += f"🛍️ إجمالي المشتريات: {int(total_items_price)} ريال\n"
    invoice_text += f"🚚 إجمالي التوصيل:   {int(total_delivery_price)} ريال\n"
    invoice_text += "======================================\n"
    grand_total = total_items_price + total_delivery_price
    invoice_text += f"💰 المبلغ الإجمالي:   {int(grand_total)} ريال\n"
    invoice_text += "```"
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

# --- 4. واجهة البوت الرئيسية ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_message = "🏪 أهلاً بك في بقالة القرية الذكية!\n\nاختر من القائمة أدناه، أو **اكتب طلبك مباشرة** (مثال: 2 كيس سكر)."
    keyboard = [
        [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse_main_cats")],
        [InlineKeyboardButton("🛍️ عرض سلتي", callback_data="view_cart")],
        [InlineKeyboardButton("📦 طلباتي السابقة", callback_data="my_orders")]
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
    msg = "🛒 *فاتورة طلبك الحالية:*\n" + invoice_text
    
    keyboard_buttons = []
    for p_id, qty in cart.items():
        item = get_product_details(p_id)
        if item:
            full_name = f"{item['sub_cat_name']} {item['name']}"
            keyboard_buttons.append([InlineKeyboardButton(f"➕ {full_name[:20]}", callback_data=f"qty_add_{p_id}")])
            keyboard_buttons.append([InlineKeyboardButton(f"➖ {full_name[:20]}", callback_data=f"qty_rem_{p_id}")])
            keyboard_buttons.append([InlineKeyboardButton(f"❌ حذف {full_name[:15]}", callback_data=f"qty_del_{p_id}")])
            keyboard_buttons.append([InlineKeyboardButton(" ", callback_data="ignore")])

    keyboard_buttons.extend([
        [InlineKeyboardButton("✅ إرسال الطلب للمراجعة", callback_data="confirm_order")],
        [InlineKeyboardButton("🗑️ تفريغ السلة", callback_data="clear_cart")],
        [InlineKeyboardButton("« متابعة التسوق", callback_data="browse_main_cats")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)
    try:
        if query: await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        else: await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    except TelegramError as e:
        if "message is not modified" not in str(e).lower(): logger.error(f"Error in view_cart: {e}")
        
# --- 5. المعالج الموحد للأزرار ---
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
        await query.answer(f"✅ تمت إضافة '{full_name}'.", show_alert=False)
        await query.delete_message()
        return

    if data.startswith("add_"):
        prod_id = data.split("_")[1]
        cart = get_user_cart(user_id)
        cart[str(prod_id)] = cart.get(str(prod_id), 0) + 1
        save_user_cart(user_id, cart)
        item = get_product_details(prod_id)
        full_name = f"{item['sub_cat_name']} {item['name']}"
        await query.answer(f"✅ تمت إضافة '{full_name}'.", show_alert=False)
    
    elif data == "browse_main_cats":
        with db_connect() as conn:
            cats = conn.execute("SELECT * FROM main_categories ORDER BY id").fetchall()
        keyboard = [[InlineKeyboardButton(f"{cat['emoji']} {cat['name']}", callback_data=f"maincat_{cat['id']}")] for cat in cats]
        keyboard.append([InlineKeyboardButton("« العودة", callback_data="main_menu")])
        await query.edit_message_text("اختر القسم الرئيسي:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("maincat_"):
        main_cat_id = data.split("_")[1]
        with db_connect() as conn:
            sub_cats = conn.execute("SELECT * FROM sub_categories WHERE main_category_id = ? ORDER BY id", (main_cat_id,)).fetchall()
        
        if not sub_cats:
            await query.answer("لا توجد منتجات في هذا القسم بعد.", show_alert=True)
            return

        if len(sub_cats) == 1:
            await show_products_for_subcategory(query, context, sub_cats[0]['id'])
        else:
            keyboard = [[InlineKeyboardButton(f"{sc['name']}", callback_data=f"subcat_{sc['id']}")] for sc in sub_cats]
            keyboard.append([InlineKeyboardButton("« العودة للأقسام الرئيسية", callback_data="browse_main_cats")])
            await query.edit_message_text("اختر النوع:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("subcat_"):
        sub_cat_id = data.split("_")[1]
        await show_products_for_subcategory(query, context, sub_cat_id)

    elif data == "main_menu": await start(update, context)
    elif data == "view_cart": await view_cart(update, context)
    elif data.startswith("qty_"):
        action, prod_id = data.split("_")[1], data.split("_")[2]
        cart = get_user_cart(user_id)
        if action == "add": cart[prod_id] = cart.get(prod_id, 0) + 1
        elif action == "rem":
            if prod_id in cart and cart[prod_id] > 1: cart[prod_id] -= 1
            elif prod_id in cart: del cart[prod_id]
        elif action == "del":
            if prod_id in cart: del cart[prod_id]
        save_user_cart(user_id, cart)
        await view_cart(update, context)
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
            cursor.execute("INSERT INTO orders (user_id, user_name, products, total_price, order_date) VALUES (?, ?, ?, ?, ?)", (user_id, user.full_name, json.dumps(cart), grand_total, order_date))
            order_id = cursor.lastrowid
            conn.commit()
        escaped_username = escape_markdown(user.full_name)
        admin_approval_msg = f"🔔 *طلب جديد رقم* `{order_id}`\n\n*العميل:* {escaped_username}\n\n*الفاتورة:*\n{invoice_text}"
        keyboard = [
            [InlineKeyboardButton("✅ موافقة", callback_data=f"order_approve_{order_id}")],
            [InlineKeyboardButton("❌ رفض", callback_data=f"order_reject_{order_id}")]
        ]
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_approval_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
        await query.edit_message_text("⏳ تم استلام طلبك وهو الآن قيد المراجعة. سيصلك إشعار عند تأكيده.")
        save_user_cart(user_id, {})
    elif data.startswith("order_approve_"):
        order_id = data.split("_")[2]
        with db_connect() as conn:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order or order['status'] != 'قيد المراجعة':
                await query.answer("خطأ: الطلب تمت معالجته.", show_alert=True)
                return
            conn.execute("UPDATE orders SET status = 'تم التأكيد' WHERE id = ?", (order_id,))
            conn.commit()
        await context.bot.send_message(chat_id=order['user_id'], text=f"✅ تم تأكيد طلبك رقم `{order_id}` وجاري تجهيزه الآن!")
        msg = f"✅ تمت الموافقة على طلب رقم `{order_id}` للعميل {escape_markdown(order['user_name'])}."
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    elif data.startswith("order_reject_"):
        order_id = data.split("_")[2]
        with db_connect() as conn:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order or order['status'] != 'قيد المراجعة':
                await query.answer("خطأ: الطلب تمت معالجته.", show_alert=True)
                return
            conn.execute("UPDATE orders SET status = 'ملغي' WHERE id = ?", (order_id,))
            conn.commit()
        await context.bot.send_message(chat_id=order['user_id'], text=f"❌ نعتذر، تم إلغاء طلبك رقم `{order_id}`.")
        msg = f"❌ تم رفض طلب رقم `{order_id}` للعميل {escape_markdown(order['user_name'])}."
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    elif data == "my_orders":
        with db_connect() as conn:
            orders = conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,)).fetchall()
        if not orders:
            await query.edit_message_text("ليس لديك أي طلبات سابقة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="main_menu")]]))
            return
        msg = "*طلباتك الأخيرة:*\n\n"
        for order in orders:
            msg += f"📦 *طلب رقم:* `{order['id']}`\n📅 *التاريخ:* {escape_markdown(order['order_date'])}\n💰 *الإجمالي:* {int(order['total_price'])} ريال\n🚦 *الحالة:* {escape_markdown(order['status'])}\n--------------------\n"
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="main_menu")]]))
    
    elif data == "admin_panel": await admin_panel(update, context)
    elif data == "admin_add_menu": await admin_add_menu(update, context)
    elif data == "admin_delete_menu": await admin_delete_menu(update, context)

# --- 6. دالة مساعدة لعرض المنتجات ---
async def show_products_for_subcategory(query, context, sub_cat_id):
    with db_connect() as conn:
        products = conn.execute("SELECT * FROM products WHERE sub_category_id = ? ORDER BY price", (sub_cat_id,)).fetchall()
        sub_cat = conn.execute("SELECT * FROM sub_categories WHERE id = ?", (sub_cat_id,)).fetchone()
    
    caption = f"اختر الحجم المطلوب من *{escape_markdown(sub_cat['name'])}*:"
    keyboard_buttons = [[InlineKeyboardButton(f"➕ {p['name']} ({int(p['price'])} ريال)", callback_data=f"add_{p['id']}")] for p in products]
    
    with db_connect() as conn:
        sub_cats_in_main = conn.execute("SELECT COUNT(*) FROM sub_categories WHERE main_category_id = ?", (sub_cat['main_category_id'],)).fetchone()[0]
    if sub_cats_in_main > 1:
        keyboard_buttons.append([InlineKeyboardButton("« العودة للأنواع", callback_data=f"maincat_{sub_cat['main_category_id']}")])
    else:
        keyboard_buttons.append([InlineKeyboardButton("« العودة للأقسام", callback_data="browse_main_cats")])

    keyboard = InlineKeyboardMarkup(keyboard_buttons)
    
    try:
        if sub_cat['image_url']:
            await query.delete_message()
            await context.bot.send_photo(chat_id=query.effective_chat.id, photo=sub_cat['image_url'], caption=caption, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.edit_message_text(caption, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Error in show_products_for_subcategory: {e}")
        await query.edit_message_text(caption, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
        

# --- 7. لوحة تحكم المدير الكاملة ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    with db_connect() as conn:
        total_sales = conn.execute("SELECT SUM(total_price) FROM orders WHERE status = 'تم التأكيد'").fetchone()[0] or 0
        pending_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'قيد المراجعة'").fetchone()[0]
    msg = f"👑 *لوحة تحكم المدير*\n\n💰 *إجمالي المبيعات:* {int(total_sales)} ريال\n⏳ *طلبات جديدة:* {pending_orders}\n\nاختر الإجراء:"
    keyboard = [
        [InlineKeyboardButton("➕ إضافة", callback_data="admin_add_menu")],
        [InlineKeyboardButton("✏️ تعديل سعر", callback_data="admin_edit_price_start")],
        [InlineKeyboardButton("🗑️ حذف", callback_data="admin_delete_menu")],
        [InlineKeyboardButton("« العودة", callback_data="main_menu")]
    ]
    await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup(keyboard))

# --- 7.1 محادثات الإضافة ---
ADD_MAIN_CAT_NAME, ADD_MAIN_CAT_EMOJI = range(2)
ADD_SUB_CAT_CHOOSE_MAIN, ADD_SUB_CAT_NAME, ADD_SUB_CAT_IMAGE = range(3)
ADD_PROD_CHOOSE_SUB, ADD_PROD_NAME, ADD_PROD_PRICE, ADD_PROD_FEE = range(4)

async def admin_add_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("قسم رئيسي جديد", callback_data="add_main_cat_start")],
        [InlineKeyboardButton("نوع منتج جديد", callback_data="add_sub_cat_start")],
        [InlineKeyboardButton("حجم/منتج نهائي جديد", callback_data="add_prod_start")],
        [InlineKeyboardButton("« العودة", callback_data="admin_panel")]
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
    await start(update, context)
    return ConversationHandler.END

async def admin_add_sub_cat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_connect() as conn:
        cats = conn.execute("SELECT * FROM main_categories").fetchall()
    keyboard = [[InlineKeyboardButton(c['name'], callback_data=f"maincatid_{c['id']}")] for c in cats]
    keyboard.append([InlineKeyboardButton("إلغاء", callback_data="cancel_conv")])
    await update.callback_query.edit_message_text("اختر القسم الرئيسي الذي ينتمي إليه النوع الجديد:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_SUB_CAT_CHOOSE_MAIN
async def admin_add_sub_cat_choose_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_sub_cat_main_id'] = update.callback_query.data.split("_")[1]
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
    await start(update, context)
    return ConversationHandler.END

async def admin_add_prod_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_connect() as conn:
        sub_cats = conn.execute("SELECT * FROM sub_categories").fetchall()
    keyboard = [[InlineKeyboardButton(sc['name'], callback_data=f"subcatid_{sc['id']}")] for sc in sub_cats]
    keyboard.append([InlineKeyboardButton("إلغاء", callback_data="cancel_conv")])
    await update.callback_query.edit_message_text("اختر النوع الذي ينتمي إليه المنتج النهائي:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_PROD_CHOOSE_SUB
async def admin_add_prod_choose_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_prod_sub_id'] = update.callback_query.data.split("_")[1]
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
    await start(update, context)
    return ConversationHandler.END

# --- 7.2 محادثات تعديل السعر ---
EDIT_PRICE_CHOOSE, EDIT_PRICE_SET = range(2)
async def admin_edit_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_connect() as conn:
        products = conn.execute("SELECT p.id, p.name, p.price, sc.name as sub_cat_name FROM products p JOIN sub_categories sc ON p.sub_category_id = sc.id ORDER BY sc.name, p.price").fetchall()
    keyboard = [[InlineKeyboardButton(f"{p['sub_cat_name']} {p['name']} ({int(p['price'])} ريال)", callback_data=f"editprice_{p['id']}")] for p in products]
    keyboard.append([InlineKeyboardButton("إلغاء", callback_data="admin_panel")])
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
    if not new_price_text.isdigit():
        await update.message.reply_text("خطأ: الرجاء إرسال أرقام فقط. حاول مرة أخرى.")
        return EDIT_PRICE_SET
    new_price = int(new_price_text)
    prod_id = context.user_data.get('product_to_edit')
    with db_connect() as conn:
        conn.execute("UPDATE products SET price = ? WHERE id = ?", (new_price, prod_id))
        conn.commit()
    item = get_product_details(prod_id)
    full_name = f"{item['sub_cat_name']} {item['name']}"
    msg = f"✅ تم تحديث سعر *{escape_markdown(full_name)}* إلى *{new_price}* ريال بنجاح."
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    del context.user_data['product_to_edit']
    await admin_panel(update, context)
    return ConversationHandler.END

# --- 7.3 محادثات الحذف ---
DELETE_CHOOSE_TYPE, DELETE_CHOOSE_ITEM = range(2)
async def admin_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("حذف قسم رئيسي", callback_data="delete_main_cat")],
        [InlineKeyboardButton("حذف نوع منتج", callback_data="delete_sub_cat")],
        [InlineKeyboardButton("حذف حجم/منتج نهائي", callback_data="delete_prod")],
        [InlineKeyboardButton("« العودة", callback_data="admin_panel")]
    ]
    await update.callback_query.edit_message_text("ماذا تريد أن تحذف؟ (تحذير: سيتم حذف كل ما يتبعه!)", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_delete_item_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_type = update.callback_query.data.split("_")[1]
    context.user_data['item_type_to_delete'] = item_type
    
    query_text, db_query = "", ""
    if item_type == "main":
        query_text = "اختر القسم الرئيسي الذي تريد حذفه:"
        db_query = "SELECT id, name FROM main_categories"
    elif item_type == "sub":
        query_text = "اختر النوع الذي تريد حذفه:"
        db_query = "SELECT id, name FROM sub_categories"
    elif item_type == "prod":
        query_text = "اختر المنتج النهائي الذي تريد حذفه:"
        db_query = "SELECT p.id, p.name, sc.name as sub_cat_name FROM products p JOIN sub_categories sc ON p.sub_category_id = sc.id"

    with db_connect() as conn:
        items = conn.execute(db_query).fetchall()
    
    keyboard = []
    for item in items:
        name = f"{item['sub_cat_name']} {item['name']}" if 'sub_cat_name' in item.keys() else item['name']
        keyboard.append([InlineKeyboardButton(name, callback_data=f"delitem_{item['id']}")])
    keyboard.append([InlineKeyboardButton("إلغاء", callback_data="admin_panel")])
    
    await update.callback_query.edit_message_text(query_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return DELETE_CHOOSE_ITEM

async def admin_delete_item_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_id = update.callback_query.data.split("_")[1]
    item_type = context.user_data['item_type_to_delete']
    
    table_name = ""
    if item_type == "main": table_name = "main_categories"
    elif item_type == "sub": table_name = "sub_categories"
    elif item_type == "prod": table_name = "products"

    with db_connect() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"DELETE FROM {table_name} WHERE id = ?", (item_id,))
        conn.commit()

    await update.callback_query.edit_message_text("✅ تم الحذف بنجاح.")
    del context.user_data['item_type_to_delete']
    await admin_panel(update, context)
    return ConversationHandler.END

# --- دالة الإلغاء العامة ---
async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keys_to_del = [k for k in context.user_data.keys() if k.startswith('new_') or k.startswith('product_to_') or k.startswith('item_type_to_')]
    for k in keys_to_del:
        del context.user_data[k]
    
    query = update.callback_query
    if query and (query.data == "admin_panel" or query.data == "cancel_conv"):
        await admin_panel(update, context)
    else:
        await start(update, context)
    return ConversationHandler.END

# --- 8. البحث الذكي والواعي ---
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
        await update.message.reply_text(response_message, parse_mode=ParseMode.MARKDOWN_V2)
    if ambiguous_items:
        for item in ambiguous_items:
            await clarify_product_options(update, context, item['term'], item['matches'])
    if not added_items and not ambiguous_items and not_found_items:
        user = update.effective_user
        forward_message = f"رسالة لم يفهمها البوت من العميل: {user.full_name} (@{user.username or 'لا يوجد'})\n\n---\n{text}\n---"
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=forward_message)
        await update.message.reply_text("شكراً لك، تم إرسال رسالتك إلى الإدارة للمراجعة والرد عليك في أقرب وقت.")

# --- 9. الإعداد والتشغيل ---
def main() -> None:
    setup_database()
    application = Application.builder().token(TOKEN).build()
    
    add_main_cat_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_main_cat_start, pattern='^add_main_cat_start$')],
        states={ADD_MAIN_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_main_cat_name)], ADD_MAIN_CAT_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_main_cat_emoji)],},
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^cancel_conv$')]
    )
    add_sub_cat_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_sub_cat_start, pattern='^add_sub_cat_start$')],
        states={ADD_SUB_CAT_CHOOSE_MAIN: [CallbackQueryHandler(admin_add_sub_cat_choose_main, pattern='^maincatid_')], ADD_SUB_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_sub_cat_name)], ADD_SUB_CAT_IMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_sub_cat_image)],},
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^cancel_conv$')]
    )
    add_prod_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_prod_start, pattern='^add_prod_start$')],
        states={ADD_PROD_CHOOSE_SUB: [CallbackQueryHandler(admin_add_prod_choose_sub, pattern='^subcatid_')], ADD_PROD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_prod_name)], ADD_PROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_prod_price)], ADD_PROD_FEE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_prod_fee)],},
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^cancel_conv$')]
    )
    edit_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_price_start, pattern='^admin_edit_price_start$')],
        states={EDIT_PRICE_CHOOSE: [CallbackQueryHandler(admin_edit_price_choose, pattern='^editprice_')], EDIT_PRICE_SET: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_price_set)],},
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^admin_panel$')]
    )
    delete_item_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_delete_item_start, pattern='^delete_main_cat$'), CallbackQueryHandler(admin_delete_item_start, pattern='^delete_sub_cat$'), CallbackQueryHandler(admin_delete_item_start, pattern='^delete_prod$'),],
        states={DELETE_CHOOSE_ITEM: [CallbackQueryHandler(admin_delete_item_confirm, pattern='^delitem_')]},
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern='^admin_panel$')]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(add_main_cat_conv)
    application.add_handler(add_sub_cat_conv)
    application.add_handler(add_prod_conv)
    application.add_handler(edit_price_conv)
    application.add_handler(delete_item_conv)
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
