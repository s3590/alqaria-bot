# alqariabot.py (النسخة النهائية والمصححة)

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
)
from telegram.constants import ParseMode
import os
from flask import Flask
import re
import database  # استيراد ملف قاعدة البيانات

# --- 1. الإعدادات الأساسية ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ★★★ استخدم متغيرات البيئة على Render لهذه القيم ★★★
TOKEN = os.environ.get("TELEGRAM_TOKEN", "8605134357:AAGC44E2Fw6ljwGFok3zcg_FuVJKnegk0q4")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "1602450100")

# تعريف حالات المحادثة للوحة تحكم المدير
(ADMIN_PANEL, SELECT_PRODUCT_TO_EDIT, EDIT_PRODUCT, GET_NEW_PRICE) = range(4)

# --- 2. الدوال المساعدة والواجهة ---
def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def format_invoice(cart: dict) -> tuple[str, int, int]:
    if not cart:
        return "", 0, 0
    total_items_price = 0
    total_delivery_price = 0
    items_table = ""
    for p_id, qty in cart.items():
        item = database.get_item_details(p_id)
        if item:
            item_total = item["price"] * qty
            total_items_price += item_total
            total_delivery_price += item["delivery_fee"] * qty
            name = item['name'][:15].ljust(16)
            quantity = f"x{qty}".ljust(5)
            price = str(item['price']).ljust(6)
            total = str(item_total).ljust(7)
            items_table += f"| {name}| {quantity}| {price}| {total}|\n"
    grand_total = total_items_price + total_delivery_price
    invoice_text = "```\n"
    invoice_text += "+-------------------------------------------+\n| فاتورة الطلب                             |\n+-----------------+-------+-------+---------+\n| الصنف           | الكمية| السعر | الإجمالي |\n+-----------------+-------+-------+---------+\n"
    invoice_text += items_table
    invoice_text += "+-----------------+-------+-------+---------+\n\n+-------------------------------------------+\n| ملخص الدفع                               |\n+-------------------------------------------+\n"
    invoice_text += f"| 🛍️ إجمالي المشتريات: {str(total_items_price).ljust(18)}|\n| 🚚 إجمالي التوصيل:   {str(total_delivery_price).ljust(18)}|\n+===========================================+\n"
    invoice_text += f"| 💰 المبلغ الإجمالي:   {str(grand_total).ljust(18)}|\n+-------------------------------------------+\n"
    invoice_text += "```"
    return invoice_text, total_items_price, total_delivery_price

def is_admin(update: Update) -> bool:
    user_id = update.effective_user.id
    return str(user_id) == str(ADMIN_CHAT_ID)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.setdefault('cart', {})
    keyboard = [
        [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse_products")],
        [InlineKeyboardButton(f"🛍️ عرض سلتي ({len(context.user_data.get('cart', {}))})", callback_data="view_cart")],
    ]
    if is_admin(update):
        keyboard.append([InlineKeyboardButton("👑 لوحة تحكم المدير", callback_data="admin_panel_main")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_message = "🏪 أهلاً بك في بقالة القرية الذكية!\n\nاختر من القائمة أدناه للبدء."
    
    # تحديد إذا كانت الرسالة جديدة أو تعديل لرسالة قائمة
    if update.callback_query:
        await update.callback_query.edit_message_text(welcome_message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)
    return 0 # العودة للحالة الرئيسية في المحادثة

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (هذه الدالة لا تحتاج تعديل)
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
    invoice_text, _, _ = format_invoice(cart)
    msg = "🛒 *فاتورة طلبك الحالية:*\n" + invoice_text
    keyboard = []
    for p_id in cart.keys():
        item = database.get_item_details(p_id)
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
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        if query:
            await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Error in view_cart: {e}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (هذه الدالة لا تحتاج تعديل)
    query = update.callback_query
    await query.answer()
    data = query.data
    cart = context.user_data.get('cart', {})

    if data == "main_menu":
        await start(update, context)
    elif data == "browse_products":
        categories = database.get_all_categories()
        keyboard = [[InlineKeyboardButton(cat["name"], callback_data=f"cat_{cat['id']}")] for cat in categories]
        keyboard.append([InlineKeyboardButton("« العودة للقائمة الرئيسية", callback_data="main_menu")])
        await query.edit_message_text("اختر الفئة:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("cat_"):
        cat_id = int(data.split("_")[1])
        products = database.get_products_by_category(cat_id)
        keyboard = [[InlineKeyboardButton(f"{p['name']} ({p['price']} ريال)", callback_data=f"add_{p['id']}")] for p in products]
        keyboard.append([InlineKeyboardButton("« العودة للفئات", callback_data="browse_products")])
        await query.edit_message_text("اختر المنتج:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("add_"):
        prod_id = int(data.split("_")[1])
        cart[prod_id] = cart.get(prod_id, 0) + 1
        context.user_data['cart'] = cart
        await query.answer(f"✅ تمت إضافة المنتج للسلة!", show_alert=False)
    elif data == "view_cart":
        await view_cart(update, context)
    elif data.startswith("qty_"):
        action, prod_id_str = data.split("_")[1], "_".join(data.split("_")[2:])
        prod_id = int(prod_id_str)
        if action == "add":
            cart[prod_id] = cart.get(prod_id, 0) + 1
        elif action == "rem":
            if prod_id in cart and cart[prod_id] > 1:
                cart[prod_id] -= 1
            elif prod_id in cart and cart[prod_id] == 1:
                del cart[prod_id]
        elif action == "del":
            if prod_id in cart:
                del cart[prod_id]
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
        invoice_text, _, _ = format_invoice(cart)
        escaped_username = escape_markdown(user.full_name)
        admin_approval_msg = (f"🔔 *طلب جديد بانتظار موافقتك*\n\n👤 *العميل:* {escaped_username}\n🆔 *المعرف:* `{user.id}`\n\n🧾 *الفاتورة:*\n{invoice_text}")
        order_id = f"order_{user.id}_{query.message.message_id}"
        context.bot_data[order_id] = {"cart": cart.copy(), "user_info": user.to_dict()}
        keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_{order_id}")], [InlineKeyboardButton("❌ رفض", callback_data=f"reject_{order_id}")]]
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_approval_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
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
        await query.edit_message_text(f"✅ تمت الموافقة على طلب العميل {escape_markdown(user_info['first_name'])}\\.", parse_mode=ParseMode.MARKDOWN_V2)
        del context.bot_data[order_id]
    elif data.startswith("reject_"):
        order_id = data.replace("reject_", "")
        order_data = context.bot_data.get(order_id)
        if order_data:
            user_info = order_data["user_info"]
            await context.bot.send_message(chat_id=user_info['id'], text="❌ نعتذر، لم يتم قبول طلبك الحالي.")
            await query.edit_message_text(f"❌ تم رفض طلب العميل {escape_markdown(user_info['first_name'])}\\.", parse_mode=ParseMode.MARKDOWN_V2)
            del context.bot_data[order_id]


# --- لوحة تحكم المدير ---
async def admin_panel_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (هذه الدوال لا تحتاج تعديل)
    query = update.callback_query
    if not is_admin(update):
        await query.answer("ليس لديك صلاحية الوصول لهذه المنطقة.", show_alert=True)
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton("📝 إدارة المنتجات", callback_data="admin_manage_products")], [InlineKeyboardButton("« العودة للقائمة الرئيسية", callback_data="main_menu")]]
    await query.edit_message_text("👑 *لوحة تحكم المدير*\n\nاختر الإجراء الذي تريده:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
    return ADMIN_PANEL

async def admin_manage_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    categories = database.get_all_categories()
    keyboard = [[InlineKeyboardButton(cat["name"], callback_data=f"admin_cat_{cat['id']}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("« العودة للوحة التحكم", callback_data="admin_panel_main")])
    await query.edit_message_text("اختر الفئة التي تريد إدارة منتجاتها:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_PRODUCT_TO_EDIT

async def admin_select_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    cat_id = int(query.data.split("_")[2])
    context.user_data['admin_last_cat'] = cat_id # حفظ الفئة للعودة إليها
    products = database.get_products_by_category(cat_id)
    keyboard = []
    for p in products:
        status = "🟢" if p['is_available'] else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status} {p['name']}", callback_data=f"admin_prod_{p['id']}")])
    keyboard.append([InlineKeyboardButton("« العودة للفئات", callback_data="admin_manage_products")])
    await query.edit_message_text("اختر المنتج للتعديل:", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_PRODUCT

async def admin_edit_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    prod_id = int(query.data.split("_")[2])
    context.user_data['product_to_edit'] = prod_id
    product = database.get_item_details(prod_id)
    status_text = "إخفاء المنتج" if product['is_available'] else "إظهار المنتج"
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل السعر", callback_data="admin_edit_price")],
        [InlineKeyboardButton(f"👁️ {status_text}", callback_data="admin_toggle_avail")],
        [InlineKeyboardButton("« العودة للمنتجات", callback_data=f"admin_cat_{product['category_id']}")]
    ]
    await query.edit_message_text(f"ماذا تريد أن تفعل بالمنتج: *{escape_markdown(product['name'])}*؟", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
    return EDIT_PRODUCT

async def admin_toggle_availability(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    prod_id = context.user_data['product_to_edit']
    database.toggle_product_availability(prod_id)
    await query.answer("✅ تم تحديث حالة المنتج بنجاح!")
    # إعادة بناء قائمة المنتجات للعودة
    cat_id = context.user_data['admin_last_cat']
    query.data = f"admin_cat_{cat_id}"
    return await admin_select_product(update, context)

async def admin_prompt_for_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    prod_id = context.user_data['product_to_edit']
    product = database.get_item_details(prod_id)
    await query.message.reply_text(f"السعر الحالي للمنتج '{product['name']}' هو {product['price']}.\n\nالرجاء إرسال السعر الجديد (أرقام فقط).")
    return GET_NEW_PRICE

async def admin_update_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        new_price = int(update.message.text)
        prod_id = context.user_data['product_to_edit']
        database.update_product_price(prod_id, new_price)
        await update.message.reply_text(f"✅ تم تحديث السعر بنجاح إلى: {new_price}")
        # العودة إلى لوحة التحكم الرئيسية
        keyboard = [[InlineKeyboardButton("👑 العودة للوحة التحكم", callback_data="admin_panel_main")]]
        await update.message.reply_text("يمكنك العودة للوحة التحكم.", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("خطأ. الرجاء إرسال أرقام فقط. حاول مرة أخرى.")
        return GET_NEW_PRICE

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await start(update, context)
    return ConversationHandler.END

# --- إعداد وتشغيل البوت ---
# إعداد تطبيق Flask
app = Flask(__name__)
@app.route('/')
def index():
    return "Bot is running!"

# إعداد تطبيق البوت
database.setup_database()
application = Application.builder().token(TOKEN).build()

# محادثة لوحة تحكم المدير
admin_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(admin_panel_main, pattern='^admin_panel_main$')],
    states={
        ADMIN_PANEL: [CallbackQueryHandler(admin_manage_products, pattern='^admin_manage_products$')],
        SELECT_PRODUCT_TO_EDIT: [CallbackQueryHandler(admin_select_product, pattern='^admin_cat_')],
        EDIT_PRODUCT: [
            CallbackQueryHandler(admin_prompt_for_price, pattern='^admin_edit_price$'),
            CallbackQueryHandler(admin_toggle_availability, pattern='^admin_toggle_avail$'),
            CallbackQueryHandler(admin_select_product, pattern='^admin_cat_')
        ],
        GET_NEW_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_update_price)],
    },
    fallbacks=[
        CallbackQueryHandler(admin_panel_main, pattern='^admin_panel_main$'),
        CallbackQueryHandler(admin_manage_products, pattern='^admin_manage_products$'),
        CallbackQueryHandler(cancel_conversation, pattern='^main_menu$'),
        CommandHandler('start', cancel_conversation)
    ],
    map_to_parent={
        ConversationHandler.END: 0,
    }
)

# المعالج الرئيسي الذي يجمع كل شيء
main_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        0: [
            admin_conv_handler,
            CallbackQueryHandler(button_handler)
        ]
    },
    fallbacks=[CommandHandler("start", start)]
)

application.add_handler(main_handler)

# ★★★ الجزء الأخير والمعدل لمنع التعارض ★★★
if __name__ == "__main__":
    # هذا الجزء يعمل فقط عند تشغيل الكود مباشرة على جهازك
    logger.info("البوت يعمل الآن في وضع Polling (للتجربة المحلية)...")
    # لا حاجة لتشغيل Flask هنا، فقط البوت
    application.run_polling()

# عندما يتم تشغيل الكود على Render بواسطة gunicorn، سيتم تجاهل `if __name__ == "__main__"`
# وسيقوم gunicorn باستيراد واستخدام كائن `app` من الأعلى مباشرة.
