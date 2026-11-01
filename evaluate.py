"""判断の一括評価（decide.py の結果）と、実機の試行記録（sort.py の結果）を集計する。

  python evaluate.py

判断の正解は、ルール文から一つに決まる場合だけ下の expected() で決める。
決まらない物（ルールが想定していない色、境界ぎりぎりの位置、主観や矛盾を含むルール）は採点から外し、
自信の値だけを見る。
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WARM, COOL = {"red", "orange", "yellow", "pink"}, {"blue", "green"}


def expected(rule_id, o, objs):
    c, single = o["colors"], len(o["colors"]) == 1
    if rule_id == "r01":
        return "left" if "pink" in c else "right"
    if rule_id == "r02":
        return "center" if o["shape"] == "round" else "left"
    if rule_id == "r03" and single:
        return {"yellow": "right", "blue": "left"}.get(c[0], "center")
    if rule_id == "r04" and single:
        return "left" if c[0] in WARM else "right" if c[0] in COOL else None
    if rule_id == "r05":
        y = o["table_cm"][1]
        # 境目（縦 7.5cm）から 1cm 以内は、物の大きさ次第でどちらとも言えるので採点しない
        return None if abs(y - 7.5) < 1 else ("center" if y > 7.5 else "right")
    if rule_id == "r06":
        return "center" if not single else ("left" if c[0] == "red" else "right")
    if rule_id == "r09" and single:
        return {"red": "left", "yellow": "center", "green": "right"}.get(c[0])
    if rule_id == "r10":
        areas = sorted((x["area_px"] for x in objs), reverse=True)
        # 大きさが 10% 以内で並ぶときは「一番大きい物」が見た目で決まらない
        if len(areas) > 1 and areas[1] > areas[0] * 0.9:
            return None
        return "right" if o["area_px"] == areas[0] else "left"
    if rule_id == "r11":
        if "green" in c:
            return "center" if single else None
        return "left" if o["shape"] == "round" else "right"
    return None  # r07（矛盾）・r08（主観）・r12（解釈）は採点しない


def load_states():
    states = {}
    for f in ROOT.glob("runs/*/states.jsonl"):
        for line in f.read_text().splitlines():
            s = json.loads(line)
            states[s["id"]] = s
    return states


def load_decisions():
    return [json.loads(l) for f in ROOT.glob("runs/*/decisions.jsonl") for l in f.read_text().splitlines()
            if not json.loads(l).get("error")]


def eval_decisions(states, rows, backend):
    rows = [d for d in rows if d.get("backend", "fable") == backend]
    if not rows:
        return
    per_rule = defaultdict(lambda: Counter())
    confs = defaultdict(list)
    wrong = []
    for d in rows:
        s = states[d["state_id"]]
        objs = s["objects"]
        for o in objs:
            a = d["answer"][o["id"]]
            confs[d["rule_id"]].append(a["confidence"])
            e = expected(d["rule_id"], o, objs)
            if e is None:
                per_rule[d["rule_id"]]["skip"] += 1
                continue
            ok = a["bin"] == e
            per_rule[d["rule_id"]]["ok" if ok else "ng"] += 1
            if not ok:
                wrong.append((d["state_id"], d["rule_id"], o["id"], o["colors"], o["table_cm"], a, e))
    print(f"\n判断の一括評価（{backend}）：{len(rows)} 回の呼び出し、費用 ${sum(d.get('cost_usd') or 0 for d in rows):.2f}、"
          f"平均 {sum(d['latency_s'] for d in rows) / len(rows):.1f} 秒")
    print("| ルール | 正解 | 不正解 | 採点外 | 自信の平均 |")
    print("|---|---|---|---|---|")
    tot = Counter()
    for r in sorted(per_rule):
        c = per_rule[r]
        tot.update(c)
        print(f"| {r} | {c['ok']} | {c['ng']} | {c['skip']} | {sum(confs[r]) / len(confs[r]):.2f} |")
    print(f"| 計 | {tot['ok']} | {tot['ng']} | {tot['skip']} | |")
    for w in wrong:
        print("  不正解:", w)


def compare_backends(states, rows):
    """同じ状態・同じルールに複数の判断先が答えていれば、置き場が分かれた物を並べる。"""
    by_key = defaultdict(dict)
    for d in rows:
        by_key[(d["state_id"], d["rule_id"])][d.get("backend", "fable")] = d["answer"]
    multi = {k: v for k, v in by_key.items() if len(v) > 1}
    if not multi:
        return
    backends = sorted({b for v in multi.values() for b in v})
    agree = Counter()
    diffs = []
    for (sid, rid), answers in sorted(multi.items()):
        objs = states[sid]["objects"]
        for o in objs:
            bins = {b: answers[b][o["id"]]["bin"] for b in answers}
            same = len(set(bins.values())) == 1
            agree["same" if same else "diff"] += 1
            if not same:
                e = expected(rid, o, objs)
                diffs.append((sid, rid, o["id"], "+".join(o["colors"]), e,
                              {b: f"{a['bin']}({a['confidence']:.2f})" for b, a in
                               ((b, answers[b][o["id"]]) for b in backends if b in answers)}))
    print(f"\n判断先の比較（{' / '.join(backends)}、同じ状態と同じルールに答えた {len(multi)} 組）："
          f"物体 {sum(agree.values())} 個のうち一致 {agree['same']}、不一致 {agree['diff']}")
    for d in diffs:
        print(f"  {d[0]} {d[1]} {d[2]} {d[3]} 正解={d[4]} {d[5]}")


def eval_runs(states):
    print("\n実機の試行（sort.py --judge）")
    recs = []
    for f in sorted(ROOT.glob("runs/*/*/sort_log.jsonl")):
        for line in f.read_text().splitlines():
            r = json.loads(line)
            recs.append(r)
    names = {"o": "成功", "g": "掴めず", "d": "途中で落下", "b": "置き場を外した"}
    for backend in sorted({r.get("backend", "fable") for r in recs}):
        rs = [r for r in recs if r.get("backend", "fable") == backend]
        c = Counter(r.get("result") or "記録なし" for r in rs)
        print(f"{backend} 全 {len(rs)} 回:", ", ".join(f"{names.get(k, k)} {v}" for k, v in c.items()))
    for r in recs:
        print(f"  {r['state_id']} {r['rule_id']} {r.get('backend', 'fable')} {'+'.join(r['colors'])} → {r['bin']} {names.get(r.get('result'), r.get('result'))}")


if __name__ == "__main__":
    st = load_states()
    rows = load_decisions()
    for b in sorted({d.get("backend", "fable") for d in rows}):
        eval_decisions(st, rows, b)
    compare_backends(st, rows)
    eval_runs(st)
