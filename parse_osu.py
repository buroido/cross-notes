# -*- coding: utf-8 -*-
"""
parse_osu.py - osu!mania(4K) の実譜面から学習データを作る

自由課題(実譜面版)。第10-11回「偽文生成(GRUによる記号列生成)」の枠組みを、
合成メロディ+ルール教師ではなく "人間が作った実譜面" に適用するための前処理。

  やること:
    1. osu_data/ 以下の .osu を走査し, Mode:3(mania) かつ 4鍵 のものだけ採用
    2. [HitObjects] からノーツの (時刻ms, レーン) を抽出   lane = x * 4 // 512
    3. 同時押し(和音)は捨てずにまとめ, その時刻の全レーンへ均等な確率を割り当てる
       (例: レーン1と3の同時押し -> [0, 0.5, 0, 0.5])
    4. 「前ステップのレーン分布(4) + 直前間隔のバケット one-hot(3)」を入力,
       「そのステップのレーン分布(4)」を出力 とする系列を作る
       -> 第10-11回と同じ "前の記号から次の記号を予測" の自己回帰型
          (和音を等重みの分布で表すため, 学習は categorical_crossentropy を使う)

  なぜルールでなく学習なのか:
    レーンは音高の決定的な関数ではなく, 同じリズムでも曲・文脈で人が違う鍵を
    選ぶ。その "人手の癖(左右交互打ち, 連打, トリル...)" は十数行のルールでは
    書けないので, 実譜面を教師にした学習で初めて意味が出る。

実行: python parse_osu.py   (osu_data/ を読み, 統計と抽出例を表示, dataset.npz を保存)

(今日の日付) by 宇佐見飛翔
"""
import os
import glob
import numpy as np

#
# PARAMETER(S)
#
DATA_DIR   = "osu_data"     # .osu を置くフォルダ(サブフォルダも再帰探索)
KEYS       = 4              # 4鍵(D F J K)固定
N_GAP_BINS = 3              # 直前間隔のバケット数 (短/中/長)
WINDOW     = 24             # 1系列あたりのステップ数(既存GRUに合わせる)
OUT_NPZ    = "osu_dataset.npz"

FEAT_DIM   = KEYS + N_GAP_BINS   # 入力次元 = 前レーン(4) + 間隔バケット(3) = 7


#
# 1. .osu のパース
#
def read_osu_meta_and_notes(path):
    """1つの .osu を読み, (mode, keys, notes) を返す。
    notes = [(time_ms, lane), ...] (時刻昇順, mania 4K 以外なら None)。"""
    mode = None
    keys = None
    notes = []
    in_hitobjects = False
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line.startswith("Mode:"):
                mode = int(line.split(":", 1)[1])
            elif line.startswith("CircleSize:"):
                # mania では CircleSize が鍵数(整数)
                try:
                    keys = int(round(float(line.split(":", 1)[1])))
                except ValueError:
                    keys = None
            elif line == "[HitObjects]":
                in_hitobjects = True
            elif in_hitobjects and line and not line.startswith("["):
                p = line.split(",")
                if len(p) < 3:
                    continue
                x = int(p[0])
                t = int(p[2])
                lane = x * KEYS // 512
                lane = min(max(lane, 0), KEYS - 1)
                notes.append((t, lane))

    if mode != 3 or keys != KEYS:        # mania かつ 4鍵 でなければ捨てる
        return mode, keys, None
    notes.sort(key=lambda r: r[0])
    return mode, keys, notes


def group_chords(notes):
    """同時刻のノーツをまとめ、その時刻に鳴る全レーンへ均等な確率を割り当てる。
    -> 各ステップを (time_ms, dist) とする。dist は長さKEYSで合計1。
       例: レーン1と3の同時押し -> [0, 0.5, 0, 0.5] (両レーンに同じ重み)。
       単押し(レーン2) -> [0, 0, 1, 0]。
    和音を捨てず「その時刻の全レーンを等しく学ぶ」ようにするための変更。"""
    out = []
    i, n = 0, len(notes)
    while i < n:
        t = notes[i][0]
        dist = np.zeros(KEYS, dtype=np.float32)
        while i < n and notes[i][0] == t:      # 同時刻をまとめる
            dist[notes[i][1]] = 1.0
            i += 1
        dist /= dist.sum()                     # 均等重み(合計1)
        out.append((t, dist))
    return out


def load_mania_charts(data_dir):
    """data_dir 以下の全 .osu から mania 4K 譜面のノーツ列を集める。
    レーン列が完全一致する譜面(速度違いコピー等)は最初の1つだけ採用し,
    特定曲が過剰に重み付けされる(過学習・偏り)のを防ぐ。"""
    charts = []
    skipped = 0
    dup = 0
    seen_lanes = set()
    for path in glob.glob(os.path.join(data_dir, "**", "*.osu"), recursive=True):
        _, _, notes = read_osu_meta_and_notes(path)
        if notes is None or len(notes) < WINDOW + 1:
            skipped += 1
            continue
        notes = group_chords(notes)
        if len(notes) < WINDOW + 1:
            skipped += 1
            continue
        # レーン集合の列で重複判定(速度違いコピー等を除去)
        lane_key = tuple(tuple(np.nonzero(d)[0].tolist()) for _, d in notes)
        if lane_key in seen_lanes:
            dup += 1
            continue
        seen_lanes.add(lane_key)
        charts.append((os.path.basename(path), notes))
    return charts, skipped, dup


#
# 2. 特徴量への変換
#
def gap_bin_edges(charts):
    """全譜面の隣接間隔から分位点を取り, バケット境界(短/中/長)を決める。"""
    gaps = []
    for _, notes in charts:
        for i in range(1, len(notes)):
            gaps.append(notes[i][0] - notes[i - 1][0])
    gaps = np.array(gaps, dtype=np.float64)
    # N_GAP_BINS=3 -> 33%,66% 分位点で 3 分割
    qs = np.linspace(0, 1, N_GAP_BINS + 1)[1:-1]
    return np.quantile(gaps, qs)


def gap_to_bin(gap, edges):
    """間隔(ms) -> バケット番号 0..N_GAP_BINS-1"""
    return int(np.searchsorted(edges, gap, side="right"))


def chart_to_steps(notes, edges):
    """1譜面のステップ列 -> (X_feat[t], Y_dist[t])。
      入力 X[t] = 前ステップのレーン分布(4) + one_hot(直前間隔バケット)(3)
      出力 Y[t] = そのステップのレーン分布(4)  (和音は均等: 例 [0,.5,0,.5])
    先頭は前レーン無し(ゼロ)・間隔最長バケットを開始トークンとする。"""
    n = len(notes)
    X = np.zeros((n, FEAT_DIM), dtype=np.float32)
    Y = np.zeros((n, KEYS), dtype=np.float32)
    for t in range(n):
        cur_t, cur_dist = notes[t]
        Y[t] = cur_dist                               # 正解=レーン分布
        if t == 0:
            X[t, KEYS + (N_GAP_BINS - 1)] = 1.0       # 開始: 間隔=長
        else:
            prev_t, prev_dist = notes[t - 1]
            X[t, :KEYS] = prev_dist                   # 前レーン分布
            b = gap_to_bin(cur_t - prev_t, edges)
            X[t, KEYS + b] = 1.0                      # 間隔バケット one-hot
    return X, Y


def build_dataset(charts, edges, window=WINDOW):
    """全譜面を window 長に切り出して X=(N,window,FEAT_DIM), Y=(N,window,KEYS) にまとめる。"""
    Xs, Ys = [], []
    for _, notes in charts:
        X, Y = chart_to_steps(notes, edges)
        n = len(notes)
        for s in range(0, n - window + 1, window):    # 非重複で切り出し
            Xs.append(X[s:s + window])
            Ys.append(Y[s:s + window])
    if not Xs:
        return (np.zeros((0, window, FEAT_DIM), np.float32),
                np.zeros((0, window, KEYS), np.float32))
    return np.stack(Xs), np.stack(Ys)


#
# MAIN
#
def main():
    print(f"[SCAN] {DATA_DIR}/")
    charts, skipped, dup = load_mania_charts(DATA_DIR)
    print(f"  mania(4K) 譜面: {len(charts)} 件   "
          f"(mania以外/短すぎ等でskip: {skipped}, レーン列が重複でskip: {dup})")
    if not charts:
        print("  -> mania 4K 譜面が見つかりません。osu!mania の譜面をDLしてください。")
        return

    total_steps = sum(len(n) for _, n in charts)
    print(f"  総ステップ数(和音まとめ後): {total_steps}")
    for name, notes in charts:
        print(f"    {len(notes):5d} steps  {name[:60]}")

    edges = gap_bin_edges(charts)
    print(f"\n[GAP BINS] 間隔バケット境界(ms): {np.round(edges).astype(int).tolist()}  "
          f"(短 < {int(edges[0])} <= 中 < {int(edges[-1])} <= 長)")

    # 抽出例(最初の譜面の先頭 15 ステップ)
    name0, notes0 = charts[0]
    X0, Y0 = chart_to_steps(notes0, edges)
    print(f"\n[EXAMPLE] {name0[:60]}")
    print("  step  time_ms  Y(レーン分布)        | prev_lane_dist       gap")
    for t in range(min(15, len(notes0))):
        prev = "----------------" if t == 0 else ",".join(
            f"{v:.1f}" for v in X0[t, :KEYS])
        gap = "".join(str(int(v)) for v in X0[t, KEYS:])
        ydist = ",".join(f"{v:.1f}" for v in Y0[t])
        print(f"  {t:4d}  {notes0[t][0]:7d}  [{ydist}]  |  {prev}  {gap}")

    X, Y = build_dataset(charts, edges)
    print(f"\n[DATASET] X={X.shape}  Y={Y.shape}   (入力次元 FEAT_DIM={FEAT_DIM})")
    if len(X) == 0:
        print("  -> 系列が作れませんでした(譜面が短い/少ない)。譜面を増やしてください。")
        return

    np.savez(OUT_NPZ, X=X, Y=Y, gap_edges=edges)
    print(f"saved: {OUT_NPZ}")
    print("\n次のステップ: この osu_dataset.npz を読んで既存GRU(入力次元7)で学習する。")


if __name__ == "__main__":
    main()
