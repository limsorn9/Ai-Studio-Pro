const rcedit = require('rcedit').rcedit;

async function updateProperties() {
    try {
        const exePath = 'e:\\Ai Studio Pro\\app\\Ai Studio Pro.exe';
        
        console.log('Applying properties to EXE...');
        await rcedit(exePath, {
            'version-string': {
                'FileDescription': 'Ai Studio Pro [ Clone សម្លេង Pro ]',
                'ProductName': 'Ai Studio Pro [ Clone សម្លេង Pro ]',
                'LegalCopyright': '© 2026 Ai Studio Pro [ Clone សម្លេង Pro ]',
                'OriginalFilename': 'Ai Studio Pro.exe'
            }
        });
        
        console.log('Successfully updated the executable properties!');
    } catch (err) {
        console.error('Failed:', err);
    }
}

updateProperties();
