"""
app.py — 英文測驗網頁（Streamlit）

環境需求：
    pip install streamlit

使用方式：
    streamlit run app.py
"""
"""
app.py — 英文測驗網頁（Streamlit）

環境需求：
    pip install streamlit

使用方式：
    streamlit run app.py
"""

import streamlit as st
import json
import os
import random
import time
from datetime import datetime, timedelta

# =========================
# 設定
# =========================

DB_DIR       = "db"
RECORD_FILE  = os.path.join(DB_DIR, "records.json")
TIME_LIMIT   = 30
STREAK_BONUS = 5

FILES = {
    "國小": "element.json",
    "國中": "junior.json",
    "高中": "high.json",
    "練習": "practice.json",
}

os.makedirs(DB_DIR, exist_ok=True)

# =========================
# JSON 讀寫（os.replace 跨平台 atomic write）
# =========================

def _read_json(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _write_json(path: str, data: list) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)   # 跨平台 atomic write，Windows 相容
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

# =========================
# 儲存成績
# =========================

def save_record(name: str, score: int, difficulty: str) -> str:
    """儲存成績並回傳本次記錄的唯一 id，供排名查詢使用。"""
    import uuid as _uuid
    record_id = str(_uuid.uuid4())
    records   = _read_json(RECORD_FILE)
    records.append({
        "id":         record_id,
        "name":       name,
        "score":      score,
        "difficulty": difficulty,
        "timestamp":  datetime.now().isoformat(),
    })
    _write_json(RECORD_FILE, records)
    return record_id
# =========================
# 題庫驗證（過濾壞題）
# =========================

def validate_questions(qs: list) -> list:
    """過濾格式不合法的題目，確保測驗不因壞題崩潰。"""
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



# =========================
# 排行榜過濾
# =========================

def filter_records(records: list, difficulty: str, period: str) -> list:
    now = datetime.now()
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

# =========================
# 安全重置 session（避免 List 參照污染）
# =========================

def reset_session(keep_name: bool = True) -> None:
    name = st.session_state.get("name", "")
    keys = [
        "step", "score", "streak", "q_index",
        "questions", "start_time",
        "last_correct", "last_answer", "last_points", "last_q",
    ]
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]
    st.session_state.step        = "setup"
    st.session_state.score       = 0
    st.session_state.streak      = 0
    st.session_state.q_index     = 0
    st.session_state.questions   = []   # 全新 List，無參照污染
    st.session_state.start_time  = 0.0
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
.big-title { font-size:2rem; font-weight:800; text-align:center; margin-bottom:.4rem; }
.sub-title { font-size:1rem; text-align:center; color:#888; margin-bottom:1.5rem; }
.score-box { font-size:3rem; font-weight:900; text-align:center; color:#1e88e5; margin:1rem 0; }
.champ-name { font-size:1rem; font-weight:700; color:#1e88e5; }
.champ-score { font-size:.9rem; color:#333; }
.champ-date  { font-size:.75rem; color:#999; }
</style>
""", unsafe_allow_html=True)

# =========================
# ① 登入
# =========================

if st.session_state.step == "login":
    st.markdown('<div class="big-title">🏆 英文測驗挑戰網</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">測試你的英文實力，挑戰榮譽榜！</div>', unsafe_allow_html=True)

    with st.form("login_form"):
        name = st.text_input("請輸入你的名字：", placeholder="例如：小明")
        submitted = st.form_submit_button("進入測驗 →", use_container_width=True)
        if submitted:
            if name.strip():
                st.session_state.name = name.strip()
                st.session_state.step = "setup"
                st.rerun()
            else:
                st.warning("請先輸入名字！")

# =========================
# ② 測驗設定 ＋ 榮譽榜
# =========================

elif st.session_state.step == "setup":
    st.markdown(f'<div class="big-title">👋 哈囉，{st.session_state.name}！</div>',
                unsafe_allow_html=True)

    tab_quiz, tab_board = st.tabs(["🎯 開始測驗", "🏅 榮譽榜"])

    # ── 開始測驗 ──
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
            filepath = os.path.join(DB_DIR, FILES[difficulty])
            all_qs   = validate_questions(_read_json(filepath))
            if len(all_qs) < q_count:
                st.error(
                    f"「{difficulty}」題庫目前只有 {len(all_qs)} 題，"
                    f"請先執行 generate_questions.py 生成題目，或選擇較少題數。"
                )
            else:
                st.session_state.questions   = random.sample(all_qs, q_count)
                st.session_state.difficulty  = difficulty
                st.session_state.score       = 0
                st.session_state.streak      = 0
                st.session_state.q_index     = 0
                st.session_state.last_correct = None
                st.session_state.last_answer  = None
                st.session_state.start_time   = time.time()
                st.session_state.step         = "quiz"
                st.rerun()

    # ── 榮譽榜 ──
    with tab_board:
        records = _read_json(RECORD_FILE)
        if not records:
            st.info("目前尚無成績記錄，完成第一場測驗後即可上榜！")
        else:
            diff_tab = st.selectbox("選擇難度榜", list(FILES.keys()), key="board_diff")
            periods  = ["本日", "本週", "本月", "本季", "本年度"]

            # 冠軍橫排顯示（並排 5 格，有儀式感）
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
                            unsafe_allow_html=True
                        )
                    else:
                        st.markdown("<span style='color:#aaa'>虛位以待</span>",
                                    unsafe_allow_html=True)

            st.markdown("---")

            # 前 10 名
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
                        f"<span style='color:#aaa;font-size:.82rem'> ／ {r['difficulty']} ／ {r['timestamp'][:10]}</span>",
                        unsafe_allow_html=True
                    )

# =========================
# ③ 答題中
# =========================

elif st.session_state.step == "quiz":
    q_idx   = st.session_state.q_index
    total_q = len(st.session_state.questions)

    if q_idx < total_q:
        current_q = st.session_state.questions[q_idx]

        # 進度列
        st.progress(q_idx / total_q)
        col_l, col_m, col_r = st.columns([2, 2, 2])
        col_l.markdown(f"**第 {q_idx+1} 題 / 共 {total_q} 題**")
        col_m.markdown(f"🔥 連勝：**{st.session_state.streak}**")
        col_r.markdown(f"⭐ 分數：**{st.session_state.score}**")

        # 剩餘時間（靜態顯示，以提交時實際時間計算）
        elapsed   = time.time() - st.session_state.start_time
        time_left = max(0, TIME_LIMIT - int(elapsed))
        color     = "success" if time_left > 20 else "warning" if time_left > 10 else "error"
        getattr(st, color)(
            f"⏱ 剩餘時間約：{time_left} 秒（分數以提交時的實際時間計算）"
        )

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
                        # 超時：強制答錯，斷連勝，0 分
                        correct = False
                        st.session_state.streak = 0
                        points  = 0
                    else:
                        correct = (user_ans == current_q["answer"])
                        if correct:
                            st.session_state.streak += 1
                            points = time_left + st.session_state.streak * STREAK_BONUS
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
        rid = save_record(
            st.session_state.name,
            st.session_state.score,
            st.session_state.difficulty,
        )
        st.session_state.record_id = rid
        st.session_state.step = "result"
        st.rerun()

# =========================
# ③-b 顯示解答
# =========================

elif st.session_state.step == "show_result":
    current_q = st.session_state.last_q
    correct   = st.session_state.last_correct
    points    = st.session_state.last_points
    q_idx     = st.session_state.q_index
    total_q   = len(st.session_state.questions)

    st.progress((q_idx + 1) / total_q)

    is_timeout = st.session_state.get("last_timeout", False)

    if is_timeout:
        st.error(f"⏰ 超時！正確答案是：**{current_q['answer']}**（超過 {TIME_LIMIT} 秒，本題 0 分）")
    elif correct:
        st.success(
            f"✅ 答對了！本題獲得 **{points} 分**"
            f"（連勝 {st.session_state.streak} 回合）"
        )
    else:
        st.error(f"❌ 答錯了！正確答案是：**{current_q['answer']}**")

    st.markdown("---")
    st.markdown(f"### {current_q['question']}")
    for opt in current_q["options"]:
        if opt == current_q["answer"]:
            st.markdown(f"✅ &nbsp; **{opt}**　←　正確答案", unsafe_allow_html=True)
        elif opt == st.session_state.last_answer and not correct:
            st.markdown(f"❌ &nbsp; ~~{opt}~~　←　你的答案", unsafe_allow_html=True)
        else:
            st.markdown(f"　　{opt}")

    st.info(f"📖 **解析：** {current_q['explanation']}")

    col1, col2 = st.columns(2)
    col1.metric("本題得分", f"+{points}")
    col2.metric("累計分數", st.session_state.score)

    st.markdown("---")
    is_last   = (q_idx + 1 >= total_q)
    btn_label = "查看結果 🎉" if is_last else "下一題 ➡️"

    if st.button(btn_label, use_container_width=True, type="primary"):
        st.session_state.q_index    += 1
        st.session_state.start_time  = time.time()   # 下一題才重置計時
        st.session_state.step        = "quiz"
        st.rerun()

# =========================
# ④ 最終結果
# =========================

elif st.session_state.step == "result":
    st.balloons()
    st.markdown('<div class="big-title">🎉 測驗結束！</div>', unsafe_allow_html=True)
    st.markdown(
        f"<div style='text-align:center;color:#666'>"
        f"玩家：{st.session_state.name}　｜　"
        f"難度：{st.session_state.difficulty}　｜　"
        f"題數：{len(st.session_state.questions)}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="score-box">{st.session_state.score} 分</div>',
                unsafe_allow_html=True)

    # 查詢排名
    records  = _read_json(RECORD_FILE)
    top_year = filter_records(records, st.session_state.difficulty, "本年度")
    record_id = st.session_state.get("record_id")
    rank      = next(
        (i + 1 for i, r in enumerate(top_year)
         if r.get("id") == record_id),
        None,
    )
    if rank:
        if rank == 1:
            st.success(f"🥇 恭喜！你是「{st.session_state.difficulty}」本年度第 1 名！")
        elif rank <= 3:
            st.success(f"🏅 太棒了！你在「{st.session_state.difficulty}」本年度榜單排名第 **{rank}** 名！")
        else:
            st.info(f"📊 你在「{st.session_state.difficulty}」本年度榜單排名第 **{rank}** 名，繼續加油！")

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
