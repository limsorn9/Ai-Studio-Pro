const pngToIco = require('png-to-ico').default;
const rcedit = require('rcedit').rcedit;
const fs = require('fs');
const path = require('path');

async function changeIcon() {
    try {
        const pngPath = 'D:\\Ai Studio Pro\\phoenix.png';
        const icoPath = 'phoenix_logo.ico';
        const exePath = 'D:\\Ai Studio Pro\\app\\AiStudioPro .exe';
        
        console.log('Converting PNG to ICO...');
        const buf = await pngToIco(pngPath);
        fs.writeFileSync(icoPath, buf);
        
        console.log('Applying ICO to EXE...');
        await rcedit(exePath, {
            icon: icoPath
        });
        
        console.log('Replacing assets...');
        const assetsDir = 'D:\\Ai Studio Pro\\app_source\\out\\renderer\\assets';
        const filesToReplace = [
            'chicken-community-CbQ5CIwe.png',
            'chicken-dropzone-C2FIzMeX.png',
            'chicken-telegram-BKcwWOoK.png',
            'ghost-mascot-B3bIS1rn.png',
            'ghost-pattern-BNPL3DEA.png'
        ];
        
        for (const file of filesToReplace) {
            fs.copyFileSync(pngPath, path.join(assetsDir, file));
            console.log('Replaced', file);
        }
        
        console.log('Successfully changed the executable icon and replaced all chicken/ghost images with phoenix!');
    } catch (err) {
        console.error('Failed:', err);
    }
}

changeIcon();
