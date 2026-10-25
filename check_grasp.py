"""掴む姿勢のずれを測る。アヒルを1個置いた状態で使う。

待機姿勢で撮影 → 爪を開いたまま掴む姿勢まで下ろして止めて撮影 → 待機姿勢に戻る。
2 枚の画像を runs/check/<時刻>/ に保存するので、爪とアヒルの位置関係を見比べる。

  python check_grasp.py
  python check_grasp.py --hold 5   # 下ろした状態で止める秒数
"""
import argparse
import time
from datetime import datetime

import cv2

from arm import connect_follower, grasp_pose_at, lifted, load_poses, move_to, travel
from common import ROOT, grab_frame, load_calib, load_config, px_to_cm
from record import annotate, detect, table_mask


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=2.0)
    args = ap.parse_args()

    cfg = load_config()
    poses = load_poses(cfg)
    corners, H = load_calib(cfg)
    out = ROOT / "runs" / "check" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    robot = connect_follower(cfg)
    try:
        move_to(robot, cfg, poses["home"], speed_scale=0.5)
        frame = grab_frame(cfg)
        objs = detect(frame, cfg, table_mask(frame.shape, corners))
        if len(objs) != 1:
            raise SystemExit(f"物体を1個だけ置いてください（いま {len(objs)} 個）")
        o = objs[0]
        x, y = px_to_cm(H, [o["pixel"]])[0]
        print(f"物体: {'+'.join(o['colors'])} 画像 {o['pixel']} → 机の {x:.1f}cm, {y:.1f}cm")
        cv2.imwrite(str(out / "1_object.jpg"), annotate(frame, corners, objs))

        g = grasp_pose_at(cfg, poses, x, y)
        travel(robot, cfg, poses, lifted(g, cfg["arm"]["hover_lift_deg"]), speed_scale=0.5)
        move_to(robot, cfg, g, speed_scale=0.3)
        time.sleep(args.hold)
        frame2 = grab_frame(cfg)
        cv2.polylines(frame2, [corners.astype("int32")], True, (255, 255, 255), 1)
        cv2.drawMarker(frame2, (int(o["pixel"][0]), int(o["pixel"][1])), (0, 0, 255), cv2.MARKER_CROSS, 16, 2)
        cv2.imwrite(str(out / "2_at_grasp.jpg"), frame2)
        move_to(robot, cfg, lifted(g, cfg["arm"]["hover_lift_deg"]), speed_scale=0.5)
        travel(robot, cfg, poses, poses["home"], speed_scale=0.5)
    finally:
        move_to(robot, cfg, poses["home"], speed_scale=0.5)
        robot.disconnect()
    print(f"保存しました: {out.relative_to(ROOT)}（赤い十字が撮影時の物体の中心）")


if __name__ == "__main__":
    main()
