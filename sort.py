"""撮影 → ルールで判断 → 掴んで置き場へ運ぶ、を通しで行う。

  python sort.py --rule r01 --dry-run    # アームは動かさず、判断と使う姿勢だけ表示
  python sort.py --rule r01 --step       # 物体ごとに Enter を待ってから動かす（最初はこれ）
  python sort.py --rule r07 --min-conf 0.7 --judge   # 自信が低い物は運ばずに残す。成否を手入力で記録
  python sort.py --rule r01 --state runs/20261024/191139/state.json --dry-run   # 保存済みの状態で
  python sort.py --rule r01 --backend astra --step --judge   # 判断を GPT-6 Astra に替える（jev も可）

Ctrl+C で止めると、待機姿勢に戻ってから終了する。
"""
import argparse
import json
import time

import yaml

from arm import connect_follower, grasp_pose_at, lifted, load_poses, move_to, travel
from common import ROOT, load_config
from decide import BACKENDS, decide_one
from record import capture_state


def plan(cfg, poses, state, decision, min_conf):
    steps = []
    for o in state["objects"]:
        ans = decision["answer"][o["id"]]
        skip = ans["confidence"] < min_conf
        x, y = o["table_cm"]
        steps.append({"obj": o, "bin": ans["bin"], "confidence": ans["confidence"], "skip": skip,
                      "grasp": None if skip else grasp_pose_at(cfg, poses, x, y)})
    return steps


def pick_and_place(robot, cfg, poses, step):
    a = cfg["arm"]
    g = step["grasp"]
    closed = max(poses["gripper_closed"] - a.get("grip_squeeze", 0), 0.0)
    opened = a.get("gripper_release", g["gripper"])
    travel(robot, cfg, poses, lifted(g, a["hover_lift_deg"]))
    move_to(robot, cfg, g, speed_scale=0.5)
    move_to(robot, cfg, {**g, "gripper": closed}, speed_scale=0.7)
    time.sleep(0.3)
    move_to(robot, cfg, {**lifted(g, a["carry_lift_deg"]), "gripper": closed}, speed_scale=0.6)
    bin_pose = poses[f"bin_{step['bin']}"]
    # カップの縁に当てないよう、真上に寄ってから下ろし、離したあとも真上に抜く
    above = lifted(bin_pose, a["bin_hover_deg"])
    move_to(robot, cfg, {**above, "gripper": closed})
    move_to(robot, cfg, {**bin_pose, "gripper": closed}, speed_scale=0.5)
    move_to(robot, cfg, {**bin_pose, "gripper": opened}, speed_scale=0.7)
    time.sleep(0.3)
    # 開いた爪がカップの内側に掛かったまま持ち上げると、カップごと運んでしまう。爪を戻してから上に抜く
    move_to(robot, cfg, {**bin_pose, "gripper": poses["gripper_closed"]}, speed_scale=0.7)
    move_to(robot, cfg, {**above, "gripper": poses["gripper_closed"]}, speed_scale=0.3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", required=True)
    ap.add_argument("--state", help="保存済みの state.json を使う（撮影しない）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--step", action="store_true", help="物体ごとに Enter を待つ")
    ap.add_argument("--min-conf", type=float, default=0.0, help="これ未満の自信の物は運ばない")
    ap.add_argument("--judge", action="store_true", help="運ぶたびに成否を入力して記録する")
    ap.add_argument("--backend", choices=BACKENDS, help="判断に使うモデル（既定は config.yaml）")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    cfg = load_config()
    backend = args.backend or cfg["decide"]["backend"]
    poses = load_poses(cfg)
    with open(ROOT / "rules.yaml") as f:
        rule = next((r for r in yaml.safe_load(f) if r["id"] == args.rule), None)
    if rule is None:
        raise SystemExit(f"ルール {args.rule} が rules.yaml にありません")

    robot = None if args.dry_run else connect_follower(cfg)
    try:
        if robot:
            # 撮影前に待機姿勢へ（アームが物体を隠さないように）
            move_to(robot, cfg, poses["home"], speed_scale=0.5)
        if args.state:
            with open(args.state) as f:
                state = json.load(f)
            run_dir = ROOT / state["image"].rsplit("/", 1)[0]
        else:
            state, run_dir = capture_state(cfg, note=args.note or f"sort {rule['id']} {backend}")
        if not state["objects"]:
            print("物体がありません")
            return

        print(f"ルール {rule['id']}: {rule['text']}（判断: {backend}）")
        decision = decide_one(cfg, state, rule, backend)
        # 一括判断（decide.py）の集計に混ざらないよう別ファイルに残す
        with open(run_dir / "sort_decisions.jsonl", "a") as f:
            f.write(json.dumps(decision, ensure_ascii=False) + "\n")

        steps = plan(cfg, poses, state, decision, args.min_conf)
        for s in steps:
            o = s["obj"]
            mark = "運ばない（自信が低い）" if s["skip"] else "→ " + s["bin"]
            print(f"  {o['id']} {'+'.join(o['colors'])} {o['shape']} {o['table_cm']} "
                  f"自信 {s['confidence']:.2f} {mark}")
        if args.dry_run:
            for s in steps:
                if s["grasp"]:
                    print(f"   {s['obj']['id']} の掴む姿勢:", {j: round(v, 1) for j, v in s["grasp"].items()})
            return

        for s in steps:
            if s["skip"]:
                continue
            if args.step and input(f"{s['obj']['id']} を {s['bin']} へ運びます。Enter で開始（s で飛ばす）> ").strip() == "s":
                continue
            t0 = time.time()
            pick_and_place(robot, cfg, poses, s)
            travel(robot, cfg, poses, poses["home"])
            rec = {"state_id": state["id"], "rule_id": rule["id"], "backend": backend, "object": s["obj"]["id"],
                   "colors": s["obj"]["colors"], "bin": s["bin"], "confidence": s["confidence"],
                   "seconds": round(time.time() - t0, 1)}
            if args.judge:
                rec["result"] = input("  結果は？ [o=成功 / g=掴めず / d=途中で落とした / b=置き場を外した] > ").strip()
            with open(run_dir / "sort_log.jsonl", "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except KeyboardInterrupt:
        print("\n中断しました")
    finally:
        if robot:
            print("待機姿勢に戻します")
            try:
                move_to(robot, cfg, poses["home"], speed_scale=0.5)
            except ConnectionError as e:  # 通信が戻らないときは、元のエラーを隠さず手動で戻してもらう
                print(f"戻せませんでした（{e}）。USB を抜き差ししてから teach.py などで待機姿勢に戻してください")
            robot.disconnect()


if __name__ == "__main__":
    main()
