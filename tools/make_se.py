# -*- coding: utf-8 -*-
"""make_se.py - 効果音(ドン・カッ・鈴)を合成して生成する

権利関係を自分で完結させるため、効果音はフリー素材を使わず、
このスクリプトで一から合成している。numpy と標準ライブラリだけで動く。

    cd tools
    python make_se.py

  生成物 (44100Hz / 16bit / ステレオ, play/ に出力)
    ドン.wav    和太鼓の面を打った音（低い胴鳴り）
    カッ.wav    縁を打った音（乾いた高い音）
    suzu.mp3 ではなく suzu.wav … 鈴（非調和倍音の減衰音）
"""
import os
import wave

import numpy as np

SR = 44100
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "play")


def _biquad_bandpass(x, f0, q):
    """2次のバンドパス。scipyを使わずに差分方程式で実装する。"""
    w0 = 2 * np.pi * f0 / SR
    alpha = np.sin(w0) / (2 * q)
    b = np.array([alpha, 0.0, -alpha])
    a = np.array([1 + alpha, -2 * np.cos(w0), 1 - alpha])
    b /= a[0]
    a = a / a[0]
    y = np.zeros_like(x)
    x1 = x2 = y1 = y2 = 0.0
    for i, xi in enumerate(x):
        yi = b[0] * xi + b[1] * x1 + b[2] * x2 - a[1] * y1 - a[2] * y2
        y[i] = yi
        x2, x1 = x1, xi
        y2, y1 = y1, yi
    return y


def _env(n, attack, decay, power=1.0):
    """立ち上がりの速い減衰エンベロープ。"""
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-6), 0, 1)
    d = np.exp(-t / decay) ** power
    return a * d


def make_don(dur=0.97):
    """和太鼓の面打ち。膜の張力が緩むことで生じる「ピッチの下降」が太鼓らしさの肝。"""
    n = int(SR * dur)
    t = np.arange(n) / SR

    # ピッチが 190Hz -> 78Hz へ急速に下がる（打面の非線形な振る舞い）
    f = 78 + (190 - 78) * np.exp(-t / 0.030)
    phase = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(phase) * _env(n, 0.0008, 0.34)

    # 円形膜の振動モード（ベッセル関数の零点比）。倍音ではなく非調和にする
    for ratio, gain, dec in ((1.593, 0.22, 0.12), (2.135, 0.13, 0.07), (2.295, 0.08, 0.05)):
        body += np.sin(2 * np.pi * 78 * ratio * t) * _env(n, 0.0008, dec) * gain

    # バチが当たる瞬間のアタック音
    rng = np.random.default_rng(1)
    click = _biquad_bandpass(rng.normal(0, 1, n), 1900, 1.1) * _env(n, 0.0002, 0.013) * 0.5

    # 胴の空気の鳴り
    air = np.sin(2 * np.pi * 52 * t) * _env(n, 0.004, 0.20) * 0.30

    y = body + click + air
    y = np.tanh(y * 1.5)                      # 軽く飽和させて胴鳴りの太さを出す
    return y


def make_ka(dur=0.54):
    """縁打ち。木の縁を叩いた乾いた高い音。減衰が非常に速い。"""
    n = int(SR * dur)
    t = np.arange(n) / SR
    rng = np.random.default_rng(2)

    noise = rng.normal(0, 1, n)
    hi = _biquad_bandpass(noise, 2600, 1.6) * _env(n, 0.0002, 0.030) * 1.0
    mid = _biquad_bandpass(noise, 1250, 3.0) * _env(n, 0.0003, 0.045) * 0.6

    # 木の縁がわずかに鳴る成分
    wood = (np.sin(2 * np.pi * 760 * t) * 0.35 + np.sin(2 * np.pi * 1130 * t) * 0.2)
    wood *= _env(n, 0.0004, 0.038)

    y = hi + mid + wood
    return np.tanh(y * 1.3)


def make_shan(dur=0.28, n_bells=14, f_lo=5000.0, f_hi=11000.0,
              dec=0.12, q=45.0, seed=11, rattle=0.9):
    """スレイベル（サンタの鈴）の「シャン」。

    単一の鈴ではなく、小さな鈴が房になって一斉に鳴る音。
    そのため正弦波を重ねる作り方ではなく、**ノイズを多数の高Qバンドパスに通す**
    方式で作る（金属の共鳴を模す古典的な手法）。

    シャンらしさの要点:
      ・鈴ごとに中心周波数がバラバラ → 密で非調和な金属の塊になる
      ・鳴り出しを数ミリ秒ずつずらす → 玉が擦れる「シャッ」という立ち上がり
      ・エネルギーは 4k〜10kHz。低域を持たせないと軽やかさが出る
    """
    n = int(SR * dur)
    rng = np.random.default_rng(seed)
    y = np.zeros(n)

    for i in range(n_bells):
        f = rng.uniform(f_lo, f_hi)
        if f > SR / 2 * 0.92:
            continue
        # 玉が擦れる時間差。これが無いと「ポン」と一発の音になってしまう
        onset = int(SR * rng.uniform(0.0, 0.008) * rattle)
        d = dec * rng.uniform(0.55, 1.25)
        seg = n - onset
        noise = rng.normal(0, 1, seg)
        res = _biquad_bandpass(noise, f, q * rng.uniform(0.7, 1.4))
        res *= _env(seg, 0.0003, d)
        y[onset:] += res * rng.uniform(0.6, 1.0)

    # 全体の立ち上がりを揃える明るいアタック（房がぶつかる瞬間）
    y += _biquad_bandpass(rng.normal(0, 1, n), (f_lo + f_hi) / 2, 0.8)          * _env(n, 0.0002, 0.010) * 0.6

    return y


def save_stereo(name, left, right, peak=0.55):
    """左右で鈴の配置を変えて広がりを出す。"""
    m = max(np.max(np.abs(left)), np.max(np.abs(right)))
    if m > 0:
        left, right = left / m * peak, right / m * peak
    fade = int(SR * 0.006)
    left[-fade:] *= np.linspace(1, 0, fade)
    right[-fade:] *= np.linspace(1, 0, fade)
    st = np.stack([(left * 32767).astype(np.int16),
                   (right * 32767).astype(np.int16)], axis=1)
    path = os.path.join(OUT, name)
    with wave.open(path, "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(st.tobytes())
    print(f"  {name:24} {len(left)/SR:.3f}s  {os.path.getsize(path)/1024:6.1f} KB")


def save(name, mono, peak=0.89):
    """ピークを揃えてステレオ16bit WAVで書き出す。"""
    m = np.max(np.abs(mono))
    if m > 0:
        mono = mono / m * peak
    fade = int(SR * 0.006)                    # 末尾のプチノイズ防止
    mono[-fade:] *= np.linspace(1, 0, fade)
    st = np.repeat((mono * 32767).astype(np.int16)[:, None], 2, axis=1)
    path = os.path.join(OUT, name)
    with wave.open(path, "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(st.tobytes())
    print(f"  {name:12} {len(mono)/SR:.3f}s  {os.path.getsize(path)/1024:6.1f} KB")


if __name__ == "__main__":
    print("効果音を合成中...")
    save("ドン.wav", make_don())
    save("カッ.wav", make_ka())
    save_stereo("suzu.wav", make_shan(seed=11), make_shan(seed=12))
    print(f"出力先: {OUT}")
