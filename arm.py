import json
import time

import numpy as np

from common import ROOT

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def connect_follower(cfg):
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

    a = cfg["arm"]
    robot = SO101Follower(SO101FollowerConfig(
        # lerobot は float か dict しか受け付けない（YAML の整数 8 だと TypeError）
        port=a["follower_port"], id=a["follower_id"], max_relative_target=float(a["max_step_deg"])))
    robot.connect()
    return robot


def connect_leader(cfg):
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

    a = cfg["arm"]
    leader = SO101Leader(SO101LeaderConfig(port=a["leader_port"], id=a["leader_id"]))
    leader.connect()
    return leader


def retry(fn, label, tries=10):
    """モーターの返事が返らないこと（There is no status packet!）がある。ケーブルの接触が戻るまで少し待ちながらやり直す。"""
    for n in range(tries):
        try:
            return fn()
        except ConnectionError as e:
            if n == tries - 1:
                raise ConnectionError(f"{label}: {e}") from e
            time.sleep(0.05 * (n + 1))


def read(robot):
    obs = retry(robot.get_observation, "フォロワーの読み取り")
    return {j: float(obs[f"{j}.pos"]) for j in JOINTS}


def send(robot, action):
    return retry(lambda: robot.send_action(action), "フォロワーへの指令")


def move_to(robot, cfg, target, speed_scale=1.0):
    """現在の姿勢から target まで、関節空間で直線補間しながらゆっくり動かす。"""
    a = cfg["arm"]
    start = read(robot)
    target = {j: target.get(j, start[j]) for j in JOINTS}
    delta = max(abs(target[j] - start[j]) for j in JOINTS)
    duration = max(delta / (a["max_speed_deg_s"] * speed_scale), 0.3)
    steps = max(int(duration * a["hz"]), 1)
    for i in range(1, steps + 1):
        t = i / steps
        # 端で加減速させる（急発進・急停止でアームが揺れるのを防ぐ）
        s = t * t * (3 - 2 * t)
        send(robot, {f"{j}.pos": start[j] + (target[j] - start[j]) * s for j in JOINTS})
        time.sleep(1 / a["hz"])
    # 最後に追従しきるまで少し待つ
    for _ in range(int(0.3 * a["hz"])):
        send(robot, {f"{j}.pos": target[j] for j in JOINTS})
        time.sleep(1 / a["hz"])


def travel(robot, cfg, poses, target, speed_scale=1.0):
    """待機姿勢と同じく畳んだまま旋回してから、目標へ伸ばす。

    伸ばしたまま関節を同時に動かすと、遠い点ほど途中で低く広く振れてカップに当たる。
    畳むと home と同じ形になるので、物体を持っていない区間でだけ使う。
    """
    home = poses["home"]
    now = read(robot)
    fold = {**home, "shoulder_pan": now["shoulder_pan"]}
    move_to(robot, cfg, fold, speed_scale=speed_scale)
    move_to(robot, cfg, {**fold, "shoulder_pan": target["shoulder_pan"]}, speed_scale=speed_scale)
    move_to(robot, cfg, target, speed_scale=speed_scale)


def load_poses(cfg):
    path = ROOT / cfg["arm"]["poses_file"]
    if not path.exists():
        raise SystemExit(f"{path.name} がありません。先に teach.py で姿勢を記録してください")
    with open(path) as f:
        return json.load(f)


def save_poses(cfg, poses):
    with open(ROOT / cfg["arm"]["poses_file"], "w") as f:
        json.dump(poses, f, ensure_ascii=False, indent=2)


def grasp_pose_at(cfg, poses, x, y):
    """方眼の 3×3 点で記録した掴む姿勢を、物体の位置 (x, y) cm で双線形補間する。範囲外は端に寄せる。"""
    a = cfg["arm"]
    gx, gy = a["grid_x"], a["grid_y"]
    dx, dy = a.get("grasp_offset_cm", [0.0, 0.0])
    x = float(np.clip(x + dx, gx[0], gx[-1]))
    y = float(np.clip(y + dy, gy[0], gy[-1]))
    i = min(int(np.searchsorted(gx, x, side="right")) - 1, len(gx) - 2)
    k = min(int(np.searchsorted(gy, y, side="right")) - 1, len(gy) - 2)
    tx = (x - gx[i]) / (gx[i + 1] - gx[i])
    ty = (y - gy[k]) / (gy[k + 1] - gy[k])

    def p(a, b):
        return poses["grid"][f"{a},{b}"]

    out = {}
    for j in JOINTS:
        top = p(i, k)[j] * (1 - tx) + p(i + 1, k)[j] * tx
        bot = p(i, k + 1)[j] * (1 - tx) + p(i + 1, k + 1)[j] * tx
        out[j] = top * (1 - ty) + bot * ty
    out["shoulder_lift"] += float(a.get("grasp_lower_deg", 0))
    if a.get("gripper_open") is not None:
        out["gripper"] = float(a["gripper_open"])
    return out


def lifted(pose, deg):
    return {**pose, "shoulder_lift": pose["shoulder_lift"] + deg}
