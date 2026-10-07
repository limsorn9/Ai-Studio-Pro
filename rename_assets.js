const fs = require('fs');
const path = require('path');

const dir = 'd:\\Ai Studio Pro\\app_source\\out\\renderer\\assets';
const files = fs.readdirSync(dir);

let renamedCount = 0;

files.forEach(f => {
    // Match files ending with something like .png_20261007083838.jpg
    const match = f.match(/^(.+\.png)_\d{14}.*\.jpg$/);
    if (match) {
        const oldName = match[1];
        const newFile = path.join(dir, f);
        const oldFile = path.join(dir, oldName);
        
        // Delete the original .png
        if (fs.existsSync(oldFile)) {
            fs.unlinkSync(oldFile);
        }
        
        // Rename the new .jpg to the .png filename
        fs.renameSync(newFile, oldFile);
        renamedCount++;
        console.log(`Renamed ${f} -> ${oldName}`);
    }
});

console.log(`Successfully processed ${renamedCount} files.`);
