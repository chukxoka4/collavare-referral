import os
import importlib
import gspread
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
import base64
import time
import json
load_dotenv()

import google.auth


BOT_TOKEN = os.getenv('TELEGRAM_API_KEY')
NOTIFICATION_CHAT_ID = int(os.getenv('NOTIFICATION_CHAT_ID'))
BCC_EMAIL = os.getenv('BCC_EMAIL')
SENDER_EMAIL = os.getenv('SENDER_EMAIL')

updater = Updater(token=BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

# Import contacts
import contacts

# Google Sheets Setup
SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.readonly']
CREDENTIALS_FILE = 'collavare-referral-tool-346f45a3947a.json'  # Update with your JSON file path
credentials = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPES)
gc = gspread.authorize(credentials)
sheet = gc.open_by_key(SHEET_ID).sheet1  # Access the first sheet

# Track processed rows
processed_rows = set()

CONTACT_LAST_ROW_FILE = 'contact_last_row.json'

def load_contact_last_row():
    if os.path.exists(CONTACT_LAST_ROW_FILE):
        with open(CONTACT_LAST_ROW_FILE, 'r') as f:
            return json.load(f)
    else:
        return {}

def save_contact_last_row(contact_last_row):
    with open(CONTACT_LAST_ROW_FILE, 'w') as f:
        json.dump(contact_last_row, f)

contact_last_row = load_contact_last_row()

def create_token_pickle():
    # Get the base64 encoded string from the environment variable
    token_pickle_base64 = os.getenv('TOKEN_PICKLE_BASE64')

    if token_pickle_base64:
        # Decode the base64 string
        token_data = base64.b64decode(token_pickle_base64)

        # Write the decoded data back to a token.pickle file
        with open('token.pickle', 'wb') as token_file:
            token_file.write(token_data)
    else:
        print("No TOKEN_PICKLE_BASE64 environment variable found.")

# Call this function at application startup
create_token_pickle()


def authenticate_gmail():
    # Gmail API scopes
    SCOPES = ['https://www.googleapis.com/auth/gmail.compose', 'https://www.googleapis.com/auth/gmail.send','https://www.googleapis.com/auth/gmail.modify', 
              'https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/drive.file',
              'https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = None
    token_file = 'token.pickle'

    # Check if token already exists
    if os.path.exists(token_file):
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)

    # If no valid creds, authenticate the user
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'collavare-referral-oauth-credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
            print("Granted Scopes:", creds.scopes)
        # Save the credentials
        with open(token_file, 'wb') as token:
            pickle.dump(creds, token)

    return build('gmail', 'v1', credentials=creds)

def create_email(sender, to, subject, message_html, logo_path, reply_to_emails=None):
    message = MIMEMultipart('related')
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    if reply_to_emails:
        # If reply_to_emails is a list, join them into a comma-separated string
        if isinstance(reply_to_emails, list):
            message['Reply-To'] = ', '.join(reply_to_emails)
        else:  # If it's a single email address, use it directly
            message['Reply-To'] = reply_to_emails

    # Alternative MIME part for HTML content
    msg_alternative = MIMEMultipart('alternative')
    message.attach(msg_alternative)
    msg_alternative.attach(MIMEText(message_html, 'html'))

    # Attach the image
    with open(logo_path, 'rb') as img:
        msg_image = MIMEImage(img.read())
        msg_image.add_header('Content-ID', '<company_logo>')
        message.attach(msg_image)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw_message}

def send_email(service, sender, to, subject, message_text, logo_path):
    bcc_email = BCC_EMAIL
    reply_to_emails = [sender, bcc_email]  # List of emails
    email_message = create_email(sender, to, subject, message_text, logo_path, reply_to_emails)
    sent_message = service.users().messages().send(userId="me", body=email_message).execute()
    print(f"Message sent to {to}: {sent_message['id']}")
    print(bcc_email)

# Initialize the Gmail API

gmail_service = authenticate_gmail()


def send_email_with_gmail(to_email, subject, html_content, logo_path):
    sender_email = SENDER_EMAIL  # Replace with your Gmail address
    try:
        send_email(gmail_service, sender_email, to_email, subject, html_content, logo_path)
    except HttpError as error:
        print(f"Failed to send email to {to_email}. Error: {error}")
        print("Error details:", error.error_details)

# Function to load email template
def load_email_template(template_path, subject, body):
    with open(template_path, 'r', encoding='utf-8') as file:
        template = file.read()
    return template.replace('{{subject}}', subject).replace('{{body}}', body)

def load_recipients(file_path):
    try:
        with open(file_path, 'r') as file:
            # Read all lines and strip any whitespace
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        print(f"Error: File {file_path} not found.")
        return []


# Example method to process rows and send emails
def process_and_send_email(row_data):
# Assuming row_data is a dictionary with the required fields
    to_emails = load_recipients("email_recipients.txt")
    if not to_emails:
        print("No recipients found. Exiting.")
        return

    subject = f"A new position for {row_data.get('Role Name', 'N/A')} is open!"  # Using .get()

    # Build the HTML table
    table_rows = ''
    fields = [
        ('📅 <b>Date</b>', row_data.get('Date', 'N/A')),
        ('🔖 <b>Role Name</b>', row_data.get('Role Name', 'N/A')),
        ('💼 <b>Experience Required</b>', row_data.get('Experience Required', 'N/A')),
        ('🏢 <b>Company Name</b>', row_data.get('Company Name', 'N/A')),
        ('📍 <b>Location</b>', row_data.get('Location', 'N/A')),
        ('💰 <b>Salary</b>', row_data.get('Salary', 'N/A')),
        ('📝 <b>Description</b>', row_data.get('Description', 'N/A')),
        ('📄🔗 <b>Full Job Description</b>', row_data.get('Full JD Link', 'N/A')),
    ]

    for label, value in fields:
        table_rows += f"""
        <tr>
            <td style="border: 1px solid #dddddd; text-align: left; padding: 8px;">{label}</td>
            <td style="border: 1px solid #dddddd; text-align: left; padding: 8px;">{value}</td>
        </tr>
        """

    table_html = f"""
    <table style="border-collapse: collapse; width: 100%;">
        {table_rows}
    </table>
    """

    body = f"""
    <p>Hi,<br><br>A new role is available for recommendations and CV submissions. See details below:<br><br></p>
    {table_html}
    <p>We look forward to your CVs!</p>
    """

    # Load the email template
    template_path = 'email_template.html'
    email_content = load_email_template(template_path, subject, body)

    # Path to the company logo image
    logo_path = 'company_logo.png'  # Ensure this file exists

    # Send emails to all recipients
    for recipient_email in to_emails:
        try:
            send_email_with_gmail(recipient_email, subject, email_content, logo_path)
        except Exception as e:
            print(f"Failed to send email to {recipient_email}. Error: {e}")

def start(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.effective_chat.id, text="Hello! Welcome to the Collavare Referral.")
    context.bot.send_message(chat_id=update.effective_chat.id, text="We will be working with you to help us with recruitment plans.")
    chat_id = update.message.chat_id
    add_chat_id(chat_id)  # Add chat ID to contacts.py
    context.bot.send_message(chat_id=chat_id, text=f"Your chat ID is: {chat_id} and we have saved it to send you updates when new roles are added")
    current_max_row = len(sheet.get_all_records())
    contact_last_row[str(chat_id)] = current_max_row  # Store chat ID as string
    save_contact_last_row(contact_last_row)
    #update.message.reply_text("Hello! Your chat ID has been saved.")
    #context.bot.send_message(chat_id=update.effective_chat.id, text="Please send this chat id to the person who added you!")

# Register the command with the dispatcher
start_handler = CommandHandler('start', start)
dispatcher.add_handler(start_handler)

# Function to reload contacts dynamically
def reload_contacts():
    importlib.reload(contacts)
    return contacts.CONTACT_CHAT_IDS

# Add chat ID to contacts.py if not already there
def add_chat_id(chat_id):
    # Reload contacts to get the latest list
    current_contacts = reload_contacts()

    if chat_id not in current_contacts:
        current_contacts.append(chat_id)
        # Write back to contacts.py
        with open("contacts.py", "w") as file:
            file.write(f"CONTACT_CHAT_IDS = {current_contacts}\n")

def send_update_to_contacts(message):
    for contact_id in reload_contacts():
        updater.bot.send_message(chat_id=contact_id, text=message, parse_mode="Markdown")

def check_new_rows(context: CallbackContext):
    global processed_rows
    rows = sheet.get_all_records()
    total_rows = len(rows)
    for chat_id_str, last_sent_row in contact_last_row.items():
        chat_id = int(chat_id_str)
        for i in range(last_sent_row, total_rows):
            row = rows[i]
            if i not in processed_rows:
                # Extract relevant fields from the row
                date_published = row.get("Date", "N/A")
                role_name = row.get("Role Name", "N/A")
                experience_required = row.get("Experience Required", "N/A")
                company_name = row.get("Company Name", "N/A")
                location = row.get("Location", "N/A")
                salary = row.get("Salary", "N/A")
                description = row.get("Description", "N/A")
                job_description = row.get("Full JD Link", "N/A")

                # Create a formatted message
                message = (
                    f"📢 *New Role Added!*\n\n"
                    f"📅 *Date*: {date_published}\n"
                    f"🔖 *Role Name*: {role_name}\n"
                    f"💼 *Experience Required*: {experience_required}\n"
                    f"🏢 *Company Name*: {company_name}\n"
                    f"📍 *Location*: {location}\n"
                    f"💰 *Salary*: {salary}\n"
                    f"📝 *Description*: {description}\n"
                    f"📄🔗 *Job Description*: {job_description}\n\n"
                    f"Please reply with CVs that match the role!"
                )
                try:
                    #context.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
                    # Send the formatted message to contacts
                    send_update_to_contacts(message)
                    #processed_rows.add(i)
                except Exception as e:
                    print(f"Error sending message to {chat_id}: {e}")
            process_and_send_email(row)
            contact_last_row[chat_id_str] = total_rows  # Update last sent row
    save_contact_last_row(contact_last_row)


# Schedule the periodic check
updater.job_queue.run_repeating(check_new_rows, interval=60, first=10)

# Add a job to send updates at intervals, e.g., every 10 seconds for testing
# updater.job_queue.run_repeating(send_update_to_contacts, interval=10, first=10)

def handle_response(update: Update, context: CallbackContext):
    user_response = update.message.text
    user_id = update.message.chat_id
    user = update.message.from_user
    first_name = user.first_name or ''
    last_name = user.last_name or ''
    username = user.username or ''
    user_info = f"{first_name} {last_name} ({username})".strip()
    context.bot.send_message(chat_id=user_id, text=f"Thanks for your response: {user_response}")
        # Notify the specific Telegram user
    try:
        notification_message = f"🔔 *New Response Received*\n\nFrom: {user_info}\nMessage: {user_response}"
        context.bot.send_message(chat_id=NOTIFICATION_CHAT_ID, text=notification_message, parse_mode='Markdown')
        context.bot.forward_message(chat_id=NOTIFICATION_CHAT_ID, from_chat_id=user_id, message_id=update.message.message_id)

    except Exception as e:
        print(f"Failed to send notification to {NOTIFICATION_CHAT_ID}: {e}")

response_handler = MessageHandler(Filters.text & (~Filters.command), handle_response)
dispatcher.add_handler(response_handler)

def handle_document(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    file = update.message.document
    file_id = file.file_id
    file_name = file.file_name

    # Get user details
    user = update.message.from_user
    first_name = user.first_name or ''
    last_name = user.last_name or ''
    username = user.username or ''
    user_info = f"{first_name} {last_name} ({username})".strip()

    # Download the file
    new_file = context.bot.getFile(file_id)
    if not os.path.exists('cv_uploads'):
        os.makedirs('cv_uploads')
    local_file_path = os.path.join('cv_uploads', file_name)
    new_file.download(local_file_path)

    # Upload the file to Google Drive
    drive_folder_id = os.getenv('DRIVE_FOLDER_ID')  # Replace with your Drive folder ID
    upload_to_drive(local_file_path, file_name, drive_folder_id, user_info)

    context.bot.send_message(chat_id=chat_id, text=f"Thank you! Your CV '{file_name}' has been received.")
        # Notify the specific Telegram user
    try:
        notification_message = (
            f"📥 *New CV Received*\n\n"
            f"From: {user_info}\n"
            f"File: {file_name}\n\n"
            f"Please check the Google Drive."
        )
        context.bot.send_message(chat_id=NOTIFICATION_CHAT_ID, text=notification_message, parse_mode='Markdown')
    except Exception as e:
        print(f"Failed to send notification to {NOTIFICATION_CHAT_ID}: {e}")

dispatcher.add_handler(MessageHandler(Filters.document, handle_document))

def check_new_emails(context: CallbackContext):
    try:
        print("Checking for new emails...")
        results = gmail_service.users().messages().list(userId='me', q='in:inbox has:attachment is:unread').execute()
        messages = results.get('messages', [])

        if not messages:
            print("No new emails found.")
            return

        print(f"Found {len(messages)} new email(s) with attachments.")

        if not os.path.exists('cv_uploads'):
            os.makedirs('cv_uploads')

        for message_data in messages:
            msg_id = message_data['id']
            message = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            payload = message['payload']
            headers = payload.get('headers', [])
            parts = payload.get('parts', [])

            sender = None
            subject = '(No Subject)'
            for header in headers:
                if header['name'] == 'From':
                    sender = header['value']
                elif header['name'] == 'Subject':
                    subject = header['value']
                    break
            print(f"Processing email from: {sender}")

            attachments = []
            # Use a recursive function to find all attachments
            def extract_attachments(parts):
                for part in parts:
                    if 'filename' in part and part['filename']:
                        if 'attachmentId' in part['body']:
                            attachments.append(part)
                    elif 'parts' in part:
                        extract_attachments(part['parts'])

            extract_attachments(parts)

            attachment_processed = False

            if attachments:
                for part in attachments:
                    try:
                        print(f"Processing attachment: {part['filename']}")
                        attachment_id = part['body']['attachmentId']
                        attachment = gmail_service.users().messages().attachments().get(
                            userId='me', messageId=msg_id, id=attachment_id
                        ).execute()
                        file_data = base64.urlsafe_b64decode(attachment['data'])
                        local_file_path = os.path.join('cv_uploads', part['filename'])
                        with open(local_file_path, 'wb') as f:
                            f.write(file_data)
                        print(f"Downloaded attachment: {part['filename']} from {sender}")

                        # Upload to Google Drive
                        drive_folder_id = os.getenv('DRIVE_FOLDER_ID')  # Ensure this is set correctly
                        upload_to_drive(local_file_path, part['filename'], drive_folder_id, sender)
                        attachment_processed = True
                    except Exception as e:
                        print(f"Error processing attachment {part['filename']}: {e}")
            else:
                print("No attachments found in the email.")

                        # Notify the specific Telegram user
            try:
                if attachment_processed:
                    notification_message = (
                        f"📧 *New Email with Attachment*\n\n"
                        f"From: {sender}\n"
                        f"Subject: {subject}\n\n"
                        f"Attachments have been uploaded to Google Drive."
                    )
                else:
                    notification_message = (
                        f"📧 *New Email Received*\n\n"
                        f"From: {sender}\n"
                        f"Subject: {subject}\n\n"
                        f"No attachments found."
                    )
                context.bot.send_message(chat_id=NOTIFICATION_CHAT_ID, text=notification_message, parse_mode='Markdown')
            except Exception as e:
                print(f"Failed to send notification to {NOTIFICATION_CHAT_ID}: {e}")

            # Mark the message as read
            gmail_service.users().messages().modify(
                userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}
            ).execute()
            print(f"Email from {sender} processed and marked as read.")

        print("All new emails have been processed.")
    except Exception as e:
        print(f"An error occurred in check_new_emails: {e}")
    results = gmail_service.users().messages().list(userId='me', q='has:attachment is:unread').execute()
    messages = results.get('messages', [])

    if not messages:
        return

    if not os.path.exists('cv_uploads'):
        os.makedirs('cv_uploads')

    for message_data in messages:
        msg_id = message_data['id']
        message = gmail_service.users().messages().get(userId='me', id=msg_id).execute()
        payload = message['payload']
        headers = payload.get('headers', [])
        parts = payload.get('parts', [])

        sender = None
        for header in headers:
            if header['name'] == 'From':
                sender = header['value']
                break

        if parts:
            for part in parts:
                if part['filename']:
                    attachment_id = part['body']['attachmentId']
                    attachment = gmail_service.users().messages().attachments().get(
                        userId='me', messageId=msg_id, id=attachment_id
                    ).execute()
                    file_data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
                    file_path = os.path.join('cv_uploads', f"{sender}_{part['filename']}")
                    with open(file_path, 'wb') as f:
                        f.write(file_data)
                    print(f"Downloaded attachment: {part['filename']} from {sender}")

        # Mark the message as read
        gmail_service.users().messages().modify(
            userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}
        ).execute()

# Schedule the email check function
updater.job_queue.run_repeating(check_new_emails, interval=300, first=10)

def authenticate_drive():
    DRIVE_CREDENTIALS_FILE = 'collavare-referral-oauth-credentials.json'
    creds = None
    token_file = 'token.pickle'
    
    # Check if token already exists
    if os.path.exists(token_file):
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)
    
    # If no valid creds, authenticate the user
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                DRIVE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            print("Granted Scopes:", creds.scopes)
        # Save the credentials
        with open(token_file, 'wb') as token:
            pickle.dump(creds, token)
    
    return build('drive', 'v3', credentials=creds)

# Initialize the Google Drive API
drive_service = authenticate_drive()

def upload_to_drive(file_path, file_name, folder_id, sender_info):
    file_metadata = {
        'name': f"{sender_info} - {file_name}",
        'parents': [folder_id],
        'description': f"Uploaded by {sender_info}"
    }
    media = MediaFileUpload(file_path, resumable=True)
    try:
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        print(f"File '{file_name}' uploaded to Google Drive with ID: {file.get('id')}")
    except HttpError as error:
        print(f"An error occurred while uploading the file: {error}")

from http.server import HTTPServer, BaseHTTPRequestHandler

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Service is running!')

def run_http_server():
    port = int(os.environ.get("PORT", 5000))  # Default to port 5000 or use specified PORT
    server_address = ('', port)
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    print(f"Starting HTTP server on port {port}")
    httpd.serve_forever()

if __name__ == '__main__':
    # Existing startup code for Telegram bot
    updater.start_polling()
    
    # Start the HTTP server for deployment compliance
    run_http_server()

    updater.idle()

# Start the bot
updater.start_polling()

updater.idle()
