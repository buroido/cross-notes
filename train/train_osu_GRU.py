# -*- coding: utf-8 -*-
"""
train_osu_GRU.py - osu!mania(4K) 実譜面のレーン配置を GRU で学習する

自由課題(実譜面版)。gen_chart_GRU.py は「合成メロディ＋人が書いたルール」を
教師にしていたため, 出力はルールの決定的な再現にすぎず, 同じことが十数行の
ルールで書けてしまう(=学習する意味が薄い)という弱点があった。

本スクリプトでは教師を "人間が作った実譜面(osu!mania 4K)" に置き換える。
レーンは音高やリズムの決定的な関数ではなく, 同じ状況でも作譜者が文脈で
違う鍵を選ぶ。その "人手の癖" はルールでは書けないので, 実データからの
学習で初めて意味が出る。

  入力 (parse_osu.py が作る osu_dataset.npz):
    X[t] = 前ステップのレーン分布(4) + one_hot(直前間隔バケット)(3)  = 7 次元
  出力:
    Y[t] = そのステップのレーン分布(4)。和音(同時押し)は鳴る全レーンへ均等な
           確率を割り当てる(例: レーン1と3 -> [0,0.5,0,0.5])。
           -> 分布を正解にするため損失は categorical_crossentropy を使う。

  -> 第10-11回「前の記号から次の記号を予測」と同型。記号が文字→レーン,
     文脈が単語列→譜面の流れ に変わっただけ。

評価:
    次レーン的中率(予測レーンがその時刻に実在するか。和音はどちらでも的中)を,
    2つの素朴なベースラインと比較する。
      (a) ランダム      : その時刻に鳴っているレーン数/4 の平均
      (b) 1次マルコフ   : P(lane_t | lane_{t-1}) の最頻レーン(履歴のみ)
    GRUがこれらを上回れば, 単純な統計を超えた癖を学べたことになる。

実行: python train_osu_GRU.py   (先に python parse_osu.py で npz を作る)

(今日の日付) by 宇佐見飛翔
Python 3.11 with tf_keras (keras2)
"""
import os
import datetime

os.environ["TF_USE_LEGACY_KERAS"] = "1"
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
import tensorflow as tf
from tensorflow import keras
import matplotlib.pyplot as plt

#
# PARAMETER(S)
#
SEED       = 1
N_LANES    = 4
_HERE      = os.path.dirname(os.path.abspath(__file__))
_PLAY      = os.path.join(_HERE, os.pardir, "play")   # 学習成果物の置き場(遊ぶ側)

NPZ_PATH   = os.path.join(_PLAY, "osu_dataset.npz")
MODEL_PATH = os.path.join(_PLAY, "osu_lane_model.keras")
CURVE_PATH = os.path.join(_HERE, "osu_learning_curve.png")

N_UNITS    = 48
EPOCHS     = 30
BATCH_SIZE = 64
VAL_RATIO  = 0.2


def set_seed(seed):
    np.random.seed(seed)
    tf.random.set_seed(seed)


#
# 1. データ読み込みと分割
#
def load_dataset():
    d = np.load(NPZ_PATH)
    # Y はレーン分布(N,T,4)。和音は等重み(例[0,.5,0,.5])
    X, Y = d["X"].astype(np.float32), d["Y"].astype(np.float32)
    feat_dim = X.shape[2]
    # 系列単位でシャッフルして train/val 分割
    n = len(X)
    idx = np.random.permutation(n)
    X, Y = X[idx], Y[idx]
    n_val = int(n * VAL_RATIO)
    return (X[n_val:], Y[n_val:], X[:n_val], Y[:n_val], feat_dim)


#
# 2. GRU モデル (gen_chart_GRU.py と同構造, 入力次元だけ 7 に)
#
def build_model(feat_dim):
    model = keras.models.Sequential([
        keras.layers.Input([None, feat_dim]),
        keras.layers.GRU(N_UNITS, return_sequences=True, dropout=0.1),
        keras.layers.GRU(N_UNITS, return_sequences=True, dropout=0.1),
        keras.layers.TimeDistributed(
            keras.layers.Dense(N_LANES, activation="softmax")),
    ])
    # 正解がレーン分布(和音は等重み)なので categorical_crossentropy を使う
    model.compile(loss="categorical_crossentropy",
                  optimizer="Adam", metrics=["accuracy"])
    return model


#
# 3. 評価とベースライン
#
def hit_rate(pred_lane, Y):
    """次レーン的中率: 予測したレーンが, その時刻に実在するレーンか。
    Y はレーン分布(…,4)。和音のときはどちらのレーンを当てても的中とする。
    pred_lane:(N,T) の予測レーン, Y:(N,T,4)。"""
    picked = np.take_along_axis(Y, pred_lane[..., None], axis=2)[..., 0]
    return float((picked > 0).mean())


def markov_baseline(X_train, Y_train, X_val, Y_val):
    """1次マルコフ: 学習データから P(lane_t | lane_{t-1}) を数え,
    各 前レーン に対し最頻の次レーンを予測する(履歴だけのモデル)。
    前レーンは入力 X の先頭 4 次元(分布)に入っている。"""
    table = np.zeros((N_LANES + 1, N_LANES), dtype=np.float64)  # 行N_LANES=開始
    def prev_lane(xrow):
        oh = xrow[:N_LANES]
        return int(np.argmax(oh)) if oh.sum() > 0 else N_LANES
    for s in range(len(X_train)):
        for t in range(X_train.shape[1]):
            table[prev_lane(X_train[s, t])] += Y_train[s, t]   # 分布を加算
    pred_map = np.argmax(table, axis=1)   # 前レーン -> 最頻次レーン
    pred_lane = np.zeros(Y_val.shape[:2], dtype=np.int64)
    for s in range(len(X_val)):
        for t in range(X_val.shape[1]):
            pred_lane[s, t] = pred_map[prev_lane(X_val[s, t])]
    return hit_rate(pred_lane, Y_val)


#
# 4. 可視化
#
def plot_history(history):
    epochs = range(1, len(history.history["loss"]) + 1)
    plt.figure(figsize=(10, 4))
    plt.subplot(1, 2, 1)
    plt.plot(epochs, history.history["loss"], "o-", label="train")
    plt.plot(epochs, history.history["val_loss"], "o-", label="validation")
    plt.xlabel("epoch"); plt.ylabel("loss"); plt.title("Loss"); plt.legend(); plt.grid(True)
    plt.subplot(1, 2, 2)
    plt.plot(epochs, history.history["accuracy"], "o-", label="train")
    plt.plot(epochs, history.history["val_accuracy"], "o-", label="validation")
    plt.xlabel("epoch"); plt.ylabel("accuracy"); plt.title("Accuracy"); plt.legend(); plt.grid(True)
    plt.tight_layout()
    plt.savefig(CURVE_PATH, dpi=140)
    print(f"saved: {CURVE_PATH}")


#
# MAIN
#
def main():
    print("TensorFlow :", tf.__version__)
    set_seed(SEED)

    if not os.path.exists(NPZ_PATH):
        print(f"  {NPZ_PATH} がありません。先に  python parse_osu.py  を実行してください。")
        return

    print("\n[LOAD DATASET]")
    X_train, Y_train, X_val, Y_val, feat_dim = load_dataset()
    print(f"  X_train={X_train.shape}  X_val={X_val.shape}  feat_dim={feat_dim}")

    print("\n[BASELINES]")
    # ランダムの期待的中率 = その時刻に鳴っているレーン数/4 の平均
    rand_acc = float((Y_val > 0).sum(axis=2).mean()) / N_LANES
    mk_acc = markov_baseline(X_train, Y_train, X_val, Y_val)
    print(f"  random          : {rand_acc*100:5.1f}%")
    print(f"  1st-order Markov : {mk_acc*100:5.1f}%")

    print("\n[GRU DEFINITION]")
    model = build_model(feat_dim)
    model.summary()

    print(f"\n{datetime.datetime.now()} model.fit() begins ...")
    history = model.fit(
        X_train, Y_train,
        validation_data=(X_val, Y_val),
        epochs=EPOCHS, batch_size=BATCH_SIZE, verbose=2,
    )
    print(f"{datetime.datetime.now()} model.fit() finished")

    loss = model.evaluate(X_val, Y_val, verbose=0)[0]
    # GRUの的中率もベースラインと同じ定義(予測レーンが実在するか)で測る
    pred_lane = np.argmax(model.predict(X_val, verbose=0), axis=2)
    acc = hit_rate(pred_lane, Y_val)
    model.save(MODEL_PATH)
    print(f"saved: {MODEL_PATH}")

    print("\n[RESULT] 次レーン的中率(検証データ)")
    print(f"  random          : {rand_acc*100:5.1f}%")
    print(f"  1st-order Markov : {mk_acc*100:5.1f}%")
    print(f"  GRU (learned)    : {acc*100:5.1f}%   (val loss={loss:.4f})")
    if acc > mk_acc:
        print("  -> GRUが1次マルコフを上回った: 履歴1個では捉えられない,")
        print("     より長い文脈(連打/トリル/左右交互)の癖を学べている。")

    plot_history(history)
    print("\nPAUSE:: close the graphics window to finish.")
    plt.show()


if __name__ == "__main__":
    main()
