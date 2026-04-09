import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
)
from telegram.constants import ParseMode
import os
from flask import Flask
import threading

# --- 1. الإعدادات الأساسية (املأها هنا مباشرة) ★★★
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ★★★ ضع التوكن والمعرفات هنا مباشرة ★★★
TOKEN = "8605134357:AAGC44E2Fw6ljwGFok3zcg_FuVJKnegk0q4"
ADMIN_CHAT_ID = "1602450100"

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

def format_invoice(cart: dict) -> tuple[str, int, int]:
    """
    ★★★ جديد: دالة لتنسيق الفاتورة بشكل جدولي ★★★
    """
    if not cart:
        return "", 0, 0

    invoice_text = "```\n"
    invoice_text += "الصنف           الكمية  السعر  الإجمالي\n"
    invoice_text += "--------------------------------------\n"
    
    total_items_price = 0
    total_delivery_price = 0

    for p_id, qty in cart.items():
        item = get_item_details(p_id)
        if item:
            item_total = item["price"] * qty
            total_items_price += item_total
            total_delivery_price += item["delivery_fee"] * qty
            
            # تنسيق السطر ليكون متوافقاً مع الجدول
            name = item['name'][:14].ljust(14) # قص الاسم لـ 14 حرفاً ومحاذاة
            quantity = f"x{qty}".ljust(6)
            price = str(item['price']).ljust(6)
            total = str(item_total)
            invoice_text += f"{name}{quantity}{price}{total}\n"

    invoice_text += "--------------------------------------\n"
    invoice_text += f"🛍️ إجمالي المشتريات: {total_items_price} ريال\n"
    invoice_text += f"🚚 إجمالي التوصيل:   {total_delivery_price} ريال\n"
    invoice_text += "======================================\n"
    invoice_text += f"💰 المبلغ الإجمالي:   {total_items_price + total_delivery_price} ريال\n"
    invoice_text += "```"
    
    return invoice_text, total_items_price, total_delivery_price

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (الكود هنا لم يتغير)
    keyboard = [
        [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse_products")],
        [InlineKeyboardButton(f"🛍️ عرض سلتي ({len(context.user_data.get('cart', {}))})", callback_data="view_cart")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_message = (
        "🏪 أهلاً بك في بقالة القرية الذكية!\n\n"
        "اختر من القائمة أدناه للبدء بالتسوق، أو **اكتب اسم المنتج الذي تبحث عنه مباشرة**."
    )
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ★★★ تحديث: لعرض السلة مع أزرار التحكم بجانب كل منتج ★★★
    """
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

    # استخدام دالة الفاتورة الجديدة
    invoice_text, _, _ = format_invoice(cart)
    msg = "🛒 **فاتورة طلبك الحالية:**\n" + invoice_text
    
    keyboard = []
    # إضافة أزرار التحكم لكل منتج
    for p_id, qty in cart.items():
        item = get_item_details(p_id)
        if item:
            keyboard.append([
                InlineKeyboardButton(f"➕ {item['name'][:15]}", callback_data=f"qty_add_{p_id}"),
                InlineKeyboardButton("➖", callback_data=f"qty_rem_{p_id}"),
                InlineKeyboardButton("❌", callback_data=f"qty_del_{p_id}")
            ])

    keyboard.extend([
        [InlineKeyboardButton("✅ إرسال الطلب للمراجعة", callback_data="confirm_order")],
        [InlineKeyboardButton("🗑️ تفريغ السلة", callback_data="clear_cart")],
        [InlineKeyboardButton("« متابعة التسوق", callback_data="browse_products")]
    ])
    
    if query:
        # التأكد من أن الرسالة تغيرت لتجنب خطأ "Message is not modified"
        if query.message.text != msg or query.message.reply_markup != InlineKeyboardMarkup(keyboard):
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    cart = context.user_data.get('cart', {})

    if data == "main_menu":
        # ... (الكود هنا لم يتغير)
        keyboard = [
            [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse_products")],
            [InlineKeyboardButton(f"🛍️ عرض سلتي ({len(cart)})", callback_data="view_cart")],
        ]
        await query.edit_message_text("القائمة الرئيسية:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "browse_products":
        # ... (الكود هنا لم يتغير)
        keyboard = [[InlineKeyboardButton(cat["name"], callback_data=f"cat_{cat_id}")] for cat_id, cat in PRODUCTS.items()]
        keyboard.append([InlineKeyboardButton("« العودة", callback_data="main_menu")])
        await query.edit_message_text("اختر القسم الذي تريده:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("cat_"):
        # ... (الكود هنا لم يتغير)
        cat_id = data.split("_", 1)[1]
        category = PRODUCTS.get(cat_id)
        keyboard = [[InlineKeyboardButton(f"{p['name']} ({p['price']} ريال)", callback_data=f"add_{p_id}")] for p_id, p in category["items"].items()]
        keyboard.append([InlineKeyboardButton("« العودة للأقسام", callback_data="browse_products")])
        await query.edit_message_text(f"منتجات قسم {category['name']}:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("add_"):
        # ... (الكود هنا لم يتغير)
        prod_id = data.split("_", 1)[1]
        cart[prod_id] = cart.get(prod_id, 0) + 1
        context.user_data['cart'] = cart
        await query.answer(f"✅ تمت إضافة المنتج للسلة!", show_alert=False)
    
    elif data == "view_cart":
        await view_cart(update, context)

    elif data.startswith("qty_"):
        # ... (الكود هنا لم يتغير)
        parts = data.split("_")
        action, prod_id = parts[1], "_".join(parts[2:])
        
        if action == "add":
            cart[prod_id] = cart.get(prod_id, 0) + 1
        elif action == "rem":
            if prod_id in cart and cart[prod_id] > 1:
                cart[prod_id] -= 1
            elif prod_id in cart and cart[prod_id] == 1:
                 del cart[prod_id]
        elif action == "del":
            if prod_id in cart: del cart[prod_id]
        
        context.user_data['cart'] = cart
        await view_cart(update, context)

    elif data == "clear_cart":
        # ... (الكود هنا لم يتغير)
        context.user_data['cart'] = {}
        await view_cart(update, context)

    elif data == "confirm_order":
        # ★★★ تحديث: لإرسال الفاتورة المنظمة للمدير ★★★
        if not cart:
            await query.answer("سلتك فارغة!", show_alert=True)
            return

        user = query.from_user
        
        # استخدام دالة الفاتورة الجديدة
        invoice_text, _, _ = format_invoice(cart)

        admin_approval_msg = (
            f"🔔 **طلب جديد بانتظار موافقتك**\n\n"
            f"**العميل:** {user.full_name} (@{user.username})\n\n"
            f"**الفاتورة:**\n{invoice_text}"
        )
        
        # استخدام معرف فريد للطلب
        order_id = f"order_{user.id}_{query.message.message_id}"
        context.bot_data[order_id] = {"cart": cart.copy(), "user_info": user.to_dict()}

        keyboard = [[InlineKeyboardButton("✅ موافقة وإرسال", callback_data=f"approve_{order_id}")], [InlineKeyboardButton("❌ رفض الطلب", callback_data=f"reject_{order_id}")]]
        
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_approval_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
        await query.edit_message_text("⏳ تم استلام طلبك وهو الآن قيد المراجعة. سيصلك إشعار عند تأكيده.")
        context.user_data['cart'] = {}

    elif data.startswith("approve_"):
        # ... (الكود هنا لم يتغير - تم تعطيل رسائل التاجر والسائق مؤقتاً)
        order_id = data.replace("approve_", "")
        order_data = context.bot_data.get(order_id)
        if not order_data:
            await query.answer("خطأ: الطلب تمت معالجته.", show_alert=True)
            return
            
        user_info = order_data["user_info"]
        
        await context.bot.send_message(chat_id=user_info['id'], text="✅ تم تأكيد طلبك وجاري تجهيزه الآن!")
        await query.edit_message_text(f"✅ تمت الموافقة على طلب العميل {user_info['first_name']}.")
        del context.bot_data[order_id] # حذف الطلب بعد معالجته

    elif data.startswith("reject_"):
        # ... (الكود هنا لم يتغير)
        order_id = data.replace("reject_", "")
        order_data = context.bot_data.get(order_id)
        if order_data:
            user_info = order_data["user_info"]
            await context.bot.send_message(chat_id=user_info['id'], text="❌ نعتذر، لم يتم قبول طلبك الحالي. يمكنك المحاولة لاحقًا أو التواصل مع الإدارة.")
            await query.edit_message_text(f"❌ تم رفض طلب العميل {user_info['first_name']}.")
            del context.bot_data[order_id]

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    ★★★ جديد: دالة البحث عن المنتجات ★★★
    """
    search_term = update.message.text.strip().lower()
    if len(search_term) < 2: return

    results = []
    for cat_id, cat_data in PRODUCTS.items():
        for p_id, p_data in cat_data["items"].items():
            if search_term in p_data["name"].lower():
                results.append((p_id, p_data))

    if not results:
        await update.message.reply_text(f"عذراً، لم يتم العثور على منتجات تطابق بحثك عن '{search_term}'.")
        return

    msg = f"🔍 **نتائج البحث عن '{search_term}':**"
    keyboard = [[InlineKeyboardButton(f"➕ {p_data['name']} ({p_data['price']} ريال)", callback_data=f"add_{p_id}")] for p_id, p_data in results]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

# --- إعداد تطبيق البوت ---
application = Application.builder().token(TOKEN).build()

# إضافة المعالجات (Handlers)
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_handler))
# ★★★ جديد: إضافة معالج البحث ★★★
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_handler))

# --- كود التوافق مع Render ---
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running!"

def run_flask():
    # استمع على المنفذ الذي يحدده Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # تشغيل خدمة فلاسك في خيط منفصل
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    logger.info("البوت يعمل الآن في وضع Polling...")
    application.run_polling()
    