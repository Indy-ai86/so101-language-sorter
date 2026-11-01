# 言葉のルールで仕分けるロボットアーム（SO-101）

Physical AI 講座 2026 応用編1 の最終課題。日本語で書いた仕分けルールに従って、机の上の物体を SO-101 アームで3つのカップに仕分ける。

- 物体の検出：真上のカメラ（C920）と色の範囲による切り出し
- 判断：判断モデルが物体ごとに置き場と確からしさ（0〜1）を返す。Claude Fable 5.1・GPT-6 Astra・Jev（TypeSafe）を切り替えられる
- 動作：リーダーアームで教えた 3×3 点の姿勢を双線形補間（学習・逆運動学なし）

結果とその分析は [report/72306.pdf](report/72306.pdf)（3モデルの比較。元の文書は `report/report_vol5.md`）にある。最初の版（Fable のみ）は [report/report.pdf](report/report.pdf)。

## 結果

| 項目 | Claude Fable 5.1 | GPT-6 Astra | Jev 1.14 |
|---|---|---|---|
| ルール判断の一括評価（12ルール・108回） | 答えが決まる 197 件すべて正解 | 197 件すべて正解 | 197 件すべて正解 |
| 判断1回の時間（平均） | 5.3 秒 | 5.3 秒 | 0.18 秒 |
| 実機の通し試験（3ルール × 3個、同じ日） | 9個中 9個 | 9個中 9個 | 9個中 9個 |
| 信号機のルールでピンクを | 「赤」とみなして左へ | 「赤」とみなして左へ | 「赤」とみなさず右へ |

答えが一つに決まる物では、3つのモデルの判断は一致した。分かれたのは、ルールに当てはまるか曖昧な物だけだった。

## ファイル

| ファイル | 役割 |
|---|---|
| `config.yaml` | カメラ・色の範囲・判断モデル・アームの設定 |
| `rules.yaml` | 仕分けルール（r01〜r12） |
| `calibrate.py` | 画像と机の座標（cm）を方眼の四隅で対応づける |
| `record.py` | 撮影して物体を検出し、状態を `runs/` に保存する |
| `decide.py` | 状態にルールを当てはめ、判断モデルに判断させる（一括評価）。`--backend fable/astra/jev` |
| `teach.py` | リーダーアームで姿勢を教える。`--test-bins` で置き場を物なしで試し、指令との関節角の差も表示する |
| `arm.py` | アームの接続、補間、移動 |
| `sort.py` | 撮影 → 判断 → 掴んで運ぶ、を通しで行う。`--backend` で判断モデルを替える |
| `check_grasp.py` | 掴む姿勢で止めて、位置のずれを確かめる |
| `evaluate.py` | 判断と実機の記録を、判断モデルごとに集計する。モデル間で置き場が分かれた物も一覧にする |
| `report/` | レポートと図の作成（`report_vol5.md`・`make_figures_vol5.py` が3モデル比較の版） |
| `video/` | 提出動画の編集（`make_video_vol5.py` が3モデル比較の版。字幕は実行記録から作る） |
| `runs/` | 撮影した状態・判断・実機の成否の記録（JSON） |

## 動かし方

Python の環境に lerobot（0.4.4）、opencv-python、numpy、pyyaml、Pillow が要る。判断モデルごとに次が要る。

- Fable：Claude Code（`claude` コマンド）にログインしていること
- Astra：Codex CLI（`codex` コマンド）にログインしていること
- Jev：TypeSafe の API キーを、環境変数 `TYPESAFE_API_KEY` かこのフォルダの `keys.env`（git には入れない）に置くこと

```
python calibrate.py --points 152,151 393,151 400,312 155,322   # 方眼の四隅（画像の画素）
python teach.py --only grid,bin --fix-roll 20.8 --fix-gripper   # 姿勢を教える
python teach.py --test-bins                                     # 置き場を物なしで試す
python check_grasp.py                                           # 掴む位置を物 1 個で確かめる
python sort.py --rule r01 --backend jev --step --judge          # 実機で仕分け
python decide.py runs/20261024/states_batch.jsonl --backend astra   # 判断の一括評価
python evaluate.py                                              # 集計
```

ポート名、キャリブレーション名、教えた姿勢（`poses.json`）は、使う機材ごとに作り直す必要がある。

動画の OP・ED・タイトルスライドは講座の配布物なので、このリポジトリには含めていない。撮影した動画と BGM も含めていない。`video/` のスクリプトは `~/Downloads` にそれらがある前提で動く。BGM は CMSL クラシック名曲サウンドライブラリー「ラストシンフォニー」のライセンスフリー素材音源（https://classical-sound.seesaa.net/article/464440694.html）を使った。
