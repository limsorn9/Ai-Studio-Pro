"""
Script to cleanly remove outer black background from assets in:
"D:\Ai Studio Pro\app_source\out\renderer\assets\PNG"
"""
import os
import cv2
import numpy as np

PNG_DIR = r"D:\Ai Studio Pro\app_source\out\renderer\assets\PNG"

def remove_outer_black(filepath):
    img = cv2.imread(filepath)
    if img is None:
        raise ValueError(f"Could not read image: {filepath}")
        
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Compute Canny edges to delineate the frame/subject boundary
    edges = cv2.Canny(gray, 25, 75)
    # Clear outer 5px of edges to ensure the perimeter is open for seeds
    edges[:5, :] = 0; edges[-5:, :] = 0; edges[:, :5] = 0; edges[:, -5:] = 0
    
    # Dilate edges into a solid wall that prevents leakage into inner shadows
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    wall = cv2.dilate(edges, kernel)
    wall[:3, :] = 0; wall[-3:, :] = 0; wall[:, :3] = 0; wall[:, -3:] = 0
    
    traversable = (wall == 0).astype(np.uint8)
    
    # Seeds from the perimeter
    seed = np.zeros((h, w), dtype=np.uint8)
    seed[0, :] = 1; seed[-1, :] = 1; seed[:, 0] = 1; seed[:, -1] = 1
    
    num_l, labels = cv2.connectedComponents(traversable, connectivity=8)
    edge_l = set(np.unique(labels[seed == 1]))
    if 0 in edge_l:
        edge_l.remove(0)
    
    outer_bg = np.isin(labels, list(edge_l))
    
    # Dilate outer_bg slightly to meet content edge
    outer_bg_dilated = cv2.dilate(outer_bg.astype(np.uint8), np.ones((5, 5), np.uint8)) == 1
    
    # Build smooth anti-aliased alpha
    alpha = np.ones((h, w), dtype=np.float32) * 255.0
    alpha[outer_bg_dilated] = 0.0
    
    # Anti-alias transition border
    edge_band = cv2.dilate(outer_bg_dilated.astype(np.uint8), np.ones((3, 3), np.uint8)) - cv2.erode(outer_bg_dilated.astype(np.uint8), np.ones((3, 3), np.uint8))
    blurred = cv2.GaussianBlur(alpha, (5, 5), 1.2)
    alpha[edge_band == 1] = blurred[edge_band == 1]
    
    bgra = np.dstack([img, np.clip(alpha, 0, 255).astype(np.uint8)])
    cv2.imwrite(filepath, bgra)
    
    trans_pct = np.mean(bgra[:, :, 3] < 10) * 100
    corners = [bgra[0,0,3], bgra[0,-1,3], bgra[-1,0,3], bgra[-1,-1,3]]
    print(f"Processed: {os.path.basename(filepath)} | Trans: {trans_pct:.1f}% | Corners: {corners}")

def main():
    files = sorted([f for f in os.listdir(PNG_DIR) if f.lower().endswith(".png")])
    print(f"Processing {len(files)} files in {PNG_DIR}...")
    for f in files:
        fpath = os.path.join(PNG_DIR, f)
        remove_outer_black(fpath)
    print("Done processing all files!")

if __name__ == "__main__":
    main()
