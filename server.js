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
      admin.initializeApp({
        credential: admin.credential.cert(serviceAccount),
        databaseURL: process.env.FIREBASE_DB_URL
      });
      db = admin.database();
      console.log('✅ Firebase initialized');
    } catch (e) {
      console.error("❌ Firebase initialization failed (invalid JSON or credentials):", e.message);
    }
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
  const WEBHOOK_URL = process.env.WebHook_URL;
  if (WEBHOOK_URL) {
    bot = new TelegramBot(BOT_TOKEN);
    bot.setWebHook(`${WEBHOOK_URL}/bot${BOT_TOKEN}`);
    app.post(`/bot${BOT_TOKEN}`, (req, res) => {
      bot.processUpdate(req.body);
      res.sendStatus(200);
    });
    console.log('✅ Telegram bot started (Webhook mode)');
  } else {
    bot = new TelegramBot(BOT_TOKEN, { polling: true });
    console.log('✅ Telegram bot started (Polling mode)');
  }

  bot.onText(/\/start/, (msg) => {
    const chatId = msg.chat.id;
    bot.sendMessage(chatId, `👋 សួស្ដី! ខ្ញុំជា License Bot របស់ *${APP_NAME}*\n\n` +
      `🔑 *Commands:*\n` +
      `/getlicense — ទទួល License Key\n` +
      `/check \\[key\\] — ពិនិត្យ License\n\n` +
      `📬 ទាក់ទងទៅ Admin: @limsorn`,
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
      `📬 ទាក់ទងទៅ Admin: @limsorn`,
      { parse_mode: 'Markdown' });
  });

  bot.onText(/\/approve(?:\s+(.+))?/, async (msg, match) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }

    if (!match[1]) {
      bot.sendMessage(chatId, '⚠️ សូមវាយបញ្ចូល ID ពីក្រោយពាក្យ approve។\n👉 ឧទាហរណ៍៖ `/approve 240224709`', { parse_mode: 'Markdown' });
      return;
    }

    const targetId = parseInt(match[1]);
    const options = {
      reply_markup: JSON.stringify({
        inline_keyboard: [
          [{ text: '១ ខែ', callback_data: `appr_${targetId}_30` }, { text: '៣ ខែ', callback_data: `appr_${targetId}_90` }],
          [{ text: '៦ ខែ', callback_data: `appr_${targetId}_180` }, { text: '១ ឆ្នាំ', callback_data: `appr_${targetId}_365` }],
          [{ text: 'Lifetime (១០ ឆ្នាំ)', callback_data: `appr_${targetId}_3650` }]
        ]
      })
    };
    bot.sendMessage(chatId, `សូមជ្រើសរើសរយៈពេលសម្រាប់ User ${targetId}៖`, options);
  });

  bot.onText(/\/genkey/, async (msg) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }
    const options = {
      reply_markup: JSON.stringify({
        inline_keyboard: [
          [{ text: '១ ខែ', callback_data: `gen_30` }, { text: '៣ ខែ', callback_data: `gen_90` }],
          [{ text: '៦ ខែ', callback_data: `gen_180` }, { text: '១ ឆ្នាំ', callback_data: `gen_365` }],
          [{ text: 'Lifetime (១០ ឆ្នាំ)', callback_data: `gen_3650` }]
        ]
      })
    };
    bot.sendMessage(chatId, 'សូមជ្រើសរើសរយៈពេលសម្រាប់ License Key ថ្មី៖', options);
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
    
    let expiredStatus = '';
    if (lic.expiresAt) {
      if (Date.now() > lic.expiresAt) expiredStatus = ' (ផុតកំណត់)';
      else expiredStatus = `\nExpires: ${formatDate(lic.expiresAt)}`;
    }

    bot.sendMessage(chatId,
      `🔑 Key: \`${key}\`\n` +
      `Status: ${lic.active ? '🟢 Active' : '🔴 Revoked'}${expiredStatus}\n` +
      `Created: ${formatDate(lic.createdAt)}\n` +
      `HWID: ${lic.hwid || 'មិនទាន់ activate'}\n` +
      `Note: ${lic.note || '-'}`,
      { parse_mode: 'Markdown' });
  });

  bot.on('callback_query', async (callbackQuery) => {
    const msg = callbackQuery.message;
    const data = callbackQuery.data;
    const chatId = msg.chat.id;

    if (String(chatId) !== String(OWNER_CHAT_ID)) return;

    bot.answerCallbackQuery(callbackQuery.id);

    const matchAppr = data.match(/^appr_(\d+)_(\d+)$/);
    const matchGen = data.match(/^gen_(\d+)$/);

    if (matchAppr || matchGen) {
      let targetId = null;
      let days = 0;
      let isApprove = false;

      if (matchAppr) {
        targetId = parseInt(matchAppr[1]);
        days = parseInt(matchAppr[2]);
        isApprove = true;
      } else {
        days = parseInt(matchGen[1]);
      }

      const newKey = generateLicenseKey();
      const expiresAt = Date.now() + (days * 24 * 60 * 60 * 1000);
      const noteStr = isApprove ? `Approved for TG ID: ${targetId} (${days} days)` : `Manual generate (${days} days)`;

      try {
        await saveLicense(newKey, {
          telegramId: targetId,
          createdAt: Date.now(),
          expiresAt: expiresAt,
          usedAt: null,
          active: true,
          hwid: null,
          note: noteStr
        });

        bot.editMessageReplyMarkup({ inline_keyboard: [] }, { chat_id: chatId, message_id: msg.message_id }).catch(()=>{});

        if (isApprove) {
          try {
            await bot.sendMessage(targetId,
              `🎉 *License Key របស់អ្នក:*\n\n` +
              `\`${newKey}\`\n\n` +
              `⏳ ផុតកំណត់: ${formatDate(expiresAt)}\n` +
              `📋 Copy key ខាងលើ ហើយ paste ក្នុង *${APP_NAME}*\n` +
              `⚠️ License នេះ bind ទៅ device ១ ។`,
              { parse_mode: 'Markdown' });
            bot.sendMessage(chatId, `✅ License \`${newKey}\` (${days} ថ្ងៃ) បានផ្ញើដល់ User ${targetId}`, { parse_mode: 'Markdown' });
          } catch (e) {
            bot.sendMessage(chatId, `⚠️ មិនអាចផ្ញើសារទៅកាន់ User ${targetId} បានទេ (គេប្រហែលជា Block Bot)។ នេះជា License របស់គេ៖\n\`${newKey}\``, { parse_mode: 'Markdown' });
          }
        } else {
          bot.sendMessage(chatId, `🔑 *License Key ថ្មី (${days} ថ្ងៃ):*\n\`${newKey}\`\n⏳ ផុតកំណត់: ${formatDate(expiresAt)}`, { parse_mode: 'Markdown' });
        }
      } catch (error) {
        bot.sendMessage(chatId, `❌ Error Saving License: ${error.message}`);
      }
    }
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

app.post('/api/v1/dubber-bei-sach-voice-clone-pro/license/activate/?', async (req, res) => {
  const record = req.body.record || req.body;
  const key = record.license_key || req.body.key || req.body.license_key;
  const hwid = record.hardware_id || req.body.hwid || req.body.hardware_id;
  if (!key) return res.status(400).json({ success: false, message: 'Key required' });

  const upperKey = key.trim().toUpperCase();
  const lic = await getLicense(upperKey);
  if (!lic) return res.status(404).json({ success: false, message: 'License key not found' });
  if (!lic.active) return res.status(403).json({ success: false, message: 'License has been revoked' });
  if (lic.expiresAt && Date.now() > lic.expiresAt) return res.status(403).json({ success: false, message: 'License has expired' });

  if (!hwid) {
    return res.status(400).json({ success: false, message: 'Hardware ID required' });
  }

  if (!lic.hwid) {
    await updateLicense(upperKey, { hwid, usedAt: Date.now() });
    lic.usedAt = Date.now();
  } else if (lic.hwid !== hwid) {
    return res.status(403).json({ success: false, message: 'License is bound to another device' });
  }

  res.json({ success: true, status: 'active' });
});

app.post('/api/v1/dubber-bei-sach-voice-clone-pro/license/verify/?', async (req, res) => {
  const record = req.body.record || req.body;
  const key = record.license_key || req.body.key || req.body.license_key;
  const hwid = record.hardware_id || req.body.hwid || req.body.hardware_id;
  if (!key) return res.status(400).json({ success: false, message: 'Key required' });

  const upperKey = key.trim().toUpperCase();
  const lic = await getLicense(upperKey);
  if (!lic) return res.status(404).json({ success: false, message: 'License key not found' });
  if (!lic.active) return res.status(403).json({ success: false, message: 'License has been revoked' });
  if (lic.expiresAt && Date.now() > lic.expiresAt) return res.status(403).json({ success: false, message: 'License has expired' });

  if (!hwid) {
    return res.status(400).json({ success: false, message: 'Hardware ID required' });
  }

  if (lic.hwid && lic.hwid !== hwid) {
    return res.status(403).json({ success: false, message: 'License is bound to another device' });
  }

  res.json({ success: true, status: 'active' });
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
app.get('/api/v1/release/status', async (req, res) => {
  const latestVersion = process.env.LATEST_VERSION || '2.6.1';
  const asarUrl = process.env.ASAR_UPDATE_URL || ('https://github.com/limsorn9/Ai-Studio-Pro/releases/download/v' + latestVersion + '/app.asar');
  res.json({
    latestVersion,
    minimumSupportedVersion: '1.0.0',
    downloadPageUrl: 'https://github.com/limsorn9/Ai-Studio-Pro/releases',
    asarUrl,
    releaseNotes: 'Ai Studio Pro Version ' + latestVersion
  });
});

app.listen(PORT, () => {
  console.log(`🚀 License Server running on port ${PORT}`);
});
