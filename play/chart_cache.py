# -*- coding: utf-8 -*-
"""chart_cache.py - 生成済み譜面(レーン配置)のキャッシュ

GRUによるレーン生成は TensorFlow を必要とし、起動も遅い。
そこで一度生成した譜面を JSON に保存しておき、次回以降はそれを読むだけにする。

これにより、キャッシュを同梱して配布すれば **遊ぶ側に TensorFlow は不要**になる。
（キャッシュが無い曲を選んだときだけ、その場で GRU 推論に切り替わる）

保存先: play/charts/<MIDI名>__<難易度>__t<温度>.json
"""
import hashlib
import json
import os
import sys

# exe(PyInstaller)化した場合は展開先の一時フォルダを基準にする
_BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
CHART_DIR = os.path.join(_BASE, "charts")


def _key(midi_path, difficulty, temperature):
    """曲・難易度・温度からキャッシュのファイル名を作る。
    MIDIの中身が変わったら別物として扱うため、内容のハッシュも混ぜる。"""
    stem = os.path.splitext(os.path.basename(midi_path))[0]
    try:
        with open(midi_path, "rb") as f:
            digest = hashlib.md5(f.read()).hexdigest()[:8]
    except OSError:
        digest = "nofile"
    safe = "".join(c for c in stem if c.isalnum() or c in "-_ ").strip() or "song"
    return f"{safe}__{difficulty}__t{temperature:.1f}__{digest}.json"


def path_for(midi_path, difficulty, temperature):
    return os.path.join(CHART_DIR, _key(midi_path, difficulty, temperature))


def load(midi_path, difficulty, temperature):
    """キャッシュがあれば notes リストを返す。無ければ None。"""
    p = path_for(midi_path, difficulty, temperature)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    notes = data.get("notes")
    if not notes:
        return None
    # 保存時に state は落としてあるので復元する
    for n in notes:
        n["state"] = "active"
    return notes


def save(midi_path, difficulty, temperature, notes):
    """生成した notes を JSON に保存する。"""
    os.makedirs(CHART_DIR, exist_ok=True)
    slim = [
        {
            "note_time": float(n["note_time"]),
            "note": int(n["note"]),
            "instrument": int(n["instrument"]),
            "column": int(n["column"]),
        }
        for n in notes
    ]
    data = {
        "source_midi": os.path.basename(midi_path),
        "difficulty": difficulty,
        "temperature": temperature,
        "note_count": len(slim),
        "notes": slim,
    }
    p = path_for(midi_path, difficulty, temperature)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    return p


_count_cache = {}


def note_count(midi_path, difficulty, temperature=1.0):
    """キャッシュ済み譜面のノーツ数を返す。キャッシュが無ければ None。

    難易度選択画面で「どれくらい叩くことになるのか」を先に見せるために使う。
    毎フレーム呼ばれるものではないが、選び直しのたびに読み直すのは無駄なので
    一度読んだ結果は覚えておく。"""
    key = (midi_path, difficulty, round(temperature, 1))
    if key in _count_cache:
        return _count_cache[key]
    path = path_for(midi_path, difficulty, temperature)
    count = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            count = data.get("note_count") or len(data.get("notes") or [])
        except (OSError, ValueError):
            count = None
    _count_cache[key] = count
    return count
