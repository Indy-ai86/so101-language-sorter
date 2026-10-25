# 言葉のルールで仕分けるロボットアーム（SO-101）

Physical AI 講座 2026 応用編1 の最終課題。日本語で書いた仕分けルールに従って、机の上の物体を SO-101 アームで3つのカップに仕分ける。

- 物体の検出：真上のカメラ（C920）と色の範囲による切り出し
- 判断：LLM（Claude Fable 5.1）が物体ごとに置き場と自信（0〜1）を返す
- 動作：リーダーアームで教えた 3×3 点の姿勢を双線形補間（学習・逆運動学なし）

結果とその分析は [report/report.pdf](report/report.pdf) にある。

## 結果

| 項目 | 結果 |
|---|---|
| ルール判断の一括評価（12ルール・108回） | 答えが一つに決まる 197 件はすべて正解 |
| 実機の通し試験（3ルール × 3個） | 9個中 8個を正しいカップへ運んだ |

## ファイル

| ファイル | 役割 |
|---|---|
| `config.yaml` | カメラ・色の範囲・アームの設定 |
| `rules.yaml` | 仕分けルール（r01〜r12） |
| `calibrate.py` | 画像と机の座標（cm）を方眼の四隅で対応づける |
| `record.py` | 撮影して物体を検出し、状態を `runs/` に保存する |
| `decide.py` | 状態にルールを当てはめ、LLM に判断させる（一括評価） |
| `teach.py` | リーダーアームで姿勢を教える。`--test-bins` で置き場を物なしで試す |
| `arm.py` | アームの接続、補間、移動 |
| `sort.py` | 撮影 → 判断 → 掴んで運ぶ、を通しで行う |
| `check_grasp.py` | 掴む姿勢で止めて、位置のずれを確かめる |
| `evaluate.py` | 判断と実機の記録を集計する |
| `report/` | レポートと図の作成 |
| `video/make_video.py` | 提出動画の編集（字幕は実行記録から作る） |
| `runs/` | 撮影した状態・判断・実機の成否の記録（JSON） |

## 動かし方

Python の環境に lerobot（0.4.4）、opencv-python、numpy、pyyaml が要る。判断には Claude Code（`claude` コマンド）を使う。

```
python calibrate.py --points 140,155 383,157 388,318 141,327   # 方眼の四隅（画像の画素）
python teach.py --only grid,bin --fix-roll 20.8 --fix-gripper   # 姿勢を教える
python teach.py --test-bins                                     # 置き場を物なしで試す
python sort.py --rule r01 --step --judge                        # 実機で仕分け
python decide.py runs/20261024/states.jsonl                     # 判断の一括評価
python evaluate.py                                              # 集計
```

ポート名、キャリブレーション名、教えた姿勢（`poses.json`）は、使う機材ごとに作り直す必要がある。

動画の OP・ED・タイトルスライドは講座の配布物なので、このリポジトリには含めていない。`video/make_video.py` は `~/Downloads` にそれらがある前提で動く。
