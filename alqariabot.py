import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters,
    PicklePersistence
)
from telegram.constants import ParseMode
import os
from flask import Flask

# --- 1. الإعدادات الأساسية (يتم جلبها من متغيرات البيئة) ★★★
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ★★★ احصل على التوكن والمعرفات من متغيرات البيئة على Render ★★★
TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

# (موصى به) تأكد من أن المتغيرات موجودة قبل تشغيل البوت
if not TOKEN or not ADMIN_CHAT_ID:
    logger.critical("خطأ فادح: لم يتم العثور على TELEGRAM_TOKEN و ADMIN_CHAT_ID في متغيرات البيئة!")
    # في بيئة الإنتاج، قد ترغب في إيقاف البرنامج إذا لم تكن المتغيرات موجودة
    # raise ValueError("متغيرات البيئة الأساسية غير موجودة")

# اترك هذه كما هي مؤقتاً
MERCHANT_CHANNEL_ID = "None"
DRIVER_CHANNEL_ID = "None"


# --- 2. قاعدة بيانات المنتجات ---
PRODUCTS = {
    "cat_flour_sugar": {"name": "🍚 دقيق وسكر", "items": {
        "prod_flour_white_full": {"name": "كيس دقيق أبيض", "price": 12700, "delivery_fee": 1000},
        "prod_flour_brown_full": {"name": "كيس دقيق طحنة (أسمر)", "price": 12000, "delivery_fee": 1000},
        "prod_flour_white_half": {"name": "نص كيس دقيق أبيض", "price": 6350, "delivery_fee": 500},
        "prod_flour_brown_half": {"name": "نص كيس دقيق طحنة (أسمر)", "price": 6000, "delivery_fee": 500},
        "prod_sugar_full": {"name": "كيس سكر (50 كيلو)", "price": 19000, "delivery_fee": 1000},
        "prod_sugar_half": {"name": "نص كيس سكر (25 كيلو)", "price": 9500, "delivery_fee": 500},
        "prod_sugar_10kg": {"name": "قطمة سكر 10 كيلو", "price": 3800, "delivery_fee": 200},
        "prod_sugar_5kg": {"name": "قطمة سكر 5 كيلو", "price": 1900, "delivery_fee": 100},
    }},
    "cat_rice_beans": {"name": "🍛 أرز وبقوليات", "items": {
        "prod_rice_raban_5kg": {"name": "رز الربان 5 كيلو", "price": 3800, "delivery_fee": 200},
        "prod_rice_raban_10kg": {"name": "رز الربان 10 كيلو", "price": 7400, "delivery_fee": 300},
        "prod_lentils_red_1kg": {"name": "عدس أحمر 1 كيلو", "price": 800, "delivery_fee": 50},
        "prod_lentils_red_halfkg": {"name": "عدس أحمر نص كيلو", "price": 400, "delivery_fee": 25},
    }},
    "cat_oils_milk": {"name": "🧈 زيوت وسمن وحليب", "items": {
        "prod_milk_powder_1kg": {"name": "كيلو حليب بودرة", "price": 1900, "delivery_fee": 50},
        "prod_oil_gallon_4l": {"name": "جالون زيت 4 لتر", "price": 3750, "delivery_fee": 200},
        "prod_ghee_mountain": {"name": "علبة سمن جبلي", "price": 1400, "delivery_fee": 50},
    }},
    "cat_canned_spices": {"name": "🥫 معلبات وبهارات", "items": {
        "prod_sauce_modhesh": {"name": "صلصة المدهش (كرتون)", "price": 2100, "delivery_fee": 100},
        "prod_spices_ground_1kg": {"name": "بهارات مطحون 1 كيلو", "price": 2400, "delivery_fee": 50},
        "prod_spices_ground_halfkg": {"name": "بهارات مطحون نص كيلو", "price": 1200, "delivery_fee": 25},
    }},
    "cat_detergents": {"name": "🧼 منظفات", "items": {
        "prod_tide_2_5kg": {"name": "تايت 2.5 كيلو", "price": 2000, "delivery_fee": 100},
    }},
}

# --- 3. الدوال المساعدة والواجهة ---
def get_item_details(prod_id):
    for cat in PRODUCTS.values():
        if prod_id in cat["items"]:
            return cat["items"][prod_id]
    return None

def is_admin(update: Update) -> bool:
    return str(update.effective_user.id) == str(ADMIN_CHAT_ID)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_chat.id
    if context.user_data.get('initialized') is not True:
        context.user_data['cart'] = {}
        context.user_data['orders'] = []
        context.user_data['initialized'] = True
    
    if 'users' not in context.bot_data:
        context.bot_data['users'] = set()
    context.bot_data['users'].add(user_id)

    keyboard = [
        [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse_products")],
        [InlineKeyboardButton(f"🛍️ عرض سلتي ({len(context.user_data.get('cart', {}))})", callback_data="view_cart")],
        [InlineKeyboardButton("📜 طلباتي السابقة", callback_data="my_orders")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_message = (
        "🏪 أهلاً بك في بقالة القرية الذكية!\n\n"
        "اختر من القائمة أدناه للبدء بالتسوق، أو اكتب اسم المنتج الذي تبحث عنه مباشرة.\n\n"
        "**ملاحظة:** يتم تجميع الطلبات خلال اليوم وتوصيلها مساءً."
    )
    if is_admin(update):
        welcome_message += "\n\nأهلاً بك يا مدير! استخدم الأوامر الإدارية للتحكم (/stats, /users, /broadcast)."

    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    cart = context.user_data.get('cart', {})

    if not cart:
        msg = "سلتك فارغة حالياً!"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("« تسوق الآن", callback_data="browse_products")]])
        if query:
            await query.edit_message_text(msg, reply_markup=markup)
        else:
            await update.message.reply_text(msg, reply_markup=markup)
        return

    msg = "🛒 **تفاصيل سلتك الحالية:**\n\n"
    total_items_price, total_delivery_price = 0, 0
    keyboard = []

    for p_id, qty in cart.items():
        item = get_item_details(p_id)
        if item:
            item_total = item["price"] * qty
            total_items_price += item_total
            total_delivery_price += item["delivery_fee"] * qty
            
            msg += f"🔹 **{item['name']}**\n   الكمية: {qty} × {item['price']} = {item_total} ريال\n"
            keyboard.append([
                InlineKeyboardButton("➕", callback_data=f"qty_add_{p_id}"),
                InlineKeyboardButton("➖", callback_data=f"qty_rem_{p_id}"),
                InlineKeyboardButton("❌ حذف", callback_data=f"qty_del_{p_id}")
            ])
    
    grand_total = total_items_price + total_delivery_price
    msg += f"\n--------------------------------\n"
    msg += f"🛍️ إجمالي المشتريات: {total_items_price} ريال\n"
    msg += f"🚚 إجمالي التوصيل: {total_delivery_price} ريال\n"
    msg += f"--------------------------------\n"
    msg += f"💰 **المبلغ الإجمالي المطلوب: {grand_total} ريال**"

    keyboard.extend([
        [InlineKeyboardButton("✅ إرسال الطلب للمراجعة", callback_data="confirm_order")],
        [InlineKeyboardButton("🗑️ تفريغ السلة", callback_data="clear_cart")],
        [InlineKeyboardButton("« متابعة التسوق", callback_data="browse_products")]
    ])
    
    try:
        if query:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in view_cart: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    cart = context.user_data.get('cart', {})

    if data == "main_menu":
        keyboard = [
            [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse_products")],
            [InlineKeyboardButton(f"🛍️ عرض سلتي ({len(cart)})", callback_data="view_cart")],
            [InlineKeyboardButton("📜 طلباتي السابقة", callback_data="my_orders")]
        ]
        await query.edit_message_text("القائمة الرئيسية:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "browse_products":
        keyboard = [[InlineKeyboardButton(cat["name"], callback_data=f"cat_{cat_id}")] for cat_id, cat in PRODUCTS.items()]
        keyboard.append([InlineKeyboardButton("« العودة", callback_data="main_menu")])
        await query.edit_message_text("اختر القسم الذي تريده:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("cat_"):
        cat_id = data.split("_", 1)[1]
        category = PRODUCTS.get(cat_id)
        keyboard = [[InlineKeyboardButton(f"{p['name']} ({p['price']} ريال)", callback_data=f"add_{p_id}")] for p_id, p in category["items"].items()]
        keyboard.append([InlineKeyboardButton("« العودة للأقسام", callback_data="browse_products")])
        await query.edit_message_text(f"منتجات قسم {category['name']}:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("add_"):
        prod_id = data.split("_", 1)[1]
        cart[prod_id] = cart.get(prod_id, 0) + 1
        context.user_data['cart'] = cart
        await query.answer(f"✅ تمت إضافة المنتج للسلة!", show_alert=False)
    
    elif data == "view_cart":
        await view_cart(update, context)

    elif data.startswith("qty_"):
        parts = data.split("_")
        action, prod_id = parts[1], "_".join(parts[2:])
        
        if action == "add":
            cart[prod_id] = cart.get(prod_id, 0) + 1
        elif action == "rem":
            if prod_id in cart and cart[prod_id] > 0:
                cart[prod_id] -= 1
                if cart[prod_id] == 0: del cart[prod_id]
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
        order_id = f"order_{user.id}_{query.message.message_id}"
        
        order_text, total_p, total_d = "", 0, 0
        for p_id, qty in cart.items():
            item = get_item_details(p_id)
            if item:
                order_text += f"- {item['name']} (الكمية: {qty})\n"
                total_p += item["price"] * qty
                total_d += item["delivery_fee"] * qty
        grand_total = total_p + total_d

        context.bot_data[order_id] = {
            "cart": cart.copy(),
            "user_info": {"full_name": user.full_name, "username": user.username, "id": user.id},
            "totals": {"items": total_p, "delivery": total_d, "grand": grand_total}
        }

        admin_approval_msg = (
            f"🔔 **طلب جديد بانتظار موافقتك**\n\n"
            f"**العميل:** {user.full_name} (@{user.username})\n\n"
            f"**الطلبات:**\n{order_text}\n"
            f"--------------------------------\n"
            f"إجمالي البضاعة: {total_p} ريال\n"
            f"إجمالي التوصيل: {total_d} ريال\n"
            f"**المجموع الكلي: {grand_total} ريال**"
        )
        keyboard = [[InlineKeyboardButton("✅ موافقة وإرسال", callback_data=f"approve_{order_id}")], [InlineKeyboardButton("❌ رفض الطلب", callback_data=f"reject_{order_id}")]]
        
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_approval_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text("⏳ تم استلام طلبك وهو الآن قيد المراجعة. سيصلك إشعار عند تأكيده.")
        context.user_data['cart'] = {}

    elif data.startswith("approve_"):
        order_id = data.replace("approve_", "")
        order_data = context.bot_data.get(order_id)
        if not order_data:
            await query.answer("خطأ: الطلب تمت معالجته.", show_alert=True)
            return
            
        cart, user_info, totals = order_data["cart"], order_data["user_info"], order_data["totals"]
        
        user_orders = context.application.user_data[user_info['id']].setdefault('orders', [])
        user_orders.append({"date": datetime.now().strftime("%Y-%m-%d"), "cart": cart, "total": totals['grand']})
        context.application.user_data[user_info['id']]['orders'] = user_orders[-5:]

        context.bot_data.setdefault('approved_orders_today', 0)
        context.bot_data['approved_orders_today'] += 1

        await context.bot.send_message(chat_id=user_info['id'], text="✅ تم تأكيد طلبك وجاري تجهيزه الآن!")
        await query.edit_message_text(f"✅ تمت الموافقة على طلب العميل {user_info['full_name']}.")

    elif data.startswith("reject_"):
        order_id = data.replace("reject_", "")
        order_data = context.bot_data.get(order_id)
        if order_data:
            user_info = order_data["user_info"]
            await context.bot.send_message(chat_id=user_info['id'], text="❌ نعتذر، لم يتم قبول طلبك الحالي. يمكنك المحاولة لاحقًا أو التواصل مع الإدارة.")
            await query.edit_message_text(f"❌ تم رفض طلب العميل {user_info['full_name']}.")
            del context.bot_data[order_id]

    elif data.startswith("ready_"):
        order_id = data.replace("ready_", "")
        order_data = context.bot_data.get(order_id)
        if order_data:
            await query.edit_message_text(f"👍 تم التجهيز. تم إعلام السائق بأن الطلبية جاهزة للاستلام.")
            await context.bot.send_message(chat_id=DRIVER_CHANNEL_ID, text=f"🔔 تحديث: طلبية العميل {order_data['user_info']['full_name']} جاهزة للاستلام من التاجر.")

    elif data.startswith("shipping_"):
        order_id = data.replace("shipping_", "")
        order_data = context.bot_data.get(order_id)
        if order_data:
            await query.edit_message_text("🚀 بالتوفيق في التوصيل!")
            await context.bot.send_message(chat_id=order_data['user_info']['id'], text="🎉 بشرى سارة! طلبك الآن مع السائق وفي طريقه إليك!")
            del context.bot_data[order_id]

    elif data == "my_orders":
        orders = context.user_data.get('orders', [])
        if not orders:
            await query.edit_message_text("ليس لديك أي طلبات سابقة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« العودة", callback_data="main_menu")]]))
            return

        msg = "📜 **سجل طلباتك السابقة:**\n\n"
        keyboard = []
        for i, order in enumerate(orders):
            msg += f"**طلب بتاريخ: {order['date']}** (إجمالي: {order['total']} ريال)\n"
            for p_id, qty in order['cart'].items():
                item = get_item_details(p_id)
                if item: msg += f"- {item['name']} (x{qty})\n"
            keyboard.append([InlineKeyboardButton(f"🔄 إعادة طلب رقم {i+1}", callback_data=f"reorder_{i}")])
            msg += "-------\n"
        
        keyboard.append([InlineKeyboardButton("« العودة", callback_data="main_menu")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("reorder_"):
        order_index = int(data.split("_")[1])
        orders = context.user_data.get('orders', [])
        if order_index < len(orders):
            context.user_data['cart'] = orders[order_index]['cart'].copy()
            await query.answer("✅ تم ملء سلتك بمنتجات الطلب السابق.", show_alert=True)
            await view_cart(update, context)
        else:
            await query.answer("خطأ: لم يتم العثور على الطلب.", show_alert=True)

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    search_term = update.message.text.strip().lower()
    if len(search_term) < 2: return

    results = [(p_id, p_data) for _, cat in PRODUCTS.items() for p_id, p_data in cat["items"].items() if search_term in p_data["name"].lower()]

    if not results:
        await update.message.reply_text(f"عذراً، لم يتم العثور على منتجات تطابق بحثك عن '{search_term}'.")
        return

    msg = f"🔍 **نتائج البحث عن '{search_term}':**"
    keyboard = [[InlineKeyboardButton(f"{p_data['name']} ({p_data['price']} ريال)", callback_data=f"add_{p_id}")] for p_id, p_data in results]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("ليس لديك صلاحية استخدام هذا الأمر.")
        return

    command, *args = update.message.text.split(' ')
    
    if command == '/stats':
        num_users = len(context.bot_data.get('users', set()))
        orders_today = context.bot_data.get('approved_orders_today', 0)
        await update.message.reply_text(f"📊 **إحصائيات البوت:**\n\n👤 عدد المستخدمين الكلي: {num_users}\n📦 الطلبات الموافق عليها اليوم: {orders_today}")

    elif command == '/users':
        users = list(context.bot_data.get('users', set()))
        msg = f"👥 **آخر 5 مستخدمين (معرفاتهم):**\n" + "\n".join(f"- `{user_id}`" for user_id in users[-5:])
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    elif command == '/broadcast':
        message_to_send = " ".join(args)
        if not message_to_send:
            await update.message.reply_text("الاستخدام: /broadcast <نص الرسالة>")
            return
        
        users, sent_count = context.bot_data.get('users', set()), 0
        for user_id in users:
            try:
                await context.bot.send_message(chat_id=user_id, text=f"📣 **رسالة من الإدارة:**\n\n{message_to_send}")
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send to {user_id}: {e}")
        await update.message.reply_text(f"✅ تم إرسال الرسالة بنجاح إلى {sent_count} مستخدم.")

# --- إعداد تطبيق البوت ---
# ملاحظة: تم تعطيل `PicklePersistence` لأن نظام الملفات في Render ليس دائماً.
# سيتم فقدان بيانات المستخدم (مثل السلة) عند كل إعادة تشغيل للخدمة.
# للبيانات الدائمة، يجب استخدام قاعدة بيانات خارجية مثل PostgreSQL أو Redis.
# persistence = PicklePersistence(filepath="bot_database.pkl")
application = Application.builder().token(TOKEN).build() # .persistence(persistence)

# إضافة المعالجات (Handlers)
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("cart", view_cart))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(CommandHandler(["stats", "users", "broadcast"], admin_commands))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_handler))

# --- إعداد خادم الويب (Flask) ---
# هذا الجزء ضروري ليعمل البوت كـ "Web Service" على Render
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running!"

@app.route(f'/{TOKEN}', methods=['POST'])
async def webhook():
    update = Update.de_json(await request.get_json(), application.bot)
    await application.process_update(update)
    return '', 200

async def setup_webhook():
    # هذه الدالة اختيارية، يمكنك ضبط الـ Webhook يدوياً عبر URL
    # أو ترك Render يقوم بذلك إذا كان يدعم الإعداد التلقائي
    url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    await application.bot.set_webhook(url)
    logger.info(f"Webhook set to {url}")

if __name__ == "__main__":
    # هذا الجزء لتشغيل البوت محلياً للتجربة (باستخدام Polling)
    # عند النشر على Render، سيتم استخدام gunicorn لتشغيل كائن `app` مباشرة
    # ولن يتم تنفيذ هذا الجزء من الكود.
    logger.info("البوت يعمل الآن في وضع Polling (للتجربة المحلية)...")
    application.run_polling()

