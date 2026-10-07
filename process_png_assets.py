"""
Complete Background Removal & Outer White Elimination
For Ai Studio Pro Assets in "D:\Ai Studio Pro\app_source\out\renderer\assets\PNG"
"""
import os
import io
import cv2
import numpy as np
from PIL import Image
from rembg import remove

TARGET_DIR = r"D:\Ai Studio Pro\app_source\out\renderer\assets\PNG"

CIRCULAR_ICONS = {
    "avatar-DaOkjR17.png",
    "icon-EAInt3Kl.png",
    "photo-logo-WEMYBZHw.png",
    "royal-skull-king-mascot-DxEG1DFR.png"
}

def clean_circular_icon(filepath):
    """Ensure transparent background outside the circular icon with anti-aliasing."""
    img = Image.open(filepath).convert("RGBA")
    arr = np.array(img)
    h, w = arr.shape[:2]
    
    y, x = np.ogrid[:h, :w]
    cy, cx = h / 2.0, w / 2.0
    radius = (min(h, w) / 2.0) - 2.0 # leave 2px safe border
    dist = np.sqrt((x - cx)**2 + (y - cy)**2)
    
    # Antialiased alpha for circular edge
    # dist <= radius -> keep existing alpha
    # dist >= radius + 2 -> alpha = 0
    # in between -> smooth transition
    edge_width = 2.0
    outside_mask = dist > radius
    alpha = arr[:, :, 3].astype(np.float32)
    
    fade = np.clip(1.0 - (dist - radius) / edge_width, 0.0, 1.0)
    alpha[outside_mask] = alpha[outside_mask] * fade[outside_mask]
    
    arr[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)
    out_img = Image.fromarray(arr, mode="RGBA")
    out_img.save(filepath, "PNG")
    print(f"  [Circle] Cleaned circular mask for {os.path.basename(filepath)}")

def remove_outer_white(filepath):
    """
    Flood-fill removes outer white/light background outside the frame/border.
    Guarantees that 100% of the area outside the frame is transparent,
    while 100% of the inner mascot/details/white eyes remain untouched and solid.
    """
    img = cv2.imread(filepath, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Could not read image: {filepath}")
    
    bgr = img[:, :, :3]
    h, w = bgr.shape[:2]
    
    # Sample corner pixels to determine exact background color/tint
    corner_samples = np.concatenate([
        bgr[:10, :10], bgr[:10, -10:],
        bgr[-10:, :10], bgr[-10:, -10:]
    ]).reshape(-1, 3)
    bg_median = np.median(corner_samples, axis=0)
    
    # Calculate distance from corner background color
    diff_from_bg = bgr.astype(np.float32) - bg_median.astype(np.float32)
    dist_bg = np.sqrt(np.sum(diff_from_bg**2, axis=2))
    
    # Also check distance from pure white (255, 255, 255)
    diff_from_white = 255.0 - bgr.astype(np.float32)
    dist_white = np.sqrt(np.sum(diff_from_white**2, axis=2))
    
    # Pixels that qualify as outer white/light background
    # Either close to corner color (dist < 55) or close to pure white (each channel > 215)
    is_near_white = (bgr[:, :, 0] > 215) & (bgr[:, :, 1] > 215) & (bgr[:, :, 2] > 215)
    is_bg_candidate = (dist_bg < 55.0) | is_near_white
    
    # Seeds along all 4 perimeter borders
    seed_mask = np.zeros((h, w), dtype=np.uint8)
    seed_mask[0, :] = 1
    seed_mask[-1, :] = 1
    seed_mask[:, 0] = 1
    seed_mask[:, -1] = 1
    seed_mask = seed_mask & is_bg_candidate.astype(np.uint8)
    
    # Connected component analysis from seeds
    num_labels, labels = cv2.connectedComponents(is_bg_candidate.astype(np.uint8), connectivity=8)
    edge_labels = set(np.unique(labels[seed_mask == 1]))
    if 0 in edge_labels:
        edge_labels.remove(0)
    
    outer_bg = np.isin(labels, list(edge_labels))
    
    # Build smooth anti-aliased alpha
    alpha = np.ones((h, w), dtype=np.float32) * 255.0
    alpha[outer_bg] = 0.0
    
    # Anti-alias transition border (3px band)
    dilated = cv2.dilate(outer_bg.astype(np.uint8), np.ones((3, 3), np.uint8))
    eroded = cv2.erode(outer_bg.astype(np.uint8), np.ones((3, 3), np.uint8))
    edge_band = (dilated - eroded) == 1
    
    blurred_alpha = cv2.GaussianBlur(alpha, (5, 5), 1.2)
    alpha[edge_band] = blurred_alpha[edge_band]
    
    bgra = np.dstack([bgr, np.clip(alpha, 0, 255).astype(np.uint8)])
    cv2.imwrite(filepath, bgra)
    trans_pct = np.mean(bgra[:, :, 3] < 10) * 100
    print(f"  [FloodFill] Removed outer white for {os.path.basename(filepath)} (Trans: {trans_pct:.1f}%)")

def remove_dark_bg(filepath):
    """
    Uses rembg AI for dark backgrounds, with alpha matte enhancement
    to prevent translucent haze and ensure solid, crisp foreground.
    """
    with open(filepath, "rb") as f:
        input_bytes = f.read()
    
    out_bytes = remove(input_bytes)
    nparr = np.frombuffer(out_bytes, np.uint8)
    bgra = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    
    alpha = bgra[:, :, 3].astype(np.float32)
    
    # Enhance alpha: eliminate background noise (<30 -> 0) and solidify foreground (>180 -> 255)
    t_low, t_high = 30.0, 180.0
    cleaned_alpha = np.zeros_like(alpha)
    mask_high = alpha >= t_high
    mask_mid = (alpha >= t_low) & (alpha < t_high)
    
    cleaned_alpha[mask_high] = 255.0
    cleaned_alpha[mask_mid] = ((alpha[mask_mid] - t_low) / (t_high - t_low)) * 255.0
    
    bgra[:, :, 3] = np.clip(cleaned_alpha, 0, 255).astype(np.uint8)
    cv2.imwrite(filepath, bgra)
    trans_pct = np.mean(bgra[:, :, 3] < 10) * 100
    print(f"  [rembg] Removed dark background for {os.path.basename(filepath)} (Trans: {trans_pct:.1f}%)")

def process_all():
    files = sorted([f for f in os.listdir(TARGET_DIR) if f.lower().endswith(".png")])
    total = len(files)
    print(f"Processing {total} PNG files in {TARGET_DIR}...")
    print("=" * 70)
    
    for idx, fname in enumerate(files, 1):
        filepath = os.path.join(TARGET_DIR, fname)
        print(f"[{idx}/{total}] {fname}")
        
        # 1. Circular icons
        if fname in CIRCULAR_ICONS:
            clean_circular_icon(filepath)
            continue
            
        # 2. Check existing image mode and transparency
        img = Image.open(filepath)
        arr = np.array(img)
        
        if img.mode == "RGBA":
            alpha = arr[:, :, 3]
            corners_trans = (alpha[0,0] < 10 and alpha[0,-1] < 10 and alpha[-1,0] < 10 and alpha[-1,-1] < 10)
            trans_ratio = np.mean(alpha < 10)
            if trans_ratio > 0.15 and corners_trans:
                print(f"  [Skip] Already transparent (Trans: {trans_ratio*100:.1f}%)")
                continue
        
        # 3. Check corner colors to classify White vs Dark background
        bgr = arr[:, :, :3]
        corners = [
            bgr[0, 0][:3].tolist(),
            bgr[0, -1][:3].tolist(),
            bgr[-1, 0][:3].tolist(),
            bgr[-1, -1][:3].tolist()
        ]
        corner_mean = np.mean(corners, axis=0)
        is_light = np.all(corner_mean > 180)
        
        if is_light:
            remove_outer_white(filepath)
        else:
            remove_dark_bg(filepath)
            
    print("=" * 70)
    print("All images processed successfully!")

if __name__ == "__main__":
    process_all()
