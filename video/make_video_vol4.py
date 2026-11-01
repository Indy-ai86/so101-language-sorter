"""提出用 vol.4：判断を Claude Fable 5.1 と Jev に替えた実機の試行を、左右に並べて比べる動画（1〜3 分、1920×1080）。

同じ日・同じルール・同じ並べ方の 2 本を、腕が畳み終わる時刻でそろえて 2 倍速で並べる。音は元の動画の音を使い、
左の映像（Fable）の音を左寄り、右の映像（Jev）の音を右寄りに混ぜる。全体の下に BGM を小さく流す。

  python video/make_video_vol4.py

判断と結果は runs/ の実行記録から読むので、表示する数字は記録と一致する。
個人情報を載せない決まりがあるため、氏名などは入れず、元動画の埋め込み情報も外す。
"""
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_video import (ACCENT, BG, DL, ED, FONT_B, FONT_R, GOOD, INK, OP, ROOT, SLIDE, SUB, WARN, W, H,  # noqa: E402
                        COLOR_JA, RESULT_JA, duration, font, para, run)

OUT = ROOT / "video" / "out" / "vol4"
SPEED = 2
# 動画と実行記録の対応、各動画で使い始める秒（腕が畳み終わる 1.5 秒前。コマを並べて目で確かめた）
PAIRS = [
    ((DL / "IMG_4544.MOV", "runs/20261101/134055", 1.3), (DL / "IMG_4549.MOV", "runs/20261101/143536", 1.3)),
    ((DL / "IMG_4545.MOV", "runs/20261101/134438", 1.3), (DL / "IMG_4551.MOV", "runs/20261101/144140", 1.3)),
    ((DL / "IMG_4546.MOV", "runs/20261101/134840", 1.3), (DL / "IMG_4543.MOV", "runs/20261101/114405", 1.2)),
]
NAMES = ("Claude Fable 5.1", "Jev（TypeSafe）")
DATES = ("11/1", "11/1")
# BGM（フリー音源のクラシック）。動画の頭から終わりまで、環境音より小さく流す
BGM = DL / "Tchaikovsky-SwanLake-act2-Seane-AR.mp3"
# 曲は最初の 50 秒がとても静かで、その後 15dB ほど大きくなる。3 秒ごとの大きさがこの値になるようならしてから混ぜる
BGM_TARGET_DB = -30.0
BIN_S = {"left": "左", "center": "中央", "right": "右"}
VW = 608                      # 縦長映像 1 本の幅（高さ 1080）
VX = (36, 36 + VW + 16)       # 左右の映像の位置
PX = VX[1] + VW + 48          # 右側の文字の開始位置
PW = W - PX - 40
HILITE = (252, 241, 214)
# 音の大きさ：動画ごとに、大きい方から 0.5% の音（腕の動作音）をこの値にそろえる
TARGET_DB = -9.0
# 録音には 100〜300Hz の唸り（空調など）が入り、増幅すると動作音が埋もれる。腕の動作音はもっと高い音なので低い音を削る
LOWCUT = "highpass=f=250:poles=2,highpass=f=250:poles=2"

ENC_V = ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "30"]
ENC_A = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def load_run(run_dir):
    d = ROOT / run_dir
    state = json.loads((d / "state.json").read_text())
    dec = [json.loads(l) for l in (d / "sort_decisions.jsonl").read_text().splitlines()][-1]
    logs = {r["object"]: r for r in map(json.loads, (d / "sort_log.jsonl").read_text().splitlines())}
    rows = []
    for o in state["objects"]:
        a = dec["answer"][o["id"]]
        # Jev の confidence は分布の偏りの度合いで、選んだ置き場の確率ではない。比べやすいよう確率を出す
        p = a["probabilities"][a["bin"]] if "probabilities" in a else a["confidence"]
        rows.append({"name": "＋".join(COLOR_JA.get(c, c) for c in o["colors"]), "bin": a["bin"], "p": p,
                     "res": logs.get(o["id"], {}).get("result")})
    rule = next(r for r in yaml.safe_load((ROOT / "rules.yaml").read_text()) if r["id"] == dec["rule_id"])
    return rule, rows, dec["latency_s"]


def panel(rule, runs, idx, with_result):
    """左右の映像の上に重ねる画面。映像の場所は透明にし、映像の上端にモデル名を載せる。"""
    im = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(im)
    for k, x in enumerate(VX):
        d.rectangle((x, 0, x + VW - 1, H), fill=(0, 0, 0, 0))
        d.rectangle((x, 0, x + VW - 1, 64), fill=(0, 0, 0, 150))
        d.text((x + 20, 12), f"{NAMES[k]}　{DATES[k]}", font=font(FONT_B, 32), fill=(255, 255, 255, 255))
    d.text((PX, 56), f"比較 {idx}/3　ルール {rule['id']}", font=font(FONT_B, 34), fill=ACCENT)
    d.text((W - 40 - 110, 62), f"{SPEED}倍速", font=font(FONT_R, 28), fill=SUB)
    y = para(d, PX, 112, rule["text"], font(FONT_B, 36), PW, gap=12) + 34
    cx = (PX, PX + 170, PX + 380)
    d.text((cx[1], y), "Fable 5.1", font=font(FONT_R, 26), fill=SUB)
    d.text((cx[2], y), "Jev", font=font(FONT_R, 26), fill=SUB)
    y += 46
    (_, frows, flat), (_, jrows, jlat) = runs
    split = False
    for fr, jr in zip(frows, jrows):
        if fr["bin"] != jr["bin"]:
            split = True
            d.rectangle((PX - 12, y - 8, W - 28, y + 88), fill=HILITE)
        d.text((cx[0], y + 4), fr["name"], font=font(FONT_B, 32), fill=INK)
        for x, r in ((cx[1], fr), (cx[2], jr)):
            low = r["p"] < 0.7
            d.text((x, y), BIN_S[r["bin"]], font=font(FONT_B, 34), fill=WARN if low else INK)
            sub = f"確率 {r['p']:.2f}"
            if with_result:
                sub += "　" + RESULT_JA.get(r["res"], "−")
            d.text((x, y + 46), sub, font=font(FONT_R, 24),
                   fill=WARN if low or (with_result and r["res"] != "o") else SUB)
        y += 108
    y += 6
    d.text((cx[0], y + 4), "判断の時間", font=font(FONT_R, 26), fill=SUB)
    d.text((cx[1], y), f"{flat:.1f} 秒", font=font(FONT_B, 32), fill=INK)
    d.text((cx[2], y), f"{jlat:.1f} 秒", font=font(FONT_B, 32), fill=INK)
    y += 70
    if with_result:
        for x, rows in ((cx[1], frows), (cx[2], jrows)):
            ok = sum(r["res"] == "o" for r in rows)
            d.text((x, y), f"{ok}/{len(rows)} 成功", font=font(FONT_B, 40), fill=GOOD if ok == len(rows) else WARN)
        y += 76
    if split:
        para(d, PX, y, "色の帯：2 つのモデルで置き場が分かれた物", font(FONT_R, 24), PW, fill=SUB, gap=8)
    d.text((PX, H - 104), "確率：選んだ置き場の確率（Fable は自己申告）", font=font(FONT_R, 22), fill=SUB)
    d.text((PX, H - 64), "置き場：左＝手前、中央＝奥、右＝画面右のカップ", font=font(FONT_R, 22), fill=SUB)
    return im


def title_card(path):
    im = Image.open(SLIDE).convert("RGB")
    d = ImageDraw.Draw(im)
    # スライドの斜めの帯にかからないよう、左下に寄せる
    d.text((90, 680), "言葉のルールで", font=font(FONT_B, 56), fill=INK)
    d.text((90, 752), "仕分けるロボットアーム", font=font(FONT_B, 56), fill=INK)
    d.text((92, 842), "vol.4　Fable 5.1 と Jev の比較", font=font(FONT_B, 36), fill=ACCENT)
    d.text((92, 898), "SO-101 × 真上のカメラ × 判断モデル（学習なし）", font=font(FONT_R, 28), fill=SUB)
    im.save(path)


def text_card(title, items, path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 24, H), fill=ACCENT)
    d.text((160, 140), title, font=font(FONT_B, 64), fill=INK)
    y = 280
    for t in items:
        y = para(d, 160, y, t, font(FONT_R, 42), W - 320, indent=56) + 24
    im.save(path)


def gain_db(src, start):
    """腕の動作音（大きい方から 0.5% の音）が TARGET_DB になる増幅量。Fable と Jev で撮影時の録音の大きさが違うのでそろえる。"""
    wav = OUT / "tmp.wav"
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", str(src), "-vn", "-ac", "1", "-af", LOWCUT,
         "-ar", "16000", str(wav)])
    with wave.open(str(wav)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float) / 32768
    n = 1600
    m = len(a) // n
    rms = np.sqrt((a[:m * n].reshape(m, n) ** 2).mean(1))
    level = 20 * np.log10(np.percentile(rms, 99.5) + 1e-9)
    return TARGET_DB - level


def level_bgm(src, out, total):
    """BGM の大きさを時間ごとにならす。3 秒の窓の実効値が BGM_TARGET_DB になる増幅量を求め、2 秒でなめらかに変える。"""
    raw = OUT / "bgm_raw.wav"
    run(["ffmpeg", "-v", "error", "-y", "-t", f"{total:.2f}", "-i", str(src), "-ac", "2", "-ar", "48000", str(raw)])
    with wave.open(str(raw)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float).reshape(-1, 2) / 32768
    sr, win = 48000, 3 * 48000
    mono = a.mean(1)
    n = len(mono) // win
    rms = np.sqrt((mono[:n * win].reshape(n, win) ** 2).mean(1)) + 1e-6
    gain_db = np.clip(BGM_TARGET_DB - 20 * np.log10(rms), -10, 30)
    # 窓の中央に置いた増幅量を線形補間し、2 秒の移動平均でなめらかにする
    t = np.arange(len(mono)) / sr
    centers = (np.arange(n) + 0.5) * 3
    g = np.interp(t, centers, gain_db)
    k = 2 * sr
    g = np.convolve(np.pad(g, (k // 2, k - k // 2), mode="edge"), np.ones(k) / k, mode="valid")[:len(mono)]
    y = a * (10 ** (g / 20))[:, None]
    y = np.clip(y, -0.99, 0.99)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((y * 32767).astype(np.int16).tobytes())


def still(png, seconds, out):
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", str(seconds), "-i", str(png),
         "-f", "lavfi", "-t", str(seconds), "-i", "anullsrc=r=48000:cl=stereo",
         "-vf", f"scale={W}:{H}", *ENC_V, *ENC_A, "-shortest", "-map_metadata", "-1", str(out)])


def jingle(src, out):
    # 配布の OP・ED は音声トラックがない。最初の部品に音声がないと、つないだ動画から音声ごと落ちるので無音を足す
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-vf", f"scale={W}:{H},fps=30", "-map", "0:v", "-map", "1:a", *ENC_V, *ENC_A, "-shortest",
         "-map_metadata", "-1", str(out)])


def segment(i, pair, out):
    (fsrc, frun, fss), (jsrc, jrun, jss) = pair
    runs = [load_run(frun), load_run(jrun)]
    rule = runs[0][0]
    assert rule["id"] == runs[1][0]["id"], "左右でルールが違う"
    a, b = OUT / f"panel{i}a.png", OUT / f"panel{i}b.png"
    panel(rule, runs, i, False).save(a)
    panel(rule, runs, i, True).save(b)
    dur = max(duration(fsrc) - fss, duration(jsrc) - jss) / SPEED
    gf, gj = gain_db(fsrc, fss), gain_db(jsrc, jss)
    print(f"  {rule['id']}: {dur:.1f} 秒、音の増幅 Fable {gf:+.1f}dB / Jev {gj:+.1f}dB")
    v = lambda k: (f"[{k}:v]setpts=(PTS-STARTPTS)/{SPEED},scale={VW}:{H},fps=30,"
                   f"tpad=stop_mode=clone:stop_duration=30[v{k}];")
    au = lambda k, g: (f"[{k}:a]asetpts=PTS-STARTPTS,atempo={SPEED},aresample=48000,"
                       f"pan=mono|c0=0.5*c0+0.5*c1,{LOWCUT},volume={g:.1f}dB,apad[a{k}];")
    fc = (f"color=c=white:s={W}x{H}:r=30:d={dur:.2f}[bg];" + v(0) + v(1) +
          f"[bg][v0]overlay={VX[0]}:0[o1];[o1][v1]overlay={VX[1]}:0[o2];"
          f"[o2][2:v]overlay=0:0:enable='lt(t,{dur - 6:.2f})'[o3];"
          f"[o3][3:v]overlay=0:0:enable='gte(t,{dur - 6:.2f})'[vout];" +
          au(0, gf) + au(1, gj) +
          # 左の映像の音を左寄り、右の映像の音を右寄りにする（完全に分けると片耳だけ鳴って不自然）
          "[a0][a1]amerge=inputs=2,pan=stereo|c0=0.8*c0+0.2*c1|c1=0.2*c0+0.8*c1,"
          "alimiter=limit=0.6:attack=1:level=false[aout]")
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(fss), "-i", str(fsrc), "-ss", str(jss), "-i", str(jsrc),
         "-i", str(a), "-i", str(b), "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
         "-t", f"{dur:.2f}", *ENC_V, *ENC_A, "-map_metadata", "-1", str(out)])
    return runs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parts = []
    jingle(OP, OUT / "p00_op.mp4"); parts.append(OUT / "p00_op.mp4")
    title_card(OUT / "c_title.png")
    still(OUT / "c_title.png", 4, OUT / "p01.mp4"); parts.append(OUT / "p01.mp4")
    text_card("比べ方", [
        "1. 検出とアームの動きは同じプログラム。判断（どの物をどの置き場へ）だけを替える",
        "2. Claude Fable 5.1 と Jev に、同じ日・同じルール・同じ並べ方で 3 個ずつ運ばせる",
        "3. 左の映像が Fable、右の映像が Jev。2 倍速、音は撮影時の音（BGM あり）",
    ], OUT / "c_method.png")
    still(OUT / "c_method.png", 7, OUT / "p02.mp4"); parts.append(OUT / "p02.mp4")

    for i, pair in enumerate(PAIRS, 1):
        out = OUT / f"p1{i}.mp4"
        segment(i, pair, out)
        parts.append(out)

    text_card("結果", [
        "判断：答えが一つに決まる物は、実機でも一括評価（各 108 回）でも両方すべて正解",
        "分かれたのは信号機の色にないピンク。Fable は左（止まれ）、Jev は右",
        "判断の時間：Fable 4〜6 秒、Jev 0.2〜0.3 秒。費用は Jev が約 800 分の 1",
        "運べた数：Fable 9/9、Jev 9/9。アームの動きは共通のプログラムなので、モデルを替えても運び方は変わらない",
    ], OUT / "c_end.png")
    still(OUT / "c_end.png", 10, OUT / "p20.mp4"); parts.append(OUT / "p20.mp4")
    jingle(ED, OUT / "p99_ed.mp4"); parts.append(OUT / "p99_ed.mp4")

    lst = OUT / "parts.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    joined = OUT / "joined.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
         "-map_metadata", "-1", str(joined)])
    # BGM を頭から動画の終わりまで重ねる。終わりは 3 秒で消す
    total = duration(joined)
    final = ROOT / "video" / "out" / "sorter_vol4.mp4"
    bgm = OUT / "bgm_leveled.wav"
    level_bgm(BGM, bgm, total)
    fc = (f"[1:a]atrim=0:{total:.2f},asetpts=PTS-STARTPTS,"
          f"afade=t=in:st=0:d=1.5,afade=t=out:st={total - 3:.2f}:d=3[bg];"
          "[0:a][bg]amix=inputs=2:duration=first:normalize=0[aout]")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(joined), "-i", str(bgm), "-filter_complex", fc,
         "-map", "0:v", "-map", "[aout]", "-c:v", "copy", *ENC_A, "-map_metadata", "-1", str(final)])
    print(f"できました: {final.relative_to(ROOT)}（{duration(final):.0f} 秒）")


if __name__ == "__main__":
    main()
