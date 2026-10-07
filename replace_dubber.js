const fs = require('fs');
const file = 'e:\\Ai Studio Pro\\app_source\\out\\renderer\\assets\\index-L22pqO0q.js';
let content = fs.readFileSync(file, 'utf8');

content = content.replace(/"Dubber "/g, '"កំពូលអ្នកបកប្រែ "');
content = content.replace(/បីសាច/g, 'Pro');

fs.writeFileSync(file, content, 'utf8');
console.log('Replaced successfully!');
