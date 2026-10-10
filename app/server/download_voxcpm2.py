import os
import sys
import json
import time
import threading
from huggingface_hub import snapshot_download

# Script to download VoxCPM2 directly from official OpenBMB repository on Hugging Face
# Features:
# 1. Direct download into app/model/VoxCPM2 without zip archives (no extraction needed)
# 2. Resumable downloads (picks up where left off if interrupted)
# 3. Real-time JSON progress output for UI Progress Bar

REPO_ID = "openbmb/VoxCPM2"
ESTIMATED_TOTAL_BYTES = 4960708493  # ~4.96 GB for complete VoxCPM2 model

# Determine target directory
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(CURRENT_DIR)
TARGET_DIR = os.path.join(APP_DIR, "model", "VoxCPM2")

is_downloading = True

def get_folder_size(folder):
    total = 0
    if not os.path.exists(folder):
        return 0
    try:
        for root, dirs, files in os.walk(folder):
            for f in files:
                fp = os.path.join(root, f)
                if not os.path.islink(fp) and not f.endswith(".incomplete"):
                    total += os.path.getsize(fp)
    except:
        pass
    return total

def is_model_installed():
    model_file = os.path.join(TARGET_DIR, "model.safetensors")
    vae_file = os.path.join(TARGET_DIR, "audiovae.pth")
    # Verify main model files exist and have non-zero size
    if os.path.exists(model_file) and os.path.exists(vae_file):
        if os.path.getsize(model_file) > 4000000000 and os.path.getsize(vae_file) > 300000000:
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

def monitor_progress():
    last_size = get_folder_size(TARGET_DIR)
    last_time = time.time()
    
    while is_downloading:
        time.sleep(1.0)
        now = time.time()
        current_size = get_folder_size(TARGET_DIR)
        
        elapsed = max(0.1, now - last_time)
        bytes_diff = max(0, current_size - last_size)
        speed_mbps = (bytes_diff / elapsed) / (1024 * 1024)
        
        remaining_bytes = max(0, ESTIMATED_TOTAL_BYTES - current_size)
        eta_seconds = (remaining_bytes / max(bytes_diff / elapsed, 1)) if bytes_diff > 0 else 0
        
        last_size = current_size
        last_time = now
        
        safe_downloaded = min(current_size, ESTIMATED_TOTAL_BYTES)
        report_progress(safe_downloaded, ESTIMATED_TOTAL_BYTES, speed_mbps, eta_seconds)

def main():
    global is_downloading
    
    # Check if user only wants to check installation status
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        if is_model_installed():
            print(json.dumps({"state": "ready", "installed": True}), flush=True)
        else:
            print(json.dumps({"state": "missing", "installed": False}), flush=True)
        sys.exit(0)
    
    # Check if already installed
    if is_model_installed():
        report_progress(ESTIMATED_TOTAL_BYTES, ESTIMATED_TOTAL_BYTES, 0, 0)
        print(json.dumps({"state": "ready", "message": "VoxCPM2 is already installed"}), flush=True)
        sys.exit(0)

    try:
        os.makedirs(TARGET_DIR, exist_ok=True)
        
        # Initial report
        initial_size = get_folder_size(TARGET_DIR)
        report_progress(min(initial_size, ESTIMATED_TOTAL_BYTES), ESTIMATED_TOTAL_BYTES)
        
        # Start background monitor thread
        monitor_thread = threading.Thread(target=monitor_progress)
        monitor_thread.daemon = True
        monitor_thread.start()
        
        # Download from official Hugging Face repository directly into target folder
        print(json.dumps({"state": "starting", "message": f"Downloading from official {REPO_ID}..."}), flush=True)
        snapshot_download(
            repo_id=REPO_ID,
            local_dir=TARGET_DIR,
            local_dir_use_symlinks=False,
            resume_download=True,
            max_workers=2
        )
        
        is_downloading = False
        time.sleep(0.5)
        report_progress(ESTIMATED_TOTAL_BYTES, ESTIMATED_TOTAL_BYTES)
        print(json.dumps({"state": "ready", "message": "VoxCPM2 download completed successfully"}), flush=True)
        
    except Exception as e:
        is_downloading = False
        print(json.dumps({"state": "error", "error": str(e)}), flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
