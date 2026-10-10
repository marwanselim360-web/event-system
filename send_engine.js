import makeWASocket, { useMultiFileAuthState, DisconnectReason } from '@whiskeysockets/baileys';
import pino from 'pino';
import qrcode from 'qrcode-terminal';
import XLSX from 'xlsx';
import fs from 'fs';
import path from 'path';
import mysql from 'mysql2/promise';

// إعدادات الاتصال بـ MySQL
// إعدادات الاتصال بـ MySQL
const DB_CONFIG = {
  host: 'localhost',
  user: 'root',
  password: 'admin', // كده حطينا الباسورد
  database: 'event_system'
};

const TICKETS_DIR = './tickets';

// إعدادات الأمان والتوقف الدوري لتفادي حظر واتساب
const CONFIG = {
  BATCH_SIZE: 25,             // عدد الرسائل قبل كل استراحة
  BATCH_COOLDOWN_MS: 30000,   // استراحة 30 ثانية لكل دفعة
  MIN_DELAY_MS: 4000,         // الحد الأدنى للانتظار بين الرسائل (4 ثوانٍ)
  MAX_DELAY_MS: 7000          // الحد الأقصى للانتظار العشوائي (7 ثوانٍ)
};

function getExcelPath() {
  const files = fs.readdirSync('.');
  return files.find(f => (f.endsWith('.xlsx') || f.endsWith('.csv')) && !f.startsWith('~$'));
}

function formatPhone(val) {
  if (!val) return null;
  let digits = String(val).replace(/\D/g, '');
  if (digits.startsWith('01') && digits.length === 11) digits = '2' + digits;
  if (digits.startsWith('1') && digits.length === 10) digits = '20' + digits;
  return digits.length >= 11 ? `${digits}@s.whatsapp.net` : null;
}

// قراءة كل الصور من مجلد التذاكر وجميع الفولدرات الفرعية الخاصة بكل إيفنت
function getAllImageFiles(dirPath, arrayOfFiles = []) {
  if (!fs.existsSync(dirPath)) return arrayOfFiles;
  const files = fs.readdirSync(dirPath);

  files.forEach((file) => {
    const fullPath = path.join(dirPath, file);
    if (fs.statSync(fullPath).isDirectory()) {
      arrayOfFiles = getAllImageFiles(fullPath, arrayOfFiles);
    } else if (file.endsWith('.png') || file.endsWith('.jpg') || file.endsWith('.jpeg')) {
      arrayOfFiles.push(fullPath);
    }
  });

  return arrayOfFiles;
}

function findTicketImage(phone, name, allImagePaths) {
  const cleanPhone = String(phone).replace(/\D/g, '');
  const cleanName = String(name).replace(/[\/\\:*?"<>|]/g, '').trim().toLowerCase();

  // 1. بحث برقم التليفون
  let match = allImagePaths.find(p => cleanPhone && path.basename(p).includes(cleanPhone));
  if (match) return match;

  // 2. بحث باسم الضيف
  match = allImagePaths.find(p => path.basename(p).toLowerCase().includes(cleanName));
  if (match) return match;

  return null;
}

// مزامنة بيانات ملف الإكسيل مع جدول MySQL
async function syncExcelToDB(db) {
  const excelFile = getExcelPath();
  if (!excelFile) {
    console.log('Error: No Excel file found in folder!');
    process.exit(1);
  }

  const allImages = getAllImageFiles(TICKETS_DIR);
  const wb = XLSX.readFile(excelFile);
  const data = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]]);

  console.log(`\n📁 تم فحص الإكسيل: وُجد ${data.length} ضيف.`);
  console.log(`🖼️ تم العثور على ${allImages.length} صورة تذكرة في المجلدات.`);

  for (const row of data) {
    const keys = Object.keys(row);
    const nameKey = keys.find(k => /name|الاسم|ضيف/i.test(k)) || keys[0];
    const phoneKey = keys.find(k => /phone|موبايل|هاتف|تليفون|رقم/i.test(k)) || keys[1];

    const guestName = String(row[nameKey] || 'Guest').trim();
    const rawPhone = String(row[phoneKey] || '');
    const cleanDigits = rawPhone.replace(/\D/g, '');

    if (!cleanDigits) continue;

    const imagePath = findTicketImage(rawPhone, guestName, allImages);

    // التحقق من وجود الرقم مسبقاً لتجنب التكرار
    const [existing] = await db.execute('SELECT id FROM guests WHERE phone = ?', [rawPhone]);
    if (existing.length === 0) {
      await db.execute(
        `INSERT INTO guests (name, phone, image_path, send_status) VALUES (?, ?, ?, 'PENDING')`,
        [guestName, rawPhone, imagePath || '']
      );
    } else if (imagePath) {
      // تحديث مسار الصورة إذا لم تكن مسجلة
      await db.execute('UPDATE guests SET image_path = ? WHERE phone = ? AND (image_path IS NULL OR image_path = "")', [imagePath, rawPhone]);
    }
  }
}

let sock = null;

async function startEngine() {
  const { state, saveCreds } = await useMultiFileAuthState('auth_session');

  sock = makeWASocket({
    auth: state,
    logger: pino({ level: 'silent' }),
    connectTimeoutMs: 60000,
    keepAliveIntervalMs: 20000
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log('\n📲 Scan QR code from WhatsApp:');
      qrcode.generate(qr, { small: true });
    }

    if (connection === 'close') {
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      console.log(`\n⚠️ الاتصال فصل (كود: ${statusCode}). إعادة المحاولة تلقائياً...`);
      if (shouldReconnect) setTimeout(startEngine, 5000);
    } else if (connection === 'open') {
      console.log('\n✅ WhatsApp Connected! جاري فحص قاعدة البيانات وبدء الإرسال...');
      await runDBDispatcher();
    }
  });
}

async function runDBDispatcher() {
  let db;
  try {
    db = await mysql.createConnection(DB_CONFIG);
  } catch (err) {
    console.log('❌ خطأ في الاتصال بـ MySQL! تأكد من الباسورد وتشغيل السيرفر:', err.message);
    process.exit(1);
  }

  // مزامنة الأسماء من الإكسيل للجدول
  await syncExcelToDB(db);

  // سحب من حالتهم PENDING فقط
  const [pending] = await db.execute(`SELECT * FROM guests WHERE send_status = 'PENDING'`);
  const [[totalCount]] = await db.execute(`SELECT COUNT(*) as count FROM guests`);
  const [[sentCount]] = await db.execute(`SELECT COUNT(*) as count FROM guests WHERE send_status = 'SENT'`);

  console.log(`\n📊 تقرير الإرسال من MySQL:`);
  console.log(`- الإجمالي المسجل: ${totalCount.count}`);
  console.log(`- تم الإرسال سابقاً: ${sentCount.count}`);
  console.log(`- متبقي الآن: ${pending.length}\n`);

  if (pending.length === 0) {
    console.log('🎉 جميع التذاكر تم إرسالها بنجاح!');
    process.exit(0);
  }

  let batchCounter = 0;

  for (const guest of pending) {
    const jid = formatPhone(guest.phone);

    if (!jid) {
      console.log(`⚠️ تخطي [${guest.name}]: رقم هاتف غير صالح.`);
      await db.execute(`UPDATE guests SET send_status = 'FAILED' WHERE id = ?`, [guest.id]);
      continue;
    }

    if (!guest.image_path || !fs.existsSync(guest.image_path)) {
      console.log(`⚠️ صورة التذكرة غير موجودة لـ: [${guest.name}]`);
      await db.execute(`UPDATE guests SET send_status = 'FAILED' WHERE id = ?`, [guest.id]);
      continue;
    }

    const caption = `أهلاً بحضرتك ${guest.name}،\nيسعدنا حضوركم ومشاركتنا هذه المناسبة الخاصة. مرفق بطاقة الدخول الخاصة بكم لتسهيل مروركم من البوابة.\n\nنتمنى لكم وقتاً ممتعاً! ✨`;

    try {
      console.log(`🚀 [ID: \({guest.id}] إرسال إلى\){guest.name} (${guest.phone})...`);
      await sock.sendMessage(jid, {
        image: fs.readFileSync(guest.image_path),
        caption: caption
      });

      // حفظ حالة الإرسال في قاعدة البيانات
      await db.execute(
        `UPDATE guests SET send_status = 'SENT', sent_at = NOW() WHERE id = ?`,
        [guest.id]
      );

      console.log(`✅ تم تسليم التذكرة لـ ${guest.name}!`);
      batchCounter++;

      // نظام الدفعات والراحة لتجنب حظر واتساب
      if (batchCounter >= CONFIG.BATCH_SIZE) {
        console.log(`\n☕ تم إرسال دفعة (\({CONFIG.BATCH_SIZE} تذاكر). استراحة أمان\){CONFIG.BATCH_COOLDOWN_MS / 1000} ثانية...`);
        await new Promise(r => setTimeout(r, CONFIG.BATCH_COOLDOWN_MS));
        batchCounter = 0;
      } else {
        const delay = Math.floor(Math.random() * (CONFIG.MAX_DELAY_MS - CONFIG.MIN_DELAY_MS)) + CONFIG.MIN_DELAY_MS;
        await new Promise(r => setTimeout(r, delay));
      }

    } catch (err) {
      console.log(`❌ فشل الإرسال لـ \({guest.name}:\){err.message}`);
      await db.execute(`UPDATE guests SET send_status = 'FAILED' WHERE id = ?`, [guest.id]);
      await new Promise(r => setTimeout(r, 4000));
    }
  }

  console.log('\n🎉 اكتمل إرسال جميع التذاكر بنجاح!');
  process.exit(0);
}

startEngine();