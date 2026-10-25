"""俯瞰カメラで1枚撮り、物体を色で検出して「状態」を保存する。

撮る前にアームを画面外の待機姿勢に戻しておくこと（物体が隠れるため）。

  python record.py                     # カメラから撮って保存
  python record.py --image test.jpg    # 保存済み画像で
  python record.py --kinds             # 物体ごとに種類（ball, block…）を入力する

保存先: runs/<日付>/<時刻>/{frame.jpg, annotated.jpg, state.json}
        runs/<日付>/states.jsonl に1行ずつ追記
"""
import argparse
import json
import math
from datetime import datetime

import cv2
import numpy as np

from common import ROOT, grab_frame, load_calib, load_config, px_to_cm


def table_mask(shape, corners):
    mask = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [corners.astype(np.int32)], 255)
    return mask


def detect(frame, cfg, roi):
    hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)
    kernel = np.ones((5, 5), np.uint8)
    dcfg = cfg["detect"]
    blobs = []
    for name, ranges in cfg["colors"].items():
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for lo, hi in ranges:
            mask |= cv2.inRange(hsv, np.array(lo), np.array(hi))
        mask &= roi
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < dcfg["min_area_px"]:
                continue
            m = cv2.moments(c)
            blobs.append({
                "color": name,
                "area": area,
                "center": (m["m10"] / m["m00"], m["m01"] / m["m00"]),
                "contour": c,
            })
    return merge(blobs, dcfg)


def merge(blobs, dcfg):
    """多色の物体（例：ピンクと緑のボール）が色ごとに別物として出るので、近いものを1つにまとめる。"""
    blobs.sort(key=lambda b: -b["area"])
    groups = []
    m = dcfg["merge_dist_px"]
    for b in blobs:
        bx, by, bw, bh = cv2.boundingRect(b["contour"])
        for g in groups if dcfg.get("merge_multicolor") else []:
            # 色の境目で接している部分どうしを拾うため、外接矩形を少し広げて重なりを見る
            gx, gy, gw, gh = cv2.boundingRect(np.vstack([p["contour"] for p in g["parts"]]))
            if not (bx < gx + gw + m and gx < bx + bw + m and by < gy + gh + m and gy < by + bh + m):
                continue
            # 接しているだけの別の物（箱とアヒルなど）は、まとめると凸包に大きな隙間ができるので除外する
            parts = g["parts"] + [b]
            hull = cv2.convexHull(np.vstack([p["contour"] for p in parts]))
            if sum(p["area"] for p in parts) / max(cv2.contourArea(hull), 1) >= dcfg["merge_min_solidity"]:
                g["parts"].append(b)
                break
        else:
            groups.append({**b, "parts": [b]})

    objects = []
    for g in groups:
        pts = np.vstack([p["contour"] for p in g["parts"]])
        hull = cv2.convexHull(pts)
        area = cv2.contourArea(hull)
        # 4πA/P² は正方形でも 0.785 と高く出て丸と紛れるので、外接円をどれだけ埋めているかで判定する（円≈1、正方形≈0.64）
        _, r = cv2.minEnclosingCircle(hull)
        circ = area / (math.pi * r * r) if r else 0.0
        m = cv2.moments(hull)
        # 面積の大きい色を先に並べる（主な色が先頭）
        colors = []
        for p in sorted(g["parts"], key=lambda p: -p["area"]):
            if p["color"] not in colors:
                colors.append(p["color"])
        objects.append({
            "colors": colors,
            "shape": "round" if circ >= dcfg["round_circularity"] else "angular",
            "circularity": round(circ, 3),
            "area_px": int(area),
            "pixel": [round(m["m10"] / m["m00"], 1), round(m["m01"] / m["m00"], 1)],
            "bbox": list(cv2.boundingRect(hull)),
            "_hull": hull,
        })
    objects.sort(key=lambda o: o["pixel"][0])
    for i, o in enumerate(objects, 1):
        o["id"] = f"o{i}"
    return objects


def annotate(frame, corners, objects):
    out = frame.copy()
    cv2.polylines(out, [corners.astype(np.int32)], True, (255, 255, 255), 1)
    for o in objects:
        cv2.drawContours(out, [o["_hull"]], -1, (0, 255, 255), 2)
        x, y = int(o["pixel"][0]), int(o["pixel"][1])
        label = f"{o['id']} {'+'.join(o['colors'])} {o['shape']}"
        cv2.putText(out, label, (x - 40, y - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
        cv2.putText(out, label, (x - 40, y - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    return out


def capture_state(cfg, image=None, note="", ask_kinds=False):
    """撮影 → 検出 → 保存して、状態（dict）と保存先フォルダを返す。"""
    corners, H = load_calib(cfg)
    frame = grab_frame(cfg, image)
    objects = detect(frame, cfg, table_mask(frame.shape, corners))

    for o, cm in zip(objects, px_to_cm(H, [o["pixel"] for o in objects])):
        o["table_cm"] = [round(float(cm[0]), 1), round(float(cm[1]), 1)]
        o["kind"] = None

    ann = annotate(frame, corners, objects)
    print(f"{len(objects)} 個検出:")
    for o in objects:
        print(f"  {o['id']}: {'+'.join(o['colors'])} / {o['shape']} (丸さ {o['circularity']}) / "
              f"机の {o['table_cm'][0]}cm, {o['table_cm'][1]}cm")

    if ask_kinds:
        cv2.imshow("record", ann)
        cv2.waitKey(300)
        for o in objects:
            v = input(f"  {o['id']} ({'+'.join(o['colors'])}) の種類（空欄で省略）: ").strip()
            o["kind"] = v or None
        cv2.destroyAllWindows()

    now = datetime.now()
    day_dir = ROOT / cfg["runs_dir"] / now.strftime("%Y%m%d")
    run_dir = day_dir / now.strftime("%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(run_dir / "frame.jpg"), frame)
    cv2.imwrite(str(run_dir / "annotated.jpg"), ann)

    state = {
        "id": f"{now:%Y%m%d}-{now:%H%M%S}",
        "timestamp": now.isoformat(timespec="seconds"),
        "note": note,
        "image": str((run_dir / "frame.jpg").relative_to(ROOT)),
        "table_cm": [cfg["table_cm"]["width"], cfg["table_cm"]["height"]],
        "objects": [{k: v for k, v in o.items() if not k.startswith("_")} for o in objects],
    }
    with open(run_dir / "state.json", "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    with open(day_dir / "states.jsonl", "a") as f:
        f.write(json.dumps(state, ensure_ascii=False) + "\n")
    print(f"保存しました: {run_dir.relative_to(ROOT)}")
    return state, run_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--kinds", action="store_true", help="物体ごとに種類を手入力する")
    ap.add_argument("--note", default="", help="この状態のメモ（配置の説明など）")
    args = ap.parse_args()
    capture_state(load_config(), args.image, args.note, args.kinds)


if __name__ == "__main__":
    main()
