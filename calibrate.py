"""俯瞰カメラの画像上の机の四隅と、机の実寸（cm）を対応づける。

カメラを動かしたら必ずやり直す。

  python calibrate.py                      # カメラ画像で四隅をクリック
  python calibrate.py --image test.jpg     # 保存済み画像で
  python calibrate.py --points 10,10 630,12 628,470 8,468   # クリックなしで指定
  python calibrate.py --auto               # 白い紙の四隅を自動で検出（アームとケーブルを紙の外に出してから）

向きはカメラ画像で見たときの上下左右に合わせる（アームの位置とは無関係）。
"""
import argparse
import json

import cv2
import numpy as np

from common import ROOT, grab_frame, load_config

ORDER = ["左上", "右上", "右下", "左下"]
# cv2.putText は日本語を描けないので画像上の表記は英字にする
LABELS = ["TL", "TR", "BR", "BL"]


def click_corners(frame):
    pts = []
    view = frame.copy()

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append((x, y))
            cv2.circle(view, (x, y), 5, (0, 0, 255), -1)
            cv2.putText(view, LABELS[len(pts) - 1], (x + 6, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

    win = "calibrate: click 4 corners (top-left, top-right, bottom-right, bottom-left) / r=redo q=quit"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)
    print("画像で見たときの四隅を次の順にクリック:", " → ".join(ORDER))
    while True:
        cv2.imshow(win, view)
        key = cv2.waitKey(20) & 0xFF
        if key == ord("r"):
            pts.clear()
            view[:] = frame
        if key == ord("q"):
            raise SystemExit("中止しました")
        if len(pts) == 4:
            cv2.imshow(win, view)
            cv2.waitKey(500)
            break
    cv2.destroyAllWindows()
    return pts


def auto_corners(frame):
    """画面内で最も大きい白っぽい四角形（方眼紙など）の四隅を返す。"""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # 紙は彩度が低く明るい。方眼の線で途切れないよう閉じてから輪郭を取る
    mask = cv2.inRange(hsv, (0, 0, 150), (179, 60, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise SystemExit("白い紙が見つかりません。--points か手動クリックで指定してください")
    c = max(contours, key=cv2.contourArea)
    quad = cv2.approxPolyDP(cv2.convexHull(c), 0.02 * cv2.arcLength(c, True), True).reshape(-1, 2)
    if len(quad) != 4:
        raise SystemExit(f"紙の角が4つに定まりません（{len(quad)} 個）。アームやケーブルが紙にかかっていないか確認してください")
    # 左上→右上→右下→左下 に並べ替える
    s, d = quad.sum(1), np.diff(quad, axis=1).ravel()
    return [tuple(int(v) for v in quad[i]) for i in (s.argmin(), d.argmin(), s.argmax(), d.argmax())]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--points", nargs=4, metavar="X,Y")
    ap.add_argument("--auto", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    frame = grab_frame(cfg, args.image)
    if args.points:
        pts = [tuple(int(v) for v in p.split(",")) for p in args.points]
    elif args.auto:
        pts = auto_corners(frame)
    else:
        pts = click_corners(frame)

    w, h = cfg["table_cm"]["width"], cfg["table_cm"]["height"]
    # 机の座標（cm）：x は画像の左→右、y は画像の上→下
    dst = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(np.array(pts, dtype=np.float32), dst)

    out = ROOT / cfg["calib_file"]
    with open(out, "w") as f:
        json.dump({"corners_px": pts, "table_cm": [w, h], "homography": H.tolist()}, f, indent=2)
    check = frame.copy()
    cv2.polylines(check, [np.array(pts, dtype=np.int32)], True, (0, 0, 255), 2)
    for name, p in zip(LABELS, pts):
        cv2.putText(check, name, (p[0] + 6, p[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    cv2.imwrite(str(ROOT / "calib_frame.jpg"), check)
    print(f"保存しました: {out.name}（四隅 {pts}）")


if __name__ == "__main__":
    main()
