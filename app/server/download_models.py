import os
import sys
import json
import time
import threading
from huggingface_hub import snapshot_download

# Global variables
total_size = 5368709120 # ~5GB estimated
cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
is_downloading = True

def get_folder_size(folder):
    total = 0
    if not os.path.exists(folder):
        return 0
    try:
        for path, dirs, files in os.walk(folder):
            for f in files:
                fp = os.path.join(path, f)
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
    except:
        pass
    return total

def get_total_downloaded():
    whisper_dir = os.path.join(cache_dir, "models--Systran--faster-whisper-large-v3")
    nllb_dir = os.path.join(cache_dir, "models--facebook--nllb-200-distilled-600M")
    locks_dir = os.path.join(cache_dir, ".locks")
    return get_folder_size(whisper_dir) + get_folder_size(nllb_dir) + get_folder_size(locks_dir)

def report_progress(downloaded, total):
    print(json.dumps({"state": "downloading", "downloadedBytes": downloaded, "totalBytes": total}), flush=True)

def monitor_progress():
    while is_downloading:
        time.sleep(1.0)
        current_size = get_total_downloaded()
        # Prevent going over 100% just in case
        safe_downloaded = min(current_size, total_size)
        report_progress(safe_downloaded, total_size)

def clean_stuck_files():
    try:
        for root, dirs, files in os.walk(cache_dir):
            for file in files:
                if file.endswith(".incomplete"):
                    path = os.path.join(root, file)
                    try:
                        # Remove 0-byte stuck files
                        if os.path.getsize(path) == 0:
                            os.remove(path)
                    except:
                        pass
    except:
        pass

def main():
    global is_downloading
    try:
        clean_stuck_files()
        
        # Initial report
        initial_size = get_total_downloaded()
        report_progress(min(initial_size, total_size), total_size)
        
        # Start progress monitor
        monitor_thread = threading.Thread(target=monitor_progress)
        monitor_thread.daemon = True
        monitor_thread.start()
        
        # Download Faster-Whisper model
        snapshot_download(repo_id="Systran/faster-whisper-large-v3", local_files_only=False, max_workers=2)
        
        # Download NLLB model
        snapshot_download(repo_id="facebook/nllb-200-distilled-600M", local_files_only=False, max_workers=2)
        
        is_downloading = False
        time.sleep(0.5)
        report_progress(total_size, total_size)
        print(json.dumps({"state": "ready"}), flush=True)
    except Exception as e:
        is_downloading = False
        print(json.dumps({"state": "error", "error": str(e)}), flush=True)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        try:
            snapshot_download(repo_id="Systran/faster-whisper-large-v3", local_files_only=True)
            snapshot_download(repo_id="facebook/nllb-200-distilled-600M", local_files_only=True)
            print(json.dumps({"state": "ready"}))
        except:
            print(json.dumps({"state": "missing"}))
        sys.exit(0)
    main()
