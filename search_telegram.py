import os
import re

search_dirs = [r"D:\Ai Studio Pro\app_source", r"D:\Ai Studio Pro\server"]
for sdir in search_dirs:
    for root, dirs, files in os.walk(sdir):
        if 'node_modules' in dirs:
            dirs.remove('node_modules')
        if '.git' in dirs:
            dirs.remove('.git')
        for f in files:
            if f.endswith(('.js', '.json', '.html', '.css')):
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as fp:
                        content = fp.read()
                except Exception:
                    continue
                
                # Check for telegram / t.me
                if 't.me' in content.lower() or 'telegram' in content.lower():
                    tme_links = set(re.findall(r'https?://t\.me/[^\s"\'<>`\\}]+', content))
                    bot_handles = set(re.findall(r'@[a-zA-Z0-9_]+', content))
                    print(f"\nMatch in: {fpath}")
                    if tme_links:
                        print(f"  t.me links: {tme_links}")
                    # Filter interesting handles
                    interesting = {h for h in bot_handles if 'bot' in h.lower() or 'sorn' in h.lower() or 'studio' in h.lower()}
                    if interesting:
                        print(f"  handles: {interesting}")
