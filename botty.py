import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from contacts import CONTACT_CHAT_IDS  # Import the list of contact chat IDs
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_API_KEY')

# Initialize the application (replaces Updater)
application = Application.builder().token(BOT_TOKEN).build()

# Define the /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    await context.bot.send_message(chat_id=chat_id, text=f"Hello! Your chat ID is: {chat_id}")

# Add the start command handler
application.add_handler(CommandHandler('start', start))

# Define a function to send updates to contacts
async def send_update_to_contacts(context: ContextTypes.DEFAULT_TYPE):
    message = "Here is the important information for today."
    for contact_id in CONTACT_CHAT_IDS:
        await context.bot.send_message(chat_id=contact_id, text=message)

# Schedule the job (e.g., every 10 seconds for testing)
application.job_queue.run_repeating(send_update_to_contacts, interval=10, first=10)

# Define a handler to process responses
async def handle_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_response = update.message.text
    user_id = update.message.chat_id
    await context.bot.send_message(chat_id=user_id, text=f"Thanks for your response: {user_response}")

application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_response))

# Start the bot
application.run_polling()
