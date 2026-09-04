# クロス・ノーツ ― 実譜面(osu!mania)を教師にした GRU 譜面レーン生成

自作の音楽ゲーム「クロス・ノーツ」の譜面のレーン配置（D・F・J・K の4鍵）を、
人間が作った実譜面(osu!mania 4K)を教師に学習した GRU で生成する実装一式。

元のゲームはレーンを `column = random.randint(0, 3)` の完全な乱数で決めており、
配置が音楽と無関係だった。ここではそれを学習モデルの出力に置き換えている。

- 入力: 前ステップのレーン分布(4) ＋ 直前のノーツ間隔バケット one-hot(3) = 7次元
- 出力: そのステップのレーン分布(4)。同時押し(和音)は鳴る全レーンへ均等な確率を割り当てる
- 損失: categorical_crossentropy / GRU(48)×2 + TimeDistributed(Dense(4, softmax))
- 推論は自己回帰: 1音ずつレーンを生成し、その出力を次の入力へ戻す

「前の記号から次の記号を予測」という枠組みは同じで、記号を文字からレーンに
置き換えたもの。教師がルールではなく実データなので、十数行のルールでは書けない
人手の癖（左右交互打ち・トリル・階段など）を学習できる。

## ファイル構成

### 学習・前処理
- `parse_osu.py` … `osu_data/` の .osu を走査し、mania 4K のみ抽出して学習データ `osu_dataset.npz` を作る
- `train_osu_GRU.py` … `osu_dataset.npz` から GRU を学習し `osu_lane_model.keras` を保存。学習曲線を `osu_learning_curve.png` に出力

### 推論ヘルパ
- `chart_ai_osu.py` … 学習済みモデルを読み込み、ノーツ時刻列[秒] → レーン列(0-3) を生成。ゲーム本体から import される

### ゲーム本体
- `game.py` … プロセカ風モードのレーン配置を `chart_ai_osu` で生成する版。
  曲選択・モード選択のあとに **temperature 調整画面**（↑↓/←→ で 0.0〜1.5、Enter で決定）が入る。
  0 = 最尤で規則的な配置、1.0 = 学習した確率をそのまま使う（人手の譜面に最も近い）、大きいほど揺らぐ。
  譜面生成（GRU推論）中はロード画面を表示する

### データ・素材
- `osu_data/` … 教師に使った実譜面（.osu のみ。音源・画像は除外）**※このリポジトリには含めない**
- `osu_dataset.npz` … 前処理済み学習データ (X, Y, gap_edges)
- `osu_lane_model.keras` … 学習済みモデル
- `music/` … 選曲できる楽曲(MIDI) **※このリポジトリには含めない**
- `ドン.wav` / `カッ.wav` / `suzu.mp3` … 効果音

## 実行方法

環境: Python 3.11 / tensorflow (tf_keras) / pygame / mido / numpy / matplotlib

```
pip install -r requirements.txt
```

カレントディレクトリをこのフォルダにして実行する。
遊ぶだけなら学習は不要（学習済みモデルを読み込むだけ）。

```
python game.py     # プレイ（曲選択 → モード/難易度選択 → temperature 調整 → 生成 → プレイ）
```

学習し直す場合（`osu_data/` に譜面を足した、設定を変えた等）:

```
python parse_osu.py        # osu_data/ -> osu_dataset.npz
python train_osu_GRU.py    # -> osu_lane_model.keras, osu_learning_curve.png
```

データの流れ:

```
osu_data/(実譜面) --parse_osu.py--> osu_dataset.npz --train_osu_GRU.py--> osu_lane_model.keras
                                                     --(遊ぶ)--> chart_ai_osu.py --> game.py
```

## 注意
- 第三者の著作物にあたる `osu_data/`(実譜面) と `music/`(楽曲MIDI) はこのリポジトリに含めていない。
  遊ぶには `music/` に MIDI を、学習し直すには `osu_data/set_XX/` に .osu を各自で用意する
  （`osu_dataset.npz` と `osu_lane_model.keras` は含めてあるので、遊ぶだけなら学習は不要）
- フォントは Windows のシステムフォント (meiryo) を使用
