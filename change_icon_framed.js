const rcedit = require('rcedit').rcedit;
const pngToIco = require('png-to-ico').default;
const fs = require('fs');

async function changeIcon() {
    try {
        const buf = await pngToIco('D:\\Ai Studio Pro\\phoenix_framed_white.png');
        fs.writeFileSync('phoenix_framed_white.ico', buf);
        console.log('Applying ICO to EXE...');
        await rcedit('D:\\Ai Studio Pro\\app\\AiStudio Pro.exe', { icon: 'phoenix_framed_white.ico' });
        console.log('Successfully changed the executable icon!');
    } catch (err) {
        console.error('Failed:', err);
    }
}
changeIcon();
