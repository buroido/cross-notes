# セットアップ

遊ぶまでの手順。学習し直す場合は [TRAINING.md](TRAINING.md) を参照。

## 1. 必要なもの

- **Windows**（フォントに meiryo、曲の再生に Windows の MIDI 出力を使うため）
- **Python 3.11**（動作確認は 3.11.9）
- **MIDI 出力デバイス** … Windows なら標準の「Microsoft GS Wavetable Synth」で動く

## 2. インストール

```
git clone https://github.com/buroido/cross-notes.git
cd cross-notes
pip install -r requirements.txt
```

入るもの:

| パッケージ | 動作確認バージョン | 用途 |
|---|---|---|
| `pygame` | 2.6.1 | 画面描画・キー入力・効果音・MIDI 出力 |
| `mido` | 1.3.3 | MIDI ファイルの解析 |
| `numpy` | 2.3.2 | 譜面データの処理 |
| `tensorflow` | 2.21.0 | レーン生成モデルの推論 |
| `tf-keras` | 2.21.0 | 同上（旧 Keras API。`tensorflow` とバージョンを揃える） |
| `matplotlib` | 3.10.8 | 学習曲線の描画（学習し直すときだけ必要） |

`chart_ai_osu.py` は `TF_USE_LEGACY_KERAS=1` を設定して旧 Keras API でモデルを読むため、
**`tensorflow` と `tf-keras` は同じマイナーバージョンに揃えてください。**
片方だけ上げるとモデルの読み込みで失敗します。

## 3. 遊ぶ曲を置く

**このリポジトリに曲は含まれていない。** `play/music/` に自分で `.mid` を置く。

```
play/
└── music/
    ├── 曲名A.mid
    ├── 曲名B.mid
    └── ...
```

- 拡張子 `.mid` のみ認識する（`.midi` は不可）
- **ファイル名がそのまま選曲画面に出る**ので、曲名を付けておくとよい
- サブフォルダは見ない。`play/music/` 直下に置く
- **曲中で BPM が変わる MIDI は非対応**。起動後に検出されて終了する
- 空のままだと `MIDIファイルがありません` と表示されて終了する

## 4. 起動する

**`play/` フォルダをカレントディレクトリにして**実行する。
効果音を相対パスで読むので、リポジトリのルートから `python play/game.py` とすると失敗する。

```
cd play
python game.py
```

タイトル画面が出れば成功。以降の操作は [README の操作方法](../README.md#操作方法) を参照。

## 5. 学習済みモデルについて

譜面のレーン配置に使うモデルは**同梱済み**なので、遊ぶだけなら学習は不要。

| ファイル | 役割 |
|---|---|
| `play/osu_lane_model.keras` | 学習済み GRU 本体 |
| `play/osu_dataset.npz` | 学習データ。推論時は「音符間隔バケットの境界」だけ読む |

`osu_dataset.npz` が無くても既定値で動くが、学習時と境界がずれるので置いたままにする。

動作確認だけしたいときは、ゲームを起動せずに推論ヘルパ単体を叩ける:

```
cd play
python chart_ai_osu.py
```

等間隔のノーツ20個に対するレーン列が2通り（temperature 0 と 0.7）表示されれば正常。

## つまずいたら

| 症状 | 原因と対処 |
|---|---|
| `MIDIファイルがありません` | `play/music/` に `.mid` が無い。手順3 |
| `ドン.wav` が見つからない | `play/` 以外から起動している。手順4 |
| `BPMの変化があるため非対応です` | その曲は使えない。別の MIDI を選ぶ |
| 曲が鳴らない / MIDI 出力のエラー | MIDI 出力デバイスが無い。`game.py` の `pygame.midi.Output(1)` の番号を環境に合わせる |
| モデルの読み込みで落ちる | `pip install tf-keras` が入っているか確認（`TF_USE_LEGACY_KERAS=1` で動かしている） |
| 譜面生成が遅い | CPU 推論で1音ずつ生成するため曲が長いほど待つ。ロード画面が出ていれば動いている |
