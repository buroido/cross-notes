# -*- coding: utf-8 -*-
"""
chart_ai_osu.py - 実譜面学習GRU(osu_lane_model.keras)でレーン配置を推論するヘルパ

音楽ゲーム「クロス・ノーツ」(EC2save7_ai.py) から import して使う。

旧 chart_ai.py との違い:
  ・教師が「合成メロディ＋人手ルール」ではなく "osu!mania の実譜面"。
  ・入力が「音高の上下」ではなく「前のレーン(4) + 直前の音符間隔バケット(3)」。
    -> 音高ではなく "ノーツの時刻列" を渡す。
  ・自己回帰型: 1音ずつレーンを生成し, その結果を次の入力に戻す。
    (学習時は実譜面の前レーンを与えていたが, 新曲には正解が無いため,
     モデル自身の直前出力を前レーンとして使う = 偽文生成と同じ生成手順)

使い方:
    import chart_ai_osu
    lanes = chart_ai_osu.predict_lanes(times)        # times: ノーツ時刻[秒]の昇順リスト
    lanes = chart_ai_osu.predict_lanes(times, temperature=0.5)  # 揺らぎを加える

(今日の日付) by 宇佐見飛翔
"""
import os

os.environ["TF_USE_LEGACY_KERAS"] = "1"
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
import tensorflow as tf
from tensorflow import keras

N_LANES    = 4
N_GAP_BINS = 3
FEAT_DIM   = N_LANES + N_GAP_BINS      # = 7 (train_osu_GRU.py と同じ)
N_UNITS    = 48

_HERE      = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_HERE, "osu_lane_model.keras")
NPZ_PATH   = os.path.join(_HERE, "osu_dataset.npz")

# 学習時に決めた間隔バケット境界[ms]。npz があればそこから読み, 無ければ既定値。
def _load_gap_edges():
    try:
        d = np.load(NPZ_PATH)
        return np.asarray(d["gap_edges"], dtype=np.float64)
    except Exception:
        return np.array([87.0, 120.0])      # 既定(35譜面学習時の値)

GAP_EDGES = _load_gap_edges()

_gen = None      # stateful な 1 ステップ推論モデル


def _build_gen():
    """学習済みモデルの重みを, 1ステップずつ状態を持って推論する
    stateful モデルへ移し替える(O(n) で自己回帰生成するため)。"""
    base = keras.models.load_model(MODEL_PATH)
    gen = keras.models.Sequential([
        keras.layers.Input(batch_shape=(1, 1, FEAT_DIM)),
        keras.layers.GRU(N_UNITS, return_sequences=True, stateful=True),
        keras.layers.GRU(N_UNITS, return_sequences=True, stateful=True),
        keras.layers.TimeDistributed(
            keras.layers.Dense(N_LANES, activation="softmax")),
    ])
    gen.set_weights(base.get_weights())     # 同一構造なので重みをそのまま移植
    return gen


def _get_gen():
    global _gen
    if _gen is None:
        _gen = _build_gen()
    return _gen


def _gap_bin(gap_ms):
    """音符間隔[ms] -> バケット番号 0..N_GAP_BINS-1"""
    b = int(np.searchsorted(GAP_EDGES, gap_ms, side="right"))
    return min(b, N_GAP_BINS - 1)


def predict_lanes(times, temperature=0.0):
    """ノーツ時刻[秒]の昇順リストからレーン番号列(0-3)を生成する。
    temperature=0 なら最尤(argmax)、>0 なら確率的サンプリングで揺らぎを加える。"""
    n = len(times)
    if n == 0:
        return []
    gen = _get_gen()
    gen.reset_states()                      # 曲の先頭で内部状態をリセット

    lanes = []
    prev_lane = None
    for t in range(n):
        x = np.zeros((1, 1, FEAT_DIM), dtype=np.float32)
        if prev_lane is None:               # 開始トークン: 前レーン無し・間隔=長
            x[0, 0, N_LANES + (N_GAP_BINS - 1)] = 1.0
        else:
            x[0, 0, prev_lane] = 1.0        # 直前に生成したレーン
            gap_ms = (times[t] - times[t - 1]) * 1000.0
            x[0, 0, N_LANES + _gap_bin(gap_ms)] = 1.0

        proba = gen.predict(x, verbose=0)[0, 0]     # (N_LANES,)
        if temperature <= 0.0:
            lane = int(np.argmax(proba))
        else:
            logits = np.log(np.clip(proba, 1e-9, 1.0)) / temperature
            lane = int(tf.random.categorical([logits], 1)[0, 0])
        lanes.append(lane)
        prev_lane = lane
    return lanes


if __name__ == "__main__":
    # 動作確認: 等間隔(0.25秒)のノーツ20個に対し生成
    demo_times = [i * 0.25 for i in range(20)]
    print("gap edges[ms]:", GAP_EDGES.tolist())
    print("times :", [round(t, 2) for t in demo_times])
    print("lanes :", predict_lanes(demo_times))
    print("lanes(temp=0.7):", predict_lanes(demo_times, temperature=0.7))
