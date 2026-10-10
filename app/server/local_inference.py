import argparse
import json
import os
import sys
import logging
import urllib.request
import urllib.parse
import time
import re

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

NLLB_CODES = {
    "km": "khm_Khm",
    "en": "eng_Latn",
    "fr": "fra_Latn",
    "es": "spa_Latn",
    "zh": "zho_Hans",
    "th": "tha_Thai",
    "vi": "vie_Latn",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "de": "deu_Latn",
    "ru": "rus_Cyrl"
}

def get_nllb_lang(code):
    return NLLB_CODES.get(code.split('-')[0], "khm_Khm")

def shorten_khmer_text(text):
    # Rule-based auto-shortening for spoken Khmer movie subtitles
    replacements = [
        (r'តើអ្នក', r'អ្នក'),
        (r'តើឯង', r'ឯង'),
        (r'តើវា', r'វា'),
        (r'តើបង', r'បង'),
        (r'តើអូន', r'អូន'),
        (r'តើលោក', r'លោក'),
        (r'តើ', r''),
        (r'ជាការពិតណាស់', r'ពិតណាស់'),
        (r'ខ្ញុំគិតថា', r'ខ្ញុំថា'),
        (r'ប្រសិនបើ', r'បើ'),
        (r'ពីព្រោះតែ', r'ព្រោះតែ'),
        (r'ពីព្រោះ', r'ព្រោះ'),
        (r'ទោះបីជា', r'ទោះជា'),
        (r'នៅក្នុង', r'ក្នុង'),
        (r'នៅពេលដែល', r'ពេល'),
        (r'ពេលដែល', r'ពេល'),
        (r'របស់ខ្ញុំ', r''),
        (r'របស់អ្នក', r''),
        (r'របស់គាត់', r'គាត់'), 
        (r'យ៉ាងម៉េចដែរ', r'ម៉េចដែរ'),
        (r'យ៉ាងដូចម្តេច', r'ម៉េច'),
        (r'នោះទេ', r'ទេ'),
        (r'មានន័យថា', r'បានន័យថា'),
        (r'គឺជារឿង', r'ជារឿង'),
        (r'គឺជា', r'ជា'),
        (r'ពិតប្រាកដណាស់', r'ពិតណាស់'),
        (r'ខ្ញុំចង់ប្រាប់អ្នកថា', r'ខ្ញុំចង់ប្រាប់ថា'),
        (r'សូមមេត្តា', r'សូម'),
        (r'អរគុណច្រើន', r'អរគុណ'),
        (r'សុំទោសផង', r'សុំទោស'),
        (r'មិនអាចទៅរួចទេ', r'មិនអាចទេ'),
        (r'មិនដែល', r'អត់ដែល'),
        (r'មិនមាន', r'អត់មាន'),
        (r'មិនមែន', r'អត់មែន'),
        (r'មិនបាន', r'អត់បាន')
    ]
    
    for old, new in replacements:
        text = re.sub(old, new, text)
        
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def run_translate(input_file, output_file, device_type, target_lang):
    logger.info("Using Protected Tag-Delimited Google Translate Engine (Anti-Ban & Alignment Safe)...")
    
    with open(input_file, 'r', encoding='utf-8') as f:
        cues = json.load(f)

    tgt_lang = get_nllb_lang(target_lang)
    lang_map = {'khm_Khm': 'km', 'eng_Latn': 'en', 'fra_Latn': 'fr', 'zho_Hans': 'zh-CN'}
    g_lang = lang_map.get(tgt_lang, tgt_lang.split('_')[0][:2])
    
    logger.info(f"Translating {len(cues)} cues to {g_lang} in protected batches")

    batch_size = 20
    batches = [cues[i:i + batch_size] for i in range(0, len(cues), batch_size)]

    endpoints = [
        f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=auto&tl={g_lang}",
        f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={g_lang}&dt=t"
    ]

    for batch_idx, batch in enumerate(batches):
        logger.info(f"Translating batch {batch_idx+1}/{len(batches)} ({len(batch)} cues)...")
        print(f"[PROGRESS] {batch_idx+1}/{len(batches)}", flush=True)

        original_texts = [(c.get('sourceText') or c.get('text') or '').strip() for c in batch]
        tagged_input = " ".join([f"[[{idx}]] {t}" for idx, t in enumerate(original_texts) if t])

        translated_results = [""] * len(batch)
        success = False

        if not tagged_input.strip():
            continue

        for attempt in range(3):
            for ep in endpoints:
                try:
                    data = urllib.parse.urlencode({'q': tagged_input}).encode('utf-8')
                    req = urllib.request.Request(
                        ep,
                        data=data,
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0'}
                    )
                    with urllib.request.urlopen(req, timeout=12) as res:
                        raw = res.read().decode('utf-8')
                        parsed = json.loads(raw)
                        translated_text = ""
                        if isinstance(parsed, list):
                            if isinstance(parsed[0], list) and isinstance(parsed[0][0], str):
                                translated_text = parsed[0][0]
                            elif isinstance(parsed[0], str):
                                translated_text = parsed[0]

                        # Split by [[idx]] tags
                        matches = list(re.finditer(r'\[\[(\d+)\]\]\s*', translated_text))
                        if matches:
                            for m_idx, m in enumerate(matches):
                                idx = int(m.group(1))
                                start_pos = m.end()
                                end_pos = matches[m_idx+1].start() if m_idx + 1 < len(matches) else len(translated_text)
                                if idx < len(translated_results):
                                    chunk_text = translated_text[start_pos:end_pos].strip()
                                    translated_results[idx] = chunk_text

                            if any(translated_results):
                                success = True
                                break
                except Exception:
                    time.sleep(1.2)

            if success:
                break
            time.sleep(2)

        # Apply results and shorten Khmer speech for natural dubbing
        for i, cue in enumerate(batch):
            trans = translated_results[i].strip() if success else ""
            if trans:
                if g_lang == 'km':
                    trans = shorten_khmer_text(trans)
                cue['text'] = trans
            else:
                cue['text'] = original_texts[i]
            if not cue.get('sourceText'):
                cue['sourceText'] = original_texts[i]
            cue['locale'] = g_lang
            cue['dubStatus'] = 'pending'

        time.sleep(0.4)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(cues, f, ensure_ascii=False, indent=2)

    logger.info("Protected Translation complete.")

def run_whisper_transcribe(input_file, output_file, device_type):
    """
    Tier 2: Whisper Speech-to-Text for movies/audio WITHOUT burnt-in subtitles.
    """
    try:
        from faster_whisper import WhisperModel
        import torch
    except ImportError:
        logger.error("faster_whisper or torch is not installed.")
        sys.exit(1)

    device = "cuda" if device_type in ['cuda', 'hybrid'] and torch.cuda.is_available() else "cpu"
    compute_type = "int8"
    
    logger.info(f"Loading Faster Whisper (large-v3-turbo) on {device} ({compute_type})")
    try:
        model = WhisperModel("large-v3-turbo", device=device, compute_type=compute_type)
    except Exception as e:
        logger.error(f"Failed to load Whisper model: {e}")
        sys.exit(1)

    logger.info(f"Transcribing {input_file} with Whisper")
    segments, info = model.transcribe(input_file, beam_size=5)

    cues = []
    for i, segment in enumerate(segments):
        cues.append({
            "id": f"c_{i}",
            "startMs": int(segment.start * 1000),
            "endMs": int(segment.end * 1000),
            "text": segment.text.strip()
        })

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(cues, f, ensure_ascii=False, indent=2)

    logger.info("Whisper transcription complete.")

def run_transcribe(input_file, output_file, device_type):
    """
    Smart Dual-Tier Entry Point:
    - If video file (.mp4, .mkv, .webm, etc.) -> automatically checks for burnt-in subtitles first!
    - If clean video or audio -> seamlessly uses Faster Whisper!
    """
    video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.ts'}
    ext = os.path.splitext(input_file)[1].lower()
    if ext in video_exts:
        run_auto_transcribe(input_file, output_file, device_type)
        return

    run_whisper_transcribe(input_file, output_file, device_type)

def run_ocr_transcribe(input_file, output_file):
    """
    Tier 1: Video Subtitle OCR for movies WITH burnt-in Chinese/English subtitles on screen.
    """
    from subtitle_ocr import VideoSubtitleOCR
    logger.info(f"Scanning burnt-in subtitles from video: {input_file}")
    ocr = VideoSubtitleOCR()
    cues = ocr.extract_subtitles(input_file)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(cues, f, ensure_ascii=False, indent=2)

    logger.info(f"OCR Subtitle extraction complete ({len(cues)} cues).")

def run_auto_transcribe(input_file, output_file, device_type):
    """
    Dual-protection Hybrid Auto-Detection:
    1. First inspects video frames for burnt-in subtitles using Video Subtitle OCR.
    2. If hardcoded subtitles detected -> uses High-Accuracy OCR!
    3. If NO subtitles detected on screen -> seamlessly falls back to Whisper Speech-to-Text!
    """
    logger.info(f"Running Smart Auto-Detection on {input_file}...")
    try:
        from subtitle_ocr import VideoSubtitleOCR
        ocr = VideoSubtitleOCR()
        if ocr.has_hardcoded_subtitles(input_file, check_seconds=35.0):
            logger.info("✅ Hardcoded subtitles detected on screen! Extracting with Video OCR...")
            cues = ocr.extract_subtitles(input_file)
            if cues and len(cues) >= 3:
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(cues, f, ensure_ascii=False, indent=2)
                logger.info(f"Auto-Detection: successfully extracted {len(cues)} cues via Video OCR.")
                return
    except Exception as ocr_err:
        logger.warning(f"OCR auto-check warning: {ocr_err}")

    logger.info("ℹ️ No hardcoded subtitles detected on screen. Falling back to Whisper Speech-to-Text...")
    run_transcribe(input_file, output_file, device_type)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["translate", "transcribe", "ocr", "auto"], required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", choices=["cpu", "cuda", "hybrid"], default="cuda")
    parser.add_argument("--target-lang", default="km")

    args = parser.parse_args()

    if args.action == "translate":
        run_translate(args.input, args.output, args.device, args.target_lang)
    elif args.action == "transcribe":
        run_transcribe(args.input, args.output, args.device)
    elif args.action == "ocr":
        run_ocr_transcribe(args.input, args.output)
    elif args.action == "auto":
        run_auto_transcribe(args.input, args.output, args.device)
