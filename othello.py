"""
Othello (Reversi) - Streamlit Çok Oyunculu
Adım 3: st_autorefresh ile otomatik ekran yenileme eklendi
"""

import streamlit as st
import copy
import threading
import uuid
from streamlit_autorefresh import st_autorefresh

# Her kaç milisaniyede bir ekran yenilensin (2000ms = 2 saniye)
REFRESH_INTERVAL_MS = 2000

SIZE = 8

# Oyuncu isimleri — 1 = Isik (⚫), 2 = Jenna (⚪)
PLAYER_NAME = {1: "Isik", 2: "Jenna"}
PLAYER_SYM  = {1: "⚫",   2: "⚪"}

# ---------------------------------------------------------------------------
# Oyun Mantığı — Pure fonksiyonlar, hiç değişmedi
# ---------------------------------------------------------------------------

def initialize_board():
    """Başlangıç tahtasını oluşturur (4 merkez taş)."""
    board = [[0] * SIZE for _ in range(SIZE)]
    mid = SIZE // 2
    board[mid - 1][mid - 1] = 1
    board[mid][mid - 1]     = 2
    board[mid - 1][mid]     = 2
    board[mid][mid]         = 1
    return board


def is_on_board(x: int, y: int) -> bool:
    return 0 <= x < SIZE and 0 <= y < SIZE


def is_valid_move(board: list, player: int, x: int, y: int) -> bool:
    opponent = 3 - player
    if board[y][x] != 0:
        return False
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if not is_on_board(nx, ny) or board[ny][nx] != opponent:
                continue
            while is_on_board(nx, ny) and board[ny][nx] == opponent:
                nx += dx
                ny += dy
            if is_on_board(nx, ny) and board[ny][nx] == player:
                return True
    return False


def execute_move(board: list, player: int, x: int, y: int) -> list:
    new_board = copy.deepcopy(board)
    opponent = 3 - player
    new_board[y][x] = player
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if not is_on_board(nx, ny) or new_board[ny][nx] != opponent:
                continue
            count = 0
            tx, ty = nx, ny
            while is_on_board(tx, ty) and new_board[ty][tx] == opponent:
                tx += dx
                ty += dy
                count += 1
            if not is_on_board(tx, ty) or new_board[ty][tx] != player:
                continue
            tx, ty = nx, ny
            for _ in range(count):
                new_board[ty][tx] = player
                tx += dx
                ty += dy
    return new_board


def get_valid_moves(board: list, player: int) -> list:
    return [
        (x, y)
        for y in range(SIZE)
        for x in range(SIZE)
        if is_valid_move(board, player, x, y)
    ]


def count_pieces(board: list) -> tuple:
    p1 = sum(row.count(1) for row in board)
    p2 = sum(row.count(2) for row in board)
    return p1, p2


def get_winner(board: list) -> int:
    p1, p2 = count_pieces(board)
    if p1 == p2:
        return 0
    return 1 if p1 > p2 else 2


# ---------------------------------------------------------------------------
# Paylaşılan Global Durum — @st.cache_resource
# ---------------------------------------------------------------------------
# cache_resource: sunucu yeniden başlatılana kadar bellekte tek kopya olarak
# yaşar. Farklı tarayıcılardan bağlanan tüm session'lar AYNI nesneyi görür.
# Bu sayede iki oyuncunun tahtası gerçek anlamda paylaşılmış olur.

@st.cache_resource
def get_game() -> dict:
    """
    Paylaşılan oyun durumu.
    board          : 8×8 liste  (0=boş, 1=Siyah, 2=Beyaz)
    current_player : sıradaki oyuncu (1 veya 2)
    game_over      : oyun bitti mi?
    log            : ekranda gösterilecek son mesajlar
    """
    return {
        "board":          initialize_board(),
        "current_player": 1,
        "game_over":      False,
        "log":            [],
    }


@st.cache_resource
def get_registry() -> dict:
    """
    session_id → oyuncu numarası (1 veya 2) eşlemesi.
    Oyun sıfırlandığında bu dict temizlenir, böylece
    her iki oyuncu da yeniden atanabilir.
    """
    return {}


@st.cache_resource
def get_lock() -> threading.Lock:
    """
    Race condition (eşzamanlı yazma yarışı) önlemi.
    İki oyuncunun aynı anda game dict'ini değiştirmesini engeller.
    """
    return threading.Lock()


# ---------------------------------------------------------------------------
# Yardımcı Fonksiyonlar
# ---------------------------------------------------------------------------

def assign_player(session_id: str, registry: dict, lock: threading.Lock):
    """
    Bu session'a oyuncu numarası atar ve döner.
    - Zaten kayıtlıysa mevcut numarayı döner (sayfa yenilemesi güvenli).
    - Boş slot varsa (önce 1, sonra 2) o slotu atar.
    - Her iki slot da doluysa None döner (izleyici modu).
    Lock ile korunur: iki session aynı anda aynı numarayı alamaz.
    """
    with lock:
        if session_id in registry:
            return registry[session_id]          # Zaten kayıtlı
        taken = set(registry.values())
        for p in [1, 2]:
            if p not in taken:
                registry[session_id] = p
                return p
        return None                              # Oyun dolu


def make_move(game: dict, lock: threading.Lock, player: int, x: int, y: int):
    """
    Hamleyi atomik olarak uygular (tüm adımlar tek lock altında):
      1. Sıra kontrolü (çift tıklama / gecikmiş istek önlemi)
      2. Tahtayı güncelle
      3. Pas / oyun-bitti durumlarını kontrol et
      4. Sırayı bir sonraki oyuncuya ver

    Bu fonksiyon dışında game dict'ine yazılmaz; tüm state değişikliği
    burada merkezi olarak yönetilir.
    """
    with lock:
        # Güvenlik: sıra hâlâ bu oyuncuda mı? (ağ gecikmesi / double-click önlemi)
        if game["current_player"] != player or game["game_over"]:
            return

        new_board  = execute_move(game["board"], player, x, y)
        game["board"] = new_board
        game["log"] = [
            f"{PLAYER_NAME[player]} {PLAYER_SYM[player]} → {chr(x + 65)}{y + 1}"
        ]

        next_player = 3 - player

        if not get_valid_moves(new_board, next_player):
            if not get_valid_moves(new_board, player):
                game["game_over"] = True
                game["log"].append("Spiel beendet!")
            else:
                game["log"].append(
                    f"{PLAYER_NAME[next_player]} {PLAYER_SYM[next_player]} "
                    f"muss aussetzen — kein Zug möglich!"
                )
                next_player = player

        game["current_player"] = next_player


def reset_game(game: dict, registry: dict, lock: threading.Lock):
    """
    Oyunu sıfırlar ve oyuncu atamalarını temizler.
    Sonraki rerun'da her iki session da yeniden atanır.
    """
    with lock:
        game["board"]          = initialize_board()
        game["current_player"] = 1
        game["game_over"]      = False
        game["log"]            = []
        registry.clear()       # Oyuncuları serbest bırak


# ---------------------------------------------------------------------------
# Streamlit Uygulaması
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Othello", page_icon="⬛", layout="centered")

# ---- CSS — Masaüstü + Mobil Uyumlu ----
st.markdown("""
<style>

/* ── Sütunlar arası gap'i sıfıra yakın tut ──────────────────────────────────
   Varsayılan ~1rem (16px) × 8 boşluk = 128px kayıp → mobilde taşma yapar.
   2px'e çekince 8 × 2px = 16px → tahta 360px ekrana sığar.              */
div[data-testid="stHorizontalBlock"] {
    gap: 2px !important;
}
/* Sütun iç yatay padding'ini kaldır — buton tam ortalansın */
div[data-testid="stColumns"] div[data-testid="column"] {
    padding-left:  0px !important;
    padding-right: 0px !important;
    min-width: 0   !important;   /* flex shrink'e izin ver */
}

/* ── Masaüstü Buton Stili ────────────────────────────────────────────────── */
div[data-testid="stColumns"] div[data-testid="column"] button {
    width:      56px !important;
    height:     56px !important;
    min-width:  56px !important;
    min-height: 56px !important;
    font-size:  26px !important;
    padding: 0 !important;
    margin: 1px auto !important;
    border-radius: 6px !important;
    border: 2px solid #3a7d44 !important;
    background-color: #1b5e20 !important;
    line-height: 1 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    /* Mobil dokunma iyileştirmeleri — çift-dokunma zoom'u önler */
    touch-action: manipulation;
    -webkit-tap-highlight-color: transparent;
    user-select: none;
}
div[data-testid="stColumns"] div[data-testid="column"] button:hover:not(:disabled) {
    background-color: #2e7d32 !important;
    border-color: #81c784 !important;
    cursor: pointer !important;
}
div[data-testid="stColumns"] div[data-testid="column"] button:disabled {
    opacity: 1 !important;
    cursor: default !important;
}
.row-label {
    text-align: center;
    font-weight: bold;
    font-size: 15px;
    margin-top: 17px;
    color: #ccc;
}
.col-label {
    text-align: center;
    font-weight: bold;
    font-size: 15px;
    color: #ccc;
    margin-bottom: 4px;
}

/* ── Mobil: yatay taşmayı her koşulda engelle ─────────────────────────── */
body { overflow-x: hidden !important; }

/* ── ≤ 640px: tablet / büyük telefon ──────────────────────────────────── */
@media (max-width: 640px) {
    .block-container {
        padding-left:  0.2rem !important;
        padding-right: 0.2rem !important;
        padding-top:   0.6rem !important;
        overflow-x: hidden !important;
    }
    /* Satır sarmalanmasını engelle — tahta tek satırda kalsın */
    div[data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap !important;
    }
    div[data-testid="stColumns"] div[data-testid="column"] button {
        width:      38px !important;
        height:     38px !important;
        min-width:  38px !important;
        min-height: 38px !important;
        font-size:  20px !important;
        border-radius: 4px !important;
        border-width: 1px !important;
        margin: 0 auto !important;
    }
    .row-label { font-size: 11px !important; margin-top: 10px !important; }
    .col-label { font-size: 11px !important; margin-bottom: 2px !important; }
    h1 { font-size: 1.3rem !important; }
}

/* ── ≤ 430px: standart dikey telefon (iPhone 14, Samsung S23 vb.) ───────
   [0.4]+[1]×8 = 8.4 birim, 430px-4px padding-16px gap = 410px
   Her hücre: 410/8.4 ≈ 48.8px → 36px buton rahatlıkla sığar           */
@media (max-width: 430px) {
    .block-container {
        padding-left:  0.1rem !important;
        padding-right: 0.1rem !important;
    }
    div[data-testid="stColumns"] div[data-testid="column"] button {
        width:      36px !important;
        height:     36px !important;
        min-width:  36px !important;
        min-height: 36px !important;
        font-size:  18px !important;
    }
    .row-label { font-size: 10px !important; margin-top: 9px !important; }
    .col-label { font-size: 10px !important; }
}

/* ── ≤ 380px: küçük / eski telefon (360px ekranlar dahil) ───────────────
   360px - 2px padding - 16px gap = 342px → her hücre: 342/8.4 ≈ 40.7px
   32px buton 40px hücreye sığar ✓                                       */
@media (max-width: 380px) {
    div[data-testid="stColumns"] div[data-testid="column"] button {
        width:      32px !important;
        height:     32px !important;
        min-width:  32px !important;
        min-height: 32px !important;
        font-size:  15px !important;
    }
    .row-label { font-size: 9px !important; margin-top: 7px !important; }
    .col-label { font-size: 9px !important; }
}

</style>
""", unsafe_allow_html=True)

# ---- Session kimliği — URL query param ile kalıcı ----
# st.session_state sayfa yenilenince sıfırlanır; st.query_params ise
# tarayıcının URL çubuğunda (?sid=xxx) yaşadığından yenilemede korunur.
#
# Akış:
#   İlk ziyaret  → URL'de ?sid yok → yeni UUID üret → URL'e yaz + session_state'e kaydet
#   Sayfa yenile → session_state kaybolur ama URL'de ?sid=xxx hâlâ var
#                → URL'den oku → session_state'e geri yükle (eski oyuncu kimliği korunur)
#   Yeni sekme   → URL'de ?sid yok → ayrı UUID → bağımsız oyuncu
if "session_id" not in st.session_state:
    if "sid" in st.query_params:
        # Yenileme: URL'deki mevcut kimliği geri yükle
        st.session_state.session_id = st.query_params["sid"]
    else:
        # İlk ziyaret: yeni UUID oluştur, URL'e ekle
        new_sid = str(uuid.uuid4())
        st.session_state.session_id = new_sid
        st.query_params["sid"] = new_sid  # Tarayıcı URL'ini günceller, rerun tetiklemez

session_id = st.session_state.session_id

# ---- Global nesneleri al ----
game     = get_game()
registry = get_registry()
lock     = get_lock()

# ---- Bu session'ın oyuncu numarasını belirle ----
my_player    = assign_player(session_id, registry, lock)
player_count = len(registry)

# ---- Kenar Çubuğu ----
with st.sidebar:
    st.markdown("## ⚙️ Spielinfo")

    if my_player == 1:
        st.success("Du bist: Isik ⚫")
    elif my_player == 2:
        st.success("Du bist: Jenna ⚪")
    else:
        st.warning("Zuschauer (Spiel voll)")

    st.markdown(f"Verbundene Spieler: **{player_count} / 2**")

    if st.button("🔄 Neues Spiel", use_container_width=True):
        reset_game(game, registry, lock)
        st.rerun()

    st.markdown("---")
    st.markdown("**Legende:**")
    st.markdown("⚫ Isik")
    st.markdown("⚪ Jenna")
    st.markdown("🟢 Möglicher Zug")
    st.markdown("---")
    st.markdown("**Spielregeln:**")
    st.markdown(
        "Setze einen Stein so, dass mindestens eine Reihe "
        "gegnerischer Steine eingeschlossen wird. "
        "Alle eingeschlossenen Steine werden umgedreht. "
        "Wer nach Spielende mehr Steine hat, gewinnt."
    )

# ---------------------------------------------------------------------------
# Bekleme Ekranı — rakip henüz bağlanmadı
# ---------------------------------------------------------------------------

if player_count < 2:
    st.markdown("<h1 style='text-align:center'>⬛⬜ Othello</h1>", unsafe_allow_html=True)

    if my_player is None:
        st.error("⛔ Spiel voll! Zwei Spieler sind bereits verbunden.")
    else:
        st.info(f"✅ Du bist: {PLAYER_NAME[my_player]} {PLAYER_SYM[my_player]}")
        st.warning("⏳ Warte auf Gegner… Schick den Link dieser Seite deinem Freund.")

    # Rakip bağlanana kadar her 2 saniyede bir sayfayı yenile
    st_autorefresh(interval=REFRESH_INTERVAL_MS, limit=None, key="waiting_refresh")

    st.stop()   # Rakip yokken tahtayı çizme

# ---------------------------------------------------------------------------
# Oyun Ekranı — her iki oyuncu da bağlı
# ---------------------------------------------------------------------------

board          = game["board"]
current_player = game["current_player"]
game_over      = game["game_over"]

# ---- Başlık ----
st.markdown("<h1 style='text-align:center'>⬛⬜ Othello</h1>", unsafe_allow_html=True)

# ---- Skor & Durum Satırı ----
p1_count, p2_count = count_pieces(board)
col_l, col_m, col_r = st.columns([2, 3, 2])

with col_l:
    ind = " 🔵" if current_player == 1 and not game_over else ""
    you = " (DU)" if my_player == 1 else ""
    st.metric(f"Isik ⚫{ind}{you}", p1_count)

with col_m:
    if not game_over:
        cp_name = PLAYER_NAME[current_player]
        cp_sym  = PLAYER_SYM[current_player]
        you_str = " **(DU)**" if current_player == my_player else ""
        st.markdown(
            f"<div style='text-align:center;font-size:18px;margin-top:8px'>"
            f"{cp_name} {cp_sym} {you_str}<br><small>ist dran</small></div>",
            unsafe_allow_html=True,
        )
    else:
        w = get_winner(board)
        if w == 0:
            st.markdown(
                "<div style='text-align:center;font-size:20px;margin-top:8px'>"
                "🤝 Unentschieden!</div>",
                unsafe_allow_html=True,
            )
        else:
            # Kazanan kim olursa olsun Isik'in adı gösterilir
            st.markdown(
                "<div style='text-align:center;font-size:20px;margin-top:8px'>"
                "🏆 Isik ⚫ gewinnt!</div>",
                unsafe_allow_html=True,
            )

with col_r:
    ind = " 🔵" if current_player == 2 and not game_over else ""
    you = " (DU)" if my_player == 2 else ""
    st.metric(f"Jenna ⚪{ind}{you}", p2_count)

# ---- Log Mesajları ----
if game["log"]:
    for msg in game["log"]:
        st.info(msg)

st.markdown("<div style='margin: 6px 0'></div>", unsafe_allow_html=True)

# ---- Geçerli Hamleler ----
valid_moves = get_valid_moves(board, current_player) if not game_over else []

# ---- Tahta: Sütun Başlıkları ----
header_cols = st.columns([0.4] + [1] * SIZE)
header_cols[0].markdown("<div class='col-label'> </div>", unsafe_allow_html=True)
for i in range(SIZE):
    header_cols[i + 1].markdown(
        f"<div class='col-label'>{chr(65 + i)}</div>",
        unsafe_allow_html=True,
    )

# ---- Tahta: Satırlar ----
for y in range(SIZE):
    row_cols = st.columns([0.4] + [1] * SIZE)
    row_cols[0].markdown(f"<div class='row-label'>{y + 1}</div>", unsafe_allow_html=True)

    for x in range(SIZE):
        cell  = board[y][x]
        is_valid = (x, y) in valid_moves

        # Yalnızca sıradaki oyuncu VE bu session o oyuncuysa tıklanabilir
        clickable = is_valid and (current_player == my_player) and not game_over

        if cell == 1:
            label = "⚫"
        elif cell == 2:
            label = "⚪"
        elif clickable:
            label = "🟢"
        else:
            label = "  "

        if row_cols[x + 1].button(
            label,
            key=f"cell_{y}_{x}",
            disabled=(not clickable),
        ):
            # Hamleyi atomik şekilde uygula, ardından ekranı yenile
            make_move(game, lock, my_player, x, y)
            st.rerun()

# ---- Bekleme mesajı + otomatik yenileme — karşı oyuncunun sırası ----
if not game_over and current_player != my_player:
    st.markdown(
        "<div style='text-align:center;color:#aaa;margin-top:12px'>"
        "⏳ Warte auf den Zug des Gegners…</div>",
        unsafe_allow_html=True,
    )
    # Rakip hamle yaptığında bu ekran da güncellensin diye her 2s'de yenile.
    # Kendi sıramızdayken çalışmaz — gereksiz yenileme yapılmaz.
    st_autorefresh(interval=REFRESH_INTERVAL_MS, limit=None, key="game_refresh")
