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
import chart_ai_osu   # 実譜面(osu!mania)学習GRUでレーン配置を推論するヘルパ

 # 画面サイズの設定
pygame.mixer.init()
SCREEN_WIDTH = 700
SCREEN_HEIGHT = 600
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
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

# SEファイルのロード
se_don = pygame.mixer.Sound("ドン.wav")  # ドン音
se_ka = pygame.mixer.Sound("カッ.wav")    # カ音
se_tambourine = pygame.mixer.Sound("suzu.mp3")  # タンバリン音

# 音量の初期値（0.5 = 半分の音量）
initial_volume = 0.1
se_don.set_volume(initial_volume)
se_ka.set_volume(initial_volume)
se_tambourine.set_volume(initial_volume)

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
    
    
    
    
    
def title():
    pygame.init()
    pygame.midi.init()
    

    # 画面サイズと設定
    SCREEN_WIDTH, SCREEN_HEIGHT = 700, 600
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    
    os.environ['SDL_VIDEO_CENTERED'] = '1'
    os.environ['SDL_VIDEO_WINDOW_POS'] = "0,0"
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

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
    # Pygameの初期化
    pygame.init()
    pygame.midi.init()

    # 画面サイズの設定
    SCREEN_WIDTH = 700
    SCREEN_HEIGHT = 600
     # 画面解像度を取得して中央位置を計算
    screen_info = pygame.display.Info()
    screen_x = (screen_info.current_w - SCREEN_WIDTH)//2
    screen_y = (screen_info.current_h - SCREEN_HEIGHT) // 2

    # Pygameウィンドウの位置を設定
    os.environ['SDL_VIDEO_WINDOW_POS'] = f"{screen_x},{screen_y}"
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    # フォントの設定
    font = pygame.font.SysFont('meiryo', 36)

    # 曲リストの表示設定
    VISIBLE_SONGS = 10  # 画面に表示する曲数

    # 曲選択関数
    music_folder = "music"  # musicフォルダの指定
    midi_files = [f for f in os.listdir(music_folder) if f.endswith('.mid')]

    if not midi_files:
            print("MIDIファイルがありません")
            pygame.quit()
            exit()

    selected_index = 0
    first_visible_index = 0  # 表示の開始位置
    selecting = True

    while selecting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_UP:
                    # 一番上の曲で上キーを押しても移動しないように修正
                    if selected_index > 0:
                        selected_index = (selected_index - 1) % len(midi_files)
                        if selected_index < first_visible_index:
                            first_visible_index = selected_index
                elif event.key == pygame.K_DOWN:
                    # 一番下の曲で下キーを押しても移動しないように修正
                    if selected_index < len(midi_files) - 1:
                        selected_index = (selected_index + 1) % len(midi_files)
                        if selected_index >= first_visible_index + VISIBLE_SONGS:
                            first_visible_index += 1
                elif event.key == pygame.K_RETURN:
                    selecting = False

            # 画面のクリア
            screen.fill((0, 0, 0))

            # タイトルを表示
            title_text = font.render("曲を選択してください", True, (255, 255, 255))
            screen.blit(title_text, (SCREEN_WIDTH // 2 - title_text.get_width() // 2, 50))
            
            

            # スクロール可能な曲リストを表示
            for i in range(VISIBLE_SONGS):
                song_index = first_visible_index + i
                if song_index < len(midi_files):
                    # 拡張子を除いた曲名を表示
                    song_name = os.path.splitext(midi_files[song_index])[0]
                    color = (255, 255, 255) if song_index == selected_index else (100, 100, 100)
                    song_text = font.render(song_name, True, color)
                    screen.blit(song_text, (SCREEN_WIDTH // 2 - song_text.get_width() // 2, 150 + i * 40))

            pygame.display.flip()

    return os.path.join(music_folder, midi_files[selected_index])


def select_solo_difficulty():
    # Pygameの初期化
    pygame.init()
    pygame.midi.init()

    # 画面サイズの設定
    SCREEN_WIDTH = 700
    SCREEN_HEIGHT = 600
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    # フォントの設定
    font = pygame.font.SysFont('meiryo', 36)
    
    selecting = True
    difficulty = None
    while selecting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1:
                    difficulty = 'Easy'
                    selecting = False
                elif event.key == pygame.K_2:
                    difficulty = 'Normal'
                    selecting = False
                elif event.key == pygame.K_3:
                    difficulty = 'Hard'
                    selecting = False
        
        screen.fill((0, 0, 0))
        title_text = font.render("難易度を選択してください", True, (255, 255, 255))
        screen.blit(title_text, (SCREEN_WIDTH // 2 - title_text.get_width() // 2, SCREEN_HEIGHT // 2 - 100))
        
        easy_text = font.render("1: Easy", True, (255, 255, 255))
        screen.blit(easy_text, (SCREEN_WIDTH // 2 - easy_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
        
        normal_text = font.render("2: Normal", True, (255, 255, 255))
        screen.blit(normal_text, (SCREEN_WIDTH // 2 - normal_text.get_width() // 2, SCREEN_HEIGHT // 2))
        
        hard_text = font.render("3: Hard", True, (255, 255, 255))
        screen.blit(hard_text, (SCREEN_WIDTH // 2 - hard_text.get_width() // 2, SCREEN_HEIGHT // 2 + 40))
        
        pygame.display.flip()

    return difficulty

def select_p1_difficulty():
    # Pygameの初期化
    pygame.init()
    pygame.midi.init()

    # 画面サイズの設定
    SCREEN_WIDTH = 700
    SCREEN_HEIGHT = 600
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    # フォントの設定
    font = pygame.font.SysFont('meiryo', 36)
    
    selecting = True
    difficulty = None
    while selecting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1:
                    difficulty = 'Easy'
                    selecting = False
                elif event.key == pygame.K_2:
                    difficulty = 'Normal'
                    selecting = False
                elif event.key == pygame.K_3:
                    difficulty = 'Hard'
                    selecting = False
        
        screen.fill((0, 0, 0))
        title_text = font.render("プレイヤー１の難易度を選択してください", True, (255, 255, 255))
        screen.blit(title_text, (SCREEN_WIDTH // 2 - title_text.get_width() // 2, SCREEN_HEIGHT // 2 - 100))
        
        easy_text = font.render("1: Easy", True, (255, 255, 255))
        screen.blit(easy_text, (SCREEN_WIDTH // 2 - easy_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
        
        normal_text = font.render("2: Normal", True, (255, 255, 255))
        screen.blit(normal_text, (SCREEN_WIDTH // 2 - normal_text.get_width() // 2, SCREEN_HEIGHT // 2))
        
        hard_text = font.render("3: Hard", True, (255, 255, 255))
        screen.blit(hard_text, (SCREEN_WIDTH // 2 - hard_text.get_width() // 2, SCREEN_HEIGHT // 2 + 40))
        
        pygame.display.flip()

    return difficulty

def select_p2_difficulty():
    # Pygameの初期化
    pygame.init()
    pygame.midi.init()

    # 画面サイズの設定
    SCREEN_WIDTH = 700
    SCREEN_HEIGHT = 600
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    # フォントの設定
    font = pygame.font.SysFont('meiryo', 36)
    
    selecting = True
    difficulty = None
    while selecting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1:
                    difficulty = 'Easy'
                    selecting = False
                elif event.key == pygame.K_2:
                    difficulty = 'Normal'
                    selecting = False
                elif event.key == pygame.K_3:
                    difficulty = 'Hard'
                    selecting = False
        
        screen.fill((0, 0, 0))
        title_text = font.render("プレイヤー２の難易度を選択してください", True, (255, 255, 255))
        screen.blit(title_text, (SCREEN_WIDTH // 2 - title_text.get_width() // 2, SCREEN_HEIGHT // 2 - 100))
        
        easy_text = font.render("1: Easy", True, (255, 255, 255))
        screen.blit(easy_text, (SCREEN_WIDTH // 2 - easy_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
        
        normal_text = font.render("2: Normal", True, (255, 255, 255))
        screen.blit(normal_text, (SCREEN_WIDTH // 2 - normal_text.get_width() // 2, SCREEN_HEIGHT // 2))
        
        hard_text = font.render("3: Hard", True, (255, 255, 255))
        screen.blit(hard_text, (SCREEN_WIDTH // 2 - hard_text.get_width() // 2, SCREEN_HEIGHT // 2 + 40))
        
        pygame.display.flip()

    return difficulty



def select_gamemode():
# Pygameの初期化
    pygame.init()

# ウィンドウサイズ
    WIDTH, HEIGHT = 700, 600
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    # 色
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)

    # フォント
    font = pygame.font.SysFont('meiryo', 36)

    # モード選択のメッセージ
    solo_mode_text = font.render("1:一人プレイモード", True, WHITE)
    multiplayer_mode_text = font.render("2:二人プレイモード", True, WHITE)
    instruction_text = font.render("モードを選択してください", True, WHITE)

    # モード選択の変数
    gamemode = 0

    # メインループ
    selecting=True
    while selecting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1:  # 1キーでソロプレイモードを選択
                    gamemode = 0
                    selecting=False
                elif event.key == pygame.K_2:  # 2キーで二人プレイモードを選択
                    gamemode = 1
                    selecting=False

        # 画面を白で塗りつぶす
        screen.fill(BLACK)

        # モード選択のテキストを描画
        screen.blit(solo_mode_text, (WIDTH // 2-solo_mode_text.get_width() // 2, HEIGHT // 2))
        screen.blit(multiplayer_mode_text, (WIDTH // 2-multiplayer_mode_text.get_width() // 2, HEIGHT // 1.5))
        screen.blit(instruction_text, (WIDTH // 2-instruction_text.get_width() // 2, HEIGHT // 3))

    
        # 画面更新
        pygame.display.flip()
        
    return gamemode

import pygame
import sys

def select_game():
    """ゲームモードを選択する画面"""
    pygame.init()

    # ウィンドウサイズと設定
    WIDTH, HEIGHT = 700, 600
    screen = pygame.display.set_mode((WIDTH, HEIGHT))

    # 色
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)

    # フォント
    font = pygame.font.SysFont('meiryo', 36)

    # モード選択のメッセージ
    proseka_mode_text = font.render("1: プロセカ風音ゲー", True, WHITE)
    taiko_mode_text = font.render("2: 太鼓の達人風音ゲー", True, WHITE)
    instruction_text = font.render("モードを選択してください", True, WHITE)

    # モード選択の変数
    gamemode = None

    # メインループ
    selecting = True
    while selecting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1:  # 1キーでプロセカ風音ゲーを選択
                    gamemode = 1
                    selecting = False
                elif event.key == pygame.K_2:  # 2キーで太鼓の達人風音ゲーを選択
                    gamemode = 2
                    selecting = False

        # 画面を黒で塗りつぶす
        screen.fill(BLACK)

        # モード選択のテキストを描画
        screen.blit(proseka_mode_text, (WIDTH // 2 - proseka_mode_text.get_width() // 2, HEIGHT // 2))
        screen.blit(taiko_mode_text, (WIDTH // 2 - taiko_mode_text.get_width() // 2, HEIGHT // 1.5))
        screen.blit(instruction_text, (WIDTH // 2 - instruction_text.get_width() // 2, HEIGHT // 3))

        # 画面更新
        pygame.display.flip()

    return gamemode


def select_game_p1():
    """ゲームモードを選択する画面"""
    pygame.init()

    # ウィンドウサイズと設定
    WIDTH, HEIGHT = 700, 600
    screen = pygame.display.set_mode((WIDTH, HEIGHT))

    # 色
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)

    # フォント
    font = pygame.font.SysFont('meiryo', 36)

    # モード選択のメッセージ
    proseka_mode_text = font.render("1: プロセカ風音ゲー", True, WHITE)
    taiko_mode_text = font.render("2: 太鼓の達人風音ゲー", True, WHITE)
    instruction_text = font.render("プレイヤー１のモードを選択してください", True, WHITE)

    # モード選択の変数
    gamemode = None

    # メインループ
    selecting = True
    while selecting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1:  # 1キーでプロセカ風音ゲーを選択
                    gamemode = 1
                    selecting = False
                elif event.key == pygame.K_2:  # 2キーで太鼓の達人風音ゲーを選択
                    gamemode = 2
                    selecting = False

        # 画面を黒で塗りつぶす
        screen.fill(BLACK)

        # モード選択のテキストを描画
        screen.blit(proseka_mode_text, (WIDTH // 2 - proseka_mode_text.get_width() // 2, HEIGHT // 2))
        screen.blit(taiko_mode_text, (WIDTH // 2 - taiko_mode_text.get_width() // 2, HEIGHT // 1.5))
        screen.blit(instruction_text, (WIDTH // 2 - instruction_text.get_width() // 2, HEIGHT // 3))

        # 画面更新
        pygame.display.flip()

    return gamemode

def select_game_p2():
    """ゲームモードを選択する画面"""
    pygame.init()

    # ウィンドウサイズと設定
    WIDTH, HEIGHT = 700, 600
    screen = pygame.display.set_mode((WIDTH, HEIGHT))

    # 色
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)

    # フォント
    font = pygame.font.SysFont('meiryo', 36)

    # モード選択のメッセージ
    proseka_mode_text = font.render("1: プロセカ風音ゲー", True, WHITE)
    taiko_mode_text = font.render("2: 太鼓の達人風音ゲー", True, WHITE)
    instruction_text = font.render("プレイヤー２のモードを選択してください", True, WHITE)

    # モード選択の変数
    gamemode = None

    # メインループ
    selecting = True
    while selecting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1:  # 1キーでプロセカ風音ゲーを選択
                    gamemode = 1
                    selecting = False
                elif event.key == pygame.K_2:  # 2キーで太鼓の達人風音ゲーを選択
                    gamemode = 2
                    selecting = False

        # 画面を黒で塗りつぶす
        screen.fill(BLACK)

        # モード選択のテキストを描画
        screen.blit(proseka_mode_text, (WIDTH // 2 - proseka_mode_text.get_width() // 2, HEIGHT // 2))
        screen.blit(taiko_mode_text, (WIDTH // 2 - taiko_mode_text.get_width() // 2, HEIGHT // 1.5))
        screen.blit(instruction_text, (WIDTH // 2 - instruction_text.get_width() // 2, HEIGHT // 3))

        # 画面更新
        pygame.display.flip()

    return gamemode

def select_battle():
    """ゲームモードを選択する画面"""
    pygame.init()

    # ウィンドウサイズと設定
    WIDTH, HEIGHT = 700, 600
    screen = pygame.display.set_mode((WIDTH, HEIGHT))

    # 色
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)

    # フォント
    font = pygame.font.SysFont('meiryo', 36)

    # モード選択のメッセージ
    peace_text=font.render("1:仲良くプレイする",True,WHITE)
    maxcombo_text = font.render("2: 最大コンボ数", True, WHITE)
    just_text = font.render("3:just数 ", True, WHITE)
    totalhit_text=font.render("4:合計hit数",True,WHITE)
    hp_text=font.render("5:サドンデス",True,WHITE)
    instruction_text = font.render("競う項目を選択してください", True, WHITE)

    # モード選択の変数
    gamemode = None

    # メインループ
    selecting = True
    while selecting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1: 
                    gamemode = 0
                    selecting = False
                elif event.key == pygame.K_2:  
                    gamemode = 1
                    selecting = False
                elif event.key == pygame.K_3:   
                    gamemode = 2
                    selecting = False
                elif event.key == pygame.K_4:   
                    gamemode = 3
                    selecting = False
                elif event.key == pygame.K_5:   
                    gamemode = 4
                    selecting = False

        # 画面を黒で塗りつぶす
        screen.fill(BLACK)

        # モード選択のテキストを描画
        screen.blit(peace_text, (WIDTH // 2 - peace_text.get_width() // 2, HEIGHT // 2-50))
        screen.blit(maxcombo_text, (WIDTH // 2 - maxcombo_text.get_width() // 2, HEIGHT // 2))
        screen.blit(just_text, (WIDTH // 2 - just_text.get_width() // 2, HEIGHT // 2+50))
        screen.blit(totalhit_text, (WIDTH // 2 - totalhit_text.get_width() // 2, HEIGHT // 2+100))
        screen.blit(hp_text, (WIDTH // 2 - hp_text.get_width() // 2, HEIGHT // 2+150))
        screen.blit(instruction_text, (WIDTH // 2 - instruction_text.get_width() // 2, 100))

        # 画面更新
        pygame.display.flip()

    return gamemode


def select_mode():
    """ゲームモードを選択する画面"""
    pygame.init()

    # ウィンドウサイズと設定
    WIDTH, HEIGHT = 700, 600
    screen = pygame.display.set_mode((WIDTH, HEIGHT))

    # 色
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)

    # フォント
    font = pygame.font.SysFont('meiryo', 36)

    # モード選択のメッセージ
    peace_text=font.render("1:ノーマルモード",True,WHITE)
    maxcombo_text = font.render("2: HPモード", True, WHITE)
    instruction_text = font.render("ソロモードを選択してください", True, WHITE)

    # モード選択の変数
    gamemode = None

    # メインループ
    selecting = True
    while selecting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1: 
                    gamemode = 0
                    selecting = False
                elif event.key == pygame.K_2:  
                    gamemode = 1
                    selecting = False

        # 画面を黒で塗りつぶす
        screen.fill(BLACK)

        # モード選択のテキストを描画
        screen.blit(peace_text, (WIDTH // 2 - peace_text.get_width() // 2, HEIGHT // 2-100))
        screen.blit(maxcombo_text, (WIDTH // 2 - maxcombo_text.get_width() // 2, HEIGHT // 2))
        screen.blit(instruction_text, (WIDTH // 2 - instruction_text.get_width() // 2, 100))

        # 画面更新
        pygame.display.flip()

    return gamemode



def calculate_bpm(tempo):
    microseconds_per_beat = tempo  # マイクロ秒/四分音符
    seconds_per_beat = microseconds_per_beat / 1e6  # 秒/四分音符
    beats_per_minute = 60 / seconds_per_beat  # BPM
    return beats_per_minute

# MIDI再生スレッドの関数
def play_midi():
    global combo, max_combo, running  # コンボ数と最大コンボ数とランニング状態をグローバルスコープで宣言する
    start_time = time.time()
    music_start_delay = (SCREEN_HEIGHT-150) / NOTE_SPEED  # 曲の再生を遅らせる時間

    try:
        time.sleep(music_start_delay)  # 曲の再生を遅延させる

        pygame.mixer.music.unpause()  # 曲を再生

        for msg in midi_file.play():
            if not msg.is_meta:
                status = msg.bytes()[0]
                data1 = msg.bytes()[1] if len(msg.bytes()) > 1 else 0
                data2 = msg.bytes()[2] if len(msg.bytes()) > 2 else 0
                midi_out.write_short(status, data1, data2)

            elapsed_time = time.time() - start_time - music_start_delay
            time.sleep(max(0, msg.time - elapsed_time))
    except Exception as e:
        print(f"Exception in MIDI thread: {e}")
    finally:
        running = False


def run_sologame():
    global total_notes,judgment_results,game,mode
    # Pygameの初期化
    pygame.init()
    pygame.midi.init()
    pygame.mixer.init(channels=32)
        # コンボ数と最大コンボ数の初期化
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
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    # フォントの設定
    font = pygame.font.Font(None, 36)
    
    
        
    # MIDI再生スレッドの開始
    midi_thread = threading.Thread(target=play_midi)
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
            color =COLOR_G if result == 'Just' else COLOR_Y if result == 'Good' else NOTE_COLOR_R  # Missは赤色
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
            result_color = COLOR_G if result == 'Just' else COLOR_Y if result == 'Good' else NOTE_COLOR_R
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
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key==pygame.K_ESCAPE:
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
                                judgment_results.append({'column': check_column, 'result': 'Just', 'time': current_time})
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
                                judgment_results.append({'column': check_column, 'result': 'Good', 'time': current_time})
                                break  # 一度反応したら他のノーツをチェックしない

                    # もしノーツがなければコンボをリセット
                    if not note_hit:
                        if(mode==1):
                            hp-=1
                        
                        judgment_results.append({'column': check_column, 'result': 'miss', 'time': current_time})
                        combo = 0
        else:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key==pygame.K_ESCAPE:
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
                                    judgment_results.append({'time': current_time, 'result': 'Just'})
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
                                    judgment_results.append({'time': current_time, 'result': 'Good'})
                                    break

                        # もしノーツがなければコンボをリセット
                        if not note_hit:
                            if(mode==1):
                                hp-=1
                            judgment_results.append({'time': current_time, 'result': 'miss'})
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
                        note['state'] = 'miss'
                        if(mode==1):
                            hp-=1
                        judgment_results.append({'column': note['column'], 'result': 'miss', 'time': current_time})
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
                        note['state'] = 'miss'
                        if(mode==1):
                            hp-=1
                        judgment_results.append({'time': current_time, 'result': 'miss'})
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
        combo_text = font.render(f"Combo: {combo}", True, (255, 255, 255))
        screen.blit(combo_text, (SCREEN_WIDTH-200, 20))

        max_combo_text = font.render(f"Max Combo: {max_combo}", True, (255, 255, 255))
        screen.blit(max_combo_text, (SCREEN_WIDTH-200, 60))

        # BPMを計算して画面に表示
        bpm = calculate_bpm(tempo)
        total_hits_text = font.render(f"Total Hits: {total_hits}", True, (255, 255, 255))
        screen.blit(total_hits_text, (SCREEN_WIDTH-200, 100))

        # justとgoodの数を画面に表示
        just_text = font.render(f"Just: {just_hits}", True, (255, 255, 255))
        screen.blit(just_text, (SCREEN_WIDTH-200, 140))

        good_text = font.render(f"Good: {good_hits}", True, (255, 255, 255))
        screen.blit(good_text, (SCREEN_WIDTH-200, 180))
        if(mode==1):
            hp_text = font.render(f"HP: {hp}", True, NOTE_COLOR_R)
            screen.blit(hp_text, (SCREEN_WIDTH-200, 220))
        
        # 判定結果の描画
        if (game==1):
            draw_judgment_results_pro()
        else:
            draw_judgment_results_taiko()
        
        if not midi_thread.is_alive():  # MIDI再生スレッドが終了していればゲームループも終了
            running = False


        # 画面更新
        pygame.display.flip()

        # 60fpsで描画
        clock.tick(60)
    midi_out.close()

    # ゲームループが終了したら、結果を表示
    screen.fill((0, 0, 0))

    result_text = font.render(f"Total Hits: {total_hits}", True, (255, 255, 255))
    screen.blit(result_text, (SCREEN_WIDTH // 2 - result_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))

    max_combo_text = font.render(f"Max Combo: {max_combo}", True, (255, 255, 255))
    screen.blit(max_combo_text, (SCREEN_WIDTH // 2 - max_combo_text.get_width() // 2, SCREEN_HEIGHT // 2))

    total_notes_text = font.render(f"Total Notes: {total_notes}", True, (255, 255, 255))
    screen.blit(total_notes_text, (SCREEN_WIDTH // 2 - total_notes_text.get_width() // 2, SCREEN_HEIGHT // 2 + 40))

    just_result_text = font.render(f"Just Hits: {just_hits}", True, (255, 255, 255))
    screen.blit(just_result_text, (SCREEN_WIDTH // 2 - just_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 80))

    good_result_text = font.render(f"Good Hits: {good_hits}", True, (255, 255, 255))
    screen.blit(good_result_text, (SCREEN_WIDTH // 2 - good_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 120))

    pygame.display.flip()

    # スコア画面を表示するフラグ
    score_shown = True
    while score_shown:
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    # ゲームを終了
                    running = False
                    exit()
                elif event.key == pygame.K_r:
                    # タイトル画面に戻る処理
                    score_shown = False
                    running=False# スコア画面を閉じる
                    # タイトル画面を表示する関数を呼び出す
            elif event.type == pygame.QUIT:
                running = False
                exit()



    # Pygameの終了処理
    pygame.quit()

    # MIDI出力とPygame MIDIの終了処理
    
    pygame.midi.quit()

    # 曲の再生スレッドとMIDI再生スレッドの終了を待つ
    midi_thread.join()


def run_battlegame():
    global total_notes, judgment_results_left, judgment_results_right,total_notes_p2,game,game_p2,battle,right_hp,left_hp
    
    # Pygameの初期化
    pygame.init()
    pygame.midi.init()
    pygame.mixer.init()
    
   
    

    # プレイヤーのコンボと最大コンボの初期化
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
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    # フォントの設定
    font = pygame.font.Font(None, 36)
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
                    note['state'] = 'miss'
                    if is_left_player:
                        judgment_results_left.append(
                            {'column': note['column'], 'result': 'miss', 'time': current_time}
                        )
                        if(battle==4):
                            left_hp-=1
                            

                    else:
                        judgment_results_right.append(
                            {'column': note['column'], 'result': 'miss', 'time': current_time}
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
                            note['state'] = 'miss'
                            if is_left_player:
                                judgment_results_left.append({'time': current_time, 'result': 'miss'})
                                if(battle==4):
                                    left_hp-=1
                            else:
                                judgment_results_right.append({'time': current_time, 'result': 'miss'})
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
                            note['state'] = 'miss'
                            if is_left_player:
                                judgment_results_left.append({'time': current_time, 'result': 'miss'})
                                
                            else:
                                judgment_results_right.append({'time': current_time, 'result': 'miss'})
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

            color = COLOR_G if result == 'Just' else COLOR_Y if result == 'Good' else NOTE_COLOR_R
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
            result_color = COLOR_G if result == 'Just' else COLOR_Y if result == 'Good' else NOTE_COLOR_R
            result_text = font.render(result, True, result_color)
            screen.blit(result_text, (x_position - result_text.get_width() // 2, int(y_position)))
   

    midi_thread = threading.Thread(target=play_midi)
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
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                
                if event.key in left_keys:
                    if(game==1):
                        check_column = left_keys[event.key]
                        result = process_hit_for_player(notes, check_column, current_time, True, judgment_results_left)
                    else:
                        note_type = left_keys[event.key]
                        result=process_hit_for_player_taiko(notes,note_type,current_time,True,judgment_results_left)
                        
                    if result == 'Just':
                            left_combo += 1
                            left_total_hits += 1
                            left_just_hits += 1
                            if left_combo > left_max_combo:
                                left_max_combo = left_combo
                    elif result=='Good':
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
                        
                    if result == 'Just':
                        right_combo += 1
                        right_total_hits+=1
                        right_just_hits+=1
                        if right_combo > right_max_combo:
                            right_max_combo = right_combo
                    elif result=='Good':
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
        left_font = pygame.font.Font(None, 36)
        left_combo_text = left_font.render(f"Combo: {left_combo}", True, (255, 255, 255))
        screen.blit(left_combo_text, (SCREEN_WIDTH/2 - 200, 20))
        
        if(battle==1):
            left_max_combo_text = left_font.render(f"Max Combo: {left_max_combo}", True, NOTE_COLOR_R)
            screen.blit(left_max_combo_text, (SCREEN_WIDTH/2 - 200, 60))
        else:
            left_max_combo_text = left_font.render(f"Max Combo: {left_max_combo}", True, (255, 255, 255))
            screen.blit(left_max_combo_text, (SCREEN_WIDTH/2 - 200, 60))

        if(battle==3):
            left_hits_text = left_font.render(f"Total Hits: {left_total_hits}", True, NOTE_COLOR_R)
            screen.blit(left_hits_text, (SCREEN_WIDTH/2 - 200, 100))
        else:
            left_hits_text = left_font.render(f"Total Hits: {left_total_hits}", True, (255, 255, 255))
            screen.blit(left_hits_text, (SCREEN_WIDTH/2 - 200, 100))
            
        
        if(battle==2):
            left_just_hits_text = left_font.render(f"Just Hits: {left_just_hits}", True, NOTE_COLOR_R)
            screen.blit(left_just_hits_text, (SCREEN_WIDTH/2 - 200, 140))
        else:
            left_just_hits_text = left_font.render(f"Just Hits: {left_just_hits}", True, (255, 255, 255))
            screen.blit(left_just_hits_text, (SCREEN_WIDTH/2 - 200, 140))


        left_good_hits_text = left_font.render(f"Good Hits: {left_good_hits}", True, (255, 255, 255))
        screen.blit(left_good_hits_text, (SCREEN_WIDTH/2 - 200, 180))
        if(battle==4):
            left_hp_text = left_font.render(f"HP: {left_hp}", True, NOTE_COLOR_R)
            screen.blit(left_hp_text, (SCREEN_WIDTH/2 - 200, 220))
        # 右プレイヤーの統計を画面右に表示
        right_font = pygame.font.Font(None, 36)
        right_combo_text = right_font.render(f"Combo: {right_combo}", True, (255, 255, 255))
        screen.blit(right_combo_text, (SCREEN_WIDTH - 200, 20))

        if(battle==1):
            right_max_combo_text = right_font.render(f"Max Combo: {right_max_combo}", True, NOTE_COLOR_R)
            screen.blit(right_max_combo_text, (SCREEN_WIDTH - 200, 60))
        else:
            right_max_combo_text = right_font.render(f"Max Combo: {right_max_combo}", True, (255, 255, 255))
            screen.blit(right_max_combo_text, (SCREEN_WIDTH - 200, 60))
        if(battle==3):
            right_hits_text = right_font.render(f"Total Hits: {right_total_hits}", True, NOTE_COLOR_R)
            screen.blit(right_hits_text, (SCREEN_WIDTH - 200, 100))
        else:
            right_hits_text = right_font.render(f"Total Hits: {right_total_hits}", True, (255, 255, 255))
            screen.blit(right_hits_text, (SCREEN_WIDTH - 200, 100))
        if(battle==2):
            right_just_hits_text = right_font.render(f"Just Hits: {right_just_hits}", True, NOTE_COLOR_R)
            screen.blit(right_just_hits_text, (SCREEN_WIDTH - 200, 140))
        else:
            right_just_hits_text = right_font.render(f"Just Hits: {right_just_hits}", True, (255, 255, 255))
            screen.blit(right_just_hits_text, (SCREEN_WIDTH - 200, 140))


        right_good_hits_text = right_font.render(f"Good Hits: {right_good_hits}", True, (255, 255, 255))
        screen.blit(right_good_hits_text, (SCREEN_WIDTH - 200, 180))
        if(battle==4):
            right_hp_text = right_font.render(f"HP: {right_hp}", True, NOTE_COLOR_R)
            screen.blit(right_hp_text, (SCREEN_WIDTH - 200, 220))

        pygame.display.flip()
        
        if not midi_thread.is_alive():  # MIDI再生スレッドが終了していればゲームループも終了
            running = False
            
        clock.tick(60)
    midi_out.close()
    
    screen.fill((0,0,0))
    
        # 統計を描画する部分（左と右に分けて表示）
    left_font = pygame.font.Font(None, 36)
    right_font = pygame.font.Font(None, 36)
    font=pygame.font.Font(None,100)
    
    if(battle==1):
        if(left_max_combo>right_max_combo):
            battle_text = font.render(f"Player1 Win", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        elif(left_max_combo==right_max_combo):
            battle_text = font.render(f"Draw", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        else:
            battle_text = font.render(f"Player2 Win", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
    elif(battle==2):
        if(left_just_hits>right_just_hits):
            battle_text = font.render(f"Player1 Win", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        elif(left_just_hits==right_just_hits):
            battle_text = font.render(f"Draw", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        else:
            battle_text = font.render(f"Player2 Win", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
    elif(battle==3):
        if(left_total_hits>right_total_hits):
            battle_text = font.render(f"Player1 Win", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        elif(left_total_hits==right_total_hits):
            battle_text = font.render(f"Draw", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        else:
            battle_text = font.render(f"Player2 Win", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
    elif(battle==4):
        if(win==1):
            battle_text = font.render(f"Player1 Win", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        else:
            battle_text = font.render(f"Player2 Win", True, NOTE_COLOR_R)
            screen.blit(battle_text, (SCREEN_WIDTH //2  - battle_text.get_width() // 2, 100))
        
    font=pygame.font.Font(None,36)

    # 左プレイヤーの統計
    if(battle==3):
        result_text = font.render(f"Player1 Total Hits: {left_total_hits}", True, NOTE_COLOR_R)
        screen.blit(result_text, (SCREEN_WIDTH // 4 - result_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
    else:
        result_text = font.render(f"Player1 Total Hits: {left_total_hits}", True, (255, 255, 255))
        screen.blit(result_text, (SCREEN_WIDTH // 4 - result_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
    if(battle==1):
        max_combo_text = font.render(f"Player1 Max Combo: {left_max_combo}", True, NOTE_COLOR_R)
        screen.blit(max_combo_text, (SCREEN_WIDTH // 4 - max_combo_text.get_width() // 2, SCREEN_HEIGHT // 2))
    else:
        max_combo_text = font.render(f"Player1 Max Combo: {left_max_combo}", True, (255, 255, 255))
        screen.blit(max_combo_text, (SCREEN_WIDTH // 4 - max_combo_text.get_width() // 2, SCREEN_HEIGHT // 2))

    
    total_notes_text = font.render(f"Player1 Total Notes: {total_notes}", True, (255, 255, 255))
    screen.blit(total_notes_text, (SCREEN_WIDTH // 4 - total_notes_text.get_width() // 2, SCREEN_HEIGHT // 2 + 40))
    if(battle==2):
        just_result_text = font.render(f"Player1 Just Hits: {left_just_hits}", True, NOTE_COLOR_R)
        screen.blit(just_result_text, (SCREEN_WIDTH // 4 - just_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 80))
    else:    
        just_result_text = font.render(f"Player1 Just Hits: {left_just_hits}", True, (255, 255, 255))
        screen.blit(just_result_text, (SCREEN_WIDTH // 4 - just_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 80))

    good_result_text = font.render(f"Player1 Good Hits: {left_good_hits}", True, (255, 255, 255))
    screen.blit(good_result_text, (SCREEN_WIDTH // 4 - good_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 120))

    
    # 右プレイヤーの統計
    if(battle==3):
        result_text = font.render(f"Player2 Total Hits: {right_total_hits}", True, NOTE_COLOR_R)
        screen.blit(result_text, (3*SCREEN_WIDTH // 4 - result_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
    else:
        result_text = font.render(f"Player2 Total Hits: {right_total_hits}", True, (255, 255, 255))
        screen.blit(result_text, (3*SCREEN_WIDTH // 4 - result_text.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
    if(battle==1):
        max_combo_text = font.render(f"Player2 Max Combo: {right_max_combo}", True, NOTE_COLOR_R)
        screen.blit(max_combo_text, (3*SCREEN_WIDTH // 4 - max_combo_text.get_width() // 2, SCREEN_HEIGHT // 2))
    else:  
        max_combo_text = font.render(f"Player2 Max Combo: {right_max_combo}", True, (255, 255, 255))
        screen.blit(max_combo_text, (3*SCREEN_WIDTH // 4 - max_combo_text.get_width() // 2, SCREEN_HEIGHT // 2))
    total_notes_text = font.render(f"Player2 Total Notes: {total_notes_p2}", True, (255, 255, 255))
    screen.blit(total_notes_text, (3*SCREEN_WIDTH // 4 - total_notes_text.get_width() // 2, SCREEN_HEIGHT // 2 + 40))

    if(battle==2):
        just_result_text = font.render(f"Player2 Just Hits: {right_just_hits}", True, NOTE_COLOR_R)
        screen.blit(just_result_text, (3*SCREEN_WIDTH // 4 - just_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 80))
    else:
        just_result_text = font.render(f"Player2 Just Hits: {right_just_hits}", True, (255, 255, 255))
        screen.blit(just_result_text, (3*SCREEN_WIDTH // 4 - just_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 80))
    good_result_text = font.render(f"Player2 Good Hits: {right_good_hits}", True, (255, 255, 255))
    screen.blit(good_result_text, (3*SCREEN_WIDTH // 4 - good_result_text.get_width() // 2, SCREEN_HEIGHT // 2 + 120))

    
    pygame.display.flip()

    # スコア画面を表示するフラグ
    score_shown = True
    while score_shown:
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    # ゲームを終了
                    running = False
                    exit()
                elif event.key == pygame.K_r:
                    # タイトル画面に戻る処理
                    score_shown = False  # スコア画面を閉じる
                    # タイトル画面を表示する関数を呼び出す
            elif event.type == pygame.QUIT:
                score_shown = False
                running = False
                exit()



    # Pygameの終了処理
    pygame.quit()

    # MIDI出力とPygame MIDIの終了処理
    
    pygame.midi.quit()

    # 曲の再生スレッドとMIDI再生スレッドの終了を待つ
    midi_thread.join()

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
                judgment_results.append({'column': column, 'result': 'Just', 'time': current_time})
                se_tambourine.play(maxtime=1000)
                return 'Just'
            elif JUDGE_LINE_Y - JUDGE_RANGE * 2 <= note_position <= JUDGE_LINE_Y + JUDGE_RANGE * 2:
                note['state'] = 'hit'
                judgment_results.append({'column': column, 'result': 'Good', 'time': current_time})
                se_tambourine.play(maxtime=1000)
                return 'Good'           
    
    judgment_results.append({'column': column, 'result': 'Miss', 'time': current_time})
    if(battle==4):
        if(player):
            left_hp-=1
        else:
            right_hp-=1
    return 'Miss'
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
                            judgment_results.append({'time': current_time, 'result': 'Just'})
                            if(note_type==0):
                                se_don.play()
                            else:
                                se_ka.play()
                                
                            return 'Just'
                        elif JUDGE_LINE_X - JUDGE_RANGE * 2 <= note_position <= JUDGE_LINE_X + JUDGE_RANGE * 2:
                            # ノーツがgoodの範囲にある場合
                            note['state'] = 'hit'
                            note_hit = True
                            # 判定結果を追加
                            judgment_results.append({'time': current_time, 'result': 'Good'})
                            if(note_type==0):
                                se_don.play()
                            else:
                                se_ka.play()
                            return'Good'

                # もしノーツがなければコンボをリセット
                if not note_hit:
                    judgment_results.append({'time': current_time, 'result': 'miss'})
                    if(battle==4):
                        if(player):
                            left_hp-=1
                        else:
                            right_hp-=1
                    return 'miss'





def select_temperature(initial=1.0):
    """GRU 生成の temperature(揺らぎ)を調整する画面。
    ↑/→で上げ、↓/←で下げ、Enterで決定。
    0=最尤(規則的な配置)、大きいほどランダム寄りの揺らぎが増える。
    初期値1.0は、学習した確率を無加工で使う設定＝人手の譜面に最も近い。"""
    pygame.init()
    pygame.midi.init()

    SCREEN_WIDTH = 700
    SCREEN_HEIGHT = 600
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    font = pygame.font.SysFont('meiryo', 40)
    small = pygame.font.SysFont('meiryo', 24)

    temp = initial
    selecting = True
    while selecting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_UP, pygame.K_RIGHT):
                    temp = min(1.5, round(temp + 0.1, 1))
                elif event.key in (pygame.K_DOWN, pygame.K_LEFT):
                    temp = max(0.0, round(temp - 0.1, 1))
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    selecting = False

        screen.fill((0, 0, 0))
        title_text = font.render("temperature を調整してください", True, (255, 255, 255))
        val_text = font.render(f"temperature = {temp:.1f}", True, (255, 255, 0))
        guide1 = small.render("↑ / → : 上げる      ↓ / ← : 下げる", True, (200, 200, 200))
        guide2 = small.render("Enter : 決定して開始", True, (200, 200, 200))
        guide3 = small.render("0 = 最尤(規則的)   大きいほど揺らぎ(ランダム寄り)", True, (150, 150, 150))
        screen.blit(title_text, (SCREEN_WIDTH // 2 - title_text.get_width() // 2, 150))
        screen.blit(val_text, (SCREEN_WIDTH // 2 - val_text.get_width() // 2, 260))
        screen.blit(guide1, (SCREEN_WIDTH // 2 - guide1.get_width() // 2, 370))
        screen.blit(guide2, (SCREEN_WIDTH // 2 - guide2.get_width() // 2, 410))
        screen.blit(guide3, (SCREEN_WIDTH // 2 - guide3.get_width() // 2, 460))
        pygame.display.flip()

    return temp


def show_loading_screen(message="譜面を生成中..."):
    """譜面生成(GRU推論)中に表示するロード画面。
    生成は同期処理でブロックするため、この1フレームを描画してから生成を呼ぶ。"""
    pygame.init()
    SCREEN_WIDTH = 700
    SCREEN_HEIGHT = 600
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
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
    midi_out = pygame.midi.Output(0)
    


    while True:
        # 曲選択
        global selected_song,gamemode,game,game_p2
        title()
        selected_song = select_song()
        print(f"Selected song: {selected_song}")
        # 選択されたMIDIファイルを読み込む
        midi_file = mido.MidiFile(selected_song)
        
        gamemode=select_gamemode()
        print(f"gamemode: {gamemode}")
        if gamemode==0:
            game=select_game()
            difficulty = select_solo_difficulty()
            print(f"difficulty:{difficulty}")
        elif gamemode==1:
            game=select_game_p1()
            difficulty=select_p1_difficulty()
            print(f"difficulty:{difficulty}")
            game_p2=select_game_p2()
            difficulty_p2=select_p2_difficulty()
            print(f"difficulty:{difficulty_p2}")

        # プロセカ風モード(レーンをGRUで生成)を選んだときだけ、生成の揺らぎを調整する
        temperature = 1.0
        if game == 1 or (gamemode == 1 and game_p2 == 1):
            temperature = select_temperature(1.0)
            print(f"temperature: {temperature}")

        # テンポを取得（デフォルトは500000マイクロ秒/四分音符）
        

        # テンポ変化のチェック
        tempo_changes = []
        for track in midi_file.tracks:
            for msg in track:
                if msg.type == 'set_tempo':
                    tempo_changes.append(msg.tempo)

        # テンポが複数回変更される場合
        if len(tempo_changes) > 1:
            print("BPMの変化があるため非対応です")
            exit()

        # MIDIファイルからNote Onイベントを抽出し、対応する楽器情報を保持
        note_on_events = []
        current_instrument = 0  # デフォルトの楽器
        instrument_columns = {}  # 楽器と列の対応を保存する辞書
        next_column = 0  # 次に割り当てる列
        for track in midi_file.tracks:
            time_accumulated = 0
            for msg in track:
                    time_accumulated += msg.time
                    if msg.type == 'program_change':
                        current_instrument = msg.program
                    if not msg.is_meta and msg.type == 'note_on' and msg.velocity > 0:
                        if current_instrument not in instrument_columns:
                            if next_column < 2: # 制限する楽器の数
                                instrument_columns[current_instrument] = next_column
                                next_column += 1
                            else:
                                continue  # n番目以降の楽器は無視する
                        note_on_events.append((time_accumulated, msg.note, current_instrument))

        # テンポ情報があれば更新
        if tempo_changes:
            tempo = tempo_changes[0]

            # タイミングを秒に変換する関数
        def midi_time_to_seconds(midi_time, tempo, ticks_per_beat):
            return midi_time * tempo / (ticks_per_beat * 1e6)

        # MIDIファイルの各ノートの時間を秒単位に変換
        ticks_per_beat = midi_file.ticks_per_beat
        note_on_seconds = [(midi_time_to_seconds(time, tempo, ticks_per_beat), note, instrument) for time, note, instrument in note_on_events]

            # 音階の平均を計算
        all_notes = [note for _, note, _ in note_on_seconds]
        average_note = np.mean(all_notes)

            # 平均以上の音階のみをフィルタリング
        note_on_seconds = [(time, note, instrument) for time, note, instrument in note_on_seconds if note >= average_note]

        # Pygameの初期化
        pygame.init()
        pygame.midi.quit()  # 以前のMIDIデバイスを終了
        pygame.midi.init()

        
        # MIDI出力の設定
        midi_out = pygame.midi.Output(1)
        

        def generate_notes(difficulty, note_on_seconds):
            if difficulty == 'Easy':
                NOTE_RATE = 0  # Easyの速度
                time_range=0.5
            elif difficulty == 'Normal':
                NOTE_RATE = 0  # Normalの速度
                time_range=0.15
            else:
                NOTE_RATE = 0  # Hardの速度
                time_range=0.1

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
            return notes, total_notes
        
        def generate_notes_taiko(difficulty, note_on_seconds):
            if difficulty == 'Easy':
                time_range = 0.5  # Easyの速度
            elif difficulty == 'Normal':
                time_range = 0.15  # Normalの速度
            else:
                time_range = 0.1  # Hardの速度
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
        
        if gamemode==0:
            mode=select_mode()
            if(game==1):
                show_loading_screen()   # GRU推論でブロックするため先にロード画面を出す
                notes,total_notes=generate_notes(difficulty,note_on_seconds)
            else:
                notes,total_notes=generate_notes_taiko(difficulty, note_on_seconds)
            run_sologame()
        elif gamemode==1:
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
            battle=select_battle()
            run_battlegame()
          
main()