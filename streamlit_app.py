"""
app.py — 英文測驗網頁（Streamlit Cloud + Firebase Realtime Database）

部署設定（Streamlit Cloud Secrets）：
    [firebase]
    type = "service_account"
    project_id = "your-project-id"
    private_key_id = "xxxx"
    private_key = "-----BEGIN PRIVATE KEY-----\\nxxxx\\n-----END PRIVATE KEY-----\\n"
    client_email = "firebase-adminsdk-xxxx@your-project.iam.gserviceaccount.com"
    client_id = "xxxx"
    auth_uri = "https://accounts.google.com/o/oauth2/auth"
    token_uri = "https://oauth2.googleapis.com/token"
    database_url = "https://your-project-default-rtdb.firebaseio.com"

    [github]
    token  = "ghp_xxxxxxxxxxxx"
    repo   = "colinchuTaiwan/english-examine"
    branch = "main"

requirements.txt：
    streamlit
    firebase-admin
    requests
"""


import streamlit as st
import json
import os
import random
import time
import base64
import requests
import uuid
from datetime import datetime, timedelta

# =========================
# Firebase 初始化
# =========================

import firebase_admin
from firebase_admin import credentials, db as firebase_db

@st.cache_resource
def init_firebase():
    """初始化 Firebase（整個 app 只做一次）。"""
    if firebase_admin._apps:
        return firebase_admin.get_app()

    s = st.secrets["firebase"]

    cert_dict = {
        "type":                         s["type"],
        "project_id":                  s["project_id"],
        "private_key_id":              s["private_key_id"],
        "private_key":                 s["private_key"].replace("\n", "\n").replace("\\n", "\n"),
        "client_email":                s["client_email"],
        "client_id":                   s["client_id"],
        "auth_uri":                    s["auth_uri"],
        "token_uri":                   s["token_uri"],
        "client_x509_cert_url":        s.get("client_x509_cert_url", ""),
        "auth_provider_x509_cert_url": s.get("auth_provider_x509_cert_url", ""),
    }
    database_url = s["database_url"]

    cred = credentials.Certificate(cert_dict)
    return firebase_admin.initialize_app(cred, {"databaseURL": database_url})

# =========================
# 訪客計數器與意見表單功能
# =========================

def track_visitor(site_id: str) -> int:
    """
    依據網站識別碼 (site_id) 進行獨立計數。
    使用 Firebase Transaction 確保多人同時操作時數據準確。
    """
    init_firebase()
    counter_ref = firebase_db.reference(f"visitor_counts/{site_id}")
    
    def increment_transaction(current_value):
        return (current_value or 0) + 1

    try:
        # 僅在 session 中尚未計數過時才增加，避免重新整理頁面重複計算
        if "counted" not in st.session_state:
            snapshot = counter_ref.transaction(increment_transaction)
            st.session_state["counted"] = True
            return snapshot
        else:
            current = counter_ref.get()
            return current if current is not None else 0
    except Exception:
        return 0

def show_feedback_qrcode():
    """顯示意見表單的 QR Code（僅保留圖片與說明，移除按鈕）"""
    st.markdown("---")
    st.markdown("### 📣 歡迎填寫意見表單")
    col_qr, col_txt = st.columns([1, 2])
    with col_qr:
        # 請確保將上傳的 QR Code 圖片命名為 '意見表單QRCode.png' 並放在與 app.py 同個資料夾下
        if os.path.exists("意見表單QRCode.png"):
            st.image("意見表單QRCode.png", width=140)
        else:
            st.caption("📷 QR Code 圖片未讀取")
    with col_txt:
        st.write("掃描左側 QR Code，協助我們把測驗做得更好！")

# =========================
# 設定
# =========================

TIME_LIMIT   = 30
STREAK_BONUS = 5
SITE_ID      = "site_english_examine"  # 本網站的獨立識別碼

FILES = {
    "國小": "db/element.json",
    "國中": "db/junior.json",
    "高中": "db/high.json",
    "練習": "db/practice.json",
}

# 觸發計數器更新
visitor_count = track_visitor(SITE_ID)

# =========================
# GitHub 讀取題庫
# =========================

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/colinchuTaiwan/english-examine/main"

@st.cache_data(ttl=300)
def load_questions_cached(filepath: str) -> list:
    url  = f"{GITHUB_RAW_BASE}/{filepath}"
    resp = requests.get(url, timeout=10)
    if not resp.ok:
        st.warning(f"⚠️ 讀取題庫失敗（{resp.status_code}）：{url}")
        return []
    try:
        return resp.json()
    except Exception:
        return []

# =========================
# 題庫驗證與 Firebase 成績讀寫
# =========================

def validate_questions(qs: list) -> list:
    valid = []
    for q in qs:
        if not isinstance(q, dict):
            continue
        question    = q.get("question",    "")
        options     = q.get("options",     [])
        answer      = q.get("answer",      "")
        explanation = q.get("explanation", "")
        if (
            isinstance(question, str)    and question.strip()    and
            isinstance(explanation, str) and explanation.strip() and
            isinstance(options, list)    and len(options) == 4   and
            all(isinstance(o, str) and o.strip() for o in options) and
            len(set(options)) == 4 and
            answer in options
        ):
            valid.append(q)
    return valid

def save_record(name: str, score: int, difficulty: str) -> str:
    init_firebase()
    record_id = str(uuid.uuid4())
    firebase_db.reference("records_english").push({
        "id":         record_id,
        "name":       name,
        "score":      score,
        "difficulty": difficulty,
        "timestamp":  datetime.now().isoformat(),
    })
    load_records_cached.clear()
    return record_id

@st.cache_data(ttl=30)
def load_records_cached() -> list:
    init_firebase()
    data = firebase_db.reference("records_english").get()
    if not data:
        return []
    return list(data.values())

def filter_records(records: list, difficulty: str, period: str) -> list:
    now    = datetime.now()
    cutoff = {
        "本年度": now - timedelta(days=365),
        "本季":   now - timedelta(days=91),
        "本月":   now - timedelta(days=30),
        "本週":   now - timedelta(weeks=1),
        "本日":   now - timedelta(days=1),
    }.get(period)

    result = [r for r in records if r.get("difficulty") == difficulty]
    if cutoff:
        result = [
            r for r in result
            if datetime.fromisoformat(r["timestamp"]) >= cutoff
        ]
    return sorted(
        result,
        key=lambda x: (-x.get("score", 0), x.get("timestamp", "")),
    )

def reset_session(keep_name: bool = True) -> None:
    name = st.session_state.get("name", "")
    for k in ["step", "score", "streak", "q_index", "questions", "start_time",
              "last_correct", "last_answer", "last_points", "last_q",
              "record_id", "last_timeout"]:
        st.session_state.pop(k, None)
    st.session_state.step         = "setup"
    st.session_state.score        = 0
    st.session_state.streak       = 0
    st.session_state.q_index      = 0
    st.session_state.questions    = []
    st.session_state.start_time   = 0.0
    st.session_state.last_correct = None
    st.session_state.last_answer  = None
    st.session_state.last_points  = 0
    st.session_state.record_id    = None
    st.session_state.last_timeout = False
    if keep_name:
        st.session_state.name = name

# =========================
# Session State 初始化
# =========================

if "step" not in st.session_state:
    st.session_state.step         = "login"
    st.session_state.name         = ""
    st.session_state.difficulty   = "國中"
    st.session_state.score        = 0
    st.session_state.streak       = 0
    st.session_state.q_index      = 0
    st.session_state.questions    = []
    st.session_state.start_time   = 0.0
    st.session_state.last_correct = None
    st.session_state.last_answer  = None
    st.session_state.last_points  = 0
    st.session_state.record_id    = None
    st.session_state.last_timeout = False

# =========================
# 頁面設定
# =========================

st.set_page_config(
    page_title="英文測驗挑戰網",
    page_icon="🏆",
    layout="centered",
)

st.markdown("""
<style>
.big-title  { font-size:2rem; font-weight:800; text-align:center; margin-bottom:.4rem; }
.sub-title  { font-size:1rem; text-align:center; color:#888; margin-bottom:1.5rem; }
.score-box  { font-size:3rem; font-weight:900; text-align:center; color:#1e88e5; margin:1rem 0; }
.champ-name { font-size:1rem; font-weight:700; color:#1e88e5; }
.champ-score{ font-size:.9rem; color:#333; }
.champ-date { font-size:.75rem; color:#999; }
.visitor-badge { text-align:center; color:#666; font-size:0.85rem; margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)

# =========================
# ① 登入頁面
# =========================

if st.session_state.step == "login":
    st.markdown('<div class="big-title">🏆 英文測驗挑戰網</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">測試你的英文實力，挑戰榮譽榜！</div>', unsafe_allow_html=True)
    
    # 顯示獨立網站訪客計數
    st.markdown(f'<div class="visitor-badge">總瀏覽人次：{visitor_count} 次</div>', unsafe_allow_html=True)

    with st.form("login_form"):
        name      = st.text_input("請輸入你的名字：", placeholder="例如：小明")
        submitted = st.form_submit_button("進入測驗 →", use_container_width=True)
        if submitted:
            if name.strip():
                st.session_state.name = name.strip()
                st.session_state.step = "setup"
                st.rerun()
            else:
                st.warning("請先輸入名字！")
                
    # 顯示表單 QRCode
    show_feedback_qrcode()

# =========================
# ② 測驗設定 ＋ 榮譽榜
# =========================

elif st.session_state.step == "setup":
    st.markdown(f'<div class="big-title">👋 哈囉，{st.session_state.name}！</div>', unsafe_allow_html=True)

    tab_quiz, tab_board = st.tabs(["🎯 開始測驗", "🏅 榮譽榜"])

    with tab_quiz:
        col1, col2 = st.columns(2)
        with col1:
            difficulty = st.selectbox("選擇難度", list(FILES.keys()), index=1)
        with col2:
            q_count = st.selectbox("選擇題數", [5, 10, 20], index=1)

        st.info(
            f"📖 每題限時 **{TIME_LIMIT} 秒**，分數 = 剩餘秒數，連續答對額外 +{STREAK_BONUS} 分\n\n"
            f"⚠️ 畫面上的秒數不會動態跳動，分數以按下「提交答案」時的實際經過時間計算。"
        )

        if st.button("🚀 開始測驗！", use_container_width=True, type="primary"):
            with st.spinner("載入題庫中..."):
                raw_qs = load_questions_cached(FILES[difficulty])
                all_qs = validate_questions(raw_qs)

            if len(all_qs) < q_count:
                st.error(f"「{difficulty}」題庫目前只有 {len(all_qs)} 題，請確認題庫完整度。")
            else:
                st.session_state.questions    = random.sample(all_qs, q_count)
                st.session_state.difficulty   = difficulty
                st.session_state.score        = 0
                st.session_state.streak       = 0
                st.session_state.q_index      = 0
                st.session_state.last_correct = None
                st.session_state.last_answer  = None
                st.session_state.start_time   = time.time()
                st.session_state.step         = "quiz"
                st.rerun()

    with tab_board:
        with st.spinner("載入榜單..."):
            records = load_records_cached()

        if not records:
            st.info("目前尚無成績記錄，完成第一場測驗後即可上榜！")
        else:
            diff_tab = st.selectbox("選擇難度榜", list(FILES.keys()), key="board_diff")
            periods  = ["本日", "本週", "本月", "本季", "本年度"]

            st.markdown("#### 🥇 各時段冠軍")
            cols = st.columns(len(periods))
            for idx, period in enumerate(periods):
                filtered = filter_records(records, diff_tab, period)
                champ    = filtered[0] if filtered else None
                with cols[idx]:
                    st.markdown(f"**{period}**")
                    if champ:
                        st.markdown(
                            f"<div class='champ-name'>{champ['name']}</div>"
                            f"<div class='champ-score'>{champ['score']} 分</div>"
                            f"<div class='champ-date'>{champ['timestamp'][:10]}</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown("<span style='color:#aaa'>虛位以待</span>", unsafe_allow_html=True)

            st.markdown("---")
            st.markdown(f"#### 📋 {diff_tab} 前 10 名（本年度）")
            top10 = filter_records(records, diff_tab, "本年度")[:10]
            if not top10:
                st.info("尚無記錄")
            else:
                medals = ["🥇", "🥈", "🥉"]
                for i, r in enumerate(top10):
                    medal = medals[i] if i < 3 else f"**#{i+1}**"
                    st.markdown(
                        f"{medal} &nbsp; **{r['name']}** &nbsp; "
                        f"<span style='color:#1e88e5;font-weight:700'>{r['score']} 分</span>"
                        f"<span style='color:#aaa;font-size:.82rem'>"
                        f" ／ {r['difficulty']} ／ {r['timestamp'][:10]}</span>",
                        unsafe_allow_html=True,
                    )

# =========================
# ③ 答題中
# =========================

elif st.session_state.step == "quiz":
    q_idx   = st.session_state.q_index
    total_q = len(st.session_state.questions)

    if q_idx < total_q:
        current_q = st.session_state.questions[q_idx]

        st.progress(q_idx / total_q)
        col_l, col_m, col_r = st.columns([2, 2, 2])
        col_l.markdown(f"**第 {q_idx+1} 題 / 共 {total_q} 題**")
        col_m.markdown(f"🔥 連勝：**{st.session_state.streak}**")
        col_r.markdown(f"⭐ 分數：**{st.session_state.score}**")

        elapsed   = time.time() - st.session_state.start_time
        time_left = max(0, TIME_LIMIT - int(elapsed))
        color     = "success" if time_left > 20 else "warning" if time_left > 10 else "error"
        getattr(st, color)(f"⏱ 剩餘時間約：{time_left} 秒（分數以提交時的實際時間計算）")

        st.markdown("---")
        st.markdown(f"### {current_q['question']}")

        with st.form(key=f"quiz_form_{q_idx}"):
            user_ans  = st.radio("請選擇答案：", current_q["options"], index=None)
            submitted = st.form_submit_button("✅ 提交答案", use_container_width=True)

            if submitted:
                if user_ans is None:
                    st.warning("請先選擇一個選項！")
                else:
                    elapsed    = time.time() - st.session_state.start_time
                    time_left  = max(0, TIME_LIMIT - int(elapsed))
                    is_timeout = elapsed > TIME_LIMIT

                    if is_timeout:
                        correct = False
                        st.session_state.streak = 0
                        points  = 0
                    else:
                        correct = (user_ans == current_q["answer"])
                        if correct:
                            st.session_state.streak += 1
                            points = time_left + (st.session_state.streak-1) * STREAK_BONUS
                        else:
                            st.session_state.streak = 0
                            points = 0

                    st.session_state.score        += points
                    st.session_state.last_correct  = correct
                    st.session_state.last_answer   = user_ans
                    st.session_state.last_points   = points
                    st.session_state.last_q        = current_q
                    st.session_state.last_timeout  = is_timeout
                    st.session_state.step          = "show_result"
                    st.rerun()
    else:
        with st.spinner("儲存成績中..."):
            rid = save_record(
                st.session_state.name,
                st.session_state.score,
                st.session_state.difficulty,
            )
        st.session_state.record_id = rid
        st.session_state.step      = "result"
        st.rerun()

# =========================
# ③-b 顯示單題解答
# =========================

elif st.session_state.step == "show_result":
    current_q  = st.session_state.last_q
    correct    = st.session_state.last_correct
    points     = st.session_state.last_points
    q_idx      = st.session_state.q_index
    total_q    = len(st.session_state.questions)
    is_timeout = st.session_state.get("last_timeout", False)

    st.progress((q_idx + 1) / total_q)

    if is_timeout:
        st.error(f"⏰ 超時！正確答案是：**{current_q['answer']}**（超過 {TIME_LIMIT} 秒，本題 0 分）")
    elif correct:
        st.success(f"✅ 答對了！本題獲得 **{points} 分**（連勝 {st.session_state.streak} 回合）")
    else:
        st.error(f"❌ 答錯了！正確答案是：**{current_q['answer']}**")

    st.markdown("---")
    st.markdown(f"### {current_q['question']}")
    for opt in current_q["options"]:
        if opt == current_q["answer"]:
            st.markdown(f"✅ &nbsp; **{opt}** ← 正確答案", unsafe_allow_html=True)
        elif opt == st.session_state.last_answer and not correct:
            st.markdown(f"❌ &nbsp; ~~{opt}~~ ← 你的答案", unsafe_allow_html=True)
        else:
            st.markdown(f"  {opt}")

    st.info(f"📖 **解析：** {current_q['explanation']}")

    col1, col2 = st.columns(2)
    col1.metric("本題得分", f"+{points}")
    col2.metric("累計分數", st.session_state.score)

    st.markdown("---")
    is_last   = (q_idx + 1 >= total_q)
    btn_label = "查看結果 🎉" if is_last else "下一題 ➡️"

    if st.button(btn_label, use_container_width=True, type="primary"):
        st.session_state.q_index    += 1
        st.session_state.start_time  = time.time()
        st.session_state.step        = "quiz"
        st.rerun()

# =========================
# ④ 最終成績結果頁
# =========================

elif st.session_state.step == "result":
    st.balloons()
    st.markdown('<div class="big-title">🎉 測驗結束！</div>', unsafe_allow_html=True)
    st.markdown(
        f"<div style='text-align:center;color:#666'>"
        f"玩家：{st.session_state.name} ｜ "
        f"難度：{st.session_state.difficulty} ｜ "
        f"題數：{len(st.session_state.questions)}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="score-box">{st.session_state.score} 分</div>', unsafe_allow_html=True)

    with st.spinner("查詢排名中..."):
        records   = load_records_cached()
        top_year  = filter_records(records, st.session_state.difficulty, "本年度")
        record_id = st.session_state.get("record_id")
        rank      = next(
            (i + 1 for i, r in enumerate(top_year) if r.get("id") == record_id),
            None,
        )

    if rank:
        if rank == 1:
            st.success(f"🥇 恭喜！你是「{st.session_state.difficulty}」本年度第 1 名！")
        elif rank <= 3:
            st.success(f"🏅 太棒了！本年度排名第 **{rank}** 名！")
        else:
            st.info(f"📊 本年度排名第 **{rank}** 名，繼續加油！")

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 再挑戰一次", use_container_width=True, type="primary"):
            reset_session(keep_name=True)
            st.rerun()
    with col2:
        if st.button("🏅 查看榮譽榜", use_container_width=True):
            reset_session(keep_name=True)
            st.rerun()
            
    # 結束測驗頁面也顯示表單 QRCode 邀請填寫
    show_feedback_qrcode()