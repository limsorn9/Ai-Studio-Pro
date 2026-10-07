const rcedit = require('rcedit').rcedit;
const exePath = 'D:\\Ai Studio Pro\\app\\AiStudio Pro.exe';
const icoPath = 'phoenix_white.ico';
async function changeIcon() {
    try {
        console.log('Applying ICO to EXE...');
        await rcedit(exePath, { icon: icoPath });
        console.log('Successfully changed the executable icon!');
    } catch (err) {
        console.error('Failed:', err);
    }
}
changeIcon();
