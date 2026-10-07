const fs = require('fs');

const indexPath = 'E:\\Ai Studio Pro\\app_source\\out\\main\\index.js';
let content = fs.readFileSync(indexPath, 'utf8');

// Replace Ww(e)
content = content.replace(/function Ww\(e\)\{.+?throw new Be.+?\}/, "function Ww(e){return e;}");

// Replace Kw(e)
content = content.replace(/async function Kw\(e\)\{.+?return\{schema:1,files:r.+?\}\}/s, "async function Kw(e){return {schema:1,files:[],builtAt:'',uvVersion:gr,sourceCommit:yt,modelRevision:Yn,torch:''};}");

fs.writeFileSync(indexPath, content, 'utf8');
console.log("Patched index.js!");
