"""Udhari Khata v2 - paise ke len-den aur udhari ka hisab rakhne wala Streamlit app.
Sirf 3 pages: Dashboard, Nayi Entry, Backup / Restore.
"""

import hmac
import sqlite3
from contextlib import closing
from datetime import date
from html import escape
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).with_name("udhari.db")

# +1 = samne wale se aapko milna badha, -1 = kam hua
KINDS = {
    "Maine udhar diya": 1,
    "Mujhe paise wapas mile": -1,
    "Maine udhar liya": -1,
    "Maine paise wapas diye": 1,
}
KIND_ICON = {
    "Maine udhar diya": "📤",
    "Mujhe paise wapas mile": "📥",
    "Maine udhar liya": "🤝",
    "Maine paise wapas diye": "💸",
}

INCOME_SOURCES = [
    "Salary", "Dukaan / Business", "Bonus", "Overtime", "Commission",
    "Kiraya", "Interest", "Gift / Tohfa", "Other",
]

GREEN = "#16a34a"
RED = "#dc2626"
BLUE = "#4f46e5"

P_DASH = "🏠  Dashboard"
P_NEW = "➕  Nayi Entry"
P_BACKUP = "💾  Backup / Restore"
PAGES = [P_DASH, P_NEW, P_BACKUP]

st.set_page_config(page_title="Udhari Khata", page_icon="📒", layout="wide")

CSS = f"""
<style>
.block-container {{ padding-top: 1.6rem; max-width: 1200px; }}
#MainMenu, footer {{ visibility: hidden; }}

.hero {{
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 55%, #db2777 100%);
    color: #fff; border-radius: 22px; padding: 26px 30px; margin-bottom: 18px;
    box-shadow: 0 10px 30px rgba(79,70,229,.28);
}}
.hero h1 {{ margin: 0; font-size: 1.9rem; color: #fff; padding: 0; }}
.hero p {{ margin: 4px 0 0; opacity: .88; font-size: .98rem; }}

.kpi {{
    border-radius: 18px; padding: 18px 20px; border: 1px solid rgba(128,128,128,.18);
    background: rgba(128,128,128,.06); height: 100%;
}}
.kpi .lbl {{ font-size: .85rem; opacity: .75; font-weight: 600; letter-spacing: .02em; }}
.kpi .val {{ font-size: 1.85rem; font-weight: 800; margin-top: 4px; line-height: 1.2; }}
.kpi .sub {{ font-size: .8rem; opacity: .65; margin-top: 2px; }}
.kpi.g {{ border-left: 6px solid {GREEN}; }} .kpi.g .val {{ color: {GREEN}; }}
.kpi.r {{ border-left: 6px solid {RED}; }}   .kpi.r .val {{ color: {RED}; }}
.kpi.b {{ border-left: 6px solid {BLUE}; }}  .kpi.b .val {{ color: {BLUE}; }}

.pcard-top {{ display: flex; align-items: center; gap: 12px; }}
.avatar {{
    width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; color: #fff; font-weight: 800; font-size: 1.1rem; flex: none;
}}
.pname {{ font-weight: 700; font-size: 1.02rem; line-height: 1.2; }}
.pmeta {{ font-size: .78rem; opacity: .6; }}
.pamt {{ font-size: 1.45rem; font-weight: 800; margin: 10px 0 4px; }}
.chip {{
    display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .75rem;
    font-weight: 700;
}}
.chip.g {{ background: rgba(22,163,74,.14); color: {GREEN}; }}
.chip.r {{ background: rgba(220,38,38,.14); color: {RED}; }}
.chip.z {{ background: rgba(128,128,128,.18); opacity: .85; }}

.act {{
    display: flex; justify-content: space-between; align-items: center; gap: 10px;
    padding: 10px 14px; border-radius: 14px; margin-bottom: 8px;
    background: rgba(128,128,128,.06); border: 1px solid rgba(128,128,128,.12);
}}
.act .l {{ font-size: .92rem; font-weight: 600; }}
.act .s {{ font-size: .76rem; opacity: .6; }}
.act .a {{ font-weight: 800; white-space: nowrap; }}
.pos {{ color: {GREEN}; }} .neg {{ color: {RED}; }}

section[data-testid="stSidebar"] .brand {{ font-size: 1.35rem; font-weight: 800; margin-bottom: 4px; }}
div[data-testid="stForm"] {{ border-radius: 18px; }}
.stButton > button, .stDownloadButton > button {{ border-radius: 12px; font-weight: 600; }}
</style>
"""


# ---------------------------------------------------------------- helpers
def inr(x):
    """Indian format: ₹1,23,456 (paise ho to .50 dikhata hai)."""
    sign = "-" if x < 0 else ""
    whole, frac = f"{abs(x):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}" + ("" if frac == "00" else f".{frac}")


AV_COLORS = ["#4f46e5", "#0ea5e9", "#14b8a6", "#f59e0b", "#ec4899", "#8b5cf6", "#ef4444", "#22c55e"]


def avatar(name):
    ch = escape(name.strip()[:1].upper() or "?")
    color = AV_COLORS[sum(map(ord, name)) % len(AV_COLORS)]
    return f'<div class="avatar" style="background:{color}">{ch}</div>'


def status_of(b):
    if b > 0:
        return "g", "Aapko milna hai"
    if b < 0:
        return "r", "Aapko dena hai"
    return "z", "Hisab barabar"


def kpi(label, value, sub, cls):
    return (
        f'<div class="kpi {cls}"><div class="lbl">{label}</div>'
        f'<div class="val">{value}</div><div class="sub">{sub}</div></div>'
    )


def hero(title, subtitle):
    st.markdown(
        f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True
    )


# ---------------------------------------------------------------- database
def run(sql, params=()):
    with closing(sqlite3.connect(DB_PATH)) as c:
        c.execute("PRAGMA foreign_keys = ON")
        cur = c.execute(sql, params)
        c.commit()
        return cur.lastrowid


def query_df(sql, params=()):
    with closing(sqlite3.connect(DB_PATH)) as c:
        return pd.read_sql_query(sql, c, params=params)


def init_db():
    with closing(sqlite3.connect(DB_PATH)) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS parties(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                phone TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS txns(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                party_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
                tdate TEXT NOT NULL,
                kind TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                note TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS income(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idate TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                source TEXT DEFAULT '',
                note TEXT DEFAULT ''
            );
            """
        )
        c.commit()


def get_or_create_party(name, phone=""):
    name, phone = name.strip(), phone.strip()
    row = query_df("SELECT id, phone FROM parties WHERE name = ?", (name,))
    if not row.empty:
        pid = int(row.iloc[0]["id"])
        if phone and not row.iloc[0]["phone"]:
            run("UPDATE parties SET phone = ? WHERE id = ?", (phone, pid))
        return pid
    return run("INSERT INTO parties(name, phone) VALUES (?, ?)", (name, phone))


def parties_df():
    return query_df("SELECT id, name, phone FROM parties ORDER BY name COLLATE NOCASE")


def txns_df():
    df = query_df(
        "SELECT t.id, t.party_id, p.name AS party, t.tdate AS date, t.kind, "
        "t.amount, t.note FROM txns t JOIN parties p ON p.id = t.party_id "
        "ORDER BY t.tdate, t.id"
    )
    df["signed"] = df["amount"] * df["kind"].map(KINDS)
    return df


def income_df():
    df = query_df("SELECT id, idate AS date, amount, source, note FROM income ORDER BY idate, id")
    df["month"] = df["date"].str[:7]
    return df


def summary_df():
    """Har party ka balance, entries ki ginti aur aakhri tarikh."""
    parties = parties_df()
    df = txns_df()
    if df.empty:
        return parties.assign(balance=0.0, entries=0, last="")
    g = df.groupby("party_id").agg(balance=("signed", "sum"), entries=("id", "count"), last=("date", "max"))
    out = parties.merge(g, left_on="id", right_index=True, how="left")
    out["balance"] = out["balance"].fillna(0.0)
    out["entries"] = out["entries"].fillna(0).astype(int)
    out["last"] = out["last"].fillna("")
    return out


# ---------------------------------------------------------------- login
def check_password():
    """Agar secrets me APP_PASSWORD set hai to login maangta hai."""
    try:
        pw = st.secrets.get("APP_PASSWORD")
    except Exception:
        pw = None
    if not pw or st.session_state.get("logged_in"):
        return True
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        hero("📒 Udhari Khata", "Apna hisab, apne haath me. Aage badhne ke liye login kijiye.")
        with st.form("login"):
            entered = st.text_input("Password", type="password")
            ok = st.form_submit_button("Login", use_container_width=True, type="primary")
        if ok:
            if hmac.compare_digest(entered.encode(), str(pw).encode()):
                st.session_state["logged_in"] = True
                st.rerun()
            else:
                st.error("Galat password")
    return False


# ---------------------------------------------------------------- navigation
def go(page, party=None):
    st.session_state["page"] = page
    if party is not None:
        st.session_state["prefill_party"] = party


# ---------------------------------------------------------------- pages
def party_card(r, key):
    cls, label = status_of(r["balance"])
    last = f"Aakhri entry: {r['last']}" if r["last"] else "Koi entry nahi"
    with st.container(border=True):
        st.markdown(
            f'<div class="pcard-top">{avatar(r["name"])}<div>'
            f'<div class="pname">{escape(r["name"])}</div>'
            f'<div class="pmeta">{r["entries"]} entries · {last}</div></div></div>'
            f'<div class="pamt {"pos" if cls == "g" else "neg" if cls == "r" else ""}">'
            f'{inr(abs(r["balance"]))}</div><span class="chip {cls}">{label}</span>',
            unsafe_allow_html=True,
        )
        st.button(
            "➕ Is party ki entry", key=key, use_container_width=True,
            on_click=go, args=(P_NEW, r["name"]),
        )


def page_dashboard():
    hero("📒 Udhari Khata", f"Aaj {date.today().strftime('%d %b %Y')} · aapka poora hisab ek nazar me")
    df = txns_df()
    inc = income_df()
    if df.empty and inc.empty:
        st.info("Abhi koi entry nahi hai. Shuru karne ke liye 'Nayi Entry' par jaiye.")
        st.button("➕ Pehli entry daalein", on_click=go, args=(P_NEW,), type="primary")
        return

    s = summary_df()
    milna = s.loc[s["balance"] > 0, "balance"].sum()
    dena = -s.loc[s["balance"] < 0, "balance"].sum()
    n_mil = int((s["balance"] > 0).sum())
    n_den = int((s["balance"] < 0).sum())

    this_month = inc.loc[inc["month"] == date.today().strftime("%Y-%m"), "amount"].sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(kpi("💰 Aapko milna hai", inr(milna), f"{n_mil} logon se", "g"), unsafe_allow_html=True)
    c2.markdown(kpi("🧾 Aapko dena hai", inr(dena), f"{n_den} logon ko", "r"), unsafe_allow_html=True)
    c3.markdown(
        kpi("⚖️ Net balance", inr(milna - dena), "milna − dena", "b"), unsafe_allow_html=True
    )
    c4.markdown(
        kpi("💵 Is mahine ki income", inr(this_month), date.today().strftime("%B %Y"), "g"),
        unsafe_allow_html=True,
    )
    st.write("")

    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("Sabse badi baaki")
        top = s[s["balance"] != 0].copy()
        top["Rakam"] = top["balance"].abs()
        top["Status"] = top["balance"].apply(lambda b: "Milna hai" if b > 0 else "Dena hai")
        top = top.sort_values("Rakam", ascending=False).head(8)
        if top.empty:
            st.success("Sabka hisab barabar hai 🎉")
        else:
            chart = (
                alt.Chart(top)
                .mark_bar(cornerRadiusEnd=6, size=22)
                .encode(
                    y=alt.Y("name:N", sort="-x", title=None),
                    x=alt.X("Rakam:Q", title="Rakam (₹)"),
                    color=alt.Color(
                        "Status:N",
                        scale=alt.Scale(domain=["Milna hai", "Dena hai"], range=[GREEN, RED]),
                        legend=alt.Legend(orient="bottom", title=None),
                    ),
                    tooltip=[alt.Tooltip("name:N", title="Naam"), "Status:N",
                             alt.Tooltip("Rakam:Q", format=",.2f")],
                )
                .properties(height=max(120, 38 * len(top)))
            )
            st.altair_chart(chart, use_container_width=True)
    with right:
        st.subheader("Haal ki entries")
        for _, r in df.sort_values(["date", "id"], ascending=False).head(6).iterrows():
            pos = r["signed"] > 0
            st.markdown(
                f'<div class="act"><div><div class="l">{KIND_ICON[r["kind"]]} {escape(r["party"])}</div>'
                f'<div class="s">{escape(r["kind"])} · {r["date"]}</div></div>'
                f'<div class="a {"pos" if pos else "neg"}">{"+" if pos else "−"}{inr(r["amount"])}</div></div>',
                unsafe_allow_html=True,
            )

    if not inc.empty:
        st.subheader("Mahine-wise income")
        monthly = inc.groupby("month")["amount"].sum().reset_index().tail(12)
        ichart = (
            alt.Chart(monthly)
            .mark_bar(cornerRadiusEnd=6, color=GREEN)
            .encode(
                x=alt.X("month:N", title=None, sort=None),
                y=alt.Y("amount:Q", title="Rakam (₹)"),
                tooltip=[alt.Tooltip("month:N", title="Mahina"),
                         alt.Tooltip("amount:Q", title="Income", format=",.2f")],
            )
            .properties(height=220)
        )
        st.altair_chart(ichart, use_container_width=True)
        st.caption(f"Ab tak ki total income: {inr(inc['amount'].sum())} · {len(inc)} entries")

    st.subheader("Saari parties")
    f1, f2 = st.columns([2, 1])
    q = f1.text_input("🔍 Naam se dhundhiye", placeholder="Naam likhiye...", label_visibility="collapsed")
    flt = f2.selectbox("Filter", ["Sab", "Mujhe milna hai", "Mujhe dena hai", "Hisab barabar"],
                       label_visibility="collapsed")
    v = s.copy()
    if q.strip():
        v = v[v["name"].str.contains(q.strip(), case=False, regex=False)]
    if flt == "Mujhe milna hai":
        v = v[v["balance"] > 0]
    elif flt == "Mujhe dena hai":
        v = v[v["balance"] < 0]
    elif flt == "Hisab barabar":
        v = v[v["balance"] == 0]
    v = v.reindex(v["balance"].abs().sort_values(ascending=False).index)
    if v.empty:
        st.caption("Koi party nahi mili.")
    rows = list(v.iterrows())
    for i in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, (_, r) in zip(cols, rows[i:i + 3]):
            with col:
                party_card(r, key=f"open_{r['id']}")


def income_form():
    # form ke bahar, taaki 'Other' chunte hi neeche naam likhne ka box turant aa jaye
    source = st.selectbox("Kahan se", INCOME_SOURCES, key="inc_source")
    other = ""
    if source == "Other":
        other = st.text_input("Other ka naam likhiye", placeholder="jaise: Tuition / Freelance", key="inc_other")
    with st.form("income_form", clear_on_submit=True):
        a, b = st.columns(2)
        amount = a.number_input("Income (₹)", min_value=0.0, step=500.0, format="%.2f")
        idate = b.date_input("Kis tarikh ko mili", value=date.today())
        note = st.text_input("Note (optional)", placeholder="jaise: overtime / commission")
        ok = st.form_submit_button("💾 Income save karein", type="primary", use_container_width=True)
    if ok:
        final_source = other.strip() if source == "Other" else source
        if amount <= 0:
            st.error("Rakam 0 se zyada honi chahiye.")
        elif not final_source:
            st.error("'Other' chuna hai to 'kahan se' likhna zaroori hai.")
        else:
            run(
                "INSERT INTO income(idate, amount, source, note) VALUES (?,?,?,?)",
                (idate.isoformat(), float(amount), final_source, note.strip()),
            )
            st.success(f"✅ {inr(amount)} ki income save ho gayi.")
            st.toast("Income save ho gayi", icon="✅")


def page_new_entry():
    hero("➕ Nayi Entry", "Len-den ya income ka hisab kuch hi second me likhiye")
    typ = st.radio(
        "Entry ka type", ["📒 Udhari / Len-den", "💰 Income (kamai)"],
        horizontal=True, key="entry_type",
    )
    if typ.startswith("💰"):
        income_form()
        return
    parties = parties_df()
    pre = st.session_state.pop("prefill_party", None)
    options = ["-- nayi party --"] + parties["name"].tolist()
    idx = options.index(pre) if pre in options else 0

    with st.form("entry_form", clear_on_submit=True):
        kind = st.radio(
            "Kya hua?", list(KINDS.keys()), horizontal=True,
            format_func=lambda k: f"{KIND_ICON[k]} {k}",
        )
        a, b = st.columns(2)
        existing = a.selectbox("Purani party", options, index=idx)
        new_name = b.text_input("Ya nayi party ka naam", placeholder="jaise: Ramesh Bhaiya")
        c, d, e = st.columns(3)
        amount = c.number_input("Rakam (₹)", min_value=0.0, step=100.0, format="%.2f")
        tdate = d.date_input("Tarikh", value=date.today())
        phone = e.text_input("Phone (optional)", placeholder="98xxxxxx10")
        note = st.text_input("Note (optional)", placeholder="jaise: dukaan ka saaman / shaadi ke liye")
        submitted = st.form_submit_button("💾 Save karein", type="primary", use_container_width=True)

    if submitted:
        name = new_name.strip() or ("" if existing.startswith("--") else existing)
        if not name:
            st.error("Party ka naam chuniye ya likhiye.")
        elif amount <= 0:
            st.error("Rakam 0 se zyada honi chahiye.")
        else:
            pid = get_or_create_party(name, phone)
            run(
                "INSERT INTO txns(party_id, tdate, kind, amount, note) VALUES (?,?,?,?,?)",
                (pid, tdate.isoformat(), kind, float(amount), note.strip()),
            )
            st.success(f"✅ {name} ke saath {inr(amount)} ki entry save ho gayi.")
            st.toast("Entry save ho gayi", icon="✅")


def page_backup():
    hero("💾 Backup / Restore", "Apna data surakshit rakhiye")
    st.warning(
        "Streamlit Cloud par app restart hone par database file mit sakti hai. "
        "Isliye time-time par CSV backup download kar lijiye."
    )
    df = txns_df()
    export = df[["party", "date", "kind", "amount", "note"]]
    phones = parties_df()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### ⬇️ Backup lein")
        st.caption(f"{len(export)} entries, {len(phones)} parties")
        st.download_button(
            "CSV backup download karein",
            export.to_csv(index=False).encode("utf-8"),
            file_name=f"udhari_backup_{date.today().isoformat()}.csv",
            mime="text/csv", disabled=export.empty, type="primary",
        )
    with c2:
        st.markdown("#### ⬆️ Restore karein")
        up = st.file_uploader("Backup CSV chuniye", type="csv", label_visibility="collapsed")
        if up is not None and st.button("Restore karein"):
            data = pd.read_csv(up).fillna("")
            need = {"party", "date", "kind", "amount", "note"}
            if not need.issubset(data.columns):
                st.error("CSV me ye columns hone chahiye: party, date, kind, amount, note")
                return
            bad = set(data["kind"]) - set(KINDS)
            if bad:
                st.error(f"Anjaan 'kind' values: {', '.join(map(str, bad))}")
                return
            seen = {
                (r.party, str(r.date), r.kind, round(float(r.amount), 2), str(r.note or ""))
                for r in export.itertuples()
            }
            added = skipped = 0
            for _, r in data.iterrows():
                key = (str(r["party"]).strip(), str(r["date"]), r["kind"], round(float(r["amount"]), 2), str(r["note"]))
                if key in seen:
                    skipped += 1
                    continue
                pid = get_or_create_party(str(r["party"]))
                run(
                    "INSERT INTO txns(party_id, tdate, kind, amount, note) VALUES (?,?,?,?,?)",
                    (pid, str(r["date"]), r["kind"], float(r["amount"]), str(r["note"])),
                )
                seen.add(key)
                added += 1
            st.success(f"{added} entries jodi gayi, {skipped} pehle se maujood thi (duplicate nahi banayi).")

    st.divider()
    inc = income_df()
    i1, i2 = st.columns(2)
    with i1:
        st.markdown("#### 💵 Income backup")
        st.caption(f"{len(inc)} income entries")
        st.download_button(
            "Income CSV backup",
            inc[["date", "amount", "source", "note"]].to_csv(index=False).encode("utf-8"),
            file_name=f"income_backup_{date.today().isoformat()}.csv",
            mime="text/csv", disabled=inc.empty,
        )
    with i2:
        st.markdown("#### 💵 Income restore")
        iup = st.file_uploader("Income CSV chuniye", type="csv", key="inc_up", label_visibility="collapsed")
        if iup is not None and st.button("Income restore karein"):
            d = pd.read_csv(iup).fillna("")
            if not {"date", "amount", "source", "note"}.issubset(d.columns):
                st.error("CSV me ye columns hone chahiye: date, amount, source, note")
            else:
                have = {(str(r.date), round(float(r.amount), 2), str(r.source), str(r.note)) for r in inc.itertuples()}
                added = 0
                for _, r in d.iterrows():
                    key = (str(r["date"]), round(float(r["amount"]), 2), str(r["source"]), str(r["note"]))
                    if key in have:
                        continue
                    run("INSERT INTO income(idate, amount, source, note) VALUES (?,?,?,?)",
                        (key[0], float(r["amount"]), key[2], key[3]))
                    have.add(key)
                    added += 1
                st.success(f"{added} income entries jodi gayi.")


# ---------------------------------------------------------------- main
def main():
    init_db()
    st.markdown(CSS, unsafe_allow_html=True)
    if not check_password():
        return
    if "page" not in st.session_state or st.session_state["page"] not in PAGES:
        st.session_state["page"] = P_DASH
    st.sidebar.markdown('<div class="brand">📒 Udhari Khata</div>', unsafe_allow_html=True)
    st.sidebar.caption("Hisab saaf, rishte saaf")
    st.sidebar.radio("Menu", PAGES, key="page", label_visibility="collapsed")

    s = summary_df()
    if not s.empty and s["entries"].sum() > 0:
        st.sidebar.divider()
        st.sidebar.metric("Net balance", inr(s["balance"].sum()))
        st.sidebar.caption(f"{len(s)} parties · {int(s['entries'].sum())} entries")

    {
        P_DASH: page_dashboard,
        P_NEW: page_new_entry,
        P_BACKUP: page_backup,
    }[st.session_state["page"]]()


main()
