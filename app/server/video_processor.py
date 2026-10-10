import os
import gc
import ffmpeg
import logging
import urllib.request
import urllib.parse
import json
import time
import re
from faster_whisper import WhisperModel
from subtitle_ocr import VideoSubtitleOCR

logger = logging.getLogger(__name__)

def shorten_khmer_text(text):
    replacements = [
        (r'តើអ្នក', r'អ្នក'), (r'តើឯង', r'ឯង'), (r'តើវា', r'វា'),
        (r'តើបង', r'បង'), (r'តើអូន', r'អូន'), (r'តើលោក', r'លោក'),
        (r'តើ', r''), (r'ជាការពិតណាស់', r'ពិតណាស់'),
        (r'ខ្ញុំគិតថា', r'ខ្ញុំថា'), (r'ប្រសិនបើ', r'បើ'),
        (r'ពីព្រោះតែ', r'ព្រោះតែ'), (r'ពីព្រោះ', r'ព្រោះ'),
        (r'ទោះបីជា', r'ទោះជា'), (r'នៅក្នុង', r'ក្នុង'),
        (r'នៅពេលដែល', r'ពេល'), (r'ពេលដែល', r'ពេល'),
        (r'របស់ខ្ញុំ', r''), (r'របស់អ្នក', r''), (r'របស់គាត់', r'គាត់'),
        (r'យ៉ាងម៉េចដែរ', r'ម៉េចដែរ'), (r'យ៉ាងដូចម្តេច', r'ម៉េច'),
        (r'នោះទេ', r'ទេ'), (r'មានន័យថា', r'បានន័យថា'),
        (r'គឺជារឿង', r'ជារឿង'), (r'គឺជា', r'ជា'),
        (r'ពិតប្រាកដណាស់', r'ពិតណាស់'), (r'ខ្ញុំចង់ប្រាប់អ្នកថា', r'ខ្ញុំចង់ប្រាប់ថា'),
        (r'សូមមេត្តា', r'សូម'), (r'អរគុណច្រើន', r'អរគុណ'),
        (r'សុំទោសផង', r'សុំទោស'), (r'មិនអាចទៅរួចទេ', r'មិនអាចទេ'),
        (r'មិនដែល', r'អត់ដែល'), (r'មិនមាន', r'អត់មាន'),
        (r'មិនមែន', r'អត់មែន'), (r'មិនបាន', r'អត់បាន')
    ]
    for old, new in replacements:
        text = re.sub(old, new, text)
    return re.sub(r'\s+', ' ', text).strip()

def translate_texts_batch_google(texts, target_lang='km', source_lang='auto'):
    if not texts:
        return []
    
    batch_size = 20
    batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
    all_translated = []

    endpoints = [
        f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl={source_lang}&tl={target_lang}",
        f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_lang}&tl={target_lang}&dt=t"
    ]

    for batch in batches:
        tagged_input = " ".join([f"[[{idx}]] {t}" for idx, t in enumerate(batch) if t.strip()])
        translated_results = [""] * len(batch)
        success = False

        if not tagged_input.strip():
            all_translated.extend(batch)
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
                    time.sleep(1.0)

            if success:
                break
            time.sleep(1.5)

        for i, original in enumerate(batch):
            trans = translated_results[i].strip() if success else ""
            if trans:
                if target_lang == 'km':
                    trans = shorten_khmer_text(trans)
                all_translated.append(trans)
            else:
                all_translated.append(original)

        time.sleep(0.3)

    return all_translated

class VideoProcessor:
    def __init__(self, whisper_model_size="large-v3-turbo", source_lang=None, target_lang="km", mode="auto", use_gpu=True):
        """
        :param mode: "auto" (Smart auto-switch), "ocr" (Burnt-in video subtitles), or "whisper" (Audio ASR)
        """
        self.device = "cuda" if use_gpu else "cpu"
        self.whisper_model_size = whisper_model_size
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.mode = mode
        self.whisper_model = None
        self.ocr_engine = VideoSubtitleOCR()

    def load_whisper(self):
        if self.whisper_model is None:
            logger.info(f"Loading Whisper model '{self.whisper_model_size}' on {self.device}...")
            compute_type = "int8"
            self.whisper_model = WhisperModel(self.whisper_model_size, device=self.device, compute_type=compute_type)

    def extract_audio(self, video_path: str, audio_path: str):
        try:
            logger.info(f"Extracting audio from {video_path}")
            (
                ffmpeg
                .input(video_path)
                .output(audio_path, acodec='pcm_s16le', ac=1, ar='16000')
                .overwrite_output()
                .run(quiet=True)
            )
        except ffmpeg.Error as e:
            logger.error(f"FFmpeg audio extraction error: {e.stderr.decode()}")
            raise

    def get_cues_from_whisper(self, audio_path: str):
        self.load_whisper()
        logger.info(f"Transcribing dialogue audio: {audio_path}")
        segments, info = self.whisper_model.transcribe(audio_path, beam_size=5, language=self.source_lang)
        results = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                results.append((segment.start, segment.end, text))
        return results

    def get_cues_from_ocr(self, video_path: str):
        logger.info(f"Extracting burnt-in subtitles from video frames: {video_path}")
        cues = self.ocr_engine.extract_subtitles(video_path)
        results = []
        for c in cues:
            start_sec = c['startMs'] / 1000.0
            end_sec = c['endMs'] / 1000.0
            results.append((start_sec, end_sec, c['text']))
        return results

    def extract_dialogues(self, video_path: str, audio_path: str):
        """
        Dual-protection workflow:
        1. If mode is "ocr" -> Uses Video OCR
        2. If mode is "whisper" -> Uses Whisper
        3. If mode is "auto":
           - Checks if video has hardcoded subtitles (Chinese/English on screen).
           - If yes -> extracts via High-Precision Video OCR!
           - If no subtitles on screen -> automatically falls back to Whisper!
        """
        if self.mode == "ocr":
            return self.get_cues_from_ocr(video_path)

        if self.mode == "auto":
            try:
                if self.ocr_engine.has_hardcoded_subtitles(video_path, check_seconds=35.0):
                    logger.info("✅ Burnt-in subtitles detected on screen! Using Video Subtitle OCR...")
                    ocr_cues = self.get_cues_from_ocr(video_path)
                    if len(ocr_cues) >= 3:
                        return ocr_cues
            except Exception as e:
                logger.warning(f"OCR check warning: {e}")

        logger.info("ℹ️ Using Whisper Speech-to-Text on dialogue audio...")
        self.extract_audio(video_path, audio_path)
        return self.get_cues_from_whisper(audio_path)

    def format_time(self, seconds: float):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"

    def write_srt(self, segments, srt_path: str):
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, (start, end, text) in enumerate(segments, start=1):
                f.write(f"{i}\n")
                f.write(f"{self.format_time(start)} --> {self.format_time(end)}\n")
                f.write(f"{text}\n\n")

    def burn_subtitles(self, video_path: str, srt_path: str, output_path: str, font_size=24):
        try:
            logger.info(f"Burning subtitles into {output_path}")
            srt_escaped = srt_path.replace("\\", "/").replace(":", "\\\\:")
            style = f"FontSize={font_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=0,MarginV=20"
            (
                ffmpeg
                .input(video_path)
                .output(output_path, vf=f"subtitles='{srt_escaped}':force_style='{style}'", vcodec="libx264", acodec="copy")
                .overwrite_output()
                .run(quiet=True)
            )
        except ffmpeg.Error as e:
            logger.error(f"FFmpeg subtitle encoding error: {e.stderr.decode()}")
            raise

    def process_video(self, video_path: str, output_path: str, font_size=24):
        base_name = os.path.splitext(video_path)[0]
        audio_path = f"{base_name}_temp_audio.wav"
        srt_path = f"{base_name}_temp.srt"

        try:
            raw_segments = self.extract_dialogues(video_path, audio_path)
            if not raw_segments:
                raise ValueError("No dialogues or subtitles detected in video!")

            # Translate using Protected Tag-Delimited Batch Google Translate
            original_texts = [seg[2] for seg in raw_segments]
            translated_texts = translate_texts_batch_google(original_texts, target_lang=self.target_lang)

            translated_segments = []
            for i, seg in enumerate(raw_segments):
                translated_segments.append((seg[0], seg[1], translated_texts[i]))

            self.write_srt(translated_segments, srt_path)
            self.burn_subtitles(video_path, srt_path, output_path, font_size=font_size)
            return True, f"Successfully processed {os.path.basename(video_path)} ({len(translated_segments)} subtitles)"
        except Exception as e:
            logger.error(f"Failed to process {video_path}: {e}")
            return False, str(e)
        finally:
            if os.path.exists(audio_path):
                os.remove(audio_path)
            if os.path.exists(srt_path):
                os.remove(srt_path)
