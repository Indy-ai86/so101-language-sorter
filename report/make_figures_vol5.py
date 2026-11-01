"""vol.5 レポート用の図：一括評価での、ルールごとの自信の平均を Fable・Astra・Jev で並べる。

  python report/make_figures_vol5.py

Jev の confidence は分布の偏りの度合いなので、選んだ置き場の確率（probabilities）を使う。
Fable と Astra は自分で申告した confidence をそのまま使う。色は検証済みの並び（青・橙・緑）を、隣り合う棒の順に当てる。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for w in ("W3", "W6"):
    font_manager.fontManager.addfont(f"/System/Library/Fonts/ヒラギノ角ゴシック {w}.ttc")
plt.rcParams["font.family"] = "Hiragino Sans"

SERIES = [("fable", "Claude Fable 5.1（自信）", "#2a78d6"), ("astra", "GPT-6 Astra（自信）", "#eb6834"),
          ("jev", "Jev（選んだ置き場の確率）", "#1baf7a")]
UNSCORED = {"r07", "r08", "r12"}  # ルールに矛盾・主観・解釈が入り、正解を決めていない


def main():
    vals = defaultdict(lambda: defaultdict(list))
    for f in ROOT.glob("runs/*/decisions.jsonl"):
        for line in f.read_text().splitlines():
            d = json.loads(line)
            if d.get("error") or d["backend"] not in ("fable", "astra", "jev"):
                continue
            for a in d["answer"].values():
                p = a["probabilities"][a["bin"]] if "probabilities" in a else a["confidence"]
                vals[d["rule_id"]][d["backend"]].append(p)
    rules = sorted(vals)
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=200)
    bg = "#fcfcfb"
    fig.patch.set_facecolor(bg); ax.set_facecolor(bg)
    w = 0.27
    for i, r in enumerate(rules):
        if r in UNSCORED:
            ax.axvspan(i - 0.5, i + 0.5, color="#f1f0ec", zorder=0)
    for k, (key, label, col) in enumerate(SERIES):
        xs = [i + (k - 1) * w for i in range(len(rules))]
        ys = [sum(vals[r][key]) / len(vals[r][key]) for r in rules]
        ax.bar(xs, ys, width=w - 0.04, color=col, label=label, edgecolor=bg, linewidth=1, zorder=2)
    ax.set_xticks(range(len(rules)), rules, fontsize=9, color="#52514e")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("平均", color="#52514e")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#c3c2b7")
    ax.tick_params(colors="#52514e")
    ax.yaxis.grid(True, color="#e6e5e0", linewidth=0.8); ax.set_axisbelow(True)
    ax.legend(ncol=3, frameon=False, loc="upper left", bbox_to_anchor=(0, 1.16), fontsize=9)
    ax.text(len(rules) - 0.5, -0.2, "灰色の帯：正解を決めていないルール", ha="right", fontsize=8, color="#52514e",
            transform=ax.transData)
    fig.tight_layout()
    out = ROOT / "report" / "fig_conf_vol5.png"
    fig.savefig(out, facecolor=bg)
    print("保存:", out.relative_to(ROOT))
    for r in rules:
        print(r, {k: round(sum(v) / len(v), 2) for k, v in vals[r].items()})


if __name__ == "__main__":
    main()
