import json
import time
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent


def load_config(path=ROOT / "config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def grab_frame(cfg, image_path=None):
    if image_path:
        frame = cv2.imread(str(image_path))
        if frame is None:
            raise SystemExit(f"画像を読めません: {image_path}")
        return frame
    cam = cfg["camera"]
    # macOS では AVFoundation を明示しないと index の割り当てがずれることがある
    cap = cv2.VideoCapture(cam["index"], cv2.CAP_AVFOUNDATION)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cam["width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cam["height"])
    if not cap.isOpened():
        raise SystemExit(f"カメラ {cam['index']} を開けません（macOS のカメラ権限を確認）")
    frame = None
    for _ in range(cam["warmup_frames"] + 1):
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
    cap.release()
    if frame is None:
        raise SystemExit("カメラから画像を取得できません")
    return frame


def load_calib(cfg):
    path = ROOT / cfg["calib_file"]
    if not path.exists():
        raise SystemExit(f"{path.name} がありません。先に calibrate.py を実行してください")
    with open(path) as f:
        c = json.load(f)
    return np.array(c["corners_px"], dtype=np.float32), np.array(c["homography"], dtype=np.float64)


def px_to_cm(H, pts):
    if len(pts) == 0:
        return np.empty((0, 2))
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, H).reshape(-1, 2)
