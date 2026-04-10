import logging
import os
import sqlite3
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters,
    ConversationHandler
)
from telegram.constants import ParseMode
from flask import Flask, request
import threading

# --- 1. الإعدادات الأساسية ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
WEB_URL = os.environ.get("WEB_URL")
PORT = int(os.environ.get("PORT", 8443))

# --- 2. إعداد قاعدة البيانات (الكود كما هو) ---
DB_FILE = "bot_database.db"
def db_connect():
    return sqlite3.connect(DB_FILE)

def setup_database():
    try:
        with db_connect() as conn:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, emoji TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, name TEXT NOT NULL, price REAL NOT NULL, delivery_fee REAL NOT NULL, FOREIGN KEY (category_id) REFERENCES categories (id))")
            cursor.execute("SELECT COUNT(*) FROM categories")
            if cursor.fetchone()[0] == 0:
                initial_categories = [('دقيق', '🍚'), ('سكر', '🍚'), ('أرز وبقوليات', '🍛'), ('زيوت وسمن', '🧈'), ('حليب', '🥛'), ('معلبات وبهارات', '🥫'), ('منظفات', '🧼')]
                cursor.executemany("INSERT INTO categories (name, emoji) VALUES (?, ?)", initial_categories)
                initial_products = [(1, 'كيس دقيق أبيض', 12700, 1000), (1, 'نص كيس دقيق أبيض', 6350, 500), (2, 'كيس سكر (50 كيلو)', 19000, 1000), (2, 'نص كيس سكر (25 كيلو)', 9500, 500), (3, 'رز الربان 10 كيلو', 7400, 300), (4, 'جالون زيت 4 لتر', 3750, 200)]
                cursor.executemany("INSERT INTO products (category_id, name, price, delivery_fee) VALUES (?, ?, ?, ?)", initial_products)
            conn.commit()
        logger.info("Database setup successful.")
    except Exception as e:
        logger.error(f"DATABASE SETUP FAILED: {e}", exc_info=True)

# --- 3. دوال مساعدة (الكود كما هو) ---
def get_product_details(prod_id):
    with db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, price, delivery_fee FROM products WHERE id = ?", (prod_id,))
        row = cursor.fetchone()
        if row:
            return {"name": row[0], "price": row[1], "delivery_fee": row[2]}
    return None

def is_admin(update: Update) -> bool:
    return str(update.effective_user.id) == str(ADMIN_CHAT_ID)

# --- 4. واجهة البوت (الكود كما هو) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.setdefault('cart', {})
    keyboard = [
        [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse_cats")],
        [InlineKeyboardButton(f"🛍️ عرض سلتي ({len(context.user_data.get('cart', {}))})", callback_data="view_cart")],
        [InlineKeyboardButton("🔍 بحث عن منتج", callback_data="search_start")]
    ]
    if is_admin(update):
        keyboard.append([InlineKeyboardButton("👑 لوحة تحكم المدير", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("🏪 أهلاً بك في بقالة القرية الذكية!", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text("🏪 أهلاً بك في بقالة القرية الذكية!", reply_markup=reply_markup)

# ... (باقي دوال البوت مثل view_cart, button_handler, etc. تبقى كما هي)
async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    cart = context.user_data.get('cart', {})
    if not cart:
        msg = "سلتك فارغة حالياً!"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("« تسوق الآن", callback_data="browse_cats")]])
        if query: await query.edit_message_text(msg, reply_markup=markup)
        else: await update.message.reply_text(msg, reply_markup=markup)
        return
    msg = "🛒 *تفاصيل سلتك الحالية:*\n\n"
    total_items_price, total_delivery_price = 0, 0
    keyboard = []
    for p_id, qty in cart.items():
        item = get_product_details(p_id)
        if item:
            item_total = item["price"] * qty
            total_items_price += item_total
            total_delivery_price += item["delivery_fee"] * qty
            msg += f"🔹 *{item['name']}*\n   الكمية: {qty} × {item['price']} = {item_total} ريال\n"
            keyboard.append([InlineKeyboardButton("➕", callback_data=f"qty_add_{p_id}"), InlineKeyboardButton("➖", callback_data=f"qty_rem_{p_id}"), InlineKeyboardButton("❌ حذف", callback_data=f"qty_del_{p_id}")])
    grand_total = total_items_price + total_delivery_price
    msg += f"\n--------------------------------\n"
    msg += f"🛍️ إجمالي المشتريات: {total_items_price} ريال\n"
    msg += f"🚚 إجمالي التوصيل: {total_delivery_price} ريال\n"
    msg += f"--------------------------------\n"
    msg += f"💰 *المبلغ الإجمالي المطلوب: {grand_total} ريال*"
    keyboard.extend([[InlineKeyboardButton("✅ إرسال الطلب للمراجعة", callback_data="confirm_order")], [InlineKeyboardButton("🗑️ تفريغ السلة", callback_data="clear_cart")], [InlineKeyboardButton("« متابعة التسوق", callback_data="browse_cats")]])
    if query: await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    else: await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    cart = context.user_data.get('cart', {})
    if data == "main_menu":
        keyboard = [[InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse_cats")], [InlineKeyboardButton(f"🛍️ عرض سلتي ({len(cart)})", callback_data="view_cart")], [InlineKeyboardButton("🔍 بحث عن منتج", callback_data="search_start")]]
        if is_admin(update): keyboard.append([InlineKeyboardButton("👑 لوحة تحكم المدير", callback_data="admin_panel")])
        await query.edit_message_text("القائمة الرئيسية:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "browse_cats":
        with db_connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, emoji FROM categories")
            cats = cursor.fetchall()
        keyboard = [[InlineKeyboardButton(f"{emoji} {name}", callback_data=f"cat_{cat_id}")] for cat_id, name, emoji in cats]
        keyboard.append([InlineKeyboardButton("« العودة", callback_data="main_menu")])
        await query.edit_message_text("اختر القسم الذي تريده:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("cat_"):
        cat_id = data.split("_")[1]
        with db_connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, price FROM products WHERE category_id = ?", (cat_id,))
            products = cursor.fetchall()
            cursor.execute("SELECT name FROM categories WHERE id = ?", (cat_id,))
            cat_name = cursor.fetchone()[0]
        keyboard = [[InlineKeyboardButton(f"{name} ({price} ريال)", callback_data=f"add_{p_id}")] for p_id, name, price in products]
        keyboard.append([InlineKeyboardButton("« العودة للأقسام", callback_data="browse_cats")])
        await query.edit_message_text(f"منتجات قسم {cat_name}:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("add_"):
        prod_id = int(data.split("_")[1])
        cart[prod_id] = cart.get(prod_id, 0) + 1
        context.user_data['cart'] = cart
        item = get_product_details(prod_id)
        await query.answer(f"✅ تمت إضافة '{item['name']}' للسلة!", show_alert=False)
    elif data == "view_cart":
        await view_cart(update, context)
    elif data.startswith("qty_"):
        parts = data.split("_")
        action, prod_id = parts[1], int(parts[2])
        if action == "add": cart[prod_id] = cart.get(prod_id, 0) + 1
        elif action == "rem":
            if prod_id in cart and cart[prod_id] > 1: cart[prod_id] -= 1
            elif prod_id in cart and cart[prod_id] == 1: del cart[prod_id]
        elif action == "del":
            if prod_id in cart: del cart[prod_id]
        context.user_data['cart'] = cart
        await view_cart(update, context)
    elif data == "clear_cart":
        context.user_data['cart'] = {}
        await view_cart(update, context)
    elif data == "confirm_order":
        if not cart:
            await query.answer("سلتك فارغة!", show_alert=True)
            return
        user = query.from_user
        order_text, total_p, total_d = "", 0, 0
        for p_id, qty in cart.items():
            item = get_product_details(p_id)
            if item:
                order_text += f"- {item['name']} (الكمية: {qty})\n"
                total_p += item["price"] * qty
                total_d += item["delivery_fee"] * qty
        grand_total = total_p + total_d
        admin_approval_msg = (f"🔔 *طلب جديد بانتظار موافقتك*\n\n*العميل:* {user.full_name} (@{user.username})\n\n*الطلبات:*\n{order_text}\n--------------------------------\nإجمالي البضاعة: {total_p} ريال\nإجمالي التوصيل: {total_d} ريال\n*المجموع الكلي: {grand_total} ريال*")
        order_id = f"order_{user.id}_{query.message.message_id}"
        context.bot_data[order_id] = {"cart": cart.copy(), "user_info": user.to_dict()}
        keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_{order_id}")], [InlineKeyboardButton("❌ رفض", callback_data=f"reject_{order_id}")]]
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_approval_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text("⏳ تم استلام طلبك وهو الآن قيد المراجعة. سيصلك إشعار عند تأكيده.")
        context.user_data['cart'] = {}
    elif data.startswith("approve_"):
        order_id = data.replace("approve_", "")
        order_data = context.bot_data.get(order_id)
        if not order_data:
            await query.answer("خطأ: الطلب تمت معالجته.", show_alert=True)
            return
        user_info = order_data["user_info"]
        await context.bot.send_message(chat_id=user_info['id'], text="✅ تم تأكيد طلبك وجاري تجهيزه الآن!")
        await query.edit_message_text(f"✅ تمت الموافقة على طلب العميل {user_info['first_name']}.")
        del context.bot_data[order_id]
    elif data.startswith("reject_"):
        order_id = data.replace("reject_", "")
        order_data = context.bot_data.get(order_id)
        if order_data:
            user_info = order_data["user_info"]
            await context.bot.send_message(chat_id=user_info['id'], text="❌ نعتذر، لم يتم قبول طلبك الحالي.")
            await query.edit_message_text(f"❌ تم رفض طلب العميل {user_info['first_name']}.")
            del context.bot_data[order_id]

# --- 5. البحث ولوحة تحكم المدير (الكود كما هو) ---
SEARCH = range(1)
async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("اكتب اسم المنتج الذي تبحث عنه:")
    return SEARCH
async def search_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_term = update.message.text.strip().lower()
    with db_connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, price FROM products WHERE name LIKE ?", (f'%{search_term}%',))
        results = cursor.fetchall()
    if not results:
        await update.message.reply_text(f"عذراً، لم يتم العثور على منتجات تطابق بحثك عن '{search_term}'.")
    else:
        msg = f"🔍 *نتائج البحث عن '{search_term}':*"
        keyboard = [[InlineKeyboardButton(f"{name} ({price} ريال)", callback_data=f"add_{p_id}")] for p_id, name, price in results]
        keyboard.append([InlineKeyboardButton("« العودة للقائمة", callback_data="main_menu")])
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END
async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)
    return ConversationHandler.END
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("👑 لوحة تحكم المدير (قيد التطوير)...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="main_menu")]]))

# --- 6. إعداد تطبيق البوت ---
setup_database()
# بناء التطبيق بدون تشغيل أي شيء بعد
application = Application.builder().token(TOKEN).build()

# إضافة المعالجات
search_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(pattern='^search_start$', callback=search_start)],
    states={SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_product)]},
    fallbacks=[CallbackQueryHandler(pattern='^main_menu$', callback=cancel_search)]
)
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(pattern='^main_menu$', callback=start))
application.add_handler(search_conv_handler)
application.add_handler(CallbackQueryHandler(pattern='^admin_panel$', callback=admin_panel))
application.add_handler(CallbackQueryHandler(button_handler))

# --- 7. الجزء الجديد والمهم: دمج Flask و PTB ---
app = Flask(__name__)

@app.route("/")
def index():
    """صفحة بسيطة للتأكد من أن الخادم يعمل (مهم لـ UptimeRobot)."""
    return "Flask server is running!"

@app.route(f'/{TOKEN}', methods=['POST'])
async def webhook():
    """هذه الدالة تستقبل التحديثات من تيليجرام."""
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return 'OK'

def run_bot():
    """دالة لتشغيل البوت وإعداد الويب هوك."""
    # نستخدم asyncio.run لضمان أن الكود غير المتزامن يعمل بشكل صحيح
    async def main():
        # تهيئة التطبيق (مهم جداً!)
        await application.initialize()
        # إعداد الويب هوك
        await application.bot.set_webhook(url=f"{WEB_URL}/{TOKEN}", allowed_updates=Update.ALL_TYPES)
        logger.info(f"Webhook has been set to {WEB_URL}/{TOKEN}")
    
    # تشغيل الدالة الرئيسية في حلقة أحداث جديدة
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"An error occurred during bot setup: {e}", exc_info=True)

# --- 8. نقطة البداية ---
# Gunicorn سيقوم بتشغيل متغير 'app' (خادم Flask)
# قبل أن يبدأ الخادم بالاستماع للطلبات، نقوم بتشغيل البوت في خيط منفصل.
# هذا يضمن أن الخادم جاهز قبل أن نحاول الاتصال بالإنترنت.
if __name__ != '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()

logger.info("--- SCRIPT INITIALIZATION COMPLETE ---")
