# -*- coding: utf-8 -*-
"""precompute_charts.py - 譜面(レーン配置)を事前生成して JSON に保存する

配布用ツール。play/music/ の全MIDIについて、全難易度ぶんの譜面をGRUで生成し
play/charts/ に保存する。これを同梱して配れば、**遊ぶ側に TensorFlow は不要**になる。

    cd tools
    python precompute_charts.py                 # 既定 temperature=1.0
    python precompute_charts.py --temperature 0.7
    python precompute_charts.py --difficulty Hard

game.py 側の生成処理と同じ手順を再現しているため、
ここで作った JSON は本編の生成結果と一致する。
"""
import argparse
import os
import random
import sys

import mido
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PLAY = os.path.join(os.path.dirname(HERE), "play")
sys.path.insert(0, PLAY)

import chart_cache  # noqa: E402

MUSIC_DIR = os.path.join(PLAY, "music")
DIFFICULTIES = ["Easy", "Normal", "Hard"]
TIME_RANGE = {"Easy": 0.5, "Normal": 0.15, "Hard": 0.1}


def midi_time_to_seconds(midi_time, tempo, ticks_per_beat):
    return midi_time * tempo / (ticks_per_beat * 1e6)


def extract_note_on_seconds(midi_path):
    """game.py main() と同じ手順で (時刻[秒], 音高, 楽器) の列を作る。
    戻り値が None のときはこのMIDIを扱えない(BPM変化あり等)。"""
    midi_file = mido.MidiFile(midi_path)

    tempo_changes = [m.tempo for tr in midi_file.tracks for m in tr if m.type == "set_tempo"]
    if len(tempo_changes) > 1:
        return None, "曲中でBPMが変化するMIDIは非対応"
    tempo = tempo_changes[0] if tempo_changes else 500000

    note_on_events = []
    instrument_columns = {}
    next_column = 0
    for track in midi_file.tracks:
        time_accumulated = 0
        current_instrument = 0
        for msg in track:
            time_accumulated += msg.time
            if msg.type == "program_change":
                current_instrument = msg.program
            if not msg.is_meta and msg.type == "note_on" and msg.velocity > 0:
                if current_instrument not in instrument_columns:
                    if next_column < 2:      # 使う楽器は2つまで
                        instrument_columns[current_instrument] = next_column
                        next_column += 1
                    else:
                        continue
                note_on_events.append((time_accumulated, msg.note, current_instrument))

    if not note_on_events:
        return None, "note_on が見つからない"

    tpb = midi_file.ticks_per_beat
    seconds = [(midi_time_to_seconds(t, tempo, tpb), n, i) for t, n, i in note_on_events]

    average_note = np.mean([n for _, n, _ in seconds])       # 音高の平均以上だけ使う
    seconds = [(t, n, i) for t, n, i in seconds if n >= average_note]
    if not seconds:
        return None, "平均音高で絞ると音が残らない"
    return seconds, None


def build_notes(note_on_seconds, difficulty, temperature, predict_lanes):
    """game.py の generate_notes と同じ処理。"""
    time_range = TIME_RANGE[difficulty]

    notes_by_time = {}
    for time_val, note, instrument in note_on_seconds:
        key = round(time_val / time_range) * time_range
        notes_by_time.setdefault(key, []).append((time_val, note, instrument))

    filtered = []
    for _, group in notes_by_time.items():
        if len(group) > 1:
            filtered.extend(random.sample(group, 1))          # NOTE_RATE=0 のため常に1つ
        else:
            filtered.extend(group)

    filtered.sort(key=lambda x: x[0])
    times = [t for (t, _, _) in filtered]
    lanes = predict_lanes(times, temperature=temperature)

    return [
        {"note_time": t, "note": n, "instrument": i, "state": "active", "column": c}
        for (t, n, i), c in zip(filtered, lanes)
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--difficulty", choices=DIFFICULTIES, action="append")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="既存のキャッシュも作り直す")
    args = ap.parse_args()

    diffs = args.difficulty or DIFFICULTIES
    temp = round(args.temperature, 1)

    if not os.path.isdir(MUSIC_DIR):
        print(f"music フォルダがありません: {MUSIC_DIR}")
        return
    midis = sorted(f for f in os.listdir(MUSIC_DIR) if f.lower().endswith(".mid"))
    if not midis:
        print(f"MIDIがありません: {MUSIC_DIR}")
        return

    print(f"対象 {len(midis)} 曲 × 難易度 {diffs} / temperature={temp}")
    from chart_ai_osu import predict_lanes      # ここで TensorFlow を読む

    made = skipped = 0
    for name in midis:
        path = os.path.join(MUSIC_DIR, name)
        seconds, err = extract_note_on_seconds(path)
        if seconds is None:
            print(f"  skip {name}  ({err})")
            skipped += 1
            continue
        for d in diffs:
            if not args.force and chart_cache.load(path, d, temp) is not None:
                print(f"  skip {name} [{d}]  (生成済み)")
                continue
            random.seed(args.seed)             # 再現性のため毎回同じ種で
            notes = build_notes(seconds, d, temp, predict_lanes)
            out = chart_cache.save(path, d, temp, notes)
            print(f"  ok   {name} [{d}] {len(notes):5d} notes -> {os.path.basename(out)}")
            made += 1

    print(f"\n完了: {made} 件生成 / {skipped} 曲スキップ")
    print(f"保存先: {chart_cache.CHART_DIR}")
    print("\nこの charts/ を同梱して配布すれば、遊ぶ側に TensorFlow は不要です。")


if __name__ == "__main__":
    main()
