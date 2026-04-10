import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask, request

# --- 1. الإعدادات الأساسية (فقط ما نحتاجه) ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEB_URL = os.environ.get("RENDER_EXTERNAL_URL")

# --- 2. دالة بسيطة جداً ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ترد على أمر /start بكلمة واحدة."""
    logger.info(f"Received /start from user {update.effective_user.id}. Responding...")
    await update.message.reply_text("أهلاً بك! أنا أعمل الآن!")
    logger.info("Response sent successfully.")

# --- 3. إعداد تطبيق البوت (بأبسط شكل) ---
application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))

# --- 4. كود التوافق مع Render (الأساسي) ---
app = Flask(__name__)

@app.route("/")
def index():
    return "Minimal Bot is running!"

@app.route(f'/{TOKEN}', methods=['POST'])
async def webhook():
    try:
        json_data = await request.get_json()
        if json_data:
            update = Update.de_json(json_data, application.bot)
            await application.process_update(update)
            return 'OK', 200
        else:
            return 'No JSON data', 400
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'Error', 500

async def setup_webhook_on_startup():
    if WEB_URL and TOKEN:
        try:
            # حذف الـ Webhook القديم أولاً لضمان بداية نظيفة
            await application.bot.delete_webhook()
            # إعداد الـ Webhook الجديد
            await application.bot.set_webhook(url=f"{WEB_URL}/{TOKEN}")
            logger.info(f"Webhook has been reset and set to {WEB_URL}/{TOKEN}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
    else:
        logger.warning("WEB_URL or TOKEN not found. Webhook not set.")

application.post_init = setup_webhook_on_startup
