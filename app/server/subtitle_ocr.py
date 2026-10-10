import os
import cv2
import re
import logging
from rapidocr_onnxruntime import RapidOCR

logger = logging.getLogger(__name__)

class VideoSubtitleOCR:
    def __init__(self, crop_bottom_ratio=0.20, sample_fps=2.5, min_confidence=0.55):
        """
        AI Subtitle Extractor from video frames.
        :param crop_bottom_ratio: Portion of bottom screen to inspect (e.g. 0.20 = bottom 20%)
        :param sample_fps: Frames to check per second (e.g. 2.5 = every 400ms)
        :param min_confidence: Minimum OCR confidence threshold
        """
        self.ocr = RapidOCR()
        self.crop_bottom_ratio = crop_bottom_ratio
        self.sample_fps = sample_fps
        self.min_confidence = min_confidence

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        # Remove common OCR noise, timestamp overlays or standalone symbols
        cleaned = re.sub(r'[\r\n\t]+', ' ', text)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        # Filter out lone single symbols like "|", "_", "-", "."
        if len(cleaned) <= 1 and not re.search(r'[\u4e00-\u9fff\w]', cleaned):
            return ""
        return cleaned

    def _is_similar(self, text1: str, text2: str) -> bool:
        t1 = re.sub(r'\s+', '', text1).lower()
        t2 = re.sub(r'\s+', '', text2).lower()
        if t1 == t2:
            return True
        if len(t1) > 4 and len(t2) > 4:
            if t1 in t2 or t2 in t1:
                return True
        return False

    def extract_subtitles(self, video_path: str, max_duration_sec: float = None) -> list:
        """
        Extract burnt-in subtitles from video file into list of cues:
        [{ 'id': 'c_0', 'startMs': int, 'endMs': int, 'text': str }]
        """
        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return []

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Cannot open video file: {video_path}")
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        max_frames = total_frames
        if max_duration_sec:
            max_frames = min(total_frames, int(fps * max_duration_sec))

        y_start = int(height * (1.0 - self.crop_bottom_ratio))
        step = max(1, int(fps / self.sample_fps))

        logger.info(f"Scanning subtitles: {width}x{height}, FPS: {fps:.1f}, Step: {step} frames")

        raw_cues = []
        current_cue = None
        frame_idx = 0

        while cap.isOpened() and frame_idx < max_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                break

            timestamp_ms = int((frame_idx / fps) * 1000)
            crop = frame[y_start:height, 0:width]

            res, _ = self.ocr(crop)
            detected_text = ""
            if res:
                fragments = [item[1] for item in res if item[2] >= self.min_confidence]
                detected_text = self._clean_text(" ".join(fragments))

            if detected_text:
                if current_cue and self._is_similar(current_cue['text'], detected_text):
                    # Extend active subtitle time
                    current_cue['endMs'] = timestamp_ms + int(1000 / self.sample_fps)
                else:
                    if current_cue:
                        raw_cues.append(current_cue)
                    current_cue = {
                        'startMs': timestamp_ms,
                        'endMs': timestamp_ms + int(1000 / self.sample_fps),
                        'text': detected_text
                    }
            else:
                if current_cue:
                    raw_cues.append(current_cue)
                    current_cue = None

            frame_idx += step

        if current_cue:
            raw_cues.append(current_cue)

        cap.release()

        # Post-filter: merge tiny gaps & discard noise shorter than 300ms
        final_cues = []
        for i, cue in enumerate(raw_cues):
            duration = cue['endMs'] - cue['startMs']
            if duration < 300 and len(cue['text']) < 3:
                continue
            cue['id'] = f"c_{len(final_cues)}"
            final_cues.append(cue)

        logger.info(f"Subtitle OCR completed: found {len(final_cues)} cues")
        return final_cues

    def has_hardcoded_subtitles(self, video_path: str, check_seconds: float = 45.0) -> bool:
        """
        Sample check to see if video contains burnt-in subtitles.
        """
        cues = self.extract_subtitles(video_path, max_duration_sec=check_seconds)
        # If at least 3 distinct subtitle cues detected in sample duration
        return len(cues) >= 3
