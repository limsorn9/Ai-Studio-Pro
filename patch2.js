const fs = require('fs');
let code = fs.readFileSync('server.js', 'utf8');

// 1. /approve
code = code.replace(/bot\.onText\(\/\\\/approve[^]+?bot\.sendMessage\(chatId, `❌ Error Saving License.*?\}\n  \}\);\n/s, `bot.onText(/\\/approve(?:\\s+(.+))?/, async (msg, match) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }

    if (!match[1]) {
      bot.sendMessage(chatId, '⚠️ សូមវាយបញ្ចូល ID ពីក្រោយពាក្យ approve។\\n👉 ឧទាហរណ៍៖ \`/approve 240224709\`', { parse_mode: 'Markdown' });
      return;
    }

    const targetId = parseInt(match[1]);
    const options = {
      reply_markup: JSON.stringify({
        inline_keyboard: [
          [{ text: '១ ខែ', callback_data: \`appr_\${targetId}_30\` }, { text: '៣ ខែ', callback_data: \`appr_\${targetId}_90\` }],
          [{ text: '៦ ខែ', callback_data: \`appr_\${targetId}_180\` }, { text: '១ ឆ្នាំ', callback_data: \`appr_\${targetId}_365\` }],
          [{ text: 'Lifetime (១០ ឆ្នាំ)', callback_data: \`appr_\${targetId}_3650\` }]
        ]
      })
    };
    bot.sendMessage(chatId, \`សូមជ្រើសរើសរយៈពេលសម្រាប់ User \${targetId}៖\`, options);
  });\n`);

// 2. /genkey
code = code.replace(/bot\.onText\(\/\\\/genkey\/, async \(msg\) => \{[^]+?bot\.sendMessage\(chatId, `❌ Error Saving License.*?\}\n  \}\);\n/s, `bot.onText(/\\/genkey/, async (msg) => {
    const chatId = msg.chat.id;
    if (String(chatId) !== String(OWNER_CHAT_ID)) {
      bot.sendMessage(chatId, '❌ Permission denied.');
      return;
    }
    const options = {
      reply_markup: JSON.stringify({
        inline_keyboard: [
          [{ text: '១ ខែ', callback_data: \`gen_30\` }, { text: '៣ ខែ', callback_data: \`gen_90\` }],
          [{ text: '៦ ខែ', callback_data: \`gen_180\` }, { text: '១ ឆ្នាំ', callback_data: \`gen_365\` }],
          [{ text: 'Lifetime (១០ ឆ្នាំ)', callback_data: \`gen_3650\` }]
        ]
      })
    };
    bot.sendMessage(chatId, 'សូមជ្រើសរើសរយៈពេលសម្រាប់ License Key ថ្មី៖', options);
  });\n`);

// 3. /check
code = code.replace(/bot\.onText\(\/\\\/check \(\.\+\)\/, async \(msg, match\) => \{[^]+?\{ parse_mode: 'Markdown' \}\);\n  \}\);\n/s, `bot.onText(/\\/check (.+)/, async (msg, match) => {
    const chatId = msg.chat.id;
    const key = match[1].trim();
    const lic = await getLicense(key);
    if (!lic) { bot.sendMessage(chatId, '❌ License Key មិនត្រឹមត្រូវ'); return; }
    
    let expiredStatus = '';
    if (lic.expiresAt) {
      if (Date.now() > lic.expiresAt) expiredStatus = ' (ផុតកំណត់)';
      else expiredStatus = \`\\nExpires: \${formatDate(lic.expiresAt)}\`;
    }

    bot.sendMessage(chatId,
      \`🔑 Key: \\\`\${key}\\\`\\n\` +
      \`Status: \${lic.active ? '🟢 Active' : '🔴 Revoked'}\${expiredStatus}\\n\` +
      \`Created: \${formatDate(lic.createdAt)}\\n\` +
      \`HWID: \${lic.hwid || 'មិនទាន់ activate'}\\n\` +
      \`Note: \${lic.note || '-'}\`,
      { parse_mode: 'Markdown' });
  });\n`);

// 4. API verify & activate
code = code.replaceAll(`if (!lic.active) return res.status(403).json({ success: false, message: 'License has been revoked' });

  if (!hwid) {`, `if (!lic.active) return res.status(403).json({ success: false, message: 'License has been revoked' });
  if (lic.expiresAt && Date.now() > lic.expiresAt) return res.status(403).json({ success: false, message: 'License has expired' });

  if (!hwid) {`);

// 5. Callback query
code = code.replace(/bot\.on\('polling_error',/s, `bot.on('callback_query', async (callbackQuery) => {
    const msg = callbackQuery.message;
    const data = callbackQuery.data;
    const chatId = msg.chat.id;

    if (String(chatId) !== String(OWNER_CHAT_ID)) return;

    bot.answerCallbackQuery(callbackQuery.id);

    const matchAppr = data.match(/^appr_(\\d+)_(\\d+)$/);
    const matchGen = data.match(/^gen_(\\d+)$/);

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
      const noteStr = isApprove ? \`Approved for TG ID: \${targetId} (\${days} days)\` : \`Manual generate (\${days} days)\`;

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

        if (isApprove) {
          bot.sendMessage(targetId,
            \`🎉 *License Key របស់អ្នក:*\\n\\n\` +
            \`\\\`\${newKey}\\\`\\n\\n\` +
            \`⏳ ផុតកំណត់: \${formatDate(expiresAt)}\\n\` +
            \`📋 Copy key ខាងលើ ហើយ paste ក្នុង *\${APP_NAME}*\\n\` +
            \`⚠️ License នេះ bind ទៅ device ១ ។\`,
            { parse_mode: 'Markdown' });
          bot.sendMessage(chatId, \`✅ License \\\`\${newKey}\\\` (\${days} ថ្ងៃ) បានផ្ញើដល់ User \${targetId}\`, { parse_mode: 'Markdown' });
        } else {
          bot.sendMessage(chatId, \`🔑 *License Key ថ្មី (\${days} ថ្ងៃ):*\\n\\\`\${newKey}\\\`\\n⏳ ផុតកំណត់: \${formatDate(expiresAt)}\`, { parse_mode: 'Markdown' });
        }
        
        bot.editMessageReplyMarkup({ inline_keyboard: [] }, { chat_id: chatId, message_id: msg.message_id });
      } catch (error) {
        bot.sendMessage(chatId, \`❌ Error Saving License: \${error.message}\`);
      }
    }
  });

  bot.on('polling_error',`);

fs.writeFileSync('server.js', code);
console.log('patched');
