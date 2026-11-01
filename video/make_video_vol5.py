"""提出用 vol.5：判断を Claude Fable 5.1・GPT-6 Astra・Jev に替えた実機の試行を、3 本並べて比べる動画（1920×1080）。

同じ日・同じルール・同じ並べ方の 3 本を、腕が畳み終わる時刻でそろえて 2 倍速で並べる。
音は元の動画の音（Fable を左、Astra を中央、Jev を右寄り）に、BGM を小さく重ねる。

  python video/make_video_vol5.py

判断と結果は runs/ の実行記録から読むので、表示する数字は記録と一致する。
個人情報を載せない決まりがあるため、氏名などは入れず、元動画の埋め込み情報も外す。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_video_vol4 as base  # noqa: E402
from make_video import (ACCENT, BG, DL, ED, FONT_B, FONT_R, GOOD, INK, OP, ROOT, SLIDE, SUB, WARN, W, H,  # noqa: E402
                        duration, font, para, run)

OUT = ROOT / "video" / "out" / "vol5"
base.OUT = OUT  # 共通の関数（音の測定・BGM の整え）の作業場所もこちらにする
SPEED = 2
# 動画と実行記録の対応、各動画で使い始める秒（腕が畳み終わる 1.5 秒前。コマを並べて目で確かめた）
TRIPLES = [
    [(DL / "IMG_4544.MOV", "runs/20261101/134055", 1.3), (DL / "IMG_4562.MOV", "runs/20261101/154930", 1.3),
     (DL / "IMG_4549.MOV", "runs/20261101/143536", 1.3)],
    [(DL / "IMG_4545.MOV", "runs/20261101/134438", 1.3), (DL / "IMG_4563.MOV", "runs/20261101/155238", 1.0),
     (DL / "IMG_4551.MOV", "runs/20261101/144140", 1.3)],
    [(DL / "IMG_4546.MOV", "runs/20261101/134840", 1.3), (DL / "IMG_4564.MOV", "runs/20261101/155604", 1.3),
     (DL / "IMG_4543.MOV", "runs/20261101/114405", 1.2)],
]
NAMES = ("Claude Fable 5.1", "GPT-6 Astra", "Jev（TypeSafe）")
BIN_S = {"left": "左", "center": "中央", "right": "右"}
BGM_CREDIT = ["BGM：CMSL クラシック名曲サウンドライブラリー「ラストシンフォニー」ライセンスフリー素材音源",
              "https://classical-sound.seesaa.net/article/464440694.html"]

COLW = W // 3
CROP_Y = 200                  # 縦長映像の上の壁・天井を切る（腕が一番高く上がっても入る位置）
VW, VH = 460, 690             # 切った映像（720×1080）を縮めた大きさ
VY = 118
PANEL_Y = VY + VH + 12
HILITE = (252, 241, 214)


def vx(c):
    return c * COLW + (COLW - VW) // 2


SHORT = ("Fable", "Astra", "Jev")


def split_note(rule_id, runs):
    """置き場が分かれた物について、短い説明を返す。r09 のピンクは信号機の色にないので、赤とみなすかで分かれる。"""
    rows = [r[1] for r in runs]
    notes = []
    for k in range(len(rows[0])):
        bins = [rs[k]["bin"] for rs in rows]
        if len(set(bins)) == 1:
            continue
        name = rows[0][k]["name"]
        if rule_id == "r09" and name == "ピンク":
            red = [SHORT[i] for i, b in enumerate(bins) if b == "left"]
            other = "、".join(f"{SHORT[i]} はそうせず{BIN_S[b]}へ" for i, b in enumerate(bins) if b != "left")
            notes.append(f"ピンク：{' と '.join(red)} は信号機の「赤」（止まれ）とみなして左へ。{other}")
        else:
            notes.append(f"{name}：" + "、".join(f"{SHORT[i]} は{BIN_S[b]}" for i, b in enumerate(bins)))
    return notes


def panel(rule, runs, idx, with_result):
    im = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(im)
    d.text((40, 18), f"比較 {idx}/3　ルール {rule['id']}", font=font(FONT_B, 30), fill=ACCENT)
    d.text((40 + 330, 18), rule["text"], font=font(FONT_B, 30), fill=INK)
    d.text((W - 40 - 92, 22), f"{SPEED}倍速", font=font(FONT_R, 26), fill=SUB)
    for i, n in enumerate(split_note(rule["id"], runs)):
        d.text((40, 66 + i * 32), n, font=font(FONT_R, 24), fill=WARN)
    split_rows = {k for k in range(len(runs[0][1])) if len({r[1][k]["bin"] for r in runs}) > 1}
    for c, (_, rows, lat) in enumerate(runs):
        x = vx(c)
        d.rectangle((x, VY, x + VW - 1, VY + VH - 1), fill=(0, 0, 0, 0))
        d.rectangle((x, VY, x + VW - 1, VY + 48), fill=(0, 0, 0, 150))
        d.text((x + 16, VY + 8), NAMES[c], font=font(FONT_B, 28), fill=(255, 255, 255, 255))
        x0, y = c * COLW + 70, PANEL_Y
        for k, r in enumerate(rows):
            if k in split_rows:
                d.rectangle((x0 - 12, y - 4, x0 + 512, y + 40), fill=HILITE)
            low = r["p"] < 0.7
            d.text((x0, y + 4), r["name"], font=font(FONT_B, 26), fill=INK)
            d.text((x0 + 130, y), BIN_S[r["bin"]], font=font(FONT_B, 30), fill=WARN if low else INK)
            sub = f"確率 {r['p']:.2f}"
            if with_result:
                from make_video import RESULT_JA
                sub += "　" + RESULT_JA.get(r["res"], "−")
            d.text((x0 + 230, y + 8), sub, font=font(FONT_R, 22),
                   fill=WARN if low or (with_result and r["res"] != "o") else SUB)
            y += 46
        d.text((x0, y + 6), "判断の時間", font=font(FONT_R, 22), fill=SUB)
        d.text((x0 + 130, y + 2), f"{lat:.1f} 秒", font=font(FONT_B, 28), fill=INK)
        if with_result:
            ok = sum(r["res"] == "o" for r in rows)
            d.text((x0 + 300, y), f"{ok}/{len(rows)} 成功", font=font(FONT_B, 30),
                   fill=GOOD if ok == len(rows) else WARN)
    d.text((40, H - 34), "確率：選んだ置き場の確率（Fable と Astra は自己申告の自信）　"
                         "置き場：左＝手前、中央＝奥、右＝画面右のカップ", font=font(FONT_R, 20), fill=SUB)
    return im


def title_card(path):
    im = Image.open(SLIDE).convert("RGB")
    d = ImageDraw.Draw(im)
    d.text((90, 680), "言葉のルールで", font=font(FONT_B, 56), fill=INK)
    d.text((90, 752), "仕分けるロボットアーム", font=font(FONT_B, 56), fill=INK)
    d.text((92, 842), "vol.5　Fable・Astra・Jev の比較", font=font(FONT_B, 34), fill=ACCENT)
    d.text((92, 898), "SO-101 × 真上のカメラ × 判断モデル（学習なし）", font=font(FONT_R, 28), fill=SUB)
    im.save(path)


def text_card(title, items, path, foot=None):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 24, H), fill=ACCENT)
    d.text((160, 140), title, font=font(FONT_B, 64), fill=INK)
    y = 280
    for t in items:
        y = para(d, 160, y, t, font(FONT_R, 40), W - 320, indent=56) + 22
    for k, line in enumerate(foot or []):
        d.text((160, H - 96 + k * 32), line, font=font(FONT_R, 22), fill=SUB)
    im.save(path)


def wrap_words(text, f, maxw):
    """英数字の単語は途中で切らずに折り返す（共通の wrap_px は 1 文字ずつ切るので「J / ev」のように割れる）。"""
    import re
    tokens = re.findall(r"[A-Za-z0-9.\-/:_]+|\s|.", text)
    lines, cur = [], ""
    for t in tokens:
        if cur and f.getlength(cur + t) > maxw and t not in "、。）」，":
            lines.append(cur.rstrip())
            cur = "" if t.isspace() else t
            continue
        cur += t
    return lines + [cur.rstrip()] if cur.strip() else lines


def para_w(d, x, y, text, f, maxw, fill=INK, gap=14, indent=0):
    for i, line in enumerate(wrap_words(text, f, maxw - indent)):
        d.text((x + (indent if i else 0), y), line, font=f, fill=fill)
        y += f.size + gap
    return y


def fig_card(title, items, img, caption, path, img_w, size=36, after=None, foot=None):
    """左に文字、右に図とキャプションを置く画面。図はレポートと同じ元画像を使う。"""
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 24, H), fill=ACCENT)
    d.text((120, 110), title, font=font(FONT_B, 60), fill=INK)
    text_w = W - img_w - 120 - 80 - 60
    y = 240
    for t in items:
        y = para_w(d, 120, y, t, font(FONT_R, size), text_w, indent=size + 10) + 20
    if after:
        para_w(d, 120, y + 16, after, font(FONT_B, size), text_w)
    fig = Image.open(img).convert("RGB")
    fig = fig.resize((img_w, round(fig.height * img_w / fig.width)), Image.LANCZOS)
    fx, fy = W - 80 - img_w, max(240, (H - fig.height) // 2 - 40)
    im.paste(fig, (fx, fy))
    cf = font(FONT_R, 24)
    while d.textlength(caption, font=cf) > img_w and cf.size > 18:  # キャプションは 1 行に収める
        cf = font(FONT_R, cf.size - 1)
    cw = d.textlength(caption, font=cf)
    d.text((fx + (img_w - cw) / 2, fy + fig.height + 18), caption, font=cf, fill=SUB)
    for k, line in enumerate(foot or []):
        d.text((120, H - 96 + k * 32), line, font=font(FONT_R, 22), fill=SUB)
    im.save(path)


def segment(i, triple, out):
    runs = [base.load_run(r) for _, r, _ in triple]
    rule = runs[0][0]
    assert all(r[0]["id"] == rule["id"] for r in runs), "ルールがそろっていない"
    a, b = OUT / f"panel{i}a.png", OUT / f"panel{i}b.png"
    panel(rule, runs, i, False).save(a)
    panel(rule, runs, i, True).save(b)
    dur = max(duration(src) - ss for src, _, ss in triple) / SPEED
    gains = [base.gain_db(src, ss) for src, _, ss in triple]
    print(f"  {rule['id']}: {dur:.1f} 秒、音の増幅 " + " / ".join(f"{g:+.1f}dB" for g in gains))
    fc = f"color=c=white:s={W}x{H}:r=30:d={dur:.2f}[bg];"
    for k in range(3):
        fc += (f"[{k}:v]setpts=(PTS-STARTPTS)/{SPEED},crop=720:1080:0:{CROP_Y},scale={VW}:{VH},fps=30,"
               f"tpad=stop_mode=clone:stop_duration=30[v{k}];")
        fc += (f"[{k}:a]asetpts=PTS-STARTPTS,atempo={SPEED},aresample=48000,"
               f"pan=mono|c0=0.5*c0+0.5*c1,{base.LOWCUT},volume={gains[k]:.1f}dB,apad[a{k}];")
    fc += (f"[bg][v0]overlay={vx(0)}:{VY}[o1];[o1][v1]overlay={vx(1)}:{VY}[o2];[o2][v2]overlay={vx(2)}:{VY}[o3];"
           f"[o3][3:v]overlay=0:0:enable='lt(t,{dur - 6:.2f})'[o4];"
           f"[o4][4:v]overlay=0:0:enable='gte(t,{dur - 6:.2f})'[vout];"
           # 左の映像の音を左寄り、中央は真ん中、右の映像の音を右寄りにする
           "[a0][a1][a2]amerge=inputs=3,"
           "pan=stereo|c0=0.6*c0+0.35*c1+0.1*c2|c1=0.1*c0+0.35*c1+0.6*c2,"
           "alimiter=limit=0.6:attack=1:level=false[aout]")
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for src, _, ss in triple:
        cmd += ["-ss", str(ss), "-i", str(src)]
    cmd += ["-i", str(a), "-i", str(b), "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
            "-t", f"{dur:.2f}", *base.ENC_V, *base.ENC_A, "-map_metadata", "-1", str(out)]
    run(cmd)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parts = []
    base.jingle(OP, OUT / "p00_op.mp4"); parts.append(OUT / "p00_op.mp4")
    title_card(OUT / "c_title.png")
    base.still(OUT / "c_title.png", 4, OUT / "p01.mp4"); parts.append(OUT / "p01.mp4")
    fig_card("比べ方", [
        "1. 日本語で書いた仕分けルールに従って、机の上の物体を SO-101 アームで3つのカップに仕分けるシステム",
        "2. Claude Fable 5.1・GPT-6 Astra・Jev に、同じ日・同じルール・同じ並べ方で 3 個ずつ運ばせる",
        "3. 物体の検出は真上のカメラと色の処理で行い、どの物をどこへ運ぶかの判断をモデルに任せた。"
        "アームの動きは学習させず、人が教えた姿勢を補間して作った",
    ], ROOT / "report" / "img" / "camera_points.jpg",
        "真上のカメラの画像。赤の 1〜9 が姿勢を教えた点、青の 10〜12 が置き場",
        OUT / "c_method.png", img_w=840)
    base.still(OUT / "c_method.png", 11, OUT / "p02.mp4"); parts.append(OUT / "p02.mp4")
    for i, triple in enumerate(TRIPLES, 1):
        out = OUT / f"p1{i}.mp4"
        segment(i, triple, out)
        parts.append(out)
    fig_card("結果", [
        "判断：答えが一つに決まる物は、実機でも一括評価（各 108 回）でも 3 モデルすべて正解",
        "信号機の色にないピンクを、Fable と Astra は信号機の「赤」（止まれ）とみなして左へ。Jev はそうせず右へ",
        "判断の時間：Fable 4〜6 秒、Astra 5〜6 秒、Jev 0.2 秒",
        "運べた数：3 モデルとも 9/9。アームの動きは共通のプログラムなので、モデルを替えても運び方は変わらない",
    ], ROOT / "report" / "fig_conf_vol5.png",
        "ルールごとの確からしさの平均。Fable と Astra は自分で申告した自信、Jev は選んだ置き場の確率",
        OUT / "c_end.png", img_w=920, size=32, foot=BGM_CREDIT)
    base.still(OUT / "c_end.png", 15, OUT / "p20.mp4"); parts.append(OUT / "p20.mp4")
    base.jingle(ED, OUT / "p99_ed.mp4"); parts.append(OUT / "p99_ed.mp4")

    lst = OUT / "parts.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    joined = OUT / "joined.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
         "-map_metadata", "-1", str(joined)])
    total = duration(joined)
    bgm = OUT / "bgm_leveled.wav"
    base.level_bgm(base.BGM, bgm, total)
    final = ROOT / "video" / "out" / "sorter_vol5.mp4"
    fc = (f"[1:a]atrim=0:{total:.2f},asetpts=PTS-STARTPTS,"
          f"afade=t=in:st=0:d=1.5,afade=t=out:st={total - 3:.2f}:d=3[bg];"
          "[0:a][bg]amix=inputs=2:duration=first:normalize=0[aout]")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(joined), "-i", str(bgm), "-filter_complex", fc,
         "-map", "0:v", "-map", "[aout]", "-c:v", "copy", *base.ENC_A, "-map_metadata", "-1", str(final)])
    print(f"できました: {final.relative_to(ROOT)}（{duration(final):.0f} 秒）")


if __name__ == "__main__":
    main()
