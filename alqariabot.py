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

# --- 2. إعداد قاعدة البيانات (v16.1 - هيكل جديد) ---
DB_FILE = "bot_database.v16.1.db"

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
            cursor.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, brand_id INTEGER, name TEXT NOT NULL, price REAL NOT NULL, delivery_fee REAL NOT NULL, description TEXT, FOREIGN KEY (brand_id) REFERENCES brands (id) ON DELETE CASCADE)")
            
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, cart TEXT DEFAULT '{}')")
            cursor.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, user_name TEXT NOT NULL, products TEXT NOT NULL, total_price REAL NOT NULL, status TEXT DEFAULT 'قيد المراجعة', order_date TEXT NOT NULL, status_history TEXT DEFAULT '[]')")

            cursor.execute("PRAGMA table_info(orders)")
            if 'status_history' not in [info['name'] for info in cursor.fetchall()]:
                cursor.execute("ALTER TABLE orders ADD COLUMN status_history TEXT DEFAULT '[]'")

            cursor.execute("SELECT COUNT(*) FROM departments")
            if cursor.fetchone()[0] == 0:
                logger.info("Populating database with new structure data...")
                
                departments_data = [('قسم الدقيق', '🌾'), ('قسم السكر', '🍚'), ('قسم الأرز', '🍛'), ('قسم البقوليات', '🫘'), ('قسم الزيوت والسمن', '🧈'), ('قسم الحليب', '🥛'), ('قسم العناية الشخصية', '🧴'), ('قسم الأطعمة العضوية', '🥦')]
                cursor.executemany("INSERT INTO departments (name, emoji) VALUES (?, ?)", departments_data)

                brands_data = [(1, 'الدقيق الأبيض', None), (1, 'دقيق الطحنة', None), (2, 'السكر الأبيض', None), (3, 'رز الديوان', None), (3, 'رز الفخامة', None), (3, 'رز أبو بنت', None), (4, 'العدس الأحمر', None), (5, 'زيت الطبخ', None), (6, 'حليب البودرة', None), (7, 'شامبو', None), (8, 'خضار عضوية', None)]
                cursor.executemany("INSERT INTO brands (department_id, name, image_url) VALUES (?, ?, ?)", brands_data)

                products_data = [
                    (1, 'كيس (50 كيلو)', 12700, 1000, 'دقيق أبيض عالي الجودة'), 
                    (1, 'نص كيس (25 كيلو)', 6350, 500, 'دقيق أبيض عالي الجودة'),
                    (2, 'كيس (45 كيلو)', 12000, 1000, 'سكر أبيض نقي'), 
                    (2, 'نص كيس (22.5 كيلو)', 6000, 500, 'سكر أبيض نقي'),
                    (3, 'كيس (10 كيلو)', 19000, 1000, 'أرز ذو جودة عالية'), 
                    (3, 'نص كيس (5 كيلو)', 9500, 500, 'أرز ذو جودة عالية'),
                    (4, 'كيس (10 كيلو)', 7400, 300, 'عدس أحمر مغذي'), 
                    (4, 'كيس (5 كيلو)', 3800, 200, 'عدس أحمر مغذي'),
                    (5, 'جالون (4 لتر)', 3750, 200, 'زيت طهي ممتاز'),
                    (6, 'كيس (25 كيلو)', 50000, 500, 'حليب بودرة عالي الجودة'), 
                    (6, 'نص كيس (12.5 كيلو)', 25000, 250, 'حليب بودرة عالي الجودة'), 
                    (7, 'شامبو مغذي', 1500, 100, 'شامبو للعناية بالشعر'), 
                    (8, 'خضار عضوية', 2000, 150, 'خضار طازجة من المزارع العضوية')
                ]
                cursor.executemany("INSERT INTO products (brand_id, name, price, delivery_fee, description) VALUES (?, ?, ?, ?, ?)", products_data)
            
            conn.commit()
        logger.info("Database v16.1 setup successful.")
    except Exception as e:
        logger.error(f"DATABASE SETUP FAILED: {e}", exc_info=True)

# --- 3. دوال مساعدة ---
def get_product_details(prod_id):
    with db_connect() as conn:
        return conn.execute("SELECT p.id, p.name, p.price, p.delivery_fee, p.description, b.name as brand_name, d.name as department_name FROM products p JOIN brands b ON p.brand_id = b.id JOIN departments d ON b.department_id = d.id WHERE p.id = ?", (prod_id,)).fetchone()

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
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

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

# ... (تابع كتابة الدوال الأخرى مثل admin_add_menu و admin_edit_delete_menu)

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
    
    # إضافة معالجات الأوامر المحددة أولاً
    application.add_handler(CommandHandler("start", start))
    
    # إضافة معالجات المحادثات
    application.add_handler(add_dept_conv)
    application.add_handler(add_brand_conv)
    application.add_handler(add_prod_conv)
    application.add_handler(edit_delete_conv)
    application.add_handler(track_order_conv)
    
    # إضافة معالج الأزرار
    application.add_handler(CallbackQueryHandler(unified_button_handler))
    
    # إضافة المعالج العام للنصوص في النهاية
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_handler))

    # تشغيل البوت
    logger.info("Starting bot with webhook...")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{WEB_URL}/{TOKEN}"
    )

if __name__ == "__main__":
    main()
