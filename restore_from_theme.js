const fs = require('fs');
const path = require('path');

const srcDir = 'C:\\Users\\limso\\Downloads\\Modern Khmer Phoenix Theme';
const destDir = 'D:\\Ai Studio Pro\\app_source\\out\\renderer\\assets';

const files = fs.readdirSync(srcDir);
let count = 0;

files.forEach(f => {
    // Match pattern: originalname.png_timestamp.jpg
    const match = f.match(/^(.+\.png)_\d{14}.*\.jpg$/);
    if (match) {
        const originalName = match[1]; // e.g. angry-shiba-mascot-B4DN_etv.png
        const srcFile = path.join(srcDir, f);
        const destFile = path.join(destDir, originalName);

        // Delete existing (damaged) file if exists
        if (fs.existsSync(destFile)) {
            fs.unlinkSync(destFile);
        }

        // Copy new file with original PNG name
        fs.copyFileSync(srcFile, destFile);
        count++;
        console.log(`Replaced: ${originalName}`);
    }
});

console.log(`\nDone! Replaced ${count} files.`);
