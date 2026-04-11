# --- بقالة القرية الذكية - الإصدار 3.0 ---
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

# --- 2. إعداد قاعدة البيانات (تحديث كبير) ---
DB_FILE = "bot_database.v3.db"

def db_connect():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    try:
        with db_connect() as conn:
            cursor = conn.cursor()
            # جدول المستخدمين لحفظ السلات
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, cart TEXT DEFAULT '{}')")
            # جدول الفئات
            cursor.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, emoji TEXT)")
            # جدول المنتجات مع حقل للصورة
            cursor.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, name TEXT NOT NULL, price REAL NOT NULL, delivery_fee REAL NOT NULL, image_url TEXT, FOREIGN KEY (category_id) REFERENCES categories (id))")
            # جدول الطلبات لتتبع الحالة
            cursor.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, user_name TEXT NOT NULL, products TEXT NOT NULL, total_price REAL NOT NULL, status TEXT DEFAULT 'قيد المراجعة', order_date TEXT NOT NULL)")

            cursor.execute("SELECT COUNT(*) FROM categories")
            if cursor.fetchone()[0] == 0:
                logger.info("Database is empty, inserting initial data...")
                categories = [('دقيق وسكر', '🍚'), ('أرز وبقوليات', '🍛'), ('زيوت وحليب', '🧈'), ('معلبات وبهارات', '🥫'), ('منظفات', '🧼')]
                cursor.executemany("INSERT INTO categories (name, emoji) VALUES (?, ?)", categories)
                products = [
                    (1, 'كيس دقيق أبيض', 12700, 1000, 'https://i.ibb.co/9hCFM5C/flour.png'),
                    (1, 'كيس سكر (50 كيلو)', 19000, 1000, 'https://i.ibb.co/yQd9y5H/sugar.png'),
                    (2, 'رز الربان 10 كيلو', 7400, 300, 'https://i.ibb.co/b3vY2W3/rice.png'),
                    (3, 'جالون زيت 4 لتر', 3750, 200, 'https://i.ibb.co/hRk1V2g/oil.png'),
                    (5, 'تايت 2.5 كيلو', 2000, 100, 'https://i.ibb.co/Lz62r1b/tide.png')
                ]
                cursor.executemany("INSERT INTO products (category_id, name, price, delivery_fee, image_url) VALUES (?, ?, ?, ?, ?)", products)
            conn.commit()
        logger.info("Database v3 setup successful.")
    except Exception as e:
        logger.error(f"DATABASE SETUP FAILED: {e}", exc_info=True)

# --- 3. دوال مساعدة ---
def get_product_details(prod_id):
    with db_connect() as conn:
        return conn.execute("SELECT * FROM products WHERE id = ?", (prod_id,)).fetchone()

def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

def format_invoice(cart: dict) -> tuple[str, int, int]:
    if not cart: return "", 0, 0
    invoice_text = "```\n"
    invoice_text += "الصنف           الكمية  السعر  الإجمالي\n"
    invoice_text += "--------------------------------------\n"
    total_items_price, total_delivery_price = 0, 0
    for p_id, qty in cart.items():
        item = get_product_details(p_id)
        if item:
            item_total = item["price"] * qty
            total_items_price += item_total
            total_delivery_price += item["delivery_fee"] * qty
            name = item['name'][:14].ljust(14)
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

# --- 4. واجهة البوت ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_message = "🏪 أهلاً بك في بقالة القرية الذكية!\n\nاختر من القائمة أدناه، أو **اكتب اسم المنتج الذي تبحث عنه مباشرة**."
    keyboard = [
        [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse_cats")],
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
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("« تسوق الآن", callback_data="browse_cats")]])
        if query: await query.edit_message_text(msg, reply_markup=markup)
        else: await update.message.reply_text(msg, reply_markup=markup)
        return

    invoice_text, _, _ = format_invoice(cart)
    msg = "🛒 *فاتورة طلبك الحالية:*\n" + invoice_text
    
    keyboard = []
    for p_id, qty in cart.items():
        item = get_product_details(p_id)
        if item:
            keyboard.append([
                InlineKeyboardButton(f"➕ {item['name'][:15]}", callback_data=f"qty_add_{p_id}"),
                InlineKeyboardButton("➖", callback_data=f"qty_rem_{p_id}"),
                InlineKeyboardButton("❌", callback_data=f"qty_del_{p_id}")
            ])

    keyboard.extend([
        [InlineKeyboardButton("✅ إرسال الطلب للمراجعة", callback_data="confirm_order")],
        [InlineKeyboardButton("🗑️ تفريغ السلة", callback_data="clear_cart")],
        [InlineKeyboardButton("« متابعة التسوق", callback_data="browse_cats")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        if query: await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        else: await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    except TelegramError as e:
        if "message is not modified" not in str(e).lower(): logger.error(f"Error in view_cart: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    cart = get_user_cart(user_id)

    if data == "main_menu":
        await start(update, context)

    elif data == "browse_cats":
        with db_connect() as conn:
            cats = conn.execute("SELECT * FROM categories").fetchall()
        keyboard = [[InlineKeyboardButton(f"{cat['emoji']} {cat['name']}", callback_data=f"cat_{cat['id']}")] for cat in cats]
        keyboard.append([InlineKeyboardButton("« العودة", callback_data="main_menu")])
        await query.edit_message_text("اختر القسم الذي تريده:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("cat_"):
        cat_id = data.split("_")[1]
        with db_connect() as conn:
            products = conn.execute("SELECT * FROM products WHERE category_id = ?", (cat_id,)).fetchall()
        
        await query.edit_message_text("جاري عرض المنتجات...")
        for product in products:
            caption = f"*{escape_markdown(product['name'])}*\n\n*السعر:* {int(product['price'])} ريال"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"➕ إضافة للسلة", callback_data=f"add_{product['id']}")]])
            try:
                if product['image_url']:
                    await context.bot.send_photo(chat_id=user_id, photo=product['image_url'], caption=caption, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
                else:
                    await context.bot.send_message(chat_id=user_id, text=caption, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
            except TelegramError as e:
                logger.error(f"Failed to send product {product['id']}: {e}")
                await context.bot.send_message(chat_id=user_id, text=f"خطأ في عرض المنتج: {product['name']}")
        
        await context.bot.send_message(chat_id=user_id, text="---", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة للأقسام", callback_data="browse_cats")]]))

    elif data.startswith("add_"):
        prod_id = data.split("_")[1]
        cart[prod_id] = cart.get(prod_id, 0) + 1
        save_user_cart(user_id, cart)
        item = get_product_details(prod_id)
        await query.answer(f"✅ تمت إضافة '{item['name']}'.", show_alert=False)
    
    elif data == "view_cart":
        await view_cart(update, context)

    elif data.startswith("qty_"):
        action, prod_id = data.split("_")[1], data.split("_")[2]
        if action == "add": cart[prod_id] = cart.get(prod_id, 0) + 1
        elif action == "rem":
            if prod_id in cart and cart[prod_id] > 1: cart[prod_id] -= 1
            else: del cart[prod_id]
        elif action == "del":
            if prod_id in cart: del cart[prod_id]
        save_user_cart(user_id, cart)
        await view_cart(update, context)

    elif data == "clear_cart":
        keyboard = [[InlineKeyboardButton("نعم، قم بالتفريغ", callback_data="clear_cart_confirm")], [InlineKeyboardButton("لا، تراجع", callback_data="view_cart")]]
        await query.edit_message_text("⚠️ هل أنت متأكد أنك تريد تفريغ سلتك بالكامل؟", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "clear_cart_confirm":
        save_user_cart(user_id, {})
        await query.edit_message_text("🗑️ تم تفريغ سلتك بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة للقائمة", callback_data="main_menu")]]))

    elif data == "confirm_order":
        if not cart:
            await query.answer("سلتك فارغة!", show_alert=True)
            return
        user = query.from_user
        invoice_text, grand_total, _ = format_invoice(cart)
        order_date = datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M')
        
        with db_connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO orders (user_id, user_name, products, total_price, order_date) VALUES (?, ?, ?, ?, ?)",
                           (user_id, user.full_name, json.dumps(cart), grand_total, order_date))
            order_id = cursor.lastrowid
            conn.commit()

        escaped_username = escape_markdown(user.full_name)
        admin_approval_msg = f"🔔 *طلب جديد رقم* `{order_id}`\n\n*العميل:* {escaped_username}\n\n*الفاتورة:*\n{invoice_text}"
        keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"order_approve_{order_id}")], [InlineKeyboardButton("❌ رفض", callback_data=f"order_reject_{order_id}")]]
        
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
        await query.edit_message_text(f"✅ تمت الموافقة على طلب رقم `{order_id}` للعميل {escape_markdown(order['user_name'])}\.", parse_mode=ParseMode.MARKDOWN_V2)

    elif data.startswith("order_reject_"):
        order_id = data.split("_")[2]
        with db_connect() as conn:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order or order['status'] != 'قيد المراجعة':
                await query.answer("خطأ: الطلب تمت معالجته.", show_alert=True)
                return
            conn.execute("UPDATE orders SET status = 'ملغي' WHERE id = ?", (order_id,))
            conn.commit()

        await context.bot.send_message(chat_id=order['user_id'], text=f"❌ نعتذر، تم إلغاء طلبك رقم `{order_id}`. يمكنك التواصل مع الإدارة للمزيد من التفاصيل.")
        await query.edit_message_text(f"❌ تم رفض طلب رقم `{order_id}` للعميل {escape_markdown(order['user_name'])}\.", parse_mode=ParseMode.MARKDOWN_V2)

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
            msg += f"🚦 *الحالة:* {escape_markdown(order['status'])}\n"
            msg += "--------------------\n"
        
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="main_menu")]]))

    elif data == "admin_panel":
        with db_connect() as conn:
            total_sales = conn.execute("SELECT SUM(total_price) FROM orders WHERE status = 'تم التأكيد'").fetchone()[0] or 0
            pending_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'قيد المراجعة'").fetchone()[0]
        
        msg = (
            f"👑 *لوحة تحكم المدير*\n\n"
            f"💰 *إجمالي المبيعات المؤكدة:* {int(total_sales)} ريال\n"
            f"⏳ *الطلبات قيد المراجعة:* {pending_orders} طلب\n\n"
            f"اختر إجراءً:"
        )
        keyboard = [
            [InlineKeyboardButton("✏️ تعديل سعر منتج", callback_data="admin_edit_price_start")],
            [InlineKeyboardButton("« العودة", callback_data="main_menu")]
        ]
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=InlineKeyboardMarkup(keyboard))

# --- 5. محادثة تعديل الأسعار للمدير ---
EDIT_PRICE_CHOOSE, EDIT_PRICE_SET = range(2)

async def admin_edit_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_connect() as conn:
        products = conn.execute("SELECT id, name, price FROM products").fetchall()
    keyboard = [[InlineKeyboardButton(f"{p['name']} ({int(p['price'])} ريال)", callback_data=f"editprice_{p['id']}")] for p in products]
    keyboard.append([InlineKeyboardButton("إلغاء", callback_data="admin_panel")])
    await update.callback_query.edit_message_text("اختر المنتج الذي تريد تعديل سعره:", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_PRICE_CHOOSE

async def admin_edit_price_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    prod_id = query.data.split("_")[1]
    context.user_data['product_to_edit'] = prod_id
    item = get_product_details(prod_id)
    await query.edit_message_text(f"السعر الحالي لـ *{escape_markdown(item['name'])}* هو {int(item['price'])} ريال\. \n\nأرسل السعر الجديد الآن \(أرقام فقط\)\.", parse_mode=ParseMode.MARKDOWN_V2)
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
    await update.message.reply_text(f"✅ تم تحديث سعر *{escape_markdown(item['name'])}* إلى *{new_price}* ريال بنجاح\.", parse_mode=ParseMode.MARKDOWN_V2)
    
    del context.user_data['product_to_edit']
    await admin_panel(update, context) # العودة إلى لوحة التحكم
    return ConversationHandler.END

async def admin_panel_from_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # دالة مساعدة للعودة من محادثة تعديل السعر
    await admin_panel(update, context)
    return ConversationHandler.END

# --- 6. البحث المباشر ---
async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    search_term = update.message.text.strip().lower()
    if len(search_term) < 2: return

    with db_connect() as conn:
        results = conn.execute("SELECT * FROM products WHERE name LIKE ?", (f'%{search_term}%',)).fetchall()

    if not results:
        await update.message.reply_text(f"عذراً، لم يتم العثور على منتجات تطابق بحثك عن '{search_term}'.")
        return

    msg = f"🔍 *نتائج البحث عن '{escape_markdown(search_term)}':*"
    keyboard = [[InlineKeyboardButton(f"➕ {p['name']} ({int(p['price'])} ريال)", callback_data=f"add_{p['id']}")] for p in results]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)

# --- 7. الإعداد والتشغيل ---
def main() -> None:
    setup_database()
    application = Application.builder().token(TOKEN).build()

    edit_price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_price_start, pattern='^admin_edit_price_start$')],
        states={
            EDIT_PRICE_CHOOSE: [CallbackQueryHandler(admin_edit_price_choose, pattern='^editprice_')],
            EDIT_PRICE_SET: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_price_set)],
        },
        fallbacks=[CallbackQueryHandler(admin_panel_from_msg, pattern='^admin_panel$')],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(edit_price_conv)
    application.add_handler(CallbackQueryHandler(button_handler))
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
