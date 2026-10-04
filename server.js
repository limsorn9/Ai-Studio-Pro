const express = require('express');
const TelegramBot = require('node-telegram-bot-api');
const crypto = require('crypto');
const cors = require('cors');
const admin = require('firebase-admin');

const app = express();
app.use(express.json());
app.use(cors());

// ============================================================
// CONFIG
// ============================================================
const BOT_TOKEN = process.env.TELEGRAM_TOKEN || process.env.API_Bot;
const OWNER_CHAT_ID = process.env.OWNER_CHAT_ID || '240224709'; // @limsorn
const PORT = process.env.PORT || 3000;
const APP_NAME = 'AiStudioPro កំពូលអ្នកបកប្រែសម្លេង';

// ============================================================
// FIREBASE INIT
// ============================================================
let db;
try {
  let serviceAccount = process.env.FIREBASE_CREDENTIALS;
  if (serviceAccount) {
    try {
      serviceAccount = JSON.parse(serviceAccount);
    } catch (e) {
      console.warn("Could not parse FIREBASE_CREDENTIALS as JSON.");
    }
    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount),
      databaseURL: process.env.FIREBASE_DB_URL
    });
    db = admin.database();
    console.log('✅ Firebase initialized');
  } else {
    console.warn('⚠️ FIREBASE_CREDENTIALS not set');
  }
} catch (error) {
  console.error('❌ Firebase initialization error:', error.message);
}

// Fallback in-memory store if Firebase fails
const memoryLicenses = new Map();

async function saveLicense(key, data) {
  if (db) {
    await db.ref('licenses/' + key).set(data);
  } else {
    memoryLicenses.set(key, data);
  }
}

async function getLicense(key) {
  if (db) {
    const snapshot = await db.ref('licenses/' + key).once('value');
    return snapshot.val();
  }
  return memoryLicenses.get(key);
}

async function getAllLicenses() {
  if (db) {
    const snapshot = await db.ref('licenses').once('value');
    return snapshot.val() || {};
  }
  return Object.fromEntries(memoryLicenses);
}

async function updateLicense(key, updates) {
  if (db) {
    await db.ref('licenses/' + key).update(updates);
  } else {
    const lic = memoryLicenses.get(key);
    if (lic) memoryLicenses.set(key, { ...lic, ...updates });
  }
}

// ============================================================
// HELPERS
// ============================================================
function generateLicenseKey() {
  const part = () => crypto.randomBytes(3).toString('hex').toUpperCase();
  return `AISTUDIO-${part()}-${part()}-${part()}`;
}

function formatDate(ms) {
  return new Date(ms).toLocaleString('km-KH', { timeZone: 'Asia/Phnom_Penh' });
}

// ============================================================
// TELEGRAM BOT
// ============================================================
let bot;
if (BOT_TOKEN) {
  bot = new TelegramBot(BOT_TOKEN, { polling: true });
  console.log('✅ Telegram bot started');

  bot.onText(/\/start/, (msg) => {
    const chatId = msg.chat.id;
    bot.sendMessage(chatId, `👋 សួស្ដី! ខ្ញុំជា License Bot របស់ *${APP_NAME}*\n\n` +
      `🔑 *Commands:*\n` +
      `/getlicense — ទទួល License Key\n` +
      `/check \\[key\\] — ពិនិត្យ License\n\n` +
      `📬 Contact: @limsorn9`,
      { parse_mode: 'Markdown' });
  });

  bot.onText(/\/getlicense/, async (msg) => {
    const chatId = msg.chat.id;
    const username = msg.from.username ? `@${msg.from.username}` : msg.from.first_name;
    const userId = msg.from.id;

    const all = await getAllLicenses();
    const existingKey = Object.keys(all).find(k => all[k].telegramId === userId && all[k].active);
    
    if (existingKey) {
      const lic = all[existingKey];
      bot.sendMessage(chatId,
        `✅ *License Key របស់អ្នក:*\n\`${existingKey}\`\n\n` +
        `📅 ចេញ: ${formatDate(lic.createdAt)}\n` +
        `Status: ${lic.active ? '🟢 Active' : '🔴 Inactive'}`,
        { parse_mode: 'Markdown' });
      return;
    }

    if (OWNER_CHAT_ID) {
      bot.sendMessage(OWNER_CHAT_ID,
        `🆕 *License Request*\n\n` +
        `👤 User: ${username}\n` +
        `🆔 ID: ${userId}\n` +
        `📅 Time: ${formatDate(Date.now())}\n\n` +
        `✅ ចុចដើម្បី approve:\n` +
        `/approve ${userId}`,
        { parse_mode: 'Markdown' });
    }

    bot.sendMessage(chatId,
      `⏳ Request បានទទួលរួចហើយ!\n\n` +
      `🔄 Admin នឹង approve License Key ក្នុងពេលឆាប់ៗ\n` +
      `📬 Contact: @limsorn9`,
      { parse_mode: 'Markdown' });
  });

  bot.onText(/\/approve (.+)/, async (msg, match) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }

    const targetId = parseInt(match[1]);
    const newKey = generateLicenseKey();
    await saveLicense(newKey, {
      telegramId: targetId,
      createdAt: Date.now(),
      usedAt: null,
      active: true,
      hwid: null,
      note: `Approved for TG ID: ${targetId}`
    });

    bot.sendMessage(targetId,
      `🎉 *License Key របស់អ្នក:*\n\n` +
      `\`${newKey}\`\n\n` +
      `📋 Copy key ខាងលើ ហើយ paste ក្នុង *${APP_NAME}*\n` +
      `✅ ប្រើបានភ្លាមៗ — ឥតគិតថ្លៃ!\n\n` +
      `⚠️ License នេះ bind ទៅ device ១ ។`,
      { parse_mode: 'Markdown' });

    bot.sendMessage(chatId, `✅ License \`${newKey}\` បានផ្ញើដល់ User ${targetId}`, { parse_mode: 'Markdown' });
  });

  bot.onText(/\/genkey/, async (msg) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }
    const key = generateLicenseKey();
    await saveLicense(key, {
      telegramId: null,
      createdAt: Date.now(),
      usedAt: null,
      active: true,
      hwid: null,
      note: 'Manual generate by owner'
    });
    bot.sendMessage(chatId, `🔑 *License Key ថ្មី:*\n\`${key}\``, { parse_mode: 'Markdown' });
  });

  bot.onText(/\/listkeys/, async (msg) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.'); return;
    }
    const all = await getAllLicenses();
    const size = Object.keys(all).length;
    if (!size) { bot.sendMessage(chatId, '📭 មិនមាន License នៅឡើយ'); return; }
    let text = `📋 *License Keys (${size}):*\n\n`;
    for (const [k, v] of Object.entries(all)) {
      text += `\`${k}\` — ${v.active ? '🟢' : '🔴'} ${v.telegramId ? `TG:${v.telegramId}` : 'Free'}\n`;
    }
    bot.sendMessage(chatId, text, { parse_mode: 'Markdown' });
  });

  bot.onText(/\/revoke (.+)/, async (msg, match) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) { bot.sendMessage(chatId, '❌ Permission denied.'); return; }
    const key = match[1].trim();
    const lic = await getLicense(key);
    if (lic) {
      await updateLicense(key, { active: false });
      bot.sendMessage(chatId, `🔴 License \`${key}\` ត្រូវបាន revoke.`, { parse_mode: 'Markdown' });
    } else {
      bot.sendMessage(chatId, '❌ License Key រកមិនឃើញ');
    }
  });

  bot.onText(/\/check (.+)/, async (msg, match) => {
    const chatId = msg.chat.id;
    const key = match[1].trim();
    const lic = await getLicense(key);
    if (!lic) { bot.sendMessage(chatId, '❌ License Key មិនត្រឹមត្រូវ'); return; }
    bot.sendMessage(chatId,
      `🔑 Key: \`${key}\`\n` +
      `Status: ${lic.active ? '🟢 Active' : '🔴 Revoked'}\n` +
      `Created: ${formatDate(lic.createdAt)}\n` +
      `HWID: ${lic.hwid || 'មិនទាន់ activate'}\n` +
      `Note: ${lic.note || '-'}`,
      { parse_mode: 'Markdown' });
  });

  bot.on('polling_error', (err) => console.error('Bot polling error:', err.message));
} else {
  console.warn('⚠️  TELEGRAM_TOKEN or API_Bot not set — Telegram bot disabled');
}

// ============================================================
// REST API
// ============================================================
app.get('/', async (req, res) => {
  const all = await getAllLicenses();
  res.json({
    app: APP_NAME,
    status: 'running',
    db: db ? 'Firebase' : 'Memory',
    licenses: Object.keys(all).length
  });
});

app.post('/api/validate', async (req, res) => {
  const { key, hwid } = req.body;
  if (!key) return res.status(400).json({ valid: false, message: 'Key required' });

  const upperKey = key.trim().toUpperCase();
  const lic = await getLicense(upperKey);
  if (!lic) return res.json({ valid: false, message: 'License key not found' });
  if (!lic.active) return res.json({ valid: false, message: 'License has been revoked' });

  if (!lic.hwid && hwid) {
    await updateLicense(upperKey, { hwid, usedAt: Date.now() });
    lic.usedAt = Date.now();
  } else if (lic.hwid && hwid && lic.hwid !== hwid) {
    return res.json({ valid: false, message: 'License is bound to another device' });
  }

  res.json({ valid: true, message: 'License valid', key: upperKey, activatedAt: lic.usedAt });
});

app.get('/api/license/:key', async (req, res) => {
  const key = req.params.key.toUpperCase();
  const lic = await getLicense(key);
  if (!lic) return res.json({ valid: false });
  res.json({ valid: lic.active, hwid: lic.hwid ? '***' : null, createdAt: lic.createdAt });
});

// ============================================================
// START SERVER
// ============================================================
app.listen(PORT, () => {
  console.log(`🚀 License Server running on port ${PORT}`);
});
