import os
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_API_KEY')

updater = Updater(token=BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

def start(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.effective_chat.id, text="Hello! I will send you important updates.")
    chat_id = update.message.chat_id
    context.bot.send_message(chat_id=chat_id, text=f"Hello! Your chat ID is: {chat_id}")
    # Note: You can use this chat ID to manually add it to a list later for testing purposes.

# Register the command with the dispatcher
start_handler = CommandHandler('start', start)
dispatcher.add_handler(start_handler)

contacts = [12345678, 87654321]  # Add the actual user chat IDs here

def send_update_to_contacts(context: CallbackContext):
    message = "Here is the important information for today."
    for contact_id in contacts:
        context.bot.send_message(chat_id=contact_id, text=message)

# Add a job to send updates at intervals, e.g., every 10 seconds for testing
updater.job_queue.run_repeating(send_update_to_contacts, interval=10)

def handle_response(update: Update, context: CallbackContext):
    user_response = update.message.text
    user_id = update.message.chat_id
    context.bot.send_message(chat_id=user_id, text=f"Thanks for your response: {user_response}")

response_handler = MessageHandler(Filters.text & (~Filters.command), handle_response)
dispatcher.add_handler(response_handler)

# Start the bot
updater.start_polling()
updater.idle()
