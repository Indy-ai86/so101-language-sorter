"""レポート用の図：実機の試行結果を、改善の段階ごとに積み上げ棒で示す。

  python report/make_figures.py
"""
import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
for w in ("W3", "W6"):
    font_manager.fontManager.addfont(f"/System/Library/Fonts/ヒラギノ角ゴシック {w}.ttc")
plt.rcParams["font.family"] = "Hiragino Sans"

# 段階の区切り（state_id の時刻）。各段階で何を直したかはレポート本文の表に対応する
PHASES = [
    ("A 初回", "20261024-000000", "20261024-235959"),
    ("B 爪の開き\n不足", "20261025-000000", "20261025-003800"),
    ("C 開き・握り\nを改善", "20261025-003800", "20261025-005500"),
    ("D 土台が\nずれた", "20261025-005500", "20261025-100000"),
    ("E 再校正・\n再記録", "20261025-100000", "20261025-115000"),
    ("F 事故後の\n復旧", "20261025-115000", "20261025-123700"),
    ("G 3個の\n通し試験", "20261025-123700", "20261025-235959"),
]
KINDS = [("o", "成功", "#2a78d6"), ("g", "掴めず", "#eb6834"), ("b", "置き場を外した", "#1baf7a"), ("d", "途中で落下", "#eda100")]


def load():
    recs = []
    for f in sorted(ROOT.glob("runs/*/*/sort_log.jsonl")):
        recs += [json.loads(l) for l in f.read_text().splitlines()]
    return recs


def main():
    recs = load()
    counts = []
    for _, lo, hi in PHASES:
        counts.append(Counter(r["result"] for r in recs if lo <= r["state_id"] < hi))
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=200)
    fig.patch.set_facecolor("#fcfcfb"); ax.set_facecolor("#fcfcfb")
    x = range(len(PHASES))
    bottom = [0] * len(PHASES)
    for key, label, col in KINDS:
        vals = [c.get(key, 0) for c in counts]
        bars = ax.bar(x, vals, bottom=bottom, color=col, width=0.6, label=label, edgecolor="#fcfcfb", linewidth=2)
        for b, v, y0 in zip(bars, vals, bottom):
            if v:
                ax.text(b.get_x() + b.get_width() / 2, y0 + v / 2, str(v), ha="center", va="center",
                        fontsize=9, color="#0b0b0b" if key in ("b", "d") else "white")
        bottom = [b + v for b, v in zip(bottom, vals)]
    for i, c in enumerate(counts):
        n = sum(c.values())
        ax.text(i, n + 0.3, f"{c.get('o', 0)}/{n}", ha="center", va="bottom", fontsize=9, color="#52514e")
    ax.set_xticks(list(x), [p[0] for p in PHASES], fontsize=8.5, color="#52514e")
    ax.set_ylabel("試行回数", color="#52514e")
    ax.set_ylim(0, max(bottom) + 2)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#c3c2b7")
    ax.tick_params(colors="#52514e")
    ax.yaxis.grid(True, color="#e6e5e0", linewidth=0.8); ax.set_axisbelow(True)
    ax.legend(ncol=4, frameon=False, loc="upper left", bbox_to_anchor=(0, 1.12), fontsize=9)
    fig.tight_layout()
    out = ROOT / "report" / "fig_trials.png"
    fig.savefig(out, facecolor=fig.get_facecolor())
    print("保存:", out.relative_to(ROOT))
    for (name, _, _), c in zip(PHASES, counts):
        print(name.replace("\n", ""), dict(c))


if __name__ == "__main__":
    main()
