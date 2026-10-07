import re

with open(r"D:\Ai Studio Pro\app_source\out\renderer\assets\index-L22pqO0q.js", "r", encoding="utf-8", errors="ignore") as f:
    renderer_js = f.read()

with open(r"D:\Ai Studio Pro\app_source\out\main\index.js", "r", encoding="utf-8", errors="ignore") as f:
    main_js = f.read()

print("=== MAIN JS ===")
for m in re.finditer(r'https?://t\.me/[^\s"\'<>`\\}]+', main_js):
    start = max(0, m.start() - 100)
    end = min(len(main_js), m.end() + 100)
    print("Found in main:", main_js[start:end])
    print("-" * 50)

print("\n=== RENDERER JS ===")
for kw in ["Licence Key", "PHSAAR", "t.me", "sorn", "Pro2_bot"]:
    matches = [m.start() for m in re.finditer(re.escape(kw), renderer_js, re.IGNORECASE)]
    print(f"Keyword '{kw}': {len(matches)} matches")
    for idx in matches[:5]:
        start = max(0, idx - 120)
        end = min(len(renderer_js), idx + 180)
        print(f"  [Pos {idx}]:\n{renderer_js[start:end]}")
        print("." * 40)
