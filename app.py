from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import mysql.connector
from datetime import datetime

app = FastAPI()

# إعدادات الاتصال بقاعدة بيانات MySQL
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "admin",
    "database": "event_system"
}

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

@app.get("/events")
def get_events():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT DISTINCT event_name FROM guests WHERE event_name IS NOT NULL")
    events = cursor.fetchall()
    cursor.close()
    conn.close()
    return events

@app.post("/scan")
async def scan_ticket(request: Request):
    data = await request.json()
    ticket_code = data.get("ticket_code")
    event_name = data.get("event_name")
    usher_name = data.get("usher_name", "بوابة 1")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = "SELECT * FROM guests WHERE ticket_code = %s AND event_name = %s"
    cursor.execute(query, (ticket_code, event_name))
    guest = cursor.fetchone()

    if not guest:
        cursor.close()
        conn.close()
        return JSONResponse({"status": "invalid", "message": "تذكرة غير صالحة أو غير مسجلة بهذا الحدث!"})

    if guest["is_attended"] == 1:
        cursor.close()
        conn.close()
        time_str = guest["attended_at"].strftime("%I:%M %p") if guest["attended_at"] else "سابقاً"
        return JSONResponse({
            "status": "already_used",
            "message": f"تنبيه: تم استخدام التذكرة مسبقاً في الساعة {time_str}!",
            "guest_name": guest["name"]
        })

    # تسجيل الحضور
    now = datetime.now()
    update_query = """
        UPDATE guests 
        SET is_attended = 1, attended_at = %s, scanned_by = %s 
        WHERE id = %s
    """
    cursor.execute(update_query, (now, usher_name, guest["id"]))
    conn.commit()

    cursor.close()
    conn.close()

    return JSONResponse({
        "status": "success",
        "message": "تم الدخول بنجاح",
        "guest_name": guest["name"],
        "phone": guest["phone"]
    })

@app.get("/", response_class=HTMLResponse)
def scanner_page():
    return """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Gate Scanner</title>
        <script src="https://unpkg.com/html5-qrcode"></script>
        <style>
            body { font-family: system-ui, sans-serif; text-align: center; margin: 0; padding: 15px; background: #0f172a; color: #f8fafc; }
            h2 { margin-bottom: 15px; color: #38bdf8; }
            select, input { width: 90%; max-width: 400px; padding: 12px; margin: 6px 0; border-radius: 8px; border: 1px solid #334155; background: #1e293b; color: #fff; font-size: 16px; outline: none; }
            #reader { width: 100%; max-width: 400px; margin: 15px auto; border-radius: 12px; overflow: hidden; border: 2px solid #38bdf8; background: #000; }
            #result-box { width: 85%; max-width: 380px; margin: 15px auto; padding: 15px; border-radius: 10px; font-weight: bold; font-size: 18px; display: none; }
            .success { background: #166534; color: #dcfce7; border: 2px solid #22c55e; }
            .warning { background: #991b1b; color: #fee2e2; border: 2px solid #ef4444; }
            .invalid { background: #854d0e; color: #fef9c3; border: 2px solid #eab308; }
        </style>
    </head>
    <body>
        <h2>نظام فحص التذاكر</h2>
        <select id="eventSelect"><option value="">جاري تحميل الفعاليات...</option></select>
        <input type="text" id="usherName" placeholder="اسم الأوشر / رقم البوابة">
        
        <div id="reader"></div>
        <div id="result-box"></div>

        <script>
            let isScanning = true;

            fetch('/events')
                .then(r => r.json())
                .then(events => {
                    const sel = document.getElementById('eventSelect');
                    if (events.length === 0) {
                        sel.innerHTML = '<option value="">لا توجد فعاليات مسجلة</option>';
                        return;
                    }
                    sel.innerHTML = '<option value="">-- اختر الفعالية --</option>';
                    events.forEach(e => {
                        sel.innerHTML += `<option value="${e.event_name}">${e.event_name}</option>`;
                    });
                });

            function onScanSuccess(decodedText) {
                if (!isScanning) return;
                const eventName = document.getElementById('eventSelect').value;
                const usher = document.getElementById('usherName').value || 'Gate 1';

                if (!eventName) {
                    alert('يرجى اختيار الفعالية أولاً!');
                    return;
                }

                isScanning = false;
                const resBox = document.getElementById('result-box');

                fetch('/scan', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ ticket_code: decodedText.trim(), event_name: eventName, usher_name: usher })
                })
                .then(r => r.json())
                .then(data => {
                    resBox.style.display = 'block';
                    if (data.status === 'success') {
                        resBox.className = 'success';
                        resBox.innerHTML = `✅ ${data.message}<br><br>👤 ${data.guest_name}`;
                    } else if (data.status === 'already_used') {
                        resBox.className = 'warning';
                        resBox.innerHTML = `⚠️ ${data.message}<br><br>👤 الاسم: ${data.guest_name}`;
                    } else {
                        resBox.className = 'invalid';
                        resBox.innerHTML = `❌ ${data.message}`;
                    }

                    setTimeout(() => {
                        resBox.style.display = 'none';
                        isScanning = true;
                    }, 2500);
                })
                .catch(() => {
                    isScanning = true;
                });
            }

            const html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps: 10, qrbox: 250 });
            html5QrcodeScanner.render(onScanSuccess);
        </script>
    </body>
    </html>
    """





