"""提出用の動画（1〜3 分、1920×1080）を作る。

講座配布の OP・ED とタイトルスライドの間に、スマホで撮った 3 回の通し試験を 2 倍速で入れる。
縦長の映像を左に置き、右側にルール・LLM の判断・結果を出す。

  python video/make_video.py

判断と結果は runs/ の実行記録から読むので、表示する数字は記録と一致する。
個人情報を載せない決まりがあるため、氏名などは入れず、元動画の埋め込み情報も外す。
"""
import json
import subprocess
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "video" / "out"
DL = Path("~/Downloads").expanduser()
W, H = 1920, 1080
SPEED = 2
FONT_B = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
FONT_R = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
OP, ED, SLIDE = DL / "PAI応用1_最終課題_OP.mp4", DL / "PAI応用1_最終課題_ED.mp4", DL / "PAI応用1_最終課題_スライド.jpg"

INK, SUB, ACCENT, BG = (20, 20, 20), (90, 90, 84), (124, 122, 86), (255, 255, 255)
GOOD, WARN = (32, 110, 200), (200, 80, 40)

# 動画と実行記録の対応。撮影はこの順に行った
CLIPS = [
    (DL / "IMG_4484.MOV", "runs/20261025/123813"),
    (DL / "IMG_4485.MOV", "runs/20261025/124111"),
    (DL / "IMG_4486.MOV", "runs/20261025/124444"),
]
COLOR_JA = {"pink": "ピンク", "yellow": "黄", "green": "緑", "red": "赤", "orange": "オレンジ", "blue": "青", "black": "黒"}
# スマホの撮影位置から見た置き場。プログラムの左右はカメラ画像の左右なので、見た目とは一致しない
BIN_JA = {"left": "左（手前のカップ）", "center": "中央（奥のカップ）", "right": "右（画面右のカップ）"}
RESULT_JA = {"o": "成功", "g": "掴めず", "d": "途中で落下", "b": "置き場を外した"}


def font(path, size):
    return ImageFont.truetype(path, size)


def wrap_px(text, f, maxw):
    """文字幅で折り返す。textwrap は空白でしか切らないので、和文と英数字が混ざると不自然な位置で改行する。"""
    lines, cur = [], ""
    for ch in text:
        if f.getlength(cur + ch) > maxw and cur and ch not in "、。）」，":
            lines.append(cur)
            cur = ""
        cur += ch
    return lines + [cur] if cur else lines


def para(d, x, y, text, f, maxw, fill=INK, gap=14, indent=0):
    for i, line in enumerate(wrap_px(text, f, maxw - indent)):
        d.text((x + (indent if i else 0), y), line, font=f, fill=fill)
        y += f.size + gap
    return y


def load_run(run):
    d = ROOT / run
    state = json.loads((d / "state.json").read_text())
    decision = [json.loads(l) for l in (d / "sort_decisions.jsonl").read_text().splitlines()][-1]
    logs = {r["object"]: r for r in map(json.loads, (d / "sort_log.jsonl").read_text().splitlines())}
    rule_id = next(iter(logs.values()))["rule_id"]
    rule = next(r for r in yaml.safe_load((ROOT / "rules.yaml").read_text()) if r["id"] == rule_id)
    rows = []
    for o in state["objects"]:
        a = decision["answer"][o["id"]]
        name = "＋".join(COLOR_JA.get(c, c) for c in o["colors"])
        rows.append((name, a["bin"], a["confidence"], logs.get(o["id"], {}).get("result")))
    return rule, rows


VX, VW = 140, 608  # 縦長映像を置く位置と幅（高さは 1080）
PX = VX + VW + 90  # 右側の文字の開始位置
PW = W - PX - 110


def panel(rule, rows, idx, with_result):
    """試行中の画面。映像を置く場所は透明にしておき、下に映像を重ねる。"""
    im = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(im)
    d.rectangle((VX, 0, VX + VW - 1, H), fill=(0, 0, 0, 0))
    d.text((PX, 90), f"試行 {idx}/3　ルール {rule['id']}", font=font(FONT_B, 40), fill=ACCENT)
    d.text((W - 110 - 120, 98), f"{SPEED}倍速", font=font(FONT_R, 30), fill=SUB)
    y = para(d, PX, 160, rule["text"], font(FONT_B, 48), PW, gap=16)
    y += 50
    d.text((PX, y), "LLM の判断（Claude Fable 5.1）", font=font(FONT_R, 30), fill=SUB)
    y += 56
    for name, b, conf, res in rows:
        col = WARN if conf < 0.7 else INK
        d.text((PX, y), f"{name} → {BIN_JA[b]}", font=font(FONT_B, 38), fill=col)
        d.text((PX + 760, y + 4), f"自信 {conf:.2f}", font=font(FONT_R, 34), fill=col)
        if with_result:
            ok = res == "o"
            d.text((PX + 760 + 220, y + 4), RESULT_JA.get(res, "−"), font=font(FONT_B, 34), fill=GOOD if ok else WARN)
        y += 64
    if with_result:
        ok = sum(r[3] == "o" for r in rows)
        y += 30
        d.text((PX, y), f"結果 {ok}/{len(rows)} 成功", font=font(FONT_B, 56), fill=GOOD if ok == len(rows) else WARN)
    d.text((PX, H - 90), "置き場：左＝手前のカップ、中央＝奥のカップ、右＝画面右のカップ", font=font(FONT_R, 26), fill=SUB)
    return im


def title_card(path):
    im = Image.open(SLIDE).convert("RGB")
    d = ImageDraw.Draw(im)
    # スライドの斜めの帯にかからないよう、2 行に分ける
    d.text((90, 680), "言葉のルールで", font=font(FONT_B, 56), fill=INK)
    d.text((90, 752), "仕分けるロボットアーム", font=font(FONT_B, 56), fill=INK)
    d.text((92, 846), "SO-101 × 真上のカメラ × LLM（学習なし）", font=font(FONT_R, 34), fill=SUB)
    im.save(path)


def text_card(title, items, path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 24, H), fill=ACCENT)
    d.text((160, 150), title, font=font(FONT_B, 64), fill=INK)
    y = 290
    for t in items:
        y = para(d, 160, y, t, font(FONT_R, 44), W - 320, indent=56) + 26
    im.save(path)


def run(cmd):
    subprocess.run(cmd, check=True)


ENC = ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "30", "-an",
       "-map_metadata", "-1"]


def duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", str(path)]).decode())


def still(png, seconds, out):
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", str(seconds), "-i", str(png), "-vf", f"scale={W}:{H}",
         *ENC, str(out)])


def jingle(src, out):
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", f"scale={W}:{H},fps=30", *ENC, str(out)])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parts = []

    jingle(OP, OUT / "p00_op.mp4"); parts.append(OUT / "p00_op.mp4")
    title_card(OUT / "c_title.png")
    still(OUT / "c_title.png", 4, OUT / "p01.mp4"); parts.append(OUT / "p01.mp4")
    text_card("しくみ（学習なし）", [
        "1. 真上のカメラで、物体の色・形・位置を検出する",
        "2. 日本語のルール文と検出結果を LLM に渡す",
        "3. LLM が物体ごとに、置き場と自信（0〜1）を返す",
        "4. 手で教えた 9 点の姿勢を補間して掴み、置き場へ運ぶ",
    ], OUT / "c_method.png")
    still(OUT / "c_method.png", 8, OUT / "p02.mp4"); parts.append(OUT / "p02.mp4")

    totals = [0, 0]
    for i, (src, rdir) in enumerate(CLIPS, 1):
        rule, rows = load_run(rdir)
        totals[0] += sum(r[3] == "o" for r in rows)
        totals[1] += len(rows)
        a, b = OUT / f"panel{i}a.png", OUT / f"panel{i}b.png"
        panel(rule, rows, i, False).save(a)
        panel(rule, rows, i, True).save(b)
        dur = duration(src) / SPEED
        fc = (f"color=c=white:s={W}x{H}:r=30:d={dur:.2f}[bg];"
              f"[0:v]setpts=PTS/{SPEED},scale={VW}:{H},fps=30[v];"
              f"[bg][v]overlay={VX}:0:shortest=1[a];"
              f"[a][1:v]overlay=0:0:enable='lt(t,{dur - 6:.2f})'[b];"
              f"[b][2:v]overlay=0:0:enable='gte(t,{dur - 6:.2f})'[out]")
        out = OUT / f"p1{i}.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-i", str(a), "-i", str(b),
             "-filter_complex", fc, "-map", "[out]", *ENC, str(out)])
        parts.append(out)

    text_card("結果", [
        f"通し試験：{totals[1]} 個中 {totals[0]} 個を正しい置き場へ運んだ（失敗 1 個は方眼の端の物）",
        "ルール判断の一括評価（108 回）：答えが一つに決まる 197 件はすべて正解",
        "r09 のピンクは「止まれの色」とみなすか迷い、自信 0.40",
        "失敗の原因はすべて位置合わせ（姿勢の記録・校正・土台の固定）で、LLM の判断による失敗はなかった",
    ], OUT / "c_end.png")
    still(OUT / "c_end.png", 8, OUT / "p20.mp4"); parts.append(OUT / "p20.mp4")
    jingle(ED, OUT / "p99_ed.mp4"); parts.append(OUT / "p99_ed.mp4")

    lst = OUT / "parts.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    final = OUT / "sorter_demo.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
         "-map_metadata", "-1", str(final)])
    print(f"できました: {final.relative_to(ROOT)}（{duration(final):.0f} 秒）")


if __name__ == "__main__":
    main()
