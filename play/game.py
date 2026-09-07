# puroseka 難易度調整
# === 自由課題(実譜面版・全メニュー): レーン配置を 実譜面学習GRU(chart_ai_osu) で生成 ===
#   曲選択・モード選択のあとに temperature(生成の揺らぎ)調整画面を挟み、
#   譜面生成(GRU推論)中はロード画面を表示する。
import pygame
import pygame.midi
import pygame.mixer
import time
import threading
import mido
import random
import numpy as np
import sys
import os
import chart_cache     # 生成済み譜面(JSON)のキャッシュ


fullscreen = False   # F11 で切り替える。次に set_display するときに反映される


def set_display(size):
    """表示モードを設定する。set_mode の代わりに必ずこれを使う。

    pygame.SCALED を付けると、ゲーム側は今までどおり論理サイズ(700x600 など)に
    描き、SDL がディスプレイに合わせて拡大してくれる。
    レーンやキー枠の座標が固定値で書かれていても崩れない。
    縦横比は保たれるので、画面が widescreen なら左右に黒帯が入る。"""
    flags = pygame.SCALED
    if fullscreen:
        flags |= pygame.FULLSCREEN
    return pygame.display.set_mode(size, flags)


def toggle_fullscreen():
    """全画面 / ウィンドウを切り替える。今の論理サイズは保ったまま張り直す。"""
    global fullscreen
    fullscreen = not fullscreen
    surf = pygame.display.get_surface()
    set_display(surf.get_size() if surf else (SCREEN_WIDTH, SCREEN_HEIGHT))


def handle_common_keys(event):
    """どの画面でも効く共通キーを処理する。処理したら True を返す。

    各イベントループの先頭で呼ぶ。今のところ F11(全画面切替)だけ。"""
    if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
        toggle_fullscreen()
        return True
    return False


_hint_font = None

# プレイ中の画面に出す「いま何を遊んでいるか」。main() の選択後に更新する。
current_song_name = ""
current_difficulty = ""
current_difficulty_p2 = ""      # 対戦時のみ使う。ソロでは空文字


def draw_key_hint(surf, esc="終了", pos=None):
    """中断方法を表示する。R=タイトルへ戻る。

    ESC の意味は場面で変わる（プレイ中=リザルトへ / リザルト=終了）ので、
    表示だけ実際の動きとズレないよう呼び出し側から渡す。

    pos を省くと画面右下に1行で出す（メニューやリザルトはそこが空いている）。
    プレイ中の右下には D/F/J/K のキー枠があって重なるため、
    空いている座標を呼び出し側が渡して2行に分けて出す。"""
    global _hint_font
    if _hint_font is None:
        _hint_font = pygame.font.SysFont("meiryo", 16)
    lines = [f"ESC: {esc}", "R: タイトルへ戻る"]
    if pos is None:
        txt = _hint_font.render("　　".join(lines), True, (140, 140, 140))
        surf.blit(txt, (surf.get_width() - txt.get_width() - 10,
                        surf.get_height() - txt.get_height() - 6))
        return
    x, y = pos
    for line in lines:
        surf.blit(_hint_font.render(line, True, (140, 140, 140)), (x, y))
        y += 22


_np_font = None


def _wrap_lines(text, font, max_w):
    """max_w に収まるように折り返した行のリストを返す。

    曲名は "Chopin_Etude_Op10-12_Revolutionary" のように長いものがある。
    幅に合わせて字を小さくすると読めなくなるので、単語で折り返して大きさを保つ。"""
    words = text.replace("_", " ").split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and font.size(trial)[0] > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [text]


def draw_now_playing(surf, x, y, max_w, max_lines=3):
    """プレイ中の曲名と難易度を表示する。

    譜面はレーンの中を流れ、下端にはキー表示があるので、重ならない場所は
    インターフェースによって違う。置き場所は呼び出し側が指定する。
    行が増えすぎると下の判定ラインに届くため、曲名は max_lines 行で打ち切る。"""
    global _np_font
    if _np_font is None:
        _np_font = _mfont(18)
    if not current_song_name and not current_difficulty:
        return
    lines = _wrap_lines(current_song_name, _np_font, max_w)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] += "…"
    for line in lines:
        surf.blit(_np_font.render(line, True, (170, 170, 170)), (x, y))
        y += 24
    if current_difficulty_p2:
        diff = f"1P {current_difficulty}　／　2P {current_difficulty_p2}"
    else:
        diff = current_difficulty
    if diff:
        f = _fit_font(diff, 18, max_w, min_size=12)
        surf.blit(f.render(diff, True, (120, 120, 120)), (x, y + 4))


# 難易度ごとの「同時刻とみなす幅」[秒]。この幅でまとめて1ノーツに間引くので、
# 幅が広いほどノーツは減る。generate_notes 系とノーツ数の下見の両方から参照する。
DIFFICULTY_TIME_RANGE = {'Easy': 0.5, 'Normal': 0.15, 'Hard': 0.1}


def read_tempo(midi_file):
    """テンポ[マイクロ秒/四分音符]と set_tempo の出現回数を返す。

    回数も返すのは、途中でBPMが変わる曲を呼び出し側で弾けるようにするため。"""
    changes = [msg.tempo for track in midi_file.tracks
               for msg in track if msg.type == 'set_tempo']
    return (changes[0] if changes else 500000), len(changes)


def extract_note_seconds(midi_file, tempo):
    """MIDIから譜面のもとになる (時刻[秒], 音高, 楽器) の並びを取り出す。

    ・楽器は先に現れた2つまで。3つ目以降は伴奏とみなして捨てる
    ・平均より低い音も伴奏とみなして落とし、主旋律だけを残す"""
    note_on_events = []
    current_instrument = 0
    instrument_columns = {}
    next_column = 0
    for track in midi_file.tracks:
        time_accumulated = 0
        for msg in track:
            time_accumulated += msg.time
            if msg.type == 'program_change':
                current_instrument = msg.program
            if not msg.is_meta and msg.type == 'note_on' and msg.velocity > 0:
                if current_instrument not in instrument_columns:
                    if next_column < 2:      # 制限する楽器の数
                        instrument_columns[current_instrument] = next_column
                        next_column += 1
                    else:
                        continue             # n番目以降の楽器は無視する
                note_on_events.append((time_accumulated, msg.note, current_instrument))

    ticks_per_beat = midi_file.ticks_per_beat
    seconds = [(time * tempo / (ticks_per_beat * 1e6), note, instrument)
               for time, note, instrument in note_on_events]
    if not seconds:
        return []
    average_note = np.mean([note for _, note, _ in seconds])
    return [(time, note, instrument) for time, note, instrument in seconds
            if note >= average_note]


def count_notes_for_difficulty(note_on_seconds, difficulty):
    """その難易度で実際に降ってくるノーツ数を、譜面を作らずに数える。

    生成側は同じ時間帯のノーツを1つに間引くので、間引いたあとの個数は
    「時間帯の種類数」と一致する。GRU推論を回さずに済むため、
    キャッシュの無い持ち込みMIDIでも難易度選択の時点で数を出せる。"""
    time_range = DIFFICULTY_TIME_RANGE.get(difficulty, 0.1)
    return len({round(time / time_range) * time_range
                for time, _, _ in note_on_seconds})


def compute_accuracy(just_hits, good_hits, total_notes):
    """精度(%)。JUSTを1点、GOODを0.5点として全ノーツで割る。"""
    if not total_notes:
        return 0.0
    return (just_hits + good_hits * 0.5) / total_notes * 100.0


def compute_rank(accuracy):
    """精度からランク文字を決める。"""
    for threshold, rank in ((95, "S"), (90, "A"), (80, "B"), (70, "C"), (50, "D")):
        if accuracy >= threshold:
            return rank
    return "E"


def resource_path(rel):
    """同梱リソース(効果音・musicフォルダ)の絶対パスを返す。

    カレントディレクトリがどこであっても、また PyInstaller で exe 化した場合でも
    同じように解決できるようにする。
      - 通常実行   : このファイル(game.py)のあるフォルダを基準にする
      - exe(onefile): PyInstaller が展開する一時フォルダ sys._MEIPASS を基準にする
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)
# chart_ai_osu(TensorFlow) は譜面キャッシュが無いときだけ遅延importする
#   → キャッシュを同梱すれば、遊ぶ側に TensorFlow は不要になる

 # 画面サイズの設定
pygame.mixer.init()
SCREEN_WIDTH = 700
SCREEN_HEIGHT = 600
screen = set_display((SCREEN_WIDTH, SCREEN_HEIGHT))
judgment_results = []
midi_out=0
midi_file=None
filtered_note_on_seconds=[]
# 合計ノーツ数を取得
total_notes =0
total_notes_p2=0
notes=[]
notes_player2=[]
tempo = 500000
left_hp=20
right_hp=20

# MIDI再生スレッドを止めるためのフラグ。
# 中断時にデバイスを閉じる前へ確実にスレッドを終わらせるために使う。
midi_stop = threading.Event()

# 効果音。pygame.quit() を挟むと Sound が無効になるため、
# ensure_audio() で必要に応じて作り直せるようにしておく。
se_don = se_ka = se_tambourine = None
initial_volume = 0.1


def ensure_audio():
    """mixer が生きていることを保証し、効果音を読み込む（必要なら作り直す）。"""
    global se_don, se_ka, se_tambourine
    if not pygame.mixer.get_init():
        pygame.mixer.init()
        se_don = None                      # mixer を作り直したら Sound も作り直す
    # 同時発音数。既定は8しかなく、密な譜面では効果音が途切れる。
    # （mixer.init(channels=...) は出力チャンネル数であって同時発音数ではない）
    if pygame.mixer.get_num_channels() < 32:
        pygame.mixer.set_num_channels(32)
    if se_don is None:
        se_don = pygame.mixer.Sound(resource_path("ドン.wav"))
        se_ka = pygame.mixer.Sound(resource_path("カッ.wav"))
        se_tambourine = pygame.mixer.Sound(resource_path("suzu.wav"))
        for s in (se_don, se_ka, se_tambourine):
            s.set_volume(initial_volume)


def stop_midi_thread(thread):
    """MIDI再生スレッドを止めてから戻る。デバイスを閉じる前に必ず呼ぶ。"""
    midi_stop.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=3.0)


ensure_audio()

start_time = time.time()

# コンボ数と最大コンボ数の初期化
combo = 0
max_combo = 0
total_hits = 0
just_hits = 0
good_hits = 0


# フォントの設定
font =None


        # 譜面のパラメータ
NOTE_SPEED = 400  # 譜面が流れる速度（ピクセル/秒）
NOTE_WIDTH = 100   # ノーツの幅
NOTE_WIDTH_T=40
NOTE_HEIGHT = 20  # ノーツの高さ
NOTE_COLOR_R=(255,0,102)
NOTE_COLOR_B=(0,204,255)
COLOR_Y=(255, 255, 51)
COLOR_G=(57, 255, 20)

        # 判定ラインのパラメータ
JUDGE_LINE_Y = SCREEN_HEIGHT - 100  # 判定ラインのY座標（画面下端からの位置）
JUDGE_LINE_COLOR = (255, 255, 255)  # 判定ラインの色
JUDGE_LINE_THICKNESS = 2            # 判定ラインの太さ


# 判定ラインのパラメータ
JUDGE_LINE_X = SCREEN_WIDTH-200  # 判定ラインのY座標（画面下端からの位置）

# 判定ラインの設定
JUDGE_LINE_RADIUS = NOTE_WIDTH_T//2  # 円の半径
JUDGE_LINE_THICKNESS = 2  # 円の線の太さ
JUDGE_LINE_COLOR = (255, 255, 255)  # 白色


        # 判定の範囲（ノーツが判定ラインを通過したときに判定される範囲）
JUDGE_RANGE = NOTE_HEIGHT  # ピクセル
    
    
    
    
    
BACK = object()   # メニューで「戻る」が選ばれたことを表す番兵

_menu_fonts = {}


def _mfont(size):
    if size not in _menu_fonts:
        _menu_fonts[size] = pygame.font.SysFont("meiryo", size)
    return _menu_fonts[size]


def _fit_font(text, base_size, max_w, min_size=16):
    """max_w に収まる最大のフォントを返す。長い曲名がはみ出すのを防ぐ。"""
    size = base_size
    while size > min_size:
        f = _mfont(size)
        if f.size(text)[0] <= max_w:
            return f
        size -= 2
    return _mfont(min_size)


def menu_select(title, options, descriptions=None, subtitle=None,
                allow_back=True, initial=0, visible=10):
    """全選択画面で共通に使うメニュー。

      ↑ ↓ … 選択を移動
      Enter … 決定
      ESC   … ひとつ前の画面へ戻る（allow_back=True のとき）

    曲選択と同じ操作・見た目に統一するための関数。
    項目が visible を超える場合はスクロールし、右端に位置バーを出す。

    戻り値: 選んだ項目の index / 戻るなら BACK
    """
    screen = pygame.display.get_surface()
    if screen is None:
        screen = set_display((SCREEN_WIDTH, SCREEN_HEIGHT))
    w, h = screen.get_width(), screen.get_height()

    f_title = _mfont(34)
    f_sub = _mfont(20)
    f_item = _mfont(30)
    f_desc = _mfont(18)
    f_hint = _mfont(16)

    # 行の高さは実測のフォント高から決める（文字が箱からはみ出さないように）
    ITEM_W = 560                      # 項目テキストに使える幅
    Y_TOP = 150                       # 一覧の開始位置
    Y_BOTTOM = h - 60                 # 操作ヒストの手前まで
    PAD_Y = 10
    row_h = f_item.get_height() + PAD_Y * 2 + (f_desc.get_height() if descriptions else 0)

    # 画面に収まる行数までしか出さない。収まらない分はスクロールで見せる
    fit_rows = max(1, (Y_BOTTOM - Y_TOP) // row_h)
    if len(options) <= fit_rows:
        visible = len(options)
    else:
        # 全部見せたいので、まず余白を詰めてから、それでも無理ならスクロール
        need = len(options)
        tight = max(1, (Y_BOTTOM - Y_TOP) // need)
        min_row = f_item.get_height() + 4 + (f_desc.get_height() if descriptions else 0)
        if tight >= min_row:
            row_h = tight
            PAD_Y = max(2, (row_h - f_item.get_height()
                            - (f_desc.get_height() if descriptions else 0)) // 2)
            visible = need
        else:
            visible = fit_rows

    idx = max(0, min(initial, len(options) - 1))
    top = max(0, min(idx - visible // 2, max(0, len(options) - visible)))
    clock = pygame.time.Clock()

    while True:
        for event in pygame.event.get():
            # F11(全画面切替)はどの画面でも先に処理する
            if handle_common_keys(event):
                continue
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type != pygame.KEYDOWN:
                continue
            if event.key in (pygame.K_UP, pygame.K_w):
                idx = (idx - 1) % len(options)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                idx = (idx + 1) % len(options)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                return idx
            elif event.key == pygame.K_ESCAPE and allow_back:
                return BACK
            # 選択位置が見える範囲に入るようスクロール
            top = min(top, idx)
            top = max(top, idx - visible + 1)
            top = max(0, min(top, max(0, len(options) - visible)))

        screen.fill((0, 0, 0))

        ts = f_title.render(title, True, (255, 255, 255))
        screen.blit(ts, (w // 2 - ts.get_width() // 2, 46))
        if subtitle:
            ss = f_sub.render(subtitle, True, (150, 150, 150))
            screen.blit(ss, (w // 2 - ss.get_width() // 2, 90))

        shown = options[top:top + visible]
        y0 = 150
        box_x = w // 2 - 300
        box_w = 600
        for i, opt in enumerate(shown):
            gi = top + i
            sel = (gi == idx)
            y = y0 + i * row_h                      # y は行の上端
            box_h = row_h - 6
            if sel:
                pygame.draw.rect(screen, (38, 38, 48), (box_x, y, box_w, box_h))
                pygame.draw.rect(screen, (255, 255, 90), (box_x, y, 5, box_h))

            col = (255, 255, 255) if sel else (110, 110, 110)
            fi = _fit_font(opt, 30, ITEM_W)          # 長すぎる項目は自動で縮める
            its = fi.render(opt, True, col)
            if descriptions:
                # 上段に項目、下段に説明
                screen.blit(its, (box_x + 20, y + PAD_Y - 2))
                d = descriptions[gi] if gi < len(descriptions) else None
                if d:
                    dcol = (190, 190, 120) if sel else (85, 85, 85)
                    fd = _fit_font(d, 18, ITEM_W)
                    ds = fd.render(d, True, dcol)
                    screen.blit(ds, (box_x + 20, y + PAD_Y + its.get_height() - 4))
            else:
                # 説明が無い場合は1行を上下中央に置く
                screen.blit(its, (box_x + 20, y + (box_h - its.get_height()) // 2))

        # スクロール位置バー（項目が入りきらないときだけ）
        if len(options) > visible:
            track_h = min(visible, len(options)) * row_h - 6
            bar_h = max(20, int(track_h * visible / len(options)))
            bar_y = y0 + int((track_h - bar_h) * top / max(1, len(options) - visible))
            pygame.draw.rect(screen, (55, 55, 55), (w // 2 + 306, y0, 4, track_h))
            pygame.draw.rect(screen, (150, 150, 150), (w // 2 + 306, bar_y, 4, bar_h))

        hint = "↑↓ 選択　　Enter 決定" + ("　　ESC 戻る" if allow_back else "") + "　　F11 全画面"
        hs = f_hint.render(hint, True, (140, 140, 140))
        screen.blit(hs, (w // 2 - hs.get_width() // 2, h - hs.get_height() - 18))

        pygame.display.flip()
        clock.tick(60)


def title():
    pygame.init()
    pygame.midi.init()
    

    # 画面サイズと設定
    SCREEN_WIDTH, SCREEN_HEIGHT = 700, 600
    screen = set_display((SCREEN_WIDTH, SCREEN_HEIGHT))
    
    os.environ['SDL_VIDEO_CENTERED'] = '1'
    os.environ['SDL_VIDEO_WINDOW_POS'] = "0,0"
    screen = set_display((SCREEN_WIDTH, SCREEN_HEIGHT))

    # フォントの設定
    title_font = pygame.font.SysFont('meiryo', 80)  # タイトル用フォント
    subtitle_font = pygame.font.SysFont('meiryo', 30)  # サブタイトル用フォント
    # 色の設定
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    

    def title_screen():
        clock = pygame.time.Clock()
        running = True
        blink = True  # 点滅用フラグ
        blink_timer = 0  # 点滅のタイマー

        while running:
            screen.fill(BLACK)  # 背景を黒に設定

            # イベント処理
            for event in pygame.event.get():
                # F11(全画面切替)はどの画面でも先に処理する
                if handle_common_keys(event):
                    continue
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:  # エンターキーでタイトル画面を終了
                        running = False

            # タイトル文字
            title_text = subtitle_font.render("異なったインターフェースによって", True, WHITE)
            title2_text=subtitle_font.render("対戦可能な音楽ゲーム", True, WHITE)
            subtitle_text = title_font.render("クロス・ノーツ", True, WHITE)

            screen.blit(title_text, (SCREEN_WIDTH // 2 - title_text.get_width() // 2, 150))
            screen.blit(title2_text, (SCREEN_WIDTH // 2 - title_text.get_width() // 2, 200))
            screen.blit(subtitle_text, (SCREEN_WIDTH // 2 - subtitle_text.get_width() // 2, 250))

            # 点滅文字
            if blink:
                start_text = subtitle_font.render("エンターキーを押してスタートしてください", True, WHITE)
                screen.blit(start_text, (SCREEN_WIDTH // 2 - start_text.get_width() // 2, 400))

            # 全画面にできることはタイトルで知らせておく（プレイ中は表示場所が無い）
            fs_text = _mfont(18).render("F11: 全画面 / ウィンドウ 切替", True, (140, 140, 140))
            screen.blit(fs_text, (SCREEN_WIDTH // 2 - fs_text.get_width() // 2, 480))

            # 点滅タイミングの更新
            blink_timer += clock.get_time()
            if blink_timer > 500:  # 500msごとに点滅を切り替え
                blink = not blink
                blink_timer = 0

            # 画面更新
            pygame.display.flip()
            clock.tick(60)
    title_screen()
def select_song():
    """曲を選ぶ。menu_select に統一。"""
    music_folder = resource_path("music")
    midi_files = sorted(f for f in os.listdir(music_folder) if f.endswith('.mid'))

    if not midi_files:
        # 以前はコンソールに出して即終了していたので、画面にも理由を出す
        screen = pygame.display.get_surface() or set_display((SCREEN_WIDTH, SCREEN_HEIGHT))
        screen.fill((0, 0, 0))
        f = _mfont(24)
        for i, line in enumerate(["MIDIファイルが見つかりません。",
                                  f"{music_folder} に .mid を置いてください。",
                                  "何かキーを押すと終了します。"]):
            s = f.render(line, True, (255, 255, 255))
            screen.blit(s, (SCREEN_WIDTH // 2 - s.get_width() // 2, 240 + i * 40))
        pygame.display.flip()
        waiting = True
        while waiting:
            for e in pygame.event.get():
                # F11(全画面切替)はどの画面でも先に処理する
                if handle_common_keys(e):
                    continue
                if e.type in (pygame.KEYDOWN, pygame.QUIT):
                    waiting = False
        pygame.quit()
        sys.exit()

    names = [os.path.splitext(f)[0] for f in midi_files]
    r = menu_select("曲を選択してください", names,
                    subtitle=f"{len(names)} 曲", allow_back=True, visible=10)
    if r is BACK:
        return BACK
    return os.path.join(music_folder, midi_files[r])


def select_difficulty(label="難易度を選択してください", song=None, note_on_seconds=None):
    """難易度を選ぶ。ソロ / プレイヤー1 / プレイヤー2 で共通に使う。

    ノーツ数は note_on_seconds から直接数えるので、同梱曲でも自分で入れたMIDIでも出る。
    (譜面キャッシュがあるときはそれを読むほうが速いので優先する)"""
    diffs = ['Easy', 'Normal', 'Hard']
    descs = ["ノーツ少なめ・ゆったり", "標準", "ノーツ多め・高密度"]
    for i, d in enumerate(diffs):
        n = chart_cache.note_count(song, d) if song else None
        if n is None and note_on_seconds:
            n = count_notes_for_difficulty(note_on_seconds, d)
        if n:
            descs[i] += f"　／　ノーツ {n}"
    r = menu_select(label, diffs, descriptions=descs)
    return BACK if r is BACK else diffs[r]


def select_gamemode():
    """一人プレイ / 二人プレイ を選ぶ。戻り値 0=ソロ, 1=対戦"""
    r = menu_select("モードを選択してください",
                    ["一人プレイ", "二人プレイ（対戦）"],
                    descriptions=["じっくり遊ぶ", "画面分割で対戦"])
    return BACK if r is BACK else r


def select_interface(label="インターフェースを選択してください"):
    """ノーツの流れ方を選ぶ。戻り値 1=プロセカ風, 2=太鼓風"""
    r = menu_select(label,
                    ["プロセカ風（上から4レーン）", "太鼓の達人風（横から2種）"],
                    descriptions=["D / F / J / K", "F・J=赤　D・K=青"])
    return BACK if r is BACK else r + 1


def select_battle():
    """対戦で競う項目を選ぶ。戻り値 0=仲良く, 1=最大コンボ, 2=JUST, 3=合計HIT, 4=サドンデス"""
    opts = ["仲良くプレイする", "最大コンボ数", "JUST数", "合計HIT数", "サドンデス"]
    descs = ["勝敗をつけない", "連続で叩けた数を競う", "正確さを競う",
             "叩いた数を競う", "HPが尽きたら負け"]
    r = menu_select("競う項目を選択してください", opts, descriptions=descs)
    return BACK if r is BACK else r


def select_mode():
    """ソロのルールを選ぶ。戻り値 0=ノーマル, 1=HP"""
    r = menu_select("ソロモードを選択してください",
                    ["ノーマルモード", "HPモード"],
                    descriptions=["最後まで遊べる", "ミスでHPが減り0で終了"])
    return BACK if r is BACK else r


def calculate_bpm(tempo):
    microseconds_per_beat = tempo  # マイクロ秒/四分音符
    seconds_per_beat = microseconds_per_beat / 1e6  # 秒/四分音符
    beats_per_minute = 60 / seconds_per_beat  # BPM
    return beats_per_minute

# MIDI再生スレッドの関数
def play_midi():
    # このスレッドはゲームループの状態を触らない。
    # （以前は global running を書き換えていたが、ゲームループ側は
    #   ローカルの running を見ているため何の効果もなく、誤解を招くだけだった）
    start_time = time.time()
    music_start_delay = (SCREEN_HEIGHT-150) / NOTE_SPEED  # 曲の再生を遅らせる時間

    try:
        time.sleep(music_start_delay)  # 曲の再生を遅延させる

        pygame.mixer.music.unpause()  # 曲を再生

        for msg in midi_file.play():
            if midi_stop.is_set():        # 中断されたら発音をやめて即抜ける
                break
            if not msg.is_meta:
                status = msg.bytes()[0]
                data1 = msg.bytes()[1] if len(msg.bytes()) > 1 else 0
                data2 = msg.bytes()[2] if len(msg.bytes()) > 2 else 0
                midi_out.write_short(status, data1, data2)

            elapsed_time = time.time() - start_time - music_start_delay
            time.sleep(max(0, msg.time - elapsed_time))
    except Exception as e:
        print(f"Exception in MIDI thread: {e}")


def run_sologame():
    global total_notes,judgment_results,game,mode
    # Pygameの初期化
    pygame.init()
    pygame.midi.init()
        # コンボ数と最大コンボ数の初期化
    quit_app = False        # QUIT(ウィンドウの×)でアプリ終了
    back_to_title = False  # Rでタイトルへ戻る
    interrupted = False    # ESCで曲の途中からリザルトへ抜けた
    combo = 0
    max_combo = 0
    total_hits = 0
    just_hits = 0
    good_hits = 0
    check_column=0
    hp=20

    # 画面サイズの設定
    SCREEN_WIDTH = 700
    SCREEN_HEIGHT = 600
    screen = set_display((SCREEN_WIDTH, SCREEN_HEIGHT))

    # フォントの設定
    font = _mfont(24)
    
    
        
    # MIDI再生スレッドの開始
    ensure_audio()               # mixer と効果音が有効であることを保証する
    midi_stop.clear()            # 前回の中断フラグを持ち越さない
    midi_thread = threading.Thread(target=play_midi, daemon=True)
    midi_thread.start()
    def draw_judgment_results_pro():
        current_time = time.time() - start_time
        global judgment_results
        # 0.1秒後に結果を消すための基準時間
        result_display_time = 0.2
    
    

        for judgment in judgment_results:
            if current_time - judgment['time'] > result_display_time:
                continue  # 経過時間が0.1秒を超えたらスキップ

            column = judgment['column']
            result = judgment['result']

            # 判定ラインの少し上に結果を表示
            y_position = JUDGE_LINE_Y - 50
            if column == 0:
                x_position = 100
            elif column == 1:
                x_position = 200
            elif column == 2:
                x_position = 300
            else:
                x_position = 400

            # 結果のテキスト
            color =COLOR_G if result == 'JUST' else COLOR_Y if result == 'GOOD' else NOTE_COLOR_R  # MISSは赤色
            result_text = font.render(result, True, color)
            screen.blit(result_text, (x_position - result_text.get_width() // 2, y_position))

        # 結果をクリアする処理
    
        judgment_results = [result for result in judgment_results if current_time - result['time'] <= result_display_time]

    def draw_judgment_results_taiko():
        current_time = time.time() - start_time
        result_display_time = 0.2  # 結果を0.2秒表示する
        slide_speed = 100  # スライドの速度（1秒あたりのピクセル移動量）

        for judgment in judgment_results:
            elapsed_time = current_time - judgment['time']
            if elapsed_time > result_display_time:
                continue  # 経過時間が基準を超えたらスキップ

            result = judgment['result']

            # 判定ラインの少し下から開始し、時間経過で下にスライド
            x_position = 200  # 判定ラインと同じX座標
            base_y_position = 300 + JUDGE_LINE_RADIUS + 20  # 判定ラインの少し下
            y_position = base_y_position + slide_speed * elapsed_time  # 時間経過に応じてY座標を変更

            # 結果に応じた色を設定
            result_color = COLOR_G if result == 'JUST' else COLOR_Y if result == 'GOOD' else NOTE_COLOR_R
            result_text = font.render(result, True, result_color)
            screen.blit(result_text, (x_position - result_text.get_width() // 2, int(y_position)))
    # 判定結果を保存するリスト
    judgment_results = []

    result_display_time = 0.1  # 秒
    judgment_results = [result for result in judgment_results if current_time - result['time'] <= result_display_time]
    
    # 太鼓の達人の場合
    if (game==2):
        key_to_type = {
            pygame.K_d: 1,  # 'd'キーはタイプ0のノーツ
            pygame.K_f: 0,  # 'f'キーもタイプ0のノーツ
            pygame.K_j: 0,  # 'j'キーはタイプ1のノーツ
            pygame.K_k: 1   # 'k'キーもタイプ1のノーツ
        }

    # ゲームループ
    running = True
    start_time = time.time()
    clock = pygame.time.Clock()
    while running:
        current_time = time.time() - start_time
        if(hp<=0):
            running =False
        
        if(game==1):
            for event in pygame.event.get():
                # F11(全画面切替)はどの画面でも先に処理する
                if handle_common_keys(event):
                    continue
                if event.type == pygame.QUIT:
                    quit_app = True
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key==pygame.K_ESCAPE:
                        # 曲の途中でやめて、そこまでの成績を見る
                        interrupted = True
                        running = False
                    elif event.key == pygame.K_r:
                        back_to_title = True
                        running = False
                    elif event.key == pygame.K_d:  # 一番左の列のキー 'd' が押された場合
                        check_column = 0
                    elif event.key == pygame.K_f:  # 二番目の左の列のキー 'f' が押された場合
                        check_column = 1
                    elif event.key == pygame.K_j:  # 三番目の左の列のキー 'j' が押された場合
                        check_column = 2
                    elif event.key == pygame.K_k:  # 一番右の列のキー 'k' が押された場合
                        check_column = 3
                    else:
                        continue

                    # ノーツが判定ラインに達しているかをチェック
                    note_hit = False
                    for note in notes:
                        if note['state'] == 'active' and note['column'] == check_column:
                            note_time = note['note_time']
                            elapsed_time = current_time - note_time
                            note_position = elapsed_time * NOTE_SPEED
                            if JUDGE_LINE_Y - JUDGE_RANGE <= note_position <= JUDGE_LINE_Y + JUDGE_RANGE:
                                # ノーツがjustの範囲にある場合
                                note['state'] = 'hit'
                                combo += 1
                                total_hits += 1
                                just_hits += 1
                                if combo > max_combo:
                                    max_combo = combo
                                note_hit = True
                              # 空いている場合のみ再生
                                se_tambourine.play(maxtime=1000,fade_ms=0)
                                
                                # 判定結果を追加
                                judgment_results.append({'column': check_column, 'result': 'JUST', 'time': current_time})
                                break  # 一度反応したら他のノーツをチェックしない
                            elif JUDGE_LINE_Y - JUDGE_RANGE * 2 <= note_position <= JUDGE_LINE_Y + JUDGE_RANGE * 2:
                                # ノーツがgoodの範囲にある場合
                                note['state'] = 'hit'
                                combo += 1
                                total_hits += 1
                                good_hits += 1
                                if combo > max_combo:
                                    max_combo = combo
                                note_hit = True
                                # 判定結果を追加
                                se_tambourine.play(maxtime=1000,fade_ms=0)
                                judgment_results.append({'column': check_column, 'result': 'GOOD', 'time': current_time})
                                break  # 一度反応したら他のノーツをチェックしない

                    # もしノーツがなければコンボをリセット
                    if not note_hit:
                        if(mode==1):
                            hp-=1
                        
                        judgment_results.append({'column': check_column, 'result': 'MISS', 'time': current_time})
                        combo = 0
        else:
            for event in pygame.event.get():
                # F11(全画面切替)はどの画面でも先に処理する
                if handle_common_keys(event):
                    continue
                if event.type == pygame.QUIT:
                    quit_app = True
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key==pygame.K_ESCAPE:
                        # 曲の途中でやめて、そこまでの成績を見る
                        interrupted = True
                        running = False
                    elif event.key == pygame.K_r:
                        back_to_title = True
                        running = False
                    elif event.key in key_to_type:  # 対応するキーが押された場合
                        note_type = key_to_type[event.key]
                        note_hit = False

                        # ノーツが判定ラインに達しているかをチェック
                        for note in notes:
                            if note['state'] == 'active' and note['note_type'] == note_type:
                                note_time = note['note_time']
                                elapsed_time = current_time - note_time
                                note_position = elapsed_time * NOTE_SPEED
                                if JUDGE_LINE_X - JUDGE_RANGE <= note_position <= JUDGE_LINE_X + JUDGE_RANGE:
                                    # ノーツがjustの範囲にある場合
                                    note['state'] = 'hit'
                                    combo += 1
                                    total_hits += 1
                                    just_hits += 1
                                    if combo > max_combo:
                                        max_combo = combo
                                    note_hit = True
                                    # 判定結果を追加
                                    if(note_type==0):
                                        se_don.play()
                                    else:
                                        se_ka.play()
                                    judgment_results.append({'time': current_time, 'result': 'JUST'})
                                    break
                                elif JUDGE_LINE_X - JUDGE_RANGE * 2 <= note_position <= JUDGE_LINE_X + JUDGE_RANGE * 2:
                                    # ノーツがgoodの範囲にある場合
                                    note['state'] = 'hit'
                                    combo += 1
                                    total_hits += 1
                                    good_hits += 1
                                    if combo > max_combo:
                                        max_combo = combo
                                    note_hit = True
                                    # 判定結果を追加
                                    if(note_type==0):
                                        se_don.play()
                                    else:
                                        se_ka.play()
                                    judgment_results.append({'time': current_time, 'result': 'GOOD'})
                                    break

                        # もしノーツがなければコンボをリセット
                        if not note_hit:
                            if(mode==1):
                                hp-=1
                            judgment_results.append({'time': current_time, 'result': 'MISS'})
                            combo = 0
                

        # 画面の描画
        screen.fill((0, 0, 0))
        if(game==1):
            D=font.render("D",True,(255,255,255))
            D_rect=D.get_rect(topleft=(92.5, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), D_rect.inflate(10,10), 2)
            screen.blit(D,D_rect.topleft)
            
            F=font.render("F",True,(255,255,255))
            F_rect=F.get_rect(topleft=(92.5+NOTE_WIDTH, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), F_rect.inflate(10,10), 2)
            screen.blit(F,F_rect.topleft)
            
            J=font.render("J",True,(255,255,255))
            J_rect=J.get_rect(topleft=(92.5+NOTE_WIDTH*2, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), J_rect.inflate(10,10), 2)
            screen.blit(J,J_rect.topleft)
            
            K=font.render("K",True,(255,255,255))
            K_rect=K.get_rect(topleft=(92.5+NOTE_WIDTH*3, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), K_rect.inflate(10,10), 2)
            screen.blit(K,K_rect.topleft)
            
            
        else:
            D=font.render("D",True,(255,255,255))
            D_rect=D.get_rect(topleft=(100, SCREEN_HEIGHT-150))
            pygame.draw.rect(screen, (255, 255, 255), D_rect.inflate(10,10), 2)
            screen.blit(D,D_rect.topleft)
            
            K=font.render("K",True,(255,255,255))
            K_rect=K.get_rect(topleft=(140, SCREEN_HEIGHT-150))
            pygame.draw.rect(screen, (255, 255, 255), K_rect.inflate(10,10), 2)
            screen.blit(K,K_rect.topleft)
            
            F=font.render("F",True,(255,255,255))
            F_rect=F.get_rect(topleft=(100, SCREEN_HEIGHT-200))
            pygame.draw.rect(screen, (255, 255, 255), F_rect.inflate(10,10), 2)
            screen.blit(F,F_rect.topleft)
            
            J=font.render("J",True,(255,255,255))
            J_rect=J.get_rect(topleft=(140, SCREEN_HEIGHT-200))
            pygame.draw.rect(screen, (255, 255, 255), J_rect.inflate(10,10), 2)
            screen.blit(J,J_rect.topleft)
            
            key=font.render("key",True,(255,255,255))
            screen.blit(key,(170,SCREEN_HEIGHT-150))
            screen.blit(key,(170,SCREEN_HEIGHT-200))
            pygame.draw.circle(screen, NOTE_COLOR_B, (50, SCREEN_HEIGHT-137.5), NOTE_WIDTH_T//2)
            pygame.draw.circle(screen, NOTE_COLOR_R, (50, SCREEN_HEIGHT-187.5), NOTE_WIDTH_T//2)
            
            
            
            
            

        # 譜面の描画（上から下に向かって）
        if(game==1):
            for note in notes:
                if note['state'] == 'active':
                    note_time = note['note_time']
                    elapsed_time = current_time - note_time
                    note_position = elapsed_time * NOTE_SPEED
                    if note_position <= SCREEN_HEIGHT:
                        # ノーツの描画位置を決定
                        if note['column'] == 0:
                            x_position = 100
                        elif note['column'] == 1:
                            x_position = 200
                        elif note['column'] == 2:
                            x_position = 300
                        else:
                            x_position = 400

                        # ノーツの描画
                        pygame.draw.rect(screen, NOTE_COLOR_B, (x_position - NOTE_WIDTH // 2, int(note_position) - NOTE_HEIGHT // 2, NOTE_WIDTH, NOTE_HEIGHT))
                    else:
                        # ノーツが画面外に出たらmissとしてコンボをリセット
                        note['state'] = 'MISS'
                        if(mode==1):
                            hp-=1
                        judgment_results.append({'column': note['column'], 'result': 'MISS', 'time': current_time})
                        combo = 0
        else:
            for note in notes:
                if note['state'] == 'active':
                    note_time = note['note_time']
                    elapsed_time = current_time - note_time
                    note_position = SCREEN_WIDTH - elapsed_time * NOTE_SPEED
                
                    if note_position >= 0:
                        # ノーツの種類に応じた色を設定（赤と青で表示）
                        note_color = NOTE_COLOR_R if note['note_type'] == 0 else NOTE_COLOR_B

                        # ノーツの描画位置はY方向で中央に固定
                        note_radius = NOTE_WIDTH_T // 2  # 円の半径
                        pygame.draw.circle(screen, note_color, (int(note_position), 300), note_radius)
                    else:
                        # ノーツが画面外に出たらmissとしてコンボをリセット
                        note['state'] = 'MISS'
                        if(mode==1):
                            hp-=1
                        judgment_results.append({'time': current_time, 'result': 'MISS'})
                        combo = 0

        # 判定ラインの描画（画面下部に描画）
        if(game==1):
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (0, JUDGE_LINE_Y), (SCREEN_WIDTH, JUDGE_LINE_Y), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (50, 0), (50, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (150, 0), (150, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (250, 0), (250, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (350, 0), (350, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (450, 0), (450, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
        else:
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (0, 350), (SCREEN_WIDTH, 350), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (0, 250), (SCREEN_WIDTH, 250), JUDGE_LINE_THICKNESS)
            pygame.draw.circle(screen, (255, 255, 255), (200, 300), JUDGE_LINE_RADIUS, JUDGE_LINE_THICKNESS)
            pygame.draw.circle(screen, (255, 255, 255), (200, 300), JUDGE_LINE_RADIUS+10, JUDGE_LINE_THICKNESS)

        # コンボ数と最大コンボ数を画面に表示
        # ステータスは幅200pxの列に収め、かつ太鼓レーンの線(y=250)に掛からない大きさにする。
        # meiryo18 は元の Font(None,36) とほぼ同じ見た目の大きさでもある。
        stat_font = _mfont(18)
        combo_text = stat_font.render(f"COMBO: {combo}", True, (255, 255, 255))
        screen.blit(combo_text, (SCREEN_WIDTH-200, 20))

        max_combo_text = stat_font.render(f"MAX COMBO: {max_combo}", True, (255, 255, 255))
        screen.blit(max_combo_text, (SCREEN_WIDTH-200, 60))

        # BPMを計算して画面に表示
        bpm = calculate_bpm(tempo)
        total_hits_text = stat_font.render(f"TOTAL HITS: {total_hits}", True, (255, 255, 255))
        screen.blit(total_hits_text, (SCREEN_WIDTH-200, 100))

        # justとgoodの数を画面に表示
        just_text = stat_font.render(f"JUST: {just_hits}", True, (255, 255, 255))
        screen.blit(just_text, (SCREEN_WIDTH-200, 140))

        good_text = stat_font.render(f"GOOD: {good_hits}", True, (255, 255, 255))
        screen.blit(good_text, (SCREEN_WIDTH-200, 180))
        if(mode==1):
            hp_text = stat_font.render(f"HP: {hp}", True, NOTE_COLOR_R)
            screen.blit(hp_text, (SCREEN_WIDTH-200, 220))
        
        # 判定結果の描画
        if (game==1):
            draw_judgment_results_pro()
        else:
            draw_judgment_results_taiko()
        
        if not midi_thread.is_alive():  # MIDI再生スレッドが終了していればゲームループも終了
            running = False


        # 画面更新
        draw_now_playing(screen, SCREEN_WIDTH - 200, 368, 190)
        draw_key_hint(screen, esc="リザルトへ", pos=(SCREEN_WIDTH - 200, 516))
        pygame.display.flip()

        # 60fpsで描画
        clock.tick(60)
    # 【順序が重要】スレッドを止めてからデバイスを閉じる。
    # 逆順にすると、閉じたデバイスへスレッドが書き込んでネイティブ側で落ちる。
    stop_midi_thread(midi_thread)
    pygame.mixer.music.stop()
    try:
        midi_out.close()
    except Exception:
        pass

    # R でタイトルへ戻る / ウィンドウを閉じた場合は、リザルトを出さずにここで抜ける
    # （ESC はリザルトを見せたいので、ここには来ない）
    if quit_app or back_to_title:
        if quit_app:
            pygame.quit()
            pygame.midi.quit()
            sys.exit()
        return          # タイトルへ戻る（pygame は落とさない。SEを生かしたままにする）

    # ゲームループが終了したら、結果を表示
    screen.fill((0, 0, 0))

    # 叩けなかったノーツ。負の値にならないよう下限を0にする。
    miss_hits = max(0, total_notes - total_hits)
    accuracy = compute_accuracy(just_hits, good_hits, total_notes)
    rank = compute_rank(accuracy)

    def _center(surface, y):
        screen.blit(surface, (SCREEN_WIDTH // 2 - surface.get_width() // 2, y))

    _center(_mfont(28).render(current_song_name, True, (150, 150, 150)), 8)
    subtitle = current_difficulty + ("　（途中で中断）" if interrupted else "")
    _center(_mfont(20).render(subtitle, True,
                              (255, 170, 80) if interrupted else (150, 150, 150)), 52)
    _center(_mfont(72).render(rank, True, (255, 220, 90)), 88)
    _center(_mfont(32).render(f"{accuracy:.1f}%", True, (255, 255, 255)), 200)

    rows = [
        ("TOTAL NOTES", total_notes, (255, 255, 255)),
        ("TOTAL HITS", total_hits, (255, 255, 255)),
        ("JUST", just_hits, (120, 200, 255)),
        ("GOOD", good_hits, (120, 255, 160)),
        ("MISS", miss_hits, (255, 120, 120)),
        ("MAX COMBO", max_combo, (255, 255, 255)),
    ]
    # ラベルは左揃え・数値は右揃えにして、桁が変わっても列が崩れないようにする
    label_font = _mfont(24)
    label_x = SCREEN_WIDTH // 2 - 130
    value_right = SCREEN_WIDTH // 2 + 130
    y = 260
    for label, value, color in rows:
        screen.blit(label_font.render(label, True, color), (label_x, y))
        vs = label_font.render(str(value), True, color)
        screen.blit(vs, (value_right - vs.get_width(), y))
        y += 34

    draw_key_hint(screen)
    pygame.display.flip()

    # スコア画面を表示するフラグ
    score_shown = True
    while score_shown:
        for event in pygame.event.get():
            # F11(全画面切替)はどの画面でも先に処理する
            if handle_common_keys(event):
                continue
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    # アプリを終了する（スレッドとデバイスを片付けてから）
                    stop_midi_thread(midi_thread)
                    pygame.mixer.music.stop()
                    pygame.quit(); pygame.midi.quit()
                    sys.exit()
                elif event.key == pygame.K_r:
                    # タイトル画面に戻る処理
                    score_shown = False
                    running=False# スコア画面を閉じる
                    # タイトル画面を表示する関数を呼び出す
            elif event.type == pygame.QUIT:
                stop_midi_thread(midi_thread)
                pygame.mixer.music.stop()
                pygame.quit(); pygame.midi.quit()
                sys.exit()



    # タイトルへ戻るだけなので pygame は終了しない。
    # （pygame.quit() すると効果音の Sound が無効になり、次のプレイで鳴らなくなる）
    stop_midi_thread(midi_thread)
    pygame.mixer.music.stop()


def run_battlegame():
    global total_notes, judgment_results_left, judgment_results_right,total_notes_p2,game,game_p2,battle,right_hp,left_hp
    
    # Pygameの初期化
    pygame.init()
    pygame.midi.init()
    pygame.mixer.init()
    
   
    

    # プレイヤーのコンボと最大コンボの初期化
    quit_app = False        # QUIT(ウィンドウの×)でアプリ終了
    back_to_title = False  # Rでタイトルへ戻る
    interrupted = False    # ESCで曲の途中からリザルトへ抜けた
    left_combo = 0
    right_combo = 0
    left_max_combo = 0
    right_max_combo = 0
    left_total_hits = 0
    right_total_hits = 0
    left_just_hits = 0
    right_just_hits = 0
    left_good_hits = 0
    right_good_hits = 0
    win=0
    left_hp=20
    right_hp=20
    # 画面サイズの設定
    SCREEN_WIDTH = 1400
    SCREEN_HEIGHT = 600
    screen_info = pygame.display.Info()
    print(f"Current resolution: {screen_info.current_w}x{screen_info.current_h}")


    # Pygameウィンドウの位置を設定
    # ウィンドウを中央に配置
    os.environ['SDL_VIDEO_CENTERED'] = '1'
    os.environ['SDL_VIDEO_WINDOW_POS'] = "0,0"
    screen = set_display((SCREEN_WIDTH, SCREEN_HEIGHT))

    # フォントの設定
    font = _mfont(24)
    if(battle==4):
        left_hp=20
        right_hp=20
    
    if(game==1):    
        left_keys = {
            pygame.K_a: 0,
            pygame.K_s: 1,
            pygame.K_d: 2,
            pygame.K_f: 3
        }
    else:
        left_keys = {
            pygame.K_a: 1,
            pygame.K_s: 0,
            pygame.K_d: 0,
            pygame.K_f: 1
        }
    
    if game_p2==1:
        right_keys = {
            pygame.K_l: 0,
            pygame.K_SEMICOLON: 1,
            pygame.K_COLON: 2,
            pygame.K_RIGHTBRACKET: 3
        }
    else:
        right_keys = {
            pygame.K_l: 1,
            pygame.K_SEMICOLON: 0,
            pygame.K_COLON: 0,
            pygame.K_RIGHTBRACKET: 1
        }

    judgment_results_left = []
    judgment_results_right = []
    
    def draw_notes_pro(notes, current_time, x_offset, combo, is_left_player):
        global left_hp,right_hp
        for note in notes:
            if note['state'] == 'active':
                note_time = note['note_time']
                elapsed_time = current_time - note_time
                note_position = elapsed_time * NOTE_SPEED
                if note_position < SCREEN_HEIGHT-10:
                    if note['column'] == 0:
                        x_position = 100 + x_offset
                    elif note['column'] == 1:
                        x_position = 200 + x_offset
                    elif note['column'] == 2:
                        x_position = 300 + x_offset
                    else:
                        x_position = 400 + x_offset
                    pygame.draw.rect(
                        screen,
                        NOTE_COLOR_B,
                        (x_position - NOTE_WIDTH // 2, int(note_position) - NOTE_HEIGHT // 2, NOTE_WIDTH, NOTE_HEIGHT),
                    )
                elif note_position>SCREEN_HEIGHT-10:
                    note['state'] = 'MISS'
                    if is_left_player:
                        judgment_results_left.append(
                            {'column': note['column'], 'result': 'MISS', 'time': current_time}
                        )
                        if(battle==4):
                            left_hp-=1
                            

                    else:
                        judgment_results_right.append(
                            {'column': note['column'], 'result': 'MISS', 'time': current_time}
                        )
                        if(battle==4):
                            right_hp-=1
                    combo = 0
        return combo
    def draw_notes_taiko(notes, current_time, x_offset, combo, is_left_player):
        global left_hp,right_hp
        for note in notes:
            if note['state'] == 'active':
                note_time = note['note_time']
                elapsed_time = current_time - note_time
                if is_left_player:
                    note_position = SCREEN_WIDTH//2 - elapsed_time * NOTE_SPEED
                else:
                    note_position = SCREEN_WIDTH - elapsed_time * NOTE_SPEED
                if is_left_player:
                    if (note_position >= 0 and note_position <= SCREEN_WIDTH//2):
                        # ノーツの種類に応じた色を設定（赤と青で表示）
                        note_color = NOTE_COLOR_R if note['note_type'] == 0 else NOTE_COLOR_B

                        # ノーツの描画位置はY方向で中央に固定
                        note_radius = NOTE_WIDTH_T // 2  # 円の半径
                        pygame.draw.circle(screen, note_color, (int(note_position), 300), note_radius)
                    else:
                        # ノーツが画面外に出たらmissとしてコンボをリセット]
                        if(note_position<NOTE_WIDTH):
                            note['state'] = 'MISS'
                            if is_left_player:
                                judgment_results_left.append({'time': current_time, 'result': 'MISS'})
                                if(battle==4):
                                    left_hp-=1
                            else:
                                judgment_results_right.append({'time': current_time, 'result': 'MISS'})
                            combo = 0
                else:
                    if (note_position >= SCREEN_WIDTH//2+50 and note_position <= SCREEN_WIDTH):
                        # ノーツの種類に応じた色を設定（赤と青で表示）
                        note_color = NOTE_COLOR_R if note['note_type'] == 0 else NOTE_COLOR_B

                        # ノーツの描画位置はY方向で中央に固定
                        note_radius = NOTE_WIDTH_T // 2  # 円の半径
                        pygame.draw.circle(screen, note_color, (int(note_position), 300), note_radius)
                    else:
                        # ノーツが画面外に出たらmissとしてコンボをリセット
                        if(note_position<SCREEN_WIDTH//2+NOTE_WIDTH+200):    
                            note['state'] = 'MISS'
                            if is_left_player:
                                judgment_results_left.append({'time': current_time, 'result': 'MISS'})
                                
                            else:
                                judgment_results_right.append({'time': current_time, 'result': 'MISS'})
                                if(battle==4):
                                    right_hp-=1
                            combo = 0
                    
        return combo
        
    
    def draw_judgment_results(judgment_results, x_offset):
        current_time = time.time() - start_time
        result_display_time = 0.2

        for judgment in judgment_results:
            if current_time - judgment['time'] > result_display_time:
                continue

            column = judgment['column']
            result = judgment['result']
            y_position = JUDGE_LINE_Y - 50

            if column == 0:
                x_position = 100 + x_offset
            elif column == 1:
                x_position = 200 + x_offset
            elif column == 2:
                x_position = 300 + x_offset
            else:
                x_position = 400 + x_offset

            color = COLOR_G if result == 'JUST' else COLOR_Y if result == 'GOOD' else NOTE_COLOR_R
            result_text = font.render(result, True, color)
            screen.blit(result_text, (x_position - result_text.get_width() // 2, y_position))

        judgment_results[:] = [result for result in judgment_results if current_time - result['time'] <= result_display_time]
        
    def draw_judgment_results_taiko(judgment_results,x_offset):
        current_time = time.time() - start_time
        result_display_time = 0.2  # 結果を0.2秒表示する
        slide_speed = 100  # スライドの速度（1秒あたりのピクセル移動量）

        for judgment in judgment_results:
            elapsed_time = current_time - judgment['time']
            if elapsed_time > result_display_time:
                continue  # 経過時間が基準を超えたらスキップ

            result = judgment['result']

            # 判定ラインの少し下から開始し、時間経過で下にスライド
            x_position = 200+x_offset  # 判定ラインと同じX座標
            base_y_position = 300 + JUDGE_LINE_RADIUS + 20  # 判定ラインの少し下
            y_position = base_y_position + slide_speed * elapsed_time  # 時間経過に応じてY座標を変更

            # 結果に応じた色を設定
            result_color = COLOR_G if result == 'JUST' else COLOR_Y if result == 'GOOD' else NOTE_COLOR_R
            result_text = font.render(result, True, result_color)
            screen.blit(result_text, (x_position - result_text.get_width() // 2, int(y_position)))
   

    ensure_audio()               # mixer と効果音が有効であることを保証する
    midi_stop.clear()            # 前回の中断フラグを持ち越さない
    midi_thread = threading.Thread(target=play_midi, daemon=True)
    midi_thread.start()

    running = True
    start_time = time.time()
    clock = pygame.time.Clock()
    while running:
        current_time = time.time() - start_time
        if(left_hp<=0):
            win=2
            running=False
        elif(right_hp<=0):
            win=1
            running=False
        

        for event in pygame.event.get():
            # F11(全画面切替)はどの画面でも先に処理する
            if handle_common_keys(event):
                continue
            if event.type == pygame.QUIT:
                quit_app = True
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    # 曲の途中でやめて、そこまでの成績を見る
                    interrupted = True
                    running = False
                elif event.key == pygame.K_r:
                    back_to_title = True
                    running = False

                if event.key in left_keys:
                    if(game==1):
                        check_column = left_keys[event.key]
                        result = process_hit_for_player(notes, check_column, current_time, True, judgment_results_left)
                    else:
                        note_type = left_keys[event.key]
                        result=process_hit_for_player_taiko(notes,note_type,current_time,True,judgment_results_left)
                        
                    if result == 'JUST':
                            left_combo += 1
                            left_total_hits += 1
                            left_just_hits += 1
                            if left_combo > left_max_combo:
                                left_max_combo = left_combo
                    elif result=='GOOD':
                            left_combo += 1
                            left_total_hits += 1
                            left_good_hits += 1
                            if left_combo > left_max_combo:
                                left_max_combo = left_combo
                    else:
                            left_combo=0
                        
                        

                if event.key in right_keys:
                    if(game_p2==1):
                        check_column = right_keys[event.key]
                        result = process_hit_for_player(notes_player2, check_column, current_time, False, judgment_results_right)
                    else:
                        note_type=right_keys[event.key]
                        result=process_hit_for_player_taiko(notes_player2,note_type,current_time,False,judgment_results_right)
                        
                    if result == 'JUST':
                        right_combo += 1
                        right_total_hits+=1
                        right_just_hits+=1
                        if right_combo > right_max_combo:
                            right_max_combo = right_combo
                    elif result=='GOOD':
                        right_combo += 1
                        right_total_hits+=1
                        right_good_hits+=1
                        if right_combo > right_max_combo:
                            right_max_combo = right_combo   
                    else :
                        right_combo=0

        screen.fill((0, 0, 0))

        if(game==1):
            A=font.render("A",True,(255,255,255))
            A_rect=A.get_rect(topleft=(92.5, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), A_rect.inflate(10,10), 2)
            screen.blit(A,A_rect.topleft)
            
            S=font.render("S",True,(255,255,255))
            S_rect=S.get_rect(topleft=(92.5+NOTE_WIDTH, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), S_rect.inflate(10,10), 2)
            screen.blit(S,S_rect.topleft)
            
            D=font.render("D",True,(255,255,255))
            D_rect=D.get_rect(topleft=(92.5+NOTE_WIDTH*2, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), D_rect.inflate(10,10), 2)
            screen.blit(D,D_rect.topleft)
            
            F=font.render("F",True,(255,255,255))
            F_rect=F.get_rect(topleft=(92.5+NOTE_WIDTH*3, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), F_rect.inflate(10,10), 2)
            screen.blit(F,F_rect.topleft)
            
            
            left_combo=draw_notes_pro(notes, current_time, 0, left_combo,True)
            pygame.draw.line(screen, (255, 255, 255), (0, JUDGE_LINE_Y), (SCREEN_WIDTH//2+25, JUDGE_LINE_Y), 2)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (50, 0), (50, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (150, 0), (150, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (250, 0), (250, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (350, 0), (350, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (450, 0), (450, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
        else:
            left_combo=draw_notes_taiko(notes, current_time, 0, left_combo,True)
            pygame.draw.circle(screen, (255, 255, 255), (200, 300), JUDGE_LINE_RADIUS, JUDGE_LINE_THICKNESS)
            pygame.draw.circle(screen, (255, 255, 255), (200, 300), JUDGE_LINE_RADIUS+10, JUDGE_LINE_THICKNESS)
            
            A=font.render("A",True,(255,255,255))
            A_rect=A.get_rect(topleft=(100, SCREEN_HEIGHT-150))
            pygame.draw.rect(screen, (255, 255, 255), A_rect.inflate(10,10), 2)
            screen.blit(A,A_rect.topleft)
            
            S=font.render("S",True,(255,255,255))
            S_rect=S.get_rect(topleft=(100, SCREEN_HEIGHT-200))
            pygame.draw.rect(screen, (255, 255, 255), S_rect.inflate(10,10), 2)
            screen.blit(S,S_rect.topleft)
            
            D=font.render("D",True,(255,255,255))
            D_rect=D.get_rect(topleft=(140, SCREEN_HEIGHT-200))
            pygame.draw.rect(screen, (255, 255, 255), D_rect.inflate(10,10), 2)
            screen.blit(D,D_rect.topleft)
            
            F=font.render("F",True,(255,255,255))
            F_rect=F.get_rect(topleft=(140, SCREEN_HEIGHT-150))
            pygame.draw.rect(screen, (255, 255, 255), F_rect.inflate(10,10), 2)
            screen.blit(F,F_rect.topleft)
            
            key=font.render("key",True,(255,255,255))
            screen.blit(key,(170,SCREEN_HEIGHT-150))
            screen.blit(key,(170,SCREEN_HEIGHT-200))
            
            pygame.draw.circle(screen, NOTE_COLOR_B, (50, SCREEN_HEIGHT-137.5), NOTE_WIDTH_T//2)
            pygame.draw.circle(screen, NOTE_COLOR_R, (50, SCREEN_HEIGHT-187.5), NOTE_WIDTH_T//2)
            
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (0, 350), (SCREEN_WIDTH//2+25, 350), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (0, 250), (SCREEN_WIDTH//2+25, 250), JUDGE_LINE_THICKNESS)
        if(game_p2==1):
            L=font.render("L",True,(255,255,255))
            L_rect=L.get_rect(topleft=(SCREEN_WIDTH//2+92.5, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), L_rect.inflate(10,10), 2)
            screen.blit(L,L_rect.topleft)
            
            sem=font.render(";",True,(255,255,255))
            sem_rect=sem.get_rect(topleft=(SCREEN_WIDTH//2+92.5+NOTE_WIDTH, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), sem_rect.inflate(10,10), 2)
            screen.blit(sem,sem_rect.topleft)
            
            koron=font.render(":",True,(255,255,255))
            koron_rect=koron.get_rect(topleft=(SCREEN_WIDTH//2+92.5+NOTE_WIDTH*2, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), koron_rect.inflate(10,10), 2)
            screen.blit(koron,koron_rect.topleft)
            
            migi=font.render("]",True,(255,255,255))
            migi_rect=migi.get_rect(topleft=(SCREEN_WIDTH//2+92.5+NOTE_WIDTH*3, SCREEN_HEIGHT-50))
            pygame.draw.rect(screen, (255, 255, 255), migi_rect.inflate(10,10), 2)
            screen.blit(migi,migi_rect.topleft)
            
            right_combo=draw_notes_pro(notes_player2, current_time, SCREEN_WIDTH // 2, right_combo,False)
            pygame.draw.line(screen, (255, 255, 255), (SCREEN_WIDTH//2+25, JUDGE_LINE_Y), (SCREEN_WIDTH, JUDGE_LINE_Y), 2)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (SCREEN_WIDTH//2+50, 0), (SCREEN_WIDTH//2+50, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (SCREEN_WIDTH//2+150, 0), (SCREEN_WIDTH//2+150, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (SCREEN_WIDTH//2+250, 0), (SCREEN_WIDTH//2+250, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (SCREEN_WIDTH//2+350, 0), (SCREEN_WIDTH//2+350, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (SCREEN_WIDTH//2+450, 0), (SCREEN_WIDTH//2+450, SCREEN_HEIGHT), JUDGE_LINE_THICKNESS)
        else:
            right_combo=draw_notes_taiko(notes_player2, current_time, SCREEN_WIDTH // 2, right_combo,False)
            pygame.draw.circle(screen, (255, 255, 255), (SCREEN_WIDTH//2+200, 300), JUDGE_LINE_RADIUS, JUDGE_LINE_THICKNESS)
            pygame.draw.circle(screen, (255, 255, 255), (SCREEN_WIDTH//2+200, 300), JUDGE_LINE_RADIUS+10, JUDGE_LINE_THICKNESS)
            
            L=font.render("L",True,(255,255,255))
            L_rect=L.get_rect(topleft=(100+SCREEN_WIDTH//2+25, SCREEN_HEIGHT-150))
            pygame.draw.rect(screen, (255, 255, 255), L_rect.inflate(10,10), 2)
            screen.blit(L,L_rect.topleft)
            
            sem=font.render(";",True,(255,255,255))
            sem_rect=sem.get_rect(topleft=(100+SCREEN_WIDTH//2+25, SCREEN_HEIGHT-200))
            pygame.draw.rect(screen, (255, 255, 255), sem_rect.inflate(10,10), 2)
            screen.blit(sem,sem_rect.topleft)
            
            koron=font.render(":",True,(255,255,255))
            koron_rect=koron.get_rect(topleft=(140+SCREEN_WIDTH//2+25, SCREEN_HEIGHT-200))
            pygame.draw.rect(screen, (255, 255, 255), koron_rect.inflate(10,10), 2)
            screen.blit(koron,koron_rect.topleft)
            
            migi=font.render("]",True,(255,255,255))
            migi_rect=migi.get_rect(topleft=(140+SCREEN_WIDTH//2+25, SCREEN_HEIGHT-150))
            pygame.draw.rect(screen, (255, 255, 255), migi_rect.inflate(10,10), 2)
            screen.blit(migi,migi_rect.topleft)
            
            key=font.render("key",True,(255,255,255))
            screen.blit(key,(170+SCREEN_WIDTH//2+25,SCREEN_HEIGHT-150))
            screen.blit(key,(170+SCREEN_WIDTH//2+25,SCREEN_HEIGHT-200))
            
            pygame.draw.circle(screen, NOTE_COLOR_B, (SCREEN_WIDTH//2+50+25, SCREEN_HEIGHT-137.5), NOTE_WIDTH_T//2)
            pygame.draw.circle(screen, NOTE_COLOR_R, (SCREEN_WIDTH//2+50+25, SCREEN_HEIGHT-187.5), NOTE_WIDTH_T//2)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (SCREEN_WIDTH//2+25, 350), (SCREEN_WIDTH, 350), JUDGE_LINE_THICKNESS)
            pygame.draw.line(screen, JUDGE_LINE_COLOR, (SCREEN_WIDTH//2+25, 250), (SCREEN_WIDTH, 250), JUDGE_LINE_THICKNESS)
        pygame.draw.line(screen, (255, 255, 255), (SCREEN_WIDTH//2+25, 0), (SCREEN_WIDTH//2+25, SCREEN_HEIGHT), 2)
            
        
        if(game==1):
            draw_judgment_results(judgment_results_left, 0)
        else:
            draw_judgment_results_taiko(judgment_results_left, 0)
        if(game_p2==1):
            draw_judgment_results(judgment_results_right, SCREEN_WIDTH // 2)
        else:
            draw_judgment_results_taiko(judgment_results_right, SCREEN_WIDTH // 2)

        # 左プレイヤーの統計を画面左に表示
        left_font = _mfont(18)   # 幅200pxの列に収め、太鼓レーンの線にも掛からない大きさ
        left_combo_text = left_font.render(f"COMBO: {left_combo}", True, (255, 255, 255))
        screen.blit(left_combo_text, (SCREEN_WIDTH/2 - 200, 20))
        
        if(battle==1):
            left_max_combo_text = left_font.render(f"MAX COMBO: {left_max_combo}", True, NOTE_COLOR_R)
            screen.blit(left_max_combo_text, (SCREEN_WIDTH/2 - 200, 60))
        else:
            left_max_combo_text = left_font.render(f"MAX COMBO: {left_max_combo}", True, (255, 255, 255))
            screen.blit(left_max_combo_text, (SCREEN_WIDTH/2 - 200, 60))

        if(battle==3):
            left_hits_text = left_font.render(f"TOTAL HITS: {left_total_hits}", True, NOTE_COLOR_R)
            screen.blit(left_hits_text, (SCREEN_WIDTH/2 - 200, 100))
        else:
            left_hits_text = left_font.render(f"TOTAL HITS: {left_total_hits}", True, (255, 255, 255))
            screen.blit(left_hits_text, (SCREEN_WIDTH/2 - 200, 100))
            
        
        if(battle==2):
            left_just_hits_text = left_font.render(f"JUST: {left_just_hits}", True, NOTE_COLOR_R)
            screen.blit(left_just_hits_text, (SCREEN_WIDTH/2 - 200, 140))
        else:
            left_just_hits_text = left_font.render(f"JUST: {left_just_hits}", True, (255, 255, 255))
            screen.blit(left_just_hits_text, (SCREEN_WIDTH/2 - 200, 140))


        left_good_hits_text = left_font.render(f"GOOD: {left_good_hits}", True, (255, 255, 255))
        screen.blit(left_good_hits_text, (SCREEN_WIDTH/2 - 200, 180))
        if(battle==4):
            left_hp_text = left_font.render(f"HP: {left_hp}", True, NOTE_COLOR_R)
            screen.blit(left_hp_text, (SCREEN_WIDTH/2 - 200, 220))
        # 右プレイヤーの統計を画面右に表示
        right_font = _mfont(18)  # 同上
        right_combo_text = right_font.render(f"COMBO: {right_combo}", True, (255, 255, 255))
        screen.blit(right_combo_text, (SCREEN_WIDTH - 200, 20))

        if(battle==1):
            right_max_combo_text = right_font.render(f"MAX COMBO: {right_max_combo}", True, NOTE_COLOR_R)
            screen.blit(right_max_combo_text, (SCREEN_WIDTH - 200, 60))
        else:
            right_max_combo_text = right_font.render(f"MAX COMBO: {right_max_combo}", True, (255, 255, 255))
            screen.blit(right_max_combo_text, (SCREEN_WIDTH - 200, 60))
        if(battle==3):
            right_hits_text = right_font.render(f"TOTAL HITS: {right_total_hits}", True, NOTE_COLOR_R)
            screen.blit(right_hits_text, (SCREEN_WIDTH - 200, 100))
        else:
            right_hits_text = right_font.render(f"TOTAL HITS: {right_total_hits}", True, (255, 255, 255))
            screen.blit(right_hits_text, (SCREEN_WIDTH - 200, 100))
        if(battle==2):
            right_just_hits_text = right_font.render(f"JUST: {right_just_hits}", True, NOTE_COLOR_R)
            screen.blit(right_just_hits_text, (SCREEN_WIDTH - 200, 140))
        else:
            right_just_hits_text = right_font.render(f"JUST: {right_just_hits}", True, (255, 255, 255))
            screen.blit(right_just_hits_text, (SCREEN_WIDTH - 200, 140))


        right_good_hits_text = right_font.render(f"GOOD: {right_good_hits}", True, (255, 255, 255))
        screen.blit(right_good_hits_text, (SCREEN_WIDTH - 200, 180))
        if(battle==4):
            right_hp_text = right_font.render(f"HP: {right_hp}", True, NOTE_COLOR_R)
            screen.blit(right_hp_text, (SCREEN_WIDTH - 200, 220))

        draw_now_playing(screen, SCREEN_WIDTH // 2 - 240, 380, 255)
        draw_key_hint(screen, esc="リザルトへ", pos=(SCREEN_WIDTH - 200, 516))
        pygame.display.flip()
        
        if not midi_thread.is_alive():  # MIDI再生スレッドが終了していればゲームループも終了
            running = False
            
        clock.tick(60)
    # 【順序が重要】スレッドを止めてからデバイスを閉じる。
    # 逆順にすると、閉じたデバイスへスレッドが書き込んでネイティブ側で落ちる。
    stop_midi_thread(midi_thread)
    pygame.mixer.music.stop()
    try:
        midi_out.close()
    except Exception:
        pass

    # R でタイトルへ戻る / ウィンドウを閉じた場合は、リザルトを出さずにここで抜ける
    # （ESC はリザルトを見せたいので、ここには来ない）
    if quit_app or back_to_title:
        if quit_app:
            pygame.quit()
            pygame.midi.quit()
            sys.exit()
        return          # タイトルへ戻る（pygame は落とさない。SEを生かしたままにする）
    
    screen.fill((0,0,0))
    
        # 統計を描画する部分（左と右に分けて表示）
    font=_mfont(64)
    
    if(battle==1):
        if(left_max_combo>right_max_combo):
            battle_text = font.render(f"PLAYER 1 WIN", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        elif(left_max_combo==right_max_combo):
            battle_text = font.render(f"DRAW", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        else:
            battle_text = font.render(f"PLAYER 2 WIN", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
    elif(battle==2):
        if(left_just_hits>right_just_hits):
            battle_text = font.render(f"PLAYER 1 WIN", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        elif(left_just_hits==right_just_hits):
            battle_text = font.render(f"DRAW", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        else:
            battle_text = font.render(f"PLAYER 2 WIN", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
    elif(battle==3):
        if(left_total_hits>right_total_hits):
            battle_text = font.render(f"PLAYER 1 WIN", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        elif(left_total_hits==right_total_hits):
            battle_text = font.render(f"DRAW", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        else:
            battle_text = font.render(f"PLAYER 2 WIN", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
    elif(battle==4):
        if(win==1):
            battle_text = font.render(f"PLAYER 1 WIN", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        else:
            battle_text = font.render(f"PLAYER 2 WIN", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        
    font=_mfont(24)

    # 左プレイヤーの統計
    if(battle==3):
        result_text = font.render(f"PLAYER1 TOTAL HITS: {left_total_hits}", True, NOTE_COLOR_R)
        screen.blit(result_text, (SCREEN_WIDTH // 4 - result_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
    else:
        result_text = font.render(f"PLAYER1 TOTAL HITS: {left_total_hits}", True, (255, 255, 255))
        screen.blit(result_text, (SCREEN_WIDTH // 4 - result_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
    if(battle==1):
        max_combo_text = font.render(f"PLAYER1 MAX COMBO: {left_max_combo}", True, NOTE_COLOR_R)
        screen.blit(max_combo_text, (SCREEN_WIDTH // 4 - max_combo_text.get_width() // 2, SCREEN_HEIGHT // 2))
    else:
        max_combo_text = font.render(f"PLAYER1 MAX COMBO: {left_max_combo}", True, (255, 255, 255))
        screen.blit(max_combo_text, (SCREEN_WIDTH // 4 - max_combo_text.get_width() // 2, SCREEN_HEIGHT // 2))

    
    total_notes_text = font.render(f"PLAYER1 TOTAL NOTES: {total_notes}", True, (255, 255, 255))
    screen.blit(total_notes_text, (SCREEN_WIDTH // 4 - total_notes_text.get_width() // 2, SCREEN_HEIGHT // 2 + 40))
    if(battle==2):
        just_result_text = font.render(f"PLAYER1 JUST: {left_just_hits}", True, NOTE_COLOR_R)
        screen.blit(just_result_text, (SCREEN_WIDTH // 4 - just_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 80))
    else:    
        just_result_text = font.render(f"PLAYER1 JUST: {left_just_hits}", True, (255, 255, 255))
        screen.blit(just_result_text, (SCREEN_WIDTH // 4 - just_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 80))

    good_result_text = font.render(f"PLAYER1 GOOD: {left_good_hits}", True, (255, 255, 255))
    screen.blit(good_result_text, (SCREEN_WIDTH // 4 - good_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 120))

    # 叩けなかったノーツと精度。1P と 2P は難易度が違いうるので別々に計算する。
    left_miss = max(0, total_notes - left_total_hits)
    left_acc = compute_accuracy(left_just_hits, left_good_hits, total_notes)
    miss_text = font.render(f"PLAYER1 MISS: {left_miss}", True, (255, 120, 120))
    screen.blit(miss_text, (SCREEN_WIDTH // 4 - miss_text.get_width() // 2, SCREEN_HEIGHT // 2 + 160))
    acc_text = font.render(f"PLAYER1 {left_acc:.1f}%  RANK {compute_rank(left_acc)}",
                           True, (255, 220, 90))
    screen.blit(acc_text, (SCREEN_WIDTH // 4 - acc_text.get_width() // 2, SCREEN_HEIGHT // 2 + 200))

    
    # 右プレイヤーの統計
    if(battle==3):
        result_text = font.render(f"PLAYER2 TOTAL HITS: {right_total_hits}", True, NOTE_COLOR_R)
        screen.blit(result_text, (3*SCREEN_WIDTH // 4 - result_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
    else:
        result_text = font.render(f"PLAYER2 TOTAL HITS: {right_total_hits}", True, (255, 255, 255))
        screen.blit(result_text, (3*SCREEN_WIDTH // 4 - result_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
    if(battle==1):
        max_combo_text = font.render(f"PLAYER2 MAX COMBO: {right_max_combo}", True, NOTE_COLOR_R)
        screen.blit(max_combo_text, (3*SCREEN_WIDTH // 4 - max_combo_text.get_width() // 2, SCREEN_HEIGHT // 2))
    else:  
        max_combo_text = font.render(f"PLAYER2 MAX COMBO: {right_max_combo}", True, (255, 255, 255))
        screen.blit(max_combo_text, (3*SCREEN_WIDTH // 4 - max_combo_text.get_width() // 2, SCREEN_HEIGHT // 2))
    total_notes_text = font.render(f"PLAYER2 TOTAL NOTES: {total_notes_p2}", True, (255, 255, 255))
    screen.blit(total_notes_text, (3*SCREEN_WIDTH // 4 - total_notes_text.get_width() // 2, SCREEN_HEIGHT // 2 + 40))

    if(battle==2):
        just_result_text = font.render(f"PLAYER2 JUST: {right_just_hits}", True, NOTE_COLOR_R)
        screen.blit(just_result_text, (3*SCREEN_WIDTH // 4 - just_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 80))
    else:
        just_result_text = font.render(f"PLAYER2 JUST: {right_just_hits}", True, (255, 255, 255))
        screen.blit(just_result_text, (3*SCREEN_WIDTH // 4 - just_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 80))
    good_result_text = font.render(f"PLAYER2 GOOD: {right_good_hits}", True, (255, 255, 255))
    screen.blit(good_result_text, (3*SCREEN_WIDTH // 4 - good_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 120))

    right_miss = max(0, total_notes_p2 - right_total_hits)
    right_acc = compute_accuracy(right_just_hits, right_good_hits, total_notes_p2)
    miss_text = font.render(f"PLAYER2 MISS: {right_miss}", True, (255, 120, 120))
    screen.blit(miss_text, (3*SCREEN_WIDTH // 4 - miss_text.get_width() // 2, SCREEN_HEIGHT // 2 + 160))
    acc_text = font.render(f"PLAYER2 {right_acc:.1f}%  RANK {compute_rank(right_acc)}",
                           True, (255, 220, 90))
    screen.blit(acc_text, (3*SCREEN_WIDTH // 4 - acc_text.get_width() // 2, SCREEN_HEIGHT // 2 + 200))

    # どの曲・どの難易度だったかをリザルトにも残す
    head = _mfont(22).render(current_song_name, True, (150, 150, 150))
    screen.blit(head, (SCREEN_WIDTH // 2 - head.get_width() // 2, 10))
    sub_txt = f"1P {current_difficulty}　／　2P {current_difficulty_p2}"
    if interrupted:
        sub_txt += "　（途中で中断）"
    sub = _mfont(18).render(sub_txt, True,
                            (255, 170, 80) if interrupted else (150, 150, 150))
    screen.blit(sub, (SCREEN_WIDTH // 2 - sub.get_width() // 2, 46))

    draw_key_hint(screen)
    pygame.display.flip()

    # スコア画面を表示するフラグ
    score_shown = True
    while score_shown:
        for event in pygame.event.get():
            # F11(全画面切替)はどの画面でも先に処理する
            if handle_common_keys(event):
                continue
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    # アプリを終了する（スレッドとデバイスを片付けてから）
                    stop_midi_thread(midi_thread)
                    pygame.mixer.music.stop()
                    pygame.quit(); pygame.midi.quit()
                    sys.exit()
                elif event.key == pygame.K_r:
                    # タイトル画面に戻る処理
                    score_shown = False  # スコア画面を閉じる
                    # タイトル画面を表示する関数を呼び出す
            elif event.type == pygame.QUIT:
                stop_midi_thread(midi_thread)
                pygame.mixer.music.stop()
                pygame.quit(); pygame.midi.quit()
                sys.exit()



    # タイトルへ戻るだけなので pygame は終了しない。
    # （pygame.quit() すると効果音の Sound が無効になり、次のプレイで鳴らなくなる）
    stop_midi_thread(midi_thread)
    pygame.mixer.music.stop()

def process_hit_for_player(notes, column, current_time, player, judgment_results):
    global left_hp,right_hp
    note_hit = False
    for note in notes:
        if note['state'] == 'active' and note['column'] == column:
            note_time = note['note_time']
            elapsed_time = current_time - note_time
            note_position = elapsed_time * NOTE_SPEED
            if JUDGE_LINE_Y - JUDGE_RANGE <= note_position <= JUDGE_LINE_Y + JUDGE_RANGE:
                note['state'] = 'hit'
                judgment_results.append({'column': column, 'result': 'JUST', 'time': current_time})
                se_tambourine.play(maxtime=1000)
                return 'JUST'
            elif JUDGE_LINE_Y - JUDGE_RANGE * 2 <= note_position <= JUDGE_LINE_Y + JUDGE_RANGE * 2:
                note['state'] = 'hit'
                judgment_results.append({'column': column, 'result': 'GOOD', 'time': current_time})
                se_tambourine.play(maxtime=1000)
                return 'GOOD'           
    
    judgment_results.append({'column': column, 'result': 'MISS', 'time': current_time})
    if(battle==4):
        if(player):
            left_hp-=1
        else:
            right_hp-=1
    return 'MISS'
def process_hit_for_player_taiko(notes,note_type,current_time, player, judgment_results):
                global left_hp,right_hp
                note_hit = False

                # ノーツが判定ラインに達しているかをチェック
                for note in notes:
                    if note['state'] == 'active' and note['note_type'] == note_type:
                        note_time = note['note_time']
                        elapsed_time = current_time - note_time
                        if player:
                            note_position = elapsed_time * NOTE_SPEED
                        else:
                            note_position = elapsed_time * NOTE_SPEED+SCREEN_WIDTH//2-350
                        
                        if JUDGE_LINE_X - JUDGE_RANGE <= note_position <= JUDGE_LINE_X + JUDGE_RANGE:
                            # ノーツがjustの範囲にある場合
                            note['state'] = 'hit'
                            # 判定結果を追加
                            judgment_results.append({'time': current_time, 'result': 'JUST'})
                            if(note_type==0):
                                se_don.play()
                            else:
                                se_ka.play()
                                
                            return 'JUST'
                        elif JUDGE_LINE_X - JUDGE_RANGE * 2 <= note_position <= JUDGE_LINE_X + JUDGE_RANGE * 2:
                            # ノーツがgoodの範囲にある場合
                            note['state'] = 'hit'
                            note_hit = True
                            # 判定結果を追加
                            judgment_results.append({'time': current_time, 'result': 'GOOD'})
                            if(note_type==0):
                                se_don.play()
                            else:
                                se_ka.play()
                            return'GOOD'

                # もしノーツがなければコンボをリセット
                if not note_hit:
                    judgment_results.append({'time': current_time, 'result': 'MISS'})
                    if(battle==4):
                        if(player):
                            left_hp-=1
                        else:
                            right_hp-=1
                    return 'MISS'





def select_temperature(initial=1.0):
    """GRU 生成の temperature(揺らぎ)を調整する画面。
    ↑/→で上げ、↓/←で下げ、Enterで決定。
    0=最尤(規則的な配置)、大きいほどランダム寄りの揺らぎが増える。
    初期値1.0は、学習した確率を無加工で使う設定＝人手の譜面に最も近い。"""
    pygame.init()
    pygame.midi.init()

    SCREEN_WIDTH = 700
    SCREEN_HEIGHT = 600
    screen = set_display((SCREEN_WIDTH, SCREEN_HEIGHT))
    font = pygame.font.SysFont('meiryo', 40)
    small = pygame.font.SysFont('meiryo', 24)

    temp = initial
    selecting = True
    while selecting:
        for event in pygame.event.get():
            # F11(全画面切替)はどの画面でも先に処理する
            if handle_common_keys(event):
                continue
            if event.type == pygame.QUIT:
                pygame.quit(); pygame.midi.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_UP, pygame.K_RIGHT):
                    temp = min(1.5, round(temp + 0.1, 1))
                elif event.key in (pygame.K_DOWN, pygame.K_LEFT):
                    temp = max(0.0, round(temp - 0.1, 1))
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    selecting = False
                elif event.key == pygame.K_ESCAPE:
                    return BACK

        screen.fill((0, 0, 0))
        title_text = font.render("temperature を調整してください", True, (255, 255, 255))
        val_text = font.render(f"temperature = {temp:.1f}", True, (255, 255, 0))
        guide1 = small.render("↑ / → : 上げる      ↓ / ← : 下げる", True, (200, 200, 200))
        guide2 = small.render("Enter : 決定して開始　　ESC : 戻る", True, (200, 200, 200))
        guide3 = small.render("0 = 最尤(規則的)   大きいほど揺らぎ(ランダム寄り)", True, (150, 150, 150))
        screen.blit(title_text, (SCREEN_WIDTH // 2 - title_text.get_width() // 2, 150))
        screen.blit(val_text, (SCREEN_WIDTH // 2 - val_text.get_width() // 2, 260))
        screen.blit(guide1, (SCREEN_WIDTH // 2 - guide1.get_width() // 2, 370))
        screen.blit(guide2, (SCREEN_WIDTH // 2 - guide2.get_width() // 2, 410))
        screen.blit(guide3, (SCREEN_WIDTH // 2 - guide3.get_width() // 2, 460))
        pygame.display.flip()

    return temp


def show_message(title, *lines, wait=True):
    """お知らせを1画面出す。エラーで落とす代わりに使う。"""
    screen = pygame.display.get_surface() or set_display((SCREEN_WIDTH, SCREEN_HEIGHT))
    w, h = screen.get_width(), screen.get_height()
    screen.fill((0, 0, 0))
    ft, fb = _mfont(34), _mfont(22)
    ts = ft.render(title, True, (255, 220, 120))
    screen.blit(ts, (w // 2 - ts.get_width() // 2, h // 2 - 110))
    for i, line in enumerate(lines):
        s = fb.render(line, True, (220, 220, 220))
        screen.blit(s, (w // 2 - s.get_width() // 2, h // 2 - 40 + i * 34))
    if wait:
        hint = _mfont(18).render("何かキーを押してください", True, (140, 140, 140))
        screen.blit(hint, (w // 2 - hint.get_width() // 2, h // 2 + 90))
    pygame.display.flip()
    if not wait:
        return
    while True:
        for e in pygame.event.get():
            # F11(全画面切替)はどの画面でも先に処理する
            if handle_common_keys(e):
                continue
            if e.type == pygame.QUIT:
                pygame.quit(); pygame.midi.quit(); sys.exit()
            if e.type == pygame.KEYDOWN:
                return
        pygame.time.wait(20)


def show_loading_screen(message="譜面を生成中..."):
    """譜面生成(GRU推論)中に表示するロード画面。
    生成は同期処理でブロックするため、この1フレームを描画してから生成を呼ぶ。"""
    pygame.init()
    SCREEN_WIDTH = 700
    SCREEN_HEIGHT = 600
    screen = set_display((SCREEN_WIDTH, SCREEN_HEIGHT))
    font = pygame.font.SysFont('meiryo', 44)
    small = pygame.font.SysFont('meiryo', 24)

    pygame.event.pump()                 # OSにウィンドウ応答を返す(無応答化を防ぐ)
    screen.fill((0, 0, 0))
    text = font.render(message, True, (255, 255, 255))
    sub = small.render("レーンの配置を決めています。しばらくお待ちください...",
                       True, (180, 180, 180))
    screen.blit(text, (SCREEN_WIDTH // 2 - text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
    screen.blit(sub, (SCREEN_WIDTH // 2 - sub.get_width() // 2, SCREEN_HEIGHT // 2 + 30))
    pygame.display.flip()
    pygame.event.pump()


def main():
    global midi_file, midi_out, judgment_results,notes,notes_player2,total_notes,filtered_note_on_seconds,total_notes_p2,battle,mode
    
    # Pygameの初期化
    pygame.init()
    pygame.midi.init()
    
    # MIDI出力の初期化
    _dev = pygame.midi.get_default_output_id()
    if _dev == -1:
        raise RuntimeError("MIDI出力デバイスが見つかりません。Windowsの既定のMIDI出力を確認してください。")
    midi_out = pygame.midi.Output(_dev)
    


    while True:
        # 曲選択
        global selected_song,gamemode,game,game_p2
        global current_song_name,current_difficulty,current_difficulty_p2
        title()
        # 前回のプレイ内容が残らないよう、選び直しのたびに消す
        current_song_name = current_difficulty = current_difficulty_p2 = ""
        selected_song = select_song()
        if selected_song is BACK:
            continue                      # タイトルへ戻る
        current_song_name = os.path.splitext(os.path.basename(selected_song))[0]
        print(f"Selected song: {selected_song}")
        # 選択されたMIDIファイルを読み込む
        midi_file = mido.MidiFile(selected_song)

        # 譜面のもとになるノーツをここで取り出しておく。
        # 遊べない曲は、モードや難易度を答えてもらう前に断りたい。
        tempo, tempo_change_count = read_tempo(midi_file)
        if tempo_change_count > 1:
            # テンポが複数回変更される場合（この曲は扱えないので選び直してもらう）
            print("BPMの変化があるため非対応です")
            show_message("この曲は再生できません",
                         "曲の途中でBPMが変化するMIDIには対応していません。",
                         "別の曲を選んでください。")
            continue
        note_on_seconds = extract_note_seconds(midi_file, tempo)
        if not note_on_seconds:
            print("譜面にできるノートがありません")
            show_message("この曲は再生できません",
                         "譜面にできるノートが見つかりませんでした。",
                         "別の曲を選んでください。")
            continue
        print(f"note_on: {len(note_on_seconds)}")

        gamemode=select_gamemode()
        if gamemode is BACK:
            continue                      # 曲選択からやり直す
        print(f"gamemode: {gamemode}")
        if gamemode==0:
            game=select_interface()
            if game is BACK: continue
            difficulty = select_difficulty(song=selected_song, note_on_seconds=note_on_seconds)
            if difficulty is BACK: continue
            current_difficulty = difficulty
            current_difficulty_p2 = ""
            print(f"difficulty:{difficulty}")
        elif gamemode==1:
            game=select_interface("プレイヤー1のインターフェース")
            if game is BACK: continue
            difficulty=select_difficulty("プレイヤー1の難易度", song=selected_song,
                                       note_on_seconds=note_on_seconds)
            if difficulty is BACK: continue
            current_difficulty = difficulty
            print(f"difficulty:{difficulty}")
            game_p2=select_interface("プレイヤー2のインターフェース")
            if game_p2 is BACK: continue
            difficulty_p2=select_difficulty("プレイヤー2の難易度", song=selected_song,
                                          note_on_seconds=note_on_seconds)
            if difficulty_p2 is BACK: continue
            current_difficulty_p2 = difficulty_p2
            print(f"difficulty:{difficulty_p2}")

        # プロセカ風モード(レーンをGRUで生成)を選んだときだけ、生成の揺らぎを調整する
        temperature = 1.0
        if getattr(sys, "frozen", False):
            # 配布版(exe)は同梱した譜面キャッシュ(temperature=1.0)だけを使うため、
            # 調整画面は出さずに 1.0 固定とする。
            print("[配布版] temperature = 1.0 固定")
        elif game == 1 or (gamemode == 1 and game_p2 == 1):
            temperature = select_temperature(1.0)
            if temperature is BACK:
                continue
            print(f"temperature: {temperature}")

        # Pygameの初期化
        pygame.init()
        pygame.midi.quit()  # 以前のMIDIデバイスを終了
        pygame.midi.init()

        
        # MIDI出力の設定
        _dev = pygame.midi.get_default_output_id()
        if _dev == -1:
            raise RuntimeError("MIDI出力デバイスが見つかりません。Windowsの既定のMIDI出力を確認してください。")
        midi_out = pygame.midi.Output(_dev)
        

        def generate_notes(difficulty, note_on_seconds):
            NOTE_RATE = 0
            # 難易度選択で見せたノーツ数と一致させるため、幅は共通の定義から取る
            time_range = DIFFICULTY_TIME_RANGE.get(difficulty, 0.1)

            # 同じタイミングのノートをグループ化
            notes_by_time = {}
            for time_val, note, instrument in note_on_seconds:
                # 時間範囲でグループ化するキーを計算
                time_key = round(time_val / time_range) * time_range
                if time_key not in notes_by_time:
                    notes_by_time[time_key] = []
                notes_by_time[time_key].append((time_val, note, instrument))
            # グループ内のノートをフィルタリング
            filtered_notes = []
            for time_val, notes in notes_by_time.items():
                if len(notes) > 1:
                    selected_notes = random.sample(notes, 2) if random.random() < NOTE_RATE else random.sample(notes, 1)
                    filtered_notes.extend(selected_notes)
                else:
                    filtered_notes.extend(notes)
            
            for time_val, note, instrument in note_on_seconds:
                if time_val not in notes_by_time:
                    notes_by_time[time_val] = []
                notes_by_time[time_val].append((time_val, note, instrument))
                
                

            # ノートを列に割り当て (★自由課題(実譜面版): 実譜面学習GRUで生成)
            #   従来: column = random.randint(0, 3)        # 音楽と無関係なランダム配置
            #   変更: ノーツの時刻列を実譜面学習GRUに入力し、人手の譜面に近いレーン配置を生成
            #
            # 生成済み譜面(JSON)があればそれを使う。無いときだけGRU推論を行う。
            #   → キャッシュ同梱で配布すれば、遊ぶ側に TensorFlow は不要
            cached = chart_cache.load(selected_song, difficulty, temperature)
            if cached is not None:
                print(f"[chart] キャッシュを使用: {len(cached)} notes")
                return cached, len(cached)

            print("[chart] キャッシュが無いのでGRUで生成します(TensorFlowが必要)")
            try:
                import chart_ai_osu   # 遅延import: ここで初めてTensorFlowを読む
            except ImportError:
                # 配布版(exe)にはTensorFlowを同梱していない。
                # 同梱済みの曲を選べば譜面キャッシュが使われるため、通常ここには来ない。
                raise SystemExit(
                    "この配布版には譜面生成AI(TensorFlow)を同梱していません。\n"
                    "同梱されている曲を選んでください。\n"
                    "新しい曲から譜面を生成したい場合はソース版をご利用ください:\n"
                    "  https://github.com/buroido/cross-notes"
                )

            filtered_notes.sort(key=lambda x: x[0])             # 時間順に整列
            times = [time_val for (time_val, _, _) in filtered_notes]  # 時刻列[秒]を取り出す
            lanes = chart_ai_osu.predict_lanes(times, temperature=temperature)  # 調整した温度で生成
            # ※ temperature は select_temperature() で決めた値(既定1.0=人手に最も近い)

            notes = []
            for (time_val, note, instrument), column in zip(filtered_notes, lanes):
                notes.append({'note_time': time_val, 'note': note,
                              'instrument': instrument, 'state': 'active',
                              'column': column})
            total_notes = len(notes)
            try:
                chart_cache.save(selected_song, difficulty, temperature, notes)
            except OSError as e:
                print(f"[chart] キャッシュ保存に失敗: {e}")
            return notes, total_notes
        
        def generate_notes_taiko(difficulty, note_on_seconds):
            time_range = DIFFICULTY_TIME_RANGE.get(difficulty, 0.1)
            # 同じ高さのノーツをグループ化
            notes_by_time = {}
            for time_val, note, instrument in note_on_seconds:
                # 時間範囲でグループ化するキーを計算
                time_key = round(time_val / time_range) * time_range
                if time_key not in notes_by_time:
                    notes_by_time[time_key] = []
                notes_by_time[time_key].append((time_val, note, instrument))
            
            # グループ内のノーツをランダムに選択
            filtered_note_on_seconds = []
            for key, notes in notes_by_time.items():
                if len(notes) >= 2:
                    selected_notes = random.sample(notes, 2) if random.random() < 0 else random.sample(notes, 1)
                    filtered_note_on_seconds.extend(selected_notes)
                else:
                    filtered_note_on_seconds.extend(notes)
            

            # ノーツの管理リスト
            notes = []
            for i, (time_val, note, instrument) in enumerate(filtered_note_on_seconds):
                # ノーツの種類を2つに設定（例えば、ノーツの音階によって色を変える）
                note_type = 0 if note % 2 == 0 else 1  # 偶数ノートはタイプ0、奇数ノートはタイプ1
                notes.append({'note_time': time_val, 'note': note, 'instrument': instrument, 'state': 'active', 'note_type': note_type})
            total_notes=len(notes)
            return notes,total_notes
        
        # 選択はすべて先に済ませてから譜面生成へ進む
        # （以前は対戦の競う項目だけ生成の後に聞いていたので、待たされてから質問される形だった）
        if gamemode==0:
            mode=select_mode()
            if mode is BACK:
                continue
            if(game==1):
                show_loading_screen()   # GRU推論でブロックするため先にロード画面を出す
                notes,total_notes=generate_notes(difficulty,note_on_seconds)
            else:
                notes,total_notes=generate_notes_taiko(difficulty, note_on_seconds)
            run_sologame()
        elif gamemode==1:
            battle=select_battle()
            if battle is BACK:
                continue
            if(game==1 or game_p2==1):
                show_loading_screen()   # GRU推論でブロックするため先にロード画面を出す
            if(game==1):
                notes,total_notes=generate_notes(difficulty,note_on_seconds)
            else:
                notes,total_notes=generate_notes_taiko(difficulty, note_on_seconds)
            if(game_p2==1):
                notes_player2,total_notes_p2=generate_notes(difficulty_p2,note_on_seconds)
            else:
                notes_player2,total_notes_p2=generate_notes_taiko(difficulty_p2,note_on_seconds)
            run_battlegame()
          
main()