from flask import Flask, request, jsonify
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
import requests
import os

load_dotenv()
app = Flask(__name__)

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
VERIFY_TOKEN = "my_secure_secret_token_123"

# Memory dictionary to track conversation progress per phone number
user_sessions = {}

def send_whatsapp_message(to_number, text_body):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {"body": text_body}
    }
    requests.post(url, json=payload, headers=headers)

# Updated to accept your new student parameters
def log_to_google_sheets(whatsapp_phone, student_name, esis_num, grade, school, parent_name, parent_phone):
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
        service = build('sheets', 'v4', credentials=creds)
        
        # Array matching Columns A through G
        values = [[whatsapp_phone, student_name, esis_num, grade, school, parent_name, parent_phone]]
        body = {'values': values}
        
        # Range expanded to A:G to handle 7 columns of data
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Sheet1!A:G",
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
    except Exception as e:
        print(f"Google Sheets Error: {e}")

@app.route('/bot', methods=['GET'])
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403

@app.route('/bot', methods=['POST'])
def bot():
    data = request.get_json()
    try:
        entry = data['entry'][0]
        changes = entry['changes'][0]
        value = changes['value']
        
        if 'messages' not in value:
            return jsonify({"status": "ignored"}), 200
            
        message_data = value['messages'][0]
        from_number = message_data['from']
        
        if message_data['type'] == 'text':
            user_msg = message_data['text']['body'].strip()
            msg_lower = user_msg.lower()
            
            # --- START OR RESET REGISTRATION ---
            if msg_lower == 'hi' or msg_lower == 'register' or from_number not in user_sessions:
                # Initialize empty fields for all your requested student/parent variables
                user_sessions[from_number] = {
                    "state": "AWAITING_STUDENT_NAME",
                    "data": {
                        "student_name": "", 
                        "esis_number": "", 
                        "grade": "", 
                        "school_name": "",
                        "parent_name": "",
                        "parent_phone": ""
                    }
                }
                send_whatsapp_message(from_number, "Welcome to the Event Registration Bot! 🎓\n\nLet's begin. What is the *Student's Full Name*?")
                return jsonify({"status": "success"}), 200

            session = user_sessions[from_number]
            current_state = session["state"]

            # --- CONVERSATIONAL QUESTION FLOW ---
            
            if current_state == "AWAITING_STUDENT_NAME":
                session["data"]["student_name"] = user_msg
                session["state"] = "AWAITING_ESIS"
                send_whatsapp_message(from_number, f"Thank you. Now, please enter the *ESIS Number* for {user_msg}:")
                
            elif current_state == "AWAITING_ESIS":
                session["data"]["esis_number"] = user_msg
                session["state"] = "AWAITING_GRADE"
                send_whatsapp_message(from_number, "What *Grade / Class* is the student currently in?")
                
            elif current_state == "AWAITING_GRADE":
                session["data"]["grade"] = user_msg
                session["state"] = "AWAITING_SCHOOL"
                send_whatsapp_message(from_number, "What is the *School Name*?")
                
            elif current_state == "AWAITING_SCHOOL":
                session["data"]["school_name"] = user_msg
                session["state"] = "AWAITING_PARENT_NAME"
                send_whatsapp_message(from_number, "Got it. What is the *Parent's Full Name*?")
                
            elif current_state == "AWAITING_PARENT_NAME":
                session["data"]["parent_name"] = user_msg
                session["state"] = "AWAITING_PARENT_PHONE"
                send_whatsapp_message(from_number, "Last question: Please provide the *Parent's Mobile Number*:")
                
            elif current_state == "AWAITING_PARENT_PHONE":
                session["data"]["parent_phone"] = user_msg
                reg_data = session["data"]
                
                # Write all 7 collected items directly to Google Sheets
                log_to_google_sheets(
                    whatsapp_phone=from_number,
                    student_name=reg_data["student_name"],
                    esis_num=reg_data["esis_number"],
                    grade=reg_data["grade"],
                    school=reg_data["school_name"],
                    parent_name=reg_data["parent_name"],
                    parent_phone=reg_data["parent_phone"]
                )
                
                # Send out final confirmation summary string
                confirmation = (f"🎉 *Registration Complete!*\n\n"
                                f"Here is a summary of the registered details:\n\n"
                                f"👨‍🎓 *Student Name:* {reg_data['student_name']}\n"
                                f"🔢 *ESIS Number:* {reg_data['esis_number']}\n"
                                f"📊 *Grade:* {reg_data['grade']}\n"
                                f"🏫 *School Name:* {reg_data['school_name']}\n"
                                f"👤 *Parent Name:* {reg_data['parent_name']}\n"
                                f"📱 *Parent Phone:* {reg_data['parent_phone']}\n\n"
                                f"Thank you! Your details have been successfully saved to our master sheet.")
                send_whatsapp_message(from_number, confirmation)
                
                # Clear memory state so the user is free to register another student if needed
                del user_sessions[from_number]

    except Exception as e:
        print(f"Error processing webhook: {e}")

    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    app.run(port=5000)