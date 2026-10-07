const pngToIco = require('png-to-ico').default;
const rcedit = require('rcedit').rcedit;
const fs = require('fs');

async function changeIcon() {
    try {
        const pngPath = 'C:\\Users\\limso\\.gemini\\antigravity-ide\\brain\\e6bbb988-d718-481e-bbde-dced1d839250\\.user_uploaded\\media_1791151259205.png';
        const icoPath = 'app_logo.ico';
        const exePath = 'e:\\Ai Studio Pro\\app\\Ai Studio Pro.exe';
        
        console.log('Converting PNG to ICO...');
        const buf = await pngToIco(pngPath);
        fs.writeFileSync(icoPath, buf);
        
        console.log('Applying ICO to EXE...');
        await rcedit(exePath, {
            icon: icoPath
        });
        
        console.log('Successfully changed the executable icon!');
    } catch (err) {
        console.error('Failed:', err);
    }
}

changeIcon();
