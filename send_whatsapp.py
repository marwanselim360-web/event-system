import os
import re
import time
import requests

# ==========================================
# إعدادات Meta WhatsApp API الرسمية
# ==========================================
ACCESS_TOKEN = "EAAUTQepb8JsBStIyq4lm9FeN7NYgmcM4QjYpT2JiEIyD7Rsa9RZCZAHeFKVKxsB6lSRZAye9QfGZCrba29g4bzJUamyUax8pZB9dzuvBZCRHpT7F3FghTAdnhyyjGaZAmTU3cEeHAvwlBOKGLx0632UAifQNfWspbZBhPKjY6MnIVzZAAZBqDOMK8fF5ImPMIY4nf72gZDZD"
PHONE_NUMBER_ID = "1412934905227314"

# إعدادات القالب
TEMPLATE_NAME = "event_invitation_ticket"
LANGUAGE_CODE = "ar"

# مسار مجلد التذاكر الرئيسي
TICKETS_FOLDER = "tickets"


def format_egypt_phone(raw_phone):
    """تنسيق رقم الهاتف ليتوافق مع الـ API (صيغة 201xxxxxxxxx)"""
    digits = re.sub(r'\D', '', str(raw_phone))
    if digits.startswith("201") and len(digits) == 12:
        return digits
    elif digits.startswith("01") and len(digits) == 11:
        return "2" + digits
    elif digits.startswith("1") and len(digits) == 10:
        return "20" + digits
    elif len(digits) >= 10:
        return digits
    return None


def upload_image_to_whatsapp(image_path):
    """رفع صورة التذكرة لسيرفرات واتساب للحصول على Media ID"""
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/media"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}"
    }
    
    with open(image_path, 'rb') as img_file:
        files = {
            'file': (os.path.basename(image_path), img_file, 'image/png')
        }
        data = {
            'messaging_product': 'whatsapp',
            'type': 'image/png'
        }
        response = requests.post(url, headers=headers, files=files, data=data)

    if response.status_code == 200:
        return response.json().get('id')
    else:
        print(f"[-] Failed to upload image {os.path.basename(image_path)}: {response.text}")
        return None


def send_whatsapp_template(phone, media_id):
    """إرسال التذكرة بالصورة وتمرير المتغيرين المطلوبين في القالب"""
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": TEMPLATE_NAME,
            "language": {
                "code": LANGUAGE_CODE
            },
            "components": [
                {
                    "type": "header",
                    "parameters": [
                        {
                            "type": "image",
                            "image": {
                                "id": media_id
                            }
                        }
                    ]
                },
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": "Guest"
                        },
                        {
                            "type": "text",
                            "text": "Welcome"
                        }
                    ]
                }
            ]
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    return response.json()


def choose_event_folder(base_folder):
    """عرض قائمة الفولدرات ليختار المستخدم الفولدر المطلوب"""
    if not os.path.exists(base_folder):
        return None

    subfolders = [f for f in os.listdir(base_folder) if os.path.isdir(os.path.join(base_folder, f))]
    
    if not subfolders:
        return None

    print("\n--- Available Events ---")
    for idx, folder_name in enumerate(subfolders, 1):
        print(f"  [{idx}] {folder_name}")
    print(f"  [A] Send All Events")

    choice = input("\nSelect Event Number (or 'A' for all): ").strip()

    if choice.lower() == 'a':
        return subfolders

    try:
        selected_idx = int(choice) - 1
        if 0 <= selected_idx < len(subfolders):
            return [subfolders[selected_idx]]
    except ValueError:
        pass

    print("[-] Invalid choice, selecting first folder by default.")
    return [subfolders[0]]


def process_folder(folder_path):
    """قراءة وإرسال جميع التذاكر من فولدر محدد"""
    files = [f for f in os.listdir(folder_path) if f.lower().endswith(".png")]
    
    if not files:
        print(f"[-] No ticket images found in: {folder_path}")
        return

    print(f"\n[+] Processing folder: {os.path.basename(folder_path)} (Tickets: {len(files)})")
    print("-" * 50)

    for idx, file_name in enumerate(files, 1):
        # استخراج رقم الهاتف من اسم الملف
        name_part = re.split(r'[_.]', file_name)[0]
        phone = format_egypt_phone(name_part)

        if not phone:
            print(f"[-] [{idx}/{len(files)}] Skipped, invalid phone name: {file_name}")
            continue

        image_path = os.path.join(folder_path, file_name)
        print(f"[>] [{idx}/{len(files)}] Uploading and sending to: +{phone}...")

        # 1. رفع الصورة لسيرفرات ميتا والحصول على media_id
        media_id = upload_image_to_whatsapp(image_path)
        if not media_id:
            continue

        # 2. إرسال الرسالة باستخدام القالب الرسمي
        res = send_whatsapp_template(phone, media_id)
        if "messages" in res:
            print(f"[+] [{idx}/{len(files)}] Successfully sent to: +{phone}")
        else:
            print(f"[-] [{idx}/{len(files)}] Error sending to +{phone}: {res}")

        # مهلة ثانيتين بين الرسائل لتجنب ضغط الـ Rate Limit
        time.sleep(2)


def main():
    if not os.path.exists(TICKETS_FOLDER):
        print(f"[-] Folder '{TICKETS_FOLDER}' not found!")
        return

    selected_folders = choose_event_folder(TICKETS_FOLDER)
    
    if not selected_folders:
        process_folder(TICKETS_FOLDER)
        return

    for folder_name in selected_folders:
        full_path = os.path.join(TICKETS_FOLDER, folder_name)
        process_folder(full_path)

    print("\n[+] All messages processed!")


if __name__ == "__main__":
    main()