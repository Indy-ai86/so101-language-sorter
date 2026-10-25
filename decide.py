"""記録した状態に仕分けルールを当てはめ、各物体の置き場を判断させる。

1回の呼び出しで、その状態の全物体の置き場をまとめて答えさせる
（「一番大きい物だけ右へ」のように他の物体と比べるルールがあるため）。

  python decide.py runs/20261012/states.jsonl                # 全ルール
  python decide.py runs/20261012/states.jsonl --rules r01,r07
  python decide.py runs/20261012/143000/state.json --dry-run  # 送る内容だけ表示

結果は入力と同じフォルダの decisions.jsonl に追記。済んだ組み合わせは飛ばすので、途中で止めても再開できる。
"""
import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

import yaml

from common import ROOT, load_config

SYSTEM = """あなたはロボットアームの仕分け係です。机の上の物体を、ルールに従って置き場（{bins}）に振り分けます。
- 机の座標は cm。俯瞰カメラで見たときの向きで、x は左→右（0〜{w}）、y は上→下（0〜{h}）。
- colors は面積の大きい順。shape は round（丸い）か angular（角ばっている）。kind は種類で、不明なら null。
- ルールで答えが一つに決まらないときも、最も妥当な置き場を選び、confidence を低くする。
- confidence は 0〜1 の自信の度合い。"""


def load_states(path):
    path = Path(path)
    if path.suffix == ".jsonl":
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()], path.parent
    with open(path) as f:
        return [json.load(f)], path.parent.parent


def scene_text(state):
    objs = [{k: o[k] for k in ("id", "colors", "shape", "kind", "area_px", "table_cm")}
            for o in state["objects"]]
    return json.dumps(objs, ensure_ascii=False)


def schema_for(state, bins):
    item = {
        "type": "object",
        "properties": {"bin": {"type": "string", "enum": bins},
                       "confidence": {"type": "number"}},
        "required": ["bin", "confidence"],
        "additionalProperties": False,
    }
    ids = [o["id"] for o in state["objects"]]
    return {"type": "object", "properties": {i: item for i in ids},
            "required": ids, "additionalProperties": False}


def decide_fable(cfg, system, user, schema):
    """Claude Code をヘッドレスで呼ぶ。API キー不要（ログイン中のアカウントの利用枠を使う）。"""
    cmd = [
        "claude", "-p", "--model", cfg["decide"]["fable_model"],
        "--tools", "", "--no-session-persistence",
        # 個人設定・hooks・MCP を読み込まないことで、入力を毎回同じにしてコストも抑える
        "--setting-sources", "", "--strict-mcp-config",
        "--system-prompt", system,
        "--output-format", "json", "--json-schema", json.dumps(schema),
        user,
    ]
    # CLAUDE.md を拾わないよう、プロジェクト外の空フォルダで実行する
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                           timeout=cfg["decide"]["timeout_s"])
    d = json.loads(p.stdout)
    if d.get("is_error") or d.get("structured_output") is None:
        raise RuntimeError(d.get("result") or p.stderr[:300])
    return d["structured_output"], {"model": cfg["decide"]["fable_model"],
                                    "cost_usd": d.get("total_cost_usd")}


BACKENDS = {"fable": decide_fable}


def decide_one(cfg, state, rule, backend=None):
    """1 つの状態に 1 つのルールを当てはめ、記録用の dict を返す（例外は呼び出し側に任せる）。"""
    backend = backend or cfg["decide"]["backend"]
    bins = cfg["bins"]
    w, h = cfg["table_cm"]["width"], cfg["table_cm"]["height"]
    system = SYSTEM.format(bins=", ".join(bins), w=w, h=h)
    user = f"ルール: {rule['text']}\n物体: {scene_text(state)}\n各物体の置き場を答えてください。"
    t0 = time.time()
    answer, meta = BACKENDS[backend](cfg, system, user, schema_for(state, bins))
    return {"state_id": state["id"], "rule_id": rule["id"], "rule": rule["text"], "backend": backend,
            "answer": answer, **meta, "latency_s": round(time.time() - t0, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("states", help="states.jsonl または state.json")
    ap.add_argument("--rules", help="カンマ区切りのルール ID（省略で全部）")
    ap.add_argument("--backend", help="fable（既定は config.yaml の decide.backend）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    backend = args.backend or cfg["decide"]["backend"]
    with open(ROOT / "rules.yaml") as f:
        rules = yaml.safe_load(f)
    if args.rules:
        want = set(args.rules.split(","))
        rules = [r for r in rules if r["id"] in want]

    states, out_dir = load_states(args.states)
    out_path = out_dir / "decisions.jsonl"
    done = set()
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                d = json.loads(line)
                if not d.get("error"):
                    done.add((d["state_id"], d["rule_id"], d["backend"]))

    bins = cfg["bins"]
    w, h = cfg["table_cm"]["width"], cfg["table_cm"]["height"]
    system = SYSTEM.format(bins=", ".join(bins), w=w, h=h)

    for state in states:
        if not state["objects"]:
            print(f"{state['id']}: 物体なし、スキップ")
            continue
        for rule in rules:
            key = (state["id"], rule["id"], backend)
            if key in done:
                continue
            user = f"ルール: {rule['text']}\n物体: {scene_text(state)}\n各物体の置き場を答えてください。"
            if args.dry_run:
                print(f"--- {state['id']} / {rule['id']}\n{user}")
                continue
            rec = {"state_id": state["id"], "rule_id": rule["id"], "rule": rule["text"],
                   "backend": backend}
            t0 = time.time()
            try:
                answer, meta = BACKENDS[backend](cfg, system, user, schema_for(state, bins))
                rec.update(answer=answer, **meta)
            except Exception as e:  # 1件の失敗で全体を止めない。error 付きの行は次回やり直す
                rec["error"] = str(e)[:300]
            rec["latency_s"] = round(time.time() - t0, 2)
            with open(out_path, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            summary = rec.get("error") or " ".join(
                f"{k}→{v['bin']}({v['confidence']:.2f})" for k, v in rec["answer"].items())
            print(f"{state['id']} {rule['id']} [{rec['latency_s']}s] {summary}")


if __name__ == "__main__":
    main()
