# bot.py — Smart Gemini + Admin Connect System
# Ultra Safe Version: Rate-limit Protection + Cooldown + Auto Language + Admin Alerts + Typing Animation

import os
import asyncio
import logging
import re
import time
import random
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    PicklePersistence
)

from google import genai


# -------------------- LOAD ENV --------------------
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not TELEGRAM_TOKEN or not GEMINI_API_KEY or ADMIN_ID == 0:
    raise SystemExit("Please set TELEGRAM_TOKEN, GEMINI_API_KEY, ADMIN_ID in .env")


# -------------------- LOGGING --------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

genai_client = genai.Client(api_key=GEMINI_API_KEY)


# -------------------- AUTO LANGUAGE DETECTION --------------------
def detect_language(text: str) -> str:
    if re.search(r'[\u0900-\u097F]', text):
        return "hindi"
    if re.search(r'[\u0980-\u09FF]', text):
        return "bengali"
    if re.search(r'[A-Za-z]', text):
        return "english"
    return "english"


# -------------------- TYPING ANIMATION --------------------
async def type_animation(update: Update, context, text="💬 Bot is typing…", delay=1.0):
    try:
        await update.message.reply_text(text, parse_mode=None)
    except:
        pass
    await asyncio.sleep(delay)


# -------------------- FALLBACK RESPONSES --------------------
FALLBACK_RESPONSES = [
    "Message sent ✅.",
]


# -------------------- SAFE GEMINI CALL --------------------
async def safe_ask_gemini(prompt: str) -> str:
    try:
        return await ask_gemini(prompt)
    except Exception as e:
        if "429" in str(e) or "rate" in str(e).lower():
            return random.choice(FALLBACK_RESPONSES)
        return "Message sent ✅"


# -------------------- GEMINI REQUEST --------------------
async def ask_gemini(prompt: str) -> str:

    def call():
        try:
            resp = genai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            if hasattr(resp, "text") and resp.text:
                return resp.text.strip()

            if hasattr(resp, "candidates") and resp.candidates:
                return str(resp.candidates[0].content).strip()

            return str(resp)

        except Exception as e:
            log.exception("Gemini error: %s", e)
            return random.choice(FALLBACK_RESPONSES)

    return await asyncio.to_thread(call)


# -------------------- USER COOLDOWN / ANTI-SPAM --------------------
def user_spam(update, context) -> bool:
    now = time.time()
    last = context.user_data.get("last_time", 0)

    if now - last < 1.5:  # Minimum 1.5 seconds gap
        return True  # block message

    context.user_data["last_time"] = now
    return False


# -------------------- PERSISTENCE --------------------
persistence = PicklePersistence(filepath="bot_data.pkl")


# -------------------- COMMANDS --------------------
async def start_cmd(update, context):
    await type_animation(update, context)
    await update.message.reply_text("👋 Welcome! Send hi to begin ✨", parse_mode=None)


async def available_cmd(update, context):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ Not allowed.")

    context.bot_data["admin_available"] = True
    context.bot_data["admin_status_changed"] = "available"

    await update.message.reply_text("🟢 Admin is now available.")


async def away_cmd(update, context):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ Not allowed.")

    context.bot_data["admin_available"] = False
    context.bot_data["admin_status_changed"] = "away"

    await update.message.reply_text("🔴 Admin is now away.")


# -------------------- ADMIN REPLY --------------------
async def admin_reply_handler(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    reply_msg = update.message.reply_to_message
    if not reply_msg:
        return

    forwarded_id = reply_msg.message_id
    user_chat = context.bot_data.get("forwarded_map", {}).get(forwarded_id)

    if not user_chat:
        return await update.message.reply_text("❌ User not found.")

    await context.bot.send_message(chat_id=user_chat, text=f"💬 Admin: {update.message.text}")
    await update.message.reply_text("✅ Sent to user.")


# -------------------- MAIN MESSAGE HANDLER --------------------
async def handle_message(update, context):

    if user_spam(update, context):
        return  # Block rapid spam

    text = update.message.text[:500]  # Limit input length
    lang = detect_language(text)

    # Silent forward
    try:
        fwd = await context.bot.forward_message(
            chat_id=ADMIN_ID,
            from_chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )
        context.bot_data.setdefault("forwarded_map", {})[fwd.message_id] = update.effective_chat.id
    except:
        pass

    await type_animation(update, context)

    # Admin Status One-time Notifications
    admin_status = context.bot_data.get("admin_status_changed", None)

    if admin_status == "available":
        context.bot_data["admin_status_changed"] = None
        return await update.message.reply_text("🟢 Admin is available. You can chat now.", parse_mode=None)

    if admin_status == "away":
        context.bot_data["admin_status_changed"] = None
        return await update.message.reply_text(
            "🔴 Admin is busy.\n📨 Message sent.\n⏳ Reply within 48 hours.",
            parse_mode=None
        )

    # First-time busy logic
    first_time = not context.user_data.get("busy_shown", False)
    context.user_data["busy_shown"] = True

    admin_available = context.bot_data.get("admin_available", False)

    # ---- AI Prompt ----
    intelligent_prompt = f"""
Reply in: {lang}

Rules:
- reply VERY short (1 or 2 lines)
- easy & simple language only

1) If greeting:
     Return a short friendly welcome.

2) If admin_available = true:
     Reply EXACTLY:
     "📩 Message sent to admin."

3) If admin_available = false AND first_time = true:
     Reply EXACTLY:
     "🔴 Admin is busy.
      📨 Message sent.
      ⏳ Reply within 48 hours."

4) If admin_available = false AND first_time = false:
     Reply EXACTLY:
     "📩 Message sent to admin."

User message: {text}
"""

    ai_reply = await safe_ask_gemini(intelligent_prompt)

    return await update.message.reply_text(ai_reply, parse_mode=None)


# -------------------- START BOT --------------------
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).persistence(persistence).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("available", available_cmd))
    app.add_handler(CommandHandler("away", away_cmd))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, admin_reply_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Safe Gemini Bot Running...")
    app.run_polling()


if __name__ == "__main__":
    main()
