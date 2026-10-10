import re
import os
import shutil

bak_path = r'd:\AI Studio Pro\resources\app_clean\out\main\index.js.bak'
path = r'd:\AI Studio Pro\resources\app_clean\out\main\index.js'

shutil.copy(bak_path, path)

with open(path, 'r', encoding='utf8') as f:
    text = f.read()

# 1. Patch dub:translate
translate_orig = 'A.handle("dub:translate",async(e,t)=>{const n=Array.isArray(t.cues)?t.cues:[],a=new Map,r=mi(t.targetLanguage);try{'
translate_new = 'A.handle("dub:translate",async(e,t)=>{const n=Array.isArray(t.cues)?t.cues:[],a=new Map,r=mi(t.targetLanguage);' + """
  if(t.sttProvider === "local") {
    try {
      const { exec } = await import('node:child_process');
      const fs = await import('node:fs');
      const path = await import('node:path');
      const os = await import('node:os');
      const tempInput = path.join(os.tmpdir(), 'nllb_in_' + Date.now() + '.json');
      const tempOutput = path.join(os.tmpdir(), 'nllb_out_' + Date.now() + '.json');
      fs.writeFileSync(tempInput, JSON.stringify(n));
      let pyExe = "python";
      let pyScript = path.join(process.cwd(), 'server', 'local_inference.py');
      if (fs.existsSync(path.join(process.cwd(), 'environment', 'Scripts', 'python.exe'))) {
          pyExe = path.join(process.cwd(), 'environment', 'Scripts', 'python.exe');
      } else {
          pyScript = path.join(process.resourcesPath, 'app.asar.unpacked', 'server', 'local_inference.py');
      }
      const settings = await Ce();
      const device = settings.runtimeDevice || 'cuda';
      await new Promise((resolve, reject) => {
        exec(`"${pyExe}" "${pyScript}" --action translate --input "${tempInput}" --output "${tempOutput}" --device ${device} --target-lang ${t.targetLanguage}`, (error, stdout, stderr) => {
          if (error) { console.error(stderr); reject(error); } else { resolve(); }
        });
      });
      const translated = JSON.parse(fs.readFileSync(tempOutput, 'utf-8'));
      if(fs.existsSync(tempInput)) fs.unlinkSync(tempInput);
      if(fs.existsSync(tempOutput)) fs.unlinkSync(tempOutput);
      return {ok: !0, cues: translated};
    } catch(err) {
      return {ok: !1, error: err.message, stage: "translating", cues: n};
    }
  }
""" + 'try{'
text = text.replace(translate_orig, translate_new)

# 2. Patch FN
idx = text.find('async function FN(e,t,n,a,r){')
if idx != -1:
    open_braces = 0
    end_idx = -1
    for i in range(idx + 28, len(text)):
        if text[i] == '{': open_braces += 1
        elif text[i] == '}':
            open_braces -= 1
            if open_braces == 0:
                end_idx = i + 1
                break
    old_fn = text[idx:end_idx]
    new_fn = """async function FN(e,t,n,a,r){
  const s=await Ae(g(Ne(),"sdachmoan-local-whisper-"));
  const l=g(s,"audio.wav");
  const c=g(s,"transcript.json");
  r({phase:"transcribing",current:0,total:100,percent:2,message:"Preparing audio for Faster-Whisper Local"});
  await Zn(e,l,a);
  r({phase:"transcribing",current:0,total:100,percent:5,message:"Transcribing locally with Faster-Whisper"});
  const { exec } = await import('node:child_process');
  const fs = await import('node:fs');
  const path = await import('node:path');
  let pyExe = "python";
  let pyScript = path.join(process.cwd(), 'server', 'local_inference.py');
  if (fs.existsSync(path.join(process.cwd(), 'environment', 'Scripts', 'python.exe'))) {
      pyExe = path.join(process.cwd(), 'environment', 'Scripts', 'python.exe');
  } else {
      pyScript = path.join(process.resourcesPath, 'app.asar.unpacked', 'server', 'local_inference.py');
  }
  const settings = await Ce();
  const device = settings.runtimeDevice || 'cuda';
  await new Promise((resolve, reject) => {
    exec(`"${pyExe}" "${pyScript}" --action transcribe --input "${l}" --output "${c}" --device ${device}`, (error, stdout, stderr) => {
      if (error) { console.error(stderr); reject(error); } else { resolve(); }
    });
  });
  return JSON.parse(fs.readFileSync(c, 'utf8'));
}"""
    text = text.replace(old_fn, new_fn)

# 3. Patch local-whisper:download
old_dl = 'A.handle("local-whisper:download",async()=>{if(dt)return dt;const e=new AbortController;Rn=e;const t=SN(e.signal,rh);dt=t;try{return await t}finally{dt===t&&(dt=null),Rn===e&&(Rn=null)}});'
new_dl = """A.handle("local-whisper:download", async () => {
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
});"""
text = text.replace(old_dl, new_dl.replace('\\n', '\\\\n').replace('\n', ''))

# 4. Patch wt()
old_wt = 'async function wt(){if(qe)return qe;const e=await vN();return e===Te?{state:"ready",downloadedBytes:e,totalBytes:Te}:Zt?{state:"error",downloadedBytes:e,totalBytes:Te,error:Zt}:{state:"missing",downloadedBytes:0,totalBytes:Te}}'
new_wt = """async function wt(){
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
}"""
text = text.replace(old_wt, new_wt.replace('\\n', '\\\\n').replace('\n', ''))

with open(path, 'w', encoding='utf8') as f:
    f.write(text)
print("All patches applied!")
