const express = require('express');
const TelegramBot = require('node-telegram-bot-api');
const crypto = require('crypto');
const cors = require('cors');

const app = express();
app.use(express.json());
app.use(cors());

// ============================================================
// CONFIG
// ============================================================
const BOT_TOKEN = process.env.API_Bot;
const OWNER_CHAT_ID = process.env.OWNER_CHAT_ID; // ដាក់ chat ID របស់អ្នកក្នុង Render env
const PORT = process.env.PORT || 3000;
const APP_NAME = 'Dubber Pro / AI Studio Pro';

// ============================================================
// LICENSE STORE (in-memory — upgrade to DB later)
// ============================================================
const licenses = new Map(); // key → { hwid, createdAt, usedAt, active, note }

// ============================================================
// HELPERS
// ============================================================
function generateLicenseKey() {
  const part = () => crypto.randomBytes(3).toString('hex').toUpperCase();
  return `DUBPRO-${part()}-${part()}-${part()}`;
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

  // /start
  bot.onText(/\/start/, (msg) => {
    const chatId = msg.chat.id;
    bot.sendMessage(chatId, `👋 សួស្ដី! ខ្ញុំជា License Bot របស់ *${APP_NAME}*\n\n` +
      `🔑 *Commands:*\n` +
      `/getlicense — ទទួល License Key\n` +
      `/check \\[key\\] — ពិនិត្យ License\n\n` +
      `📬 Contact: @limsorn9`,
      { parse_mode: 'Markdown' });
  });

  // /getlicense — user request license
  bot.onText(/\/getlicense/, (msg) => {
    const chatId = msg.chat.id;
    const username = msg.from.username ? `@${msg.from.username}` : msg.from.first_name;
    const userId = msg.from.id;

    // Check if already has license
    const existing = [...licenses.entries()].find(([k, v]) => v.telegramId === userId && v.active);
    if (existing) {
      bot.sendMessage(chatId,
        `✅ *License Key របស់អ្នក:*\n\`${existing[0]}\`\n\n` +
        `📅 ចេញ: ${formatDate(existing[1].createdAt)}\n` +
        `Status: ${existing[1].active ? '🟢 Active' : '🔴 Inactive'}`,
        { parse_mode: 'Markdown' });
      return;
    }

    // Notify owner
    if (OWNER_CHAT_ID && bot) {
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

  // /approve [userId] — owner approves license
  bot.onText(/\/approve (.+)/, (msg, match) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }

    const targetId = parseInt(match[1]);
    const newKey = generateLicenseKey();
    licenses.set(newKey, {
      telegramId: targetId,
      createdAt: Date.now(),
      usedAt: null,
      active: true,
      hwid: null,
      note: `Approved for TG ID: ${targetId}`
    });

    // Send key to user
    bot.sendMessage(targetId,
      `🎉 *License Key របស់អ្នក:*\n\n` +
      `\`${newKey}\`\n\n` +
      `📋 Copy key ខាងលើ ហើយ paste ក្នុង *${APP_NAME}*\n` +
      `✅ ប្រើបានភ្លាមៗ — ឥតគិតថ្លៃ!\n\n` +
      `⚠️ License នេះ bind ទៅ device ១ ។`,
      { parse_mode: 'Markdown' });

    bot.sendMessage(chatId, `✅ License \`${newKey}\` បានផ្ញើដល់ User ${targetId}`, { parse_mode: 'Markdown' });
  });

  // /genkey — owner generate key directly
  bot.onText(/\/genkey/, (msg) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }
    const key = generateLicenseKey();
    licenses.set(key, {
      telegramId: null,
      createdAt: Date.now(),
      usedAt: null,
      active: true,
      hwid: null,
      note: 'Manual generate by owner'
    });
    bot.sendMessage(chatId, `🔑 *License Key ថ្មី:*\n\`${key}\``, { parse_mode: 'Markdown' });
  });

  // /listkeys — owner see all licenses
  bot.onText(/\/listkeys/, (msg) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.'); return;
    }
    if (!licenses.size) { bot.sendMessage(chatId, '📭 មិនមាន License នៅឡើយ'); return; }
    let text = `📋 *License Keys (${licenses.size}):*\n\n`;
    for (const [k, v] of licenses) {
      text += `\`${k}\` — ${v.active ? '🟢' : '🔴'} ${v.telegramId ? `TG:${v.telegramId}` : 'Free'}\n`;
    }
    bot.sendMessage(chatId, text, { parse_mode: 'Markdown' });
  });

  // /revoke [key] — revoke a license
  bot.onText(/\/revoke (.+)/, (msg, match) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) { bot.sendMessage(chatId, '❌ Permission denied.'); return; }
    const key = match[1].trim();
    if (licenses.has(key)) {
      licenses.get(key).active = false;
      bot.sendMessage(chatId, `🔴 License \`${key}\` ត្រូវបាន revoke.`, { parse_mode: 'Markdown' });
    } else {
      bot.sendMessage(chatId, '❌ License Key រកមិនឃើញ');
    }
  });

  // /check [key] — check license status
  bot.onText(/\/check (.+)/, (msg, match) => {
    const chatId = msg.chat.id;
    const key = match[1].trim();
    const lic = licenses.get(key);
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
  console.warn('⚠️  API_Bot not set — Telegram bot disabled');
}

// ============================================================
// REST API — for Electron app to validate license
// ============================================================

// Health check
app.get('/', (req, res) => {
  res.json({
    app: APP_NAME,
    status: 'running',
    version: '1.0.0',
    licenses: licenses.size
  });
});

// Validate license key
app.post('/api/validate', (req, res) => {
  const { key, hwid } = req.body;
  if (!key) return res.status(400).json({ valid: false, message: 'Key required' });

  const lic = licenses.get(key.trim().toUpperCase());
  if (!lic) return res.json({ valid: false, message: 'License key not found' });
  if (!lic.active) return res.json({ valid: false, message: 'License has been revoked' });

  // Bind HWID on first use
  if (!lic.hwid && hwid) {
    lic.hwid = hwid;
    lic.usedAt = Date.now();
  } else if (lic.hwid && hwid && lic.hwid !== hwid) {
    return res.json({ valid: false, message: 'License is bound to another device' });
  }

  res.json({ valid: true, message: 'License valid', key, activatedAt: lic.usedAt });
});

// Check license status (GET)
app.get('/api/license/:key', (req, res) => {
  const key = req.params.key.toUpperCase();
  const lic = licenses.get(key);
  if (!lic) return res.json({ valid: false });
  res.json({ valid: lic.active, hwid: lic.hwid ? '***' : null, createdAt: lic.createdAt });
});

// ============================================================
// START SERVER
// ============================================================
app.listen(PORT, () => {
  console.log(`🚀 License Server running on port ${PORT}`);
  console.log(`🔗 URL: https://ai-studio-pro-capt.onrender.com`);
  if (bot) console.log(`🤖 Telegram Bot: @AiStudioPro2_bot`);
});
