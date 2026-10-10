import re
import os

path = r'd:\AI Studio Pro\resources\app_clean\out\main\index.js'
with open(path, 'r', encoding='utf8') as f:
    text = f.read()

# Replace local-whisper:download
old_download = 'A.handle("local-whisper:download",async()=>{if(dt)return dt;const e=new AbortController;Rn=e;const t=SN(e.signal,rh);dt=t;try{return await t}finally{dt===t&&(dt=null),Rn===e&&(Rn=null)}});'

new_download = """
A.handle("local-whisper:download", async () => {
    if (dt) return dt;
    const { spawn } = await import('node:child_process');
    const path = await import('node:path');
    const fs = await import('node:fs');
    let pyExe = "python";
    let pyScript = path.join(process.cwd(), 'server', 'download_models.py');
    if (fs.existsSync(path.join(process.cwd(), 'environment', 'Scripts', 'python.exe'))) {
        pyExe = path.join(process.cwd(), 'environment', 'Scripts', 'python.exe');
    } else {
        pyScript = path.join(process.resourcesPath, 'app.asar.unpacked', 'server', 'download_models.py');
    }
    
    dt = new Promise((resolve, reject) => {
        const proc = spawn(pyExe, [pyScript]);
        proc.stdout.on('data', (data) => {
            const lines = data.toString().split('\\n');
            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const state = JSON.parse(line);
                    if (state.state === "ready") {
                        rh({state: "ready", downloadedBytes: 100, totalBytes: 100});
                        resolve();
                    } else if (state.state === "error") {
                        rh({state: "error", error: state.error});
                        reject(new Error(state.error));
                    } else {
                        rh(state);
                    }
                } catch(e) {}
            }
        });
        proc.stderr.on('data', (data) => { console.error(data.toString()); });
        proc.on('close', () => { dt = null; resolve(); });
    });
    return await dt;
});
""".replace('\n', '')

text = text.replace(old_download, new_download)

# Replace wt()
idx = text.find('async function wt(){if(qe)return qe;const e=await vN();return e===Te?{state:"ready",downloadedBytes:e,totalBytes:Te}:Zt?{state:"error",downloadedBytes:e,totalBytes:Te,error:Zt}:{state:"missing",downloadedBytes:0,totalBytes:Te}}')

new_wt = """
async function wt(){
    const { exec } = await import('node:child_process');
    const path = await import('node:path');
    const fs = await import('node:fs');
    let pyExe = "python";
    let pyScript = path.join(process.cwd(), 'server', 'download_models.py');
    if (fs.existsSync(path.join(process.cwd(), 'environment', 'Scripts', 'python.exe'))) {
        pyExe = path.join(process.cwd(), 'environment', 'Scripts', 'python.exe');
    } else {
        pyScript = path.join(process.resourcesPath, 'app.asar.unpacked', 'server', 'download_models.py');
    }
    return await new Promise((resolve) => {
        exec(`"${pyExe}" "${pyScript}" --check`, (err, stdout, stderr) => {
            try {
                const state = JSON.parse(stdout.trim().split('\\n').pop());
                if (state.state === "ready") {
                    resolve({state: "ready", downloadedBytes: 100, totalBytes: 100});
                } else {
                    resolve({state: "missing", downloadedBytes: 0, totalBytes: 100});
                }
            } catch(e) {
                resolve({state: "missing", downloadedBytes: 0, totalBytes: 100});
            }
        });
    });
}
""".replace('\n', '')

text = text.replace(text[idx:idx+len('async function wt(){if(qe)return qe;const e=await vN();return e===Te?{state:"ready",downloadedBytes:e,totalBytes:Te}:Zt?{state:"error",downloadedBytes:e,totalBytes:Te,error:Zt}:{state:"missing",downloadedBytes:0,totalBytes:Te}')], new_wt)

with open(path, 'w', encoding='utf8') as f:
    f.write(text)
print("index.js patched successfully.")
