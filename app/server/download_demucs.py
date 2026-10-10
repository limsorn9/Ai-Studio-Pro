import os
import sys
import json
import time
import zipfile
import requests

# Script to download Demucs CUDA Bundle directly from Google Drive
# Features:
# 1. Direct stream from Google Drive with exact Content-Length
# 2. Real-time JSON progress output for UI Progress Bar
# 3. Automatic extraction into app directory (Zero manual work for customers)
# 4. Cleans up temporary zip file after extraction
# 5. Check mode via --check

FILE_ID = "16pSVW2_JtzW-Mf1G5luziYJo0_ZyV1hL"
DOWNLOAD_URL = f"https://drive.usercontent.google.com/download?id={FILE_ID}&export=download&confirm=t"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(CURRENT_DIR)
TEMP_ZIP = os.path.join(APP_DIR, "Demucs_Bundle_CUDA.tmp.zip")

def is_demucs_installed():
    # Verify key Demucs / CUDA indicators exist
    indicator_dirs = [
        os.path.join(APP_DIR, "environment", "Lib", "site-packages", "demucs"),
        os.path.join(APP_DIR, "resources", "separator", "demucs")
    ]
    for p in indicator_dirs:
        if os.path.exists(p):
            return True
    return False

def report_progress(downloaded_bytes, total_bytes, speed_mbps=0.0, eta_seconds=0):
    percent = round((downloaded_bytes / max(total_bytes, 1)) * 100, 1)
    percent = min(100.0, max(0.0, percent))
    data = {
        "state": "downloading",
        "percent": percent,
        "downloadedBytes": downloaded_bytes,
        "totalBytes": total_bytes,
        "downloadedMB": round(downloaded_bytes / (1024 * 1024), 1),
        "totalMB": round(total_bytes / (1024 * 1024), 1),
        "speedMBs": round(speed_mbps, 2),
        "etaSeconds": round(eta_seconds)
    }
    print(json.dumps(data), flush=True)

def download_and_extract():
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        if is_demucs_installed():
            print(json.dumps({"state": "ready", "installed": True}), flush=True)
        else:
            print(json.dumps({"state": "missing", "installed": False}), flush=True)
        sys.exit(0)

    try:
        print(json.dumps({"state": "connecting", "message": "កំពុងភ្ជាប់ទៅកាន់ Google Drive..."}), flush=True)
        session = requests.Session()
        response = session.get(DOWNLOAD_URL, stream=True, timeout=30)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 2824728607))
        chunk_size = 1024 * 1024 * 2  # 2MB chunks
        downloaded = 0

        last_time = time.time()
        last_downloaded = 0

        # Stream download to temporary zip file
        with open(TEMP_ZIP, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)

                now = time.time()
                elapsed = now - last_time
                if elapsed >= 1.0 or downloaded >= total_size:
                    speed = ((downloaded - last_downloaded) / max(elapsed, 0.1)) / (1024 * 1024)
                    remaining = max(0, total_size - downloaded)
                    eta = remaining / max((downloaded - last_downloaded) / max(elapsed, 0.1), 1)
                    report_progress(downloaded, total_size, speed, eta)
                    last_time = now
                    last_downloaded = downloaded

        # Extraction phase
        print(json.dumps({"state": "extracting", "percent": 100, "message": "ទាញយកចប់សព្វគ្រប់! កំពុងដំឡើង និងពន្លាដោយស្វ័យប្រវត្តិ..."}), flush=True)
        with zipfile.ZipFile(TEMP_ZIP, "r") as z:
            z.extractall(APP_DIR)

        # Remove temporary zip file
        if os.path.exists(TEMP_ZIP):
            os.remove(TEMP_ZIP)

        print(json.dumps({"state": "ready", "installed": True, "message": "ដំឡើង Demucs CUDA រួចរាល់ដោយជោគជ័យ!"}), flush=True)

    except Exception as e:
        if os.path.exists(TEMP_ZIP):
            try:
                os.remove(TEMP_ZIP)
            except:
                pass
        print(json.dumps({"state": "error", "error": str(e)}), flush=True)
        sys.exit(1)

if __name__ == "__main__":
    download_and_extract()
