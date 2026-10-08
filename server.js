const express = require('express');
const TelegramBot = require('node-telegram-bot-api');
const crypto = require('crypto');
const cors = require('cors');
const admin = require('firebase-admin');

const app = express();
app.use(express.json());
app.use(cors());

// ============================================================
// CONFIG & APP REGISTRY (MULTI-APP ARCHITECTURE)
// ============================================================
const BOT_TOKEN = process.env.TELEGRAM_TOKEN || process.env.API_Bot;
const OWNER_CHAT_ID = process.env.OWNER_CHAT_ID || '240224709'; // @limsorn
const PORT = process.env.PORT || 3000;

// កាតាឡុកកម្មវិធីទាំងអស់ដែល Bot នេះគ្រប់គ្រង
const APPS = {
  'aistudio': {
    id: 'aistudio',
    name: 'Ai Studio Pro (បកប្រែសម្លេង)',
    icon: '🎙️',
    prefix: 'AISTUDIO',
    route: 'dubber-bei-sach-voice-clone-pro'
  },
  'suno': {
    id: 'suno',
    name: 'PlengBox Suno AI (តែងទំនុកច្រៀង)',
    icon: '🎵',
    prefix: 'SUNO',
    route: 'bisach-suno-ai-lyric-writer'
  }
};

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
function detectAppId(key) {
  if (!key) return 'aistudio';
  const upper = key.toUpperCase();
  for (const [id, appInfo] of Object.entries(APPS)) {
    if (upper.startsWith(appInfo.prefix + '-')) return id;
  }
  return 'aistudio'; // Default legacy backward compatibility
}

function generateLicenseKey(appId = 'aistudio') {
  const prefix = APPS[appId]?.prefix || 'KEY';
  const part = () => crypto.randomBytes(3).toString('hex').toUpperCase();
  return `${prefix}-${part()}-${part()}-${part()}`;
}

function formatDate(ms) {
  if (!ms) return '-';
  return new Date(ms).toLocaleString('km-KH', { timeZone: 'Asia/Phnom_Penh' });
}

// ============================================================
// TELEGRAM BOT
// ============================================================
let bot;
if (BOT_TOKEN) {
  const rawWebhook = process.env.WebHook_URL || process.env.RENDER_EXTERNAL_URL || 'https://ai-studio-pro-capt.onrender.com';
  const cleanUrl = rawWebhook ? rawWebhook.trim().replace(/\/+$/, '') : '';

  if (cleanUrl && !process.env.USE_POLLING) {
    bot = new TelegramBot(BOT_TOKEN);
    const webhookPath = `/bot${BOT_TOKEN}`;
    const fullWebhookUrl = `${cleanUrl}${webhookPath}`;

    app.post(webhookPath, (req, res) => {
      try {
        bot.processUpdate(req.body);
      } catch (err) {
        console.error('Error processing telegram update:', err.message);
      }
      res.sendStatus(200);
    });

    bot.setWebHook(fullWebhookUrl)
      .then(() => console.log(`✅ Telegram webhook successfully set to: ${fullWebhookUrl}`))
      .catch((err) => {
        console.error(`❌ Telegram setWebHook failed (${err.message}). Falling back to polling...`);
        bot.startPolling();
      });

    console.log(`✅ Telegram bot initialized (Webhook mode -> ${fullWebhookUrl})`);
  } else {
    bot = new TelegramBot(BOT_TOKEN, { polling: true });
    console.log('✅ Telegram bot started (Polling mode)');
  }

  // /start
  bot.onText(/\/start/, (msg) => {
    const chatId = msg.chat.id;
    const appListText = Object.values(APPS).map(a => `${a.icon} *${a.name}*`).join('\n');
    bot.sendMessage(chatId,
      `👋 សួស្ដី! ខ្ញុំជា Central License Bot គ្រប់គ្រងកម្មវិធី៖\n\n` +
      `${appListText}\n\n` +
      `🔑 *Commands:*\n` +
      `/getlicense — ស្នើសុំ License Key\n` +
      `/check \\[key\\] — ពិនិត្យ License\n\n` +
      `📬 ទំនាក់ទំនង Admin: @limsorn`,
      { parse_mode: 'Markdown' });
  });

  // /getlicense
  bot.onText(/\/getlicense/, async (msg) => {
    const chatId = msg.chat.id;
    const keyboard = Object.values(APPS).map(a => [
      { text: `${a.icon} ${a.name}`, callback_data: `req_${a.id}` }
    ]);

    bot.sendMessage(chatId, '📱 *សូមជ្រើសរើសកម្មវិធីដែលអ្នកចង់ស្នើសុំ License:*', {
      parse_mode: 'Markdown',
      reply_markup: JSON.stringify({ inline_keyboard: keyboard })
    });
  });

  // /approve [userId] [appId]
  bot.onText(/\/approve(?:\s+(\d+))?(?:\s+([a-zA-Z0-9_-]+))?/, async (msg, match) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }

    const targetId = match[1] ? parseInt(match[1]) : null;
    let appId = match[2] ? match[2].toLowerCase() : null;

    if (!targetId) {
      bot.sendMessage(chatId,
        '⚠️ សូមវាយបញ្ចូល ID ពីក្រោយពាក្យ approve។\n👉 ឧទាហរណ៍៖ `/approve 240224709 aistudio` ឬ `/approve 240224709 suno`',
        { parse_mode: 'Markdown' });
      return;
    }

    if (!appId || !APPS[appId]) {
      // Prompt admin to select app for this user
      const keyboard = Object.values(APPS).map(a => [
        { text: `${a.icon} ${a.name}`, callback_data: `selappr_${targetId}_${a.id}` }
      ]);
      bot.sendMessage(chatId, `សូមជ្រើសរើសកម្មវិធីសម្រាប់ User ${targetId}៖`, {
        reply_markup: JSON.stringify({ inline_keyboard: keyboard })
      });
      return;
    }

    sendApproveDurationMenu(chatId, targetId, appId);
  });

  function sendApproveDurationMenu(chatId, targetId, appId, messageId = null) {
    const appInfo = APPS[appId] || { name: appId, icon: '📱' };
    const options = {
      reply_markup: JSON.stringify({
        inline_keyboard: [
          [{ text: '១ ខែ', callback_data: `appr_${targetId}_${appId}_30` }, { text: '៣ ខែ', callback_data: `appr_${targetId}_${appId}_90` }],
          [{ text: '៦ ខែ', callback_data: `appr_${targetId}_${appId}_180` }, { text: '១ ឆ្នាំ', callback_data: `appr_${targetId}_${appId}_365` }],
          [{ text: 'Lifetime (១០ ឆ្នាំ)', callback_data: `appr_${targetId}_${appId}_3650` }]
        ]
      })
    };
    const text = `សូមជ្រើសរើសរយៈពេលសម្រាប់ User ${targetId} លើកម្មវិធី ${appInfo.icon} *${appInfo.name}*៖`;
    if (messageId) {
      bot.editMessageText(text, { chat_id: chatId, message_id: messageId, parse_mode: 'Markdown', ...options }).catch(() => {});
    } else {
      bot.sendMessage(chatId, text, { parse_mode: 'Markdown', ...options });
    }
  }

  // /genkey
  bot.onText(/\/genkey/, async (msg) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }

    const keyboard = Object.values(APPS).map(a => [
      { text: `${a.icon} ${a.name}`, callback_data: `genapp_${a.id}` }
    ]);

    bot.sendMessage(chatId, '📱 *សូមជ្រើសរើសកម្មវិធីដើម្បីបង្កើត License Key ថ្មី:*', {
      parse_mode: 'Markdown',
      reply_markup: JSON.stringify({ inline_keyboard: keyboard })
    });
  });

  // /listkeys
  bot.onText(/\/listkeys/, async (msg) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }
    const all = await getAllLicenses();
    const size = Object.keys(all).length;
    if (!size) {
      bot.sendMessage(chatId, '📭 មិនមាន License នៅឡើយ');
      return;
    }
    let text = `📋 *License Keys សរុប (${size}):*\n\n`;
    for (const [k, v] of Object.entries(all)) {
      const appId = v.appId || detectAppId(k);
      const icon = APPS[appId]?.icon || '📱';
      text += `${icon} \`${k}\` — ${v.active ? '🟢' : '🔴'} ${v.telegramId ? `TG:${v.telegramId}` : 'Free'}\n`;
    }
    bot.sendMessage(chatId, text, { parse_mode: 'Markdown' });
  });

  // /revoke [key]
  bot.onText(/\/revoke (.+)/, async (msg, match) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }
    const key = match[1].trim().toUpperCase();
    const lic = await getLicense(key);
    if (lic) {
      await updateLicense(key, { active: false });
      bot.sendMessage(chatId, `🔴 License \`${key}\` ត្រូវបាន revoke.`, { parse_mode: 'Markdown' });
    } else {
      bot.sendMessage(chatId, '❌ License Key រកមិនឃើញ');
    }
  });

  // /check [key]
  bot.onText(/\/check (.+)/, async (msg, match) => {
    const chatId = msg.chat.id;
    const key = match[1].trim().toUpperCase();
    const lic = await getLicense(key);
    if (!lic) {
      bot.sendMessage(chatId, '❌ License Key មិនត្រឹមត្រូវ');
      return;
    }

    const appId = lic.appId || detectAppId(key);
    const appInfo = APPS[appId] || { name: appId, icon: '📱' };

    let expiredStatus = '';
    if (lic.expiresAt) {
      if (Date.now() > lic.expiresAt) expiredStatus = ' (ផុតកំណត់)';
      else expiredStatus = `\nExpires: ${formatDate(lic.expiresAt)}`;
    }

    bot.sendMessage(chatId,
      `🔑 Key: \`${key}\`\n` +
      `📱 App: ${appInfo.icon} *${appInfo.name}*\n` +
      `Status: ${lic.active ? '🟢 Active' : '🔴 Revoked'}${expiredStatus}\n` +
      `Created: ${formatDate(lic.createdAt)}\n` +
      `HWID: ${lic.hwid || 'មិនទាន់ activate'}\n` +
      `Note: ${lic.note || '-'}`,
      { parse_mode: 'Markdown' });
  });

  // CALLBACK QUERIES
  bot.on('callback_query', async (callbackQuery) => {
    const msg = callbackQuery.message;
    const data = callbackQuery.data;
    const chatId = msg.chat.id;
    const fromUser = callbackQuery.from;

    bot.answerCallbackQuery(callbackQuery.id);

    // 1. User Requests License for a specific App (req_appId)
    if (data.startsWith('req_')) {
      const appId = data.replace('req_', '');
      const appInfo = APPS[appId] || { name: appId, icon: '📱' };
      const userId = fromUser.id;
      const username = fromUser.username ? `@${fromUser.username}` : fromUser.first_name;

      const all = await getAllLicenses();
      const existingKey = Object.keys(all).find(k => {
        const item = all[k];
        const itemAppId = item.appId || detectAppId(k);
        return item.telegramId === userId && item.active && itemAppId === appId;
      });

      if (existingKey) {
        const lic = all[existingKey];
        bot.sendMessage(chatId,
          `✅ *License Key សម្រាប់ ${appInfo.icon} ${appInfo.name} របស់អ្នក:*\n\`${existingKey}\`\n\n` +
          `📅 ចេញ: ${formatDate(lic.createdAt)}\n` +
          `Status: ${lic.active ? '🟢 Active' : '🔴 Inactive'}`,
          { parse_mode: 'Markdown' });
        return;
      }

      if (OWNER_CHAT_ID) {
        bot.sendMessage(OWNER_CHAT_ID,
          `🆕 *License Request*\n\n` +
          `📱 App: ${appInfo.icon} *${appInfo.name}*\n` +
          `👤 User: ${username}\n` +
          `🆔 ID: \`${userId}\`\n` +
          `📅 Time: ${formatDate(Date.now())}\n\n` +
          `✅ ចុចដើម្បី approve:\n` +
          `/approve ${userId} ${appId}`,
          { parse_mode: 'Markdown' });
      }

      bot.sendMessage(chatId,
        `⏳ Request សម្រាប់ ${appInfo.icon} *${appInfo.name}* បានទទួលរួចហើយ!\n\n` +
        `🔄 Admin នឹង approve License Key ក្នុងពេលឆាប់ៗ\n` +
        `📬 ទំនាក់ទំនង Admin: @limsorn`,
        { parse_mode: 'Markdown' });
      return;
    }

    // Must be Admin for remainder of actions
    if (String(chatId) !== String(OWNER_CHAT_ID)) return;

    // 2. Admin selecting App for /approve (selappr_userId_appId)
    if (data.startsWith('selappr_')) {
      const parts = data.split('_');
      const targetId = parseInt(parts[1]);
      const appId = parts[2];
      sendApproveDurationMenu(chatId, targetId, appId, msg.message_id);
      return;
    }

    // 3. Admin selecting App for /genkey (genapp_appId)
    if (data.startsWith('genapp_')) {
      const appId = data.replace('genapp_', '');
      const appInfo = APPS[appId] || { name: appId, icon: '📱' };
      const options = {
        chat_id: chatId,
        message_id: msg.message_id,
        parse_mode: 'Markdown',
        reply_markup: JSON.stringify({
          inline_keyboard: [
            [{ text: '១ ខែ', callback_data: `gen_${appId}_30` }, { text: '៣ ខែ', callback_data: `gen_${appId}_90` }],
            [{ text: '៦ ខែ', callback_data: `gen_${appId}_180` }, { text: '១ ឆ្នាំ', callback_data: `gen_${appId}_365` }],
            [{ text: 'Lifetime (១០ ឆ្នាំ)', callback_data: `gen_${appId}_3650` }]
          ]
        })
      };
      bot.editMessageText(`សូមជ្រើសរើសរយៈពេលសម្រាប់ ${appInfo.icon} *${appInfo.name}*៖`, options).catch(() => {});
      return;
    }

    // 4. Admin Approving or Generating Key with Duration
    const matchAppr = data.match(/^appr_(\d+)_([a-zA-Z0-9_-]+)_(\d+)$/);
    const matchGen = data.match(/^gen_([a-zA-Z0-9_-]+)_(\d+)$/);

    if (matchAppr || matchGen) {
      let targetId = null;
      let appId = 'aistudio';
      let days = 0;
      let isApprove = false;

      if (matchAppr) {
        targetId = parseInt(matchAppr[1]);
        appId = matchAppr[2];
        days = parseInt(matchAppr[3]);
        isApprove = true;
      } else {
        appId = matchGen[1];
        days = parseInt(matchGen[2]);
      }

      const appInfo = APPS[appId] || { name: appId, icon: '📱' };
      const newKey = generateLicenseKey(appId);
      const expiresAt = Date.now() + (days * 24 * 60 * 60 * 1000);
      const noteStr = isApprove ? `Approved for TG ID: ${targetId} (${days} days)` : `Manual generate (${days} days)`;

      try {
        await saveLicense(newKey, {
          appId: appId,
          appName: appInfo.name,
          telegramId: targetId,
          createdAt: Date.now(),
          expiresAt: expiresAt,
          usedAt: null,
          active: true,
          hwid: null,
          note: noteStr
        });

        bot.editMessageReplyMarkup({ inline_keyboard: [] }, { chat_id: chatId, message_id: msg.message_id }).catch(() => {});

        if (isApprove) {
          try {
            await bot.sendMessage(targetId,
              `🎉 *License Key សម្រាប់ ${appInfo.icon} ${appInfo.name} របស់អ្នក:*\n\n` +
              `\`${newKey}\`\n\n` +
              `⏳ ផុតកំណត់: ${formatDate(expiresAt)}\n` +
              `📋 Copy key ខាងលើ ហើយ paste ក្នុងកម្មវិធី *${appInfo.name}*\n` +
              `⚠️ License នេះ bind ទៅ device ១ ប៉ុណ្ណោះ។`,
              { parse_mode: 'Markdown' });
            bot.sendMessage(chatId, `✅ License \`${newKey}\` (${days} ថ្ងៃ) សម្រាប់ ${appInfo.icon} ${appInfo.name} បានផ្ញើដល់ User ${targetId}`, { parse_mode: 'Markdown' });
          } catch (e) {
            bot.sendMessage(chatId, `⚠️ មិនអាចផ្ញើសារទៅកាន់ User ${targetId} បានទេ (User ប្រហែលជា Block Bot)។ នេះជា License របស់គេ៖\n\`${newKey}\``, { parse_mode: 'Markdown' });
          }
        } else {
          bot.sendMessage(chatId,
            `🔑 *License Key ថ្មី (${days} ថ្ងៃ):*\n` +
            `📱 App: ${appInfo.icon} *${appInfo.name}*\n` +
            `Key: \`${newKey}\`\n` +
            `⏳ ផុតកំណត់: ${formatDate(expiresAt)}`,
            { parse_mode: 'Markdown' });
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
// REST API (UNIVERSAL MULTI-APP ENGINE)
// ============================================================
app.get('/', async (req, res) => {
  const all = await getAllLicenses();
  res.json({
    name: 'Unified Multi-App License Server',
    status: 'running',
    supportedApps: Object.values(APPS).map(a => ({ id: a.id, name: a.name, prefix: a.prefix })),
    db: db ? 'Firebase' : 'Memory',
    licensesCount: Object.keys(all).length
  });
});

// Common Activation Handler
async function handleActivation(req, res, targetAppId) {
  const record = req.body.record || req.body;
  const key = record.license_key || req.body.key || req.body.license_key;
  const hwid = record.hardware_id || req.body.hwid || req.body.hardware_id;
  if (!key) return res.status(400).json({ success: false, message: 'Key required' });

  const upperKey = key.trim().toUpperCase();
  const lic = await getLicense(upperKey);
  if (!lic) return res.status(404).json({ success: false, message: 'License key not found' });
  if (!lic.active) return res.status(403).json({ success: false, message: 'License has been revoked' });
  if (lic.expiresAt && Date.now() > lic.expiresAt) return res.status(403).json({ success: false, message: 'License has expired' });

  // Cross-app protection
  const keyAppId = lic.appId || detectAppId(upperKey);
  if (keyAppId !== targetAppId) {
    const targetAppName = APPS[targetAppId]?.name || targetAppId;
    const originAppName = APPS[keyAppId]?.name || keyAppId;
    return res.status(403).json({
      success: false,
      message: `License key នេះសម្រាប់កម្មវិធី "${originAppName}" មិនអាចប្រើលើកម្មវិធី "${targetAppName}" បានទេ`
    });
  }

  if (!hwid) {
    return res.status(400).json({ success: false, message: 'Hardware ID required' });
  }

  if (!lic.hwid) {
    await updateLicense(upperKey, { hwid, usedAt: Date.now() });
    lic.usedAt = Date.now();
    lic.hwid = hwid;
  } else if (lic.hwid !== hwid) {
    return res.status(403).json({
      success: false,
      error: 'device_already_bound',
      message: 'License is bound to another device'
    });
  }

  res.json({
    success: true,
    status: 'active',
    app: APPS[targetAppId]?.name,
    expiresAt: lic.expiresAt ? new Date(lic.expiresAt).toISOString() : null,
    serverTime: new Date().toISOString()
  });
}

// Common Verification Handler
async function handleVerification(req, res, targetAppId) {
  const record = req.body.record || req.body;
  const key = record.license_key || req.body.key || req.body.license_key;
  const hwid = record.hardware_id || req.body.hwid || req.body.hardware_id;
  if (!key) return res.status(400).json({ success: false, message: 'Key required' });

  const upperKey = key.trim().toUpperCase();
  const lic = await getLicense(upperKey);
  if (!lic) return res.status(404).json({ success: false, message: 'License key not found' });
  if (!lic.active) return res.status(403).json({ success: false, message: 'License has been revoked' });
  if (lic.expiresAt && Date.now() > lic.expiresAt) return res.status(403).json({ success: false, message: 'License has expired' });

  // Cross-app protection
  const keyAppId = lic.appId || detectAppId(upperKey);
  if (keyAppId !== targetAppId) {
    return res.status(403).json({ success: false, message: 'License key is for another application' });
  }

  if (!hwid) {
    return res.status(400).json({ success: false, message: 'Hardware ID required' });
  }

  if (lic.hwid && lic.hwid !== hwid) {
    return res.status(403).json({
      success: false,
      error: 'device_already_bound',
      message: 'License is bound to another device'
    });
  }

  res.json({
    success: true,
    status: 'active',
    app: APPS[targetAppId]?.name,
    expiresAt: lic.expiresAt ? new Date(lic.expiresAt).toISOString() : null,
    serverTime: new Date().toISOString()
  });
}

// 1. Endpoints សម្រាប់ Ai Studio Pro
app.post('/api/v1/dubber-bei-sach-voice-clone-pro/license/activate/?', (req, res) => handleActivation(req, res, 'aistudio'));
app.post('/api/v1/dubber-bei-sach-voice-clone-pro/license/verify/?', (req, res) => handleVerification(req, res, 'aistudio'));

// 2. Endpoints សម្រាប់ PlengBox Suno AI Lyric Writer
app.post('/api/v1/bisach-suno-ai-lyric-writer/license/activate/?', (req, res) => handleActivation(req, res, 'suno'));
app.post('/api/v1/bisach-suno-ai-lyric-writer/license/verify/?', (req, res) => handleVerification(req, res, 'suno'));

// Simple Key Inspection
app.get('/api/license/:key', async (req, res) => {
  const key = req.params.key.toUpperCase();
  const lic = await getLicense(key);
  if (!lic) return res.json({ valid: false });
  const appId = lic.appId || detectAppId(key);
  res.json({
    valid: lic.active,
    appId: appId,
    appName: APPS[appId]?.name || appId,
    hwid: lic.hwid ? '***' : null,
    createdAt: lic.createdAt,
    expiresAt: lic.expiresAt
  });
});

// Auto-updater metadata for Ai Studio Pro
app.get('/api/v1/release/status', async (req, res) => {
  const latestVersion = process.env.LATEST_VERSION || '2.7.0';
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
  console.log(`🚀 Unified Multi-App License Server running on port ${PORT}`);
  console.log(`📦 Registered Apps: ${Object.keys(APPS).join(', ')}`);

  // Keep-alive self-ping for Render free tier (prevents sleep during active usage)
  const KEEP_ALIVE_URL = process.env.RENDER_EXTERNAL_URL || 'https://ai-studio-pro-capt.onrender.com';
  if (KEEP_ALIVE_URL) {
    setInterval(() => {
      fetch(`${KEEP_ALIVE_URL.replace(/\/+$/, '')}/`)
        .catch(() => {});
    }, 10 * 60 * 1000);
    console.log(`⏱️ Keep-alive ping active for: ${KEEP_ALIVE_URL}`);
  }
});
