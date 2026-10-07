"""
AI Background Remover for Ai Studio Pro Assets
Uses rembg (AI model) to remove backgrounds from all PNG images in the assets folder.
Only processes files that are actual image assets (mascots, icons, etc.) and NOT:
- CSS, JS files
- Logo/flag files that should keep their look
"""
import os
from pathlib import Path
from rembg import remove
from PIL import Image
import io

ASSETS_DIR = r"D:\Ai Studio Pro\app_source\out\renderer\assets"

# Skip these files (UI images that shouldn't have bg removed)
SKIP_FILES = {
    "index-BQmrldh6.css",
    "index-L22pqO0q.js",
}

# Skip keywords in filenames (flags, QR codes, covers - keep their bg)
SKIP_KEYWORDS = ["flag-", "qr-", "cover-studio", "index-"]

def should_skip(filename):
    if filename in SKIP_FILES:
        return True
    for kw in SKIP_KEYWORDS:
        if kw in filename:
            return True
    return False

def main():
    assets = Path(ASSETS_DIR)
    png_files = sorted([f for f in assets.glob("*.png") if not should_skip(f.name)])
    
    total = len(png_files)
    print(f"Found {total} PNG files to process...")
    print("=" * 60)
    
    for i, filepath in enumerate(png_files, 1):
        try:
            print(f"[{i}/{total}] Processing: {filepath.name}")
            
            with open(filepath, "rb") as f:
                input_data = f.read()
            
            # Use rembg AI to remove background
            output_data = remove(input_data)
            
            # Save back as PNG with transparency
            img = Image.open(io.BytesIO(output_data)).convert("RGBA")
            img.save(filepath, "PNG")
            
            print(f"  ✓ Done! Size: {filepath.stat().st_size // 1024} KB")
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    print("=" * 60)
    print(f"Finished! Processed {total} files.")

if __name__ == "__main__":
    main()
