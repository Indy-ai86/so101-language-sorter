"""リーダーアームでフォロワーを動かし、仕分けに使う姿勢を Enter で記録する。

  python teach.py              # 全部を順に記録
  python teach.py --only bin_left,grid_1_1   # 一部だけ記録し直す
  python teach.py --test-lift  # 記録後、持ち上げ方向（hover_lift_deg の符号）を確かめる
  python teach.py --test-bins  # 物を持たずに各カップで「下ろす→開く→閉じる→抜く」を試し、爪が引っかからないか確かめる
  python teach.py --only grid --fix-roll 21   # 方眼の9点だけ、手首のひねりを 21 度に固定して記録し直す
  python teach.py --only grid_1_2 --fix-roll 20.8 --fix-gripper   # 爪の開きも実行時（gripper_open）と同じにして記録

記録する姿勢:
  home        待機姿勢。カメラに写らず、トルクが切れても倒れない畳んだ姿勢
  grid_i_k    方眼の点 (grid_x[i], grid_y[k]) で、グリッパーを開いて物体を掴む高さまで下ろした姿勢
  gripper     アヒルを実際に掴んで閉じたときのグリッパーの値（どの点でもよい）
  bin_*       各カップの真上で、物体を離す姿勢
"""
import argparse
import threading
import time

from arm import (JOINTS, connect_follower, connect_leader, lifted, load_poses, move_to, read, retry,
                 save_poses, send)
from common import ROOT, load_config


def steps(cfg):
    a = cfg["arm"]
    out = [("home", "待機姿勢（カメラに写らない・畳んだ姿勢）")]
    # 座っている位置からは画像と机の向きが違って見えるので、座標ではなくカップとアームの根元を目印に案内する
    cols = ["左のカップ側", "真ん中", "右のカップ側"]
    rows = ["アームの根元に近い側", "真ん中", "下のカップに近い側"]
    for k, y in enumerate(a["grid_y"]):
        for i, x in enumerate(a["grid_x"]):
            out.append((f"grid_{i}_{k}", f"{rows[k]}の行・{cols[i]}の列（枠の角から {x}cm × {y}cm）で、"
                                         "グリッパーを開いて掴む高さまで下ろす"))
    out.append(("gripper", "どこかでアヒルを実際に掴んで、グリッパーを閉じる"))
    for b in cfg["bins"]:
        # 挟んだアヒルは固定側の爪に寄るので、爪の隙間ではなくアヒル自体をカップの中心に合わせる（--fix-gripper は付けない）
        out.append((f"bin_{b}", f"アヒルを挟んだまま、アヒルの中心が {b} のカップの真上に来る位置（底が縁より 1〜2cm 上）"))
    return out


def mirror(robot, leader, stop, hz, errors, fix_roll=None, fix_gripper=None):
    try:
        while not stop.is_set():
            action = retry(leader.get_action, "リーダーの読み取り")
            if fix_roll is not None:
                # 点ごとに手首のひねりが違うと、補間した姿勢で爪の位置がずれる。記録中は一定に保つ
                action["wrist_roll.pos"] = fix_roll
            if fix_gripper is not None:
                # 片側の爪だけが動くので、開きが違うと隙間の中心がずれる。実行時と同じ開きで記録する
                action["gripper.pos"] = fix_gripper
            send(robot, action)
            time.sleep(1 / hz)
    except Exception as e:  # 追従が止まったことを入力待ちの側に伝える
        errors.append(e)
        stop.set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--test-lift", action="store_true")
    ap.add_argument("--test-bins", action="store_true")
    ap.add_argument("--fix-roll", type=float, help="記録中のフォロワーの手首のひねり（wrist_roll）をこの角度に固定する")
    ap.add_argument("--fix-gripper", action="store_true", help="記録中の爪の開きを config の gripper_open に固定する")
    args = ap.parse_args()

    cfg = load_config()
    path = ROOT / cfg["arm"]["poses_file"]
    poses = load_poses(cfg) if path.exists() else {"grid": {}}

    robot = connect_follower(cfg)
    try:
        if args.test_lift:
            test_lift(robot, cfg, poses)
            return
        if args.test_bins:
            test_bins(robot, cfg, poses)
            return

        leader = connect_leader(cfg)
        # 追従を始める前に、フォロワーをリーダーの姿勢までゆっくり合わせる（いきなり追従させると速く動いて危ない）
        print("フォロワーをリーダーの姿勢にゆっくり合わせます")
        start = retry(leader.get_action, "リーダーの読み取り")
        fix_gripper = float(cfg["arm"]["gripper_open"]) if args.fix_gripper else None
        if args.fix_roll is not None:
            start["wrist_roll.pos"] = args.fix_roll
        if fix_gripper is not None:
            start["gripper.pos"] = fix_gripper
        move_to(robot, cfg, {j: float(start[f"{j}.pos"]) for j in JOINTS}, speed_scale=0.5)
        stop, errors = threading.Event(), []
        th = threading.Thread(target=mirror, args=(robot, leader, stop, cfg["arm"]["hz"], errors, args.fix_roll, fix_gripper), daemon=True)
        th.start()
        todo = steps(cfg)
        if args.only:
            want = args.only.split(",")
            # "grid" や "bin" のように先頭だけ書けば、まとめて指定できる
            todo = [s for s in todo if any(s[0] == w or s[0].startswith(w + "_") for w in want)]
        print("リーダーを動かすとフォロワーが追従します。姿勢が決まったら Enter（s で飛ばす、q で中断して保存）")
        for n, (key, desc) in enumerate(todo, 1):
            ans = input(f"({n}/{len(todo)}) [{key}] {desc} > ").strip().lower()
            if errors:
                raise SystemExit(f"追従が止まりました: {errors[0]!r}")
            if ans == "q":
                break
            if ans == "s":
                continue
            pose = read(robot)
            if key == "gripper":
                poses["gripper_closed"] = pose["gripper"]
            elif key.startswith("grid_"):
                _, i, k = key.split("_")
                poses["grid"][f"{i},{k}"] = pose
            else:
                poses[key] = pose
            save_poses(cfg, poses)
            print("   記録:", {j: round(pose[j], 1) for j in JOINTS})
        stop.set()
        th.join()
        check_grid(poses)
        leader.disconnect()
        if "home" in poses:
            print("待機姿勢に戻します")
            move_to(robot, cfg, poses["home"], speed_scale=0.5)
    finally:
        robot.disconnect()


def check_grid(poses):
    """記録の取り違え（順番のずれ・縦横の入れ替え）を見つける。

    方眼の右の列ほど肩の旋回（shoulder_pan）が小さく、アームから遠い行ほど肩が前に倒れる（shoulder_lift が大きい）。
    この並びが崩れていたら、どこかの点を別の位置で記録している。
    """
    g = poses.get("grid", {})
    if len(g) < 9:
        return True
    bad = []
    for k in range(3):
        pans = [g[f"{i},{k}"]["shoulder_pan"] for i in range(3)]
        if not (pans[0] > pans[1] > pans[2]):
            bad.append(f"行 {k}（左→右）の旋回角が順に小さくなっていない: {[round(v, 1) for v in pans]}")
    for i in range(3):
        lifts = [g[f"{i},{k}"]["shoulder_lift"] for k in range(3)]
        if not (lifts[0] < lifts[1] < lifts[2]):
            bad.append(f"列 {i}（根元側→下のカップ側）の肩の角度が順に大きくなっていない: {[round(v, 1) for v in lifts]}")
    if bad:
        print("注意: 方眼の記録の並びがおかしいところがあります。取り違えた点を記録し直してください")
        for b in bad:
            print("  -", b)
    else:
        print("方眼の9点の並びは正常です")
    return not bad


def test_lift(robot, cfg, poses):
    g = poses["grid"].get("1,1")
    if not g or "home" not in poses:
        raise SystemExit("home と grid_1_1 を先に記録してください")
    deg = cfg["arm"]["hover_lift_deg"]
    print("真ん中の点の上空 → 掴む高さ → 上空 の順に動かします。持ち上がる方向に動くか見てください")
    move_to(robot, cfg, lifted(g, deg), speed_scale=0.5)
    move_to(robot, cfg, g, speed_scale=0.5)
    time.sleep(0.5)
    move_to(robot, cfg, lifted(g, deg), speed_scale=0.5)
    ans = input("上に持ち上がりましたか？ [y/n] > ").strip().lower()
    if ans == "n":
        print(f"config.yaml の hover_lift_deg と carry_lift_deg の符号を反転してください（いまは {deg}）")
    move_to(robot, cfg, poses["home"], speed_scale=0.5)


def test_bins(robot, cfg, poses):
    """置き場の姿勢を記録し直したら、物を運ぶ前に必ずこれで確かめる（爪がカップに掛かると、カップごと運んでしまう）。"""
    from arm import travel
    a = cfg["arm"]
    closed = poses["gripper_closed"]
    opened = a.get("gripper_release", 35)
    for b in cfg["bins"]:
        if input(f"{b} のカップを試します。Enter で開始（s で飛ばす）> ").strip() == "s":
            continue
        bin_pose = poses[f"bin_{b}"]
        above = lifted(bin_pose, a["bin_hover_deg"])
        travel(robot, cfg, poses, {**above, "gripper": closed}, speed_scale=0.5)
        move_to(robot, cfg, {**bin_pose, "gripper": closed}, speed_scale=0.3)
        # 下ろした所で止めて、指令と実際の関節角の差を出す。差が大きい関節は、届いていない（垂れている・何かに当たっている）。
        # 差が小さいのに位置がずれるなら、モーターと腕の取り付け（ねじ・ホーン）がずれている
        time.sleep(1.0)
        now = read(robot)
        print("  指令との差（度）: " + "  ".join(f"{j} {now[j] - bin_pose[j]:+.1f}" for j in JOINTS if j != "gripper"))
        move_to(robot, cfg, {**bin_pose, "gripper": opened}, speed_scale=0.5)
        time.sleep(0.5)
        move_to(robot, cfg, {**bin_pose, "gripper": closed}, speed_scale=0.5)
        move_to(robot, cfg, {**above, "gripper": closed}, speed_scale=0.3)
        travel(robot, cfg, poses, poses["home"], speed_scale=0.5)
        ans = input("  爪はカップの縁より上で開き、カップに触れずに抜けましたか？ [y/n] > ").strip().lower()
        if ans == "n":
            print(f"  python teach.py --only bin_{b} --fix-roll 20.8 で、もう少し高い位置に記録し直してください")


if __name__ == "__main__":
    main()
