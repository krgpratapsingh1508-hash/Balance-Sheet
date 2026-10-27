"""Udhari Khata v2 - paise ke len-den aur udhari ka hisab rakhne wala Streamlit app.
Sirf 3 pages: Dashboard, Nayi Entry, Backup / Restore.
"""

import calendar
import hmac
import sqlite3
from contextlib import closing
from datetime import date
from html import escape
from io import BytesIO
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


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
            CREATE TABLE IF NOT EXISTS loans(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL COLLATE NOCASE,
                loan_amount REAL DEFAULT 0,
                kist_amount REAL NOT NULL CHECK(kist_amount > 0),
                total_kists INTEGER NOT NULL CHECK(total_kists >= 1),
                first_due TEXT NOT NULL,
                penalty_type TEXT NOT NULL DEFAULT 'fixed',
                penalty_amount REAL NOT NULL DEFAULT 0,
                note TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS loan_payments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
                pdate TEXT NOT NULL,
                kind TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
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


LOAN_PEN_TYPES = {
    "fixed": "Fixed (har late kist par ek baar)",
    "daily": "Per din (har din ki der par)",
}


def add_months(d, n):
    """Date d se n mahine aage (din wahi rehta hai, mahina chhota ho to aakhri din)."""
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def loans_df():
    return query_df(
        "SELECT id, name, loan_amount, kist_amount, total_kists, first_due, "
        "penalty_type, penalty_amount, note FROM loans ORDER BY id"
    )


def loan_pay_df():
    return query_df(
        "SELECT p.id, p.loan_id, l.name AS loan, p.pdate AS date, p.kind, p.amount, p.note "
        "FROM loan_payments p JOIN loans l ON l.id = p.loan_id ORDER BY p.pdate, p.id"
    )


def loan_schedule(loan, pays, today):
    """Har kist ki due date, kab bhari, kitne din late aur penalty."""
    kist = float(loan["kist_amount"])
    n = int(loan["total_kists"])
    first = date.fromisoformat(str(loan["first_due"])[:10])
    pen = float(loan["penalty_amount"])
    daily = loan["penalty_type"] == "daily"
    events, cum = [], 0.0
    for r in pays[pays["kind"] == "kist"].itertuples():
        cum += float(r.amount)
        events.append((date.fromisoformat(str(r.date)[:10]), cum))
    rows = []
    for i in range(1, n + 1):
        due = add_months(first, i - 1)
        # i-vi kist tab bhari maani jaati hai jab ab tak ki total kist-rakam i*kist tak pahunch jaye
        paid_on = next((d for d, c in events if c >= kist * i - 0.005), None)
        late = max(((paid_on or today) - due).days, 0)
        penalty = (pen * late if daily else pen) if late > 0 else 0.0
        rows.append({"no": i, "due": due, "paid_on": paid_on, "late": late, "penalty": penalty})
    return rows


def loan_summary(loan, pays, today):
    rows = loan_schedule(loan, pays, today)
    kist = float(loan["kist_amount"])
    n = int(loan["total_kists"])
    paid = float(pays.loc[pays["kind"] == "kist", "amount"].sum())
    pen_paid = float(pays.loc[pays["kind"] == "penalty", "amount"].sum())
    pen_total = sum(r["penalty"] for r in rows)
    total = kist * n
    pending = max(total - paid, 0.0)
    principal = float(loan["loan_amount"] or 0)
    interest = max(total - principal, 0.0) if principal > 0 else None
    share = pending / total if total else 0.0  # baaki kist ka hissa (mool aur bayaj barabar hisab se)
    return {
        "rows": rows,
        "paid": paid,
        "total": total,
        "pending": pending,
        "principal": principal,
        "interest": interest,
        "pend_principal": principal * share if principal > 0 else None,
        "pend_interest": interest * share if interest is not None else None,
        "paid_cnt": min(int((paid + 0.005) // kist), n),
        "pen_total": pen_total,
        "pen_paid": pen_paid,
        "pen_due": max(pen_total - pen_paid, 0.0),
        "overdue": [r for r in rows if r["paid_on"] is None and r["due"] < today],
        "next": next((r for r in rows if r["paid_on"] is None), None),
    }


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


CF_COLS = ["Income", "Udhar diya", "Udhar wapas diya", "Kist", "Penalty", "Wapas mile", "Udhar liya"]
CF_OUT = ["Udhar diya", "Udhar wapas diya", "Kist", "Penalty"]  # paisa gaya
CF_IN = ["Income", "Wapas mile", "Udhar liya"]  # paisa aaya


def cash_flow():
    """Mahine-wise: income, kitna gaya (udhari/kist/penalty), kitna aur aaya aur kitna bacha."""
    parts = []
    inc = income_df()
    if not inc.empty:
        parts.append(pd.DataFrame({"month": inc["month"], "Income": inc["amount"]}))
    t = txns_df()
    if not t.empty:
        amt, kind = t["amount"], t["kind"]
        parts.append(pd.DataFrame({
            "month": t["date"].str[:7],
            "Udhar diya": amt.where(kind == "Maine udhar diya", 0.0),
            "Udhar wapas diya": amt.where(kind == "Maine paise wapas diye", 0.0),
            "Wapas mile": amt.where(kind == "Mujhe paise wapas mile", 0.0),
            "Udhar liya": amt.where(kind == "Maine udhar liya", 0.0),
        }))
    p = loan_pay_df()
    if not p.empty:
        parts.append(pd.DataFrame({
            "month": p["date"].str[:7],
            "Kist": p["amount"].where(p["kind"] == "kist", 0.0),
            "Penalty": p["amount"].where(p["kind"] == "penalty", 0.0),
        }))
    if not parts:
        return pd.DataFrame(columns=CF_COLS + ["Gaya", "Aaya", "Bacha"], dtype=float)
    cf = pd.concat(parts).fillna(0.0).groupby("month").sum().reindex(columns=CF_COLS, fill_value=0.0)
    cf["Gaya"] = cf[CF_OUT].sum(axis=1)
    cf["Aaya"] = cf[CF_IN].sum(axis=1)
    cf["Bacha"] = cf["Aaya"] - cf["Gaya"]
    return cf.sort_index()


def cash_total():
    cf = cash_flow()
    return float(cf["Bacha"].sum()) if not cf.empty else 0.0


def show_cash_left():
    st.caption(f"👛 Income me se ab bacha: {inr(cash_total())}")


def cash_section():
    cf = cash_flow()
    if cf.empty:
        return
    income = float(cf["Income"].sum())
    gaya = float(cf["Gaya"].sum())
    other_in = float((cf["Wapas mile"] + cf["Udhar liya"]).sum())
    bacha = float(cf["Bacha"].sum())
    st.subheader("👛 Income me se hisab")
    k1, k2, k3 = st.columns(3)
    k1.markdown(kpi("💵 Kul income", inr(income), "ab tak ki", "g"), unsafe_allow_html=True)
    k2.markdown(
        kpi("📤 Kul gaya", inr(gaya), "udhari diya, wapas diye, kist, penalty", "r"),
        unsafe_allow_html=True,
    )
    k3.markdown(
        kpi("👛 Income me se bacha", inr(bacha), f"income + {inr(other_in)} aur aaya − gaya",
            "g" if bacha >= 0 else "r"),
        unsafe_allow_html=True,
    )
    st.caption(
        f"Gaya: udhar diya {inr(cf['Udhar diya'].sum())} · udhar wapas diya {inr(cf['Udhar wapas diya'].sum())} · "
        f"kist {inr(cf['Kist'].sum())} · penalty {inr(cf['Penalty'].sum())}. "
        f"Aur aaya: paise wapas mile {inr(cf['Wapas mile'].sum())} · udhar liya {inr(cf['Udhar liya'].sum())}."
    )
    with st.expander("Mahine-wise hisab"):
        tbl = pd.DataFrame({
            "Income": cf["Income"],
            "Aur aaya": cf["Wapas mile"] + cf["Udhar liya"],
            "Gaya": cf["Gaya"],
            "Bacha": cf["Bacha"],
            "Ab tak bacha": cf["Bacha"].cumsum(),
        }).iloc[::-1].reset_index().rename(columns={"month": "Mahina"})
        money = st.column_config.NumberColumn(format="₹%.2f")
        st.dataframe(
            tbl, hide_index=True, use_container_width=True,
            column_config={c: money for c in ["Income", "Aur aaya", "Gaya", "Bacha", "Ab tak bacha"]},
        )
    st.write("")


def loan_section():
    loans = loans_df()
    if loans.empty:
        return
    pays = loan_pay_df()
    today = date.today()
    items = [
        (l, loan_summary(l, pays[pays["loan_id"] == l["id"]], today))
        for l in loans.to_dict("records")
    ]
    st.subheader("🏦 Loan aur Kist")
    pending = sum(i["pending"] for _, i in items)
    pen_due = sum(i["pen_due"] for _, i in items)
    n_late = sum(len(i["overdue"]) for _, i in items)
    known = [i for _, i in items if i["pend_interest"] is not None]
    pend_interest = sum(i["pend_interest"] for i in known)
    pend_principal = sum(i["pend_principal"] for i in known)
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(
        kpi("🏦 Loan baaki (bayaj ke sath)", inr(pending), f"{len(items)} loan", "b"),
        unsafe_allow_html=True,
    )
    k2.markdown(
        kpi("💹 Isme bayaj", inr(pend_interest), f"mool {inr(pend_principal)} + bayaj",
            "r" if pend_interest > 0.005 else "g"),
        unsafe_allow_html=True,
    )
    k3.markdown(
        kpi("⚠️ Penalty baaki", inr(pen_due), "late kist ki penalty", "r" if pen_due > 0.005 else "g"),
        unsafe_allow_html=True,
    )
    k4.markdown(
        kpi("⏰ Late kist", str(n_late), "time par nahi bhari", "r" if n_late else "g"),
        unsafe_allow_html=True,
    )
    st.caption(f"Penalty ke sath kul dena: {inr(pending + pen_due)}")
    st.write("")
    for start in range(0, len(items), 3):
        cols = st.columns(3)
        for col, (l, i) in zip(cols, items[start:start + 3]):
            with col, st.container(border=True):
                if i["overdue"]:
                    cls, label = "r", f"{len(i['overdue'])} kist late"
                elif i["pending"] <= 0.005 and i["pen_due"] > 0.005:
                    cls, label = "r", "Penalty baaki"
                elif i["pending"] <= 0.005:
                    cls, label = "g", "Loan poora"
                else:
                    cls, label = "g", "Time par"
                nxt = i["next"]
                nxt_txt = f"Agli kist: {nxt['due'].strftime('%d %b %Y')}" if nxt else "Saari kist ho gayi"
                st.markdown(
                    f'<div class="pcard-top">{avatar(l["name"])}<div>'
                    f'<div class="pname">{escape(l["name"])}</div>'
                    f'<div class="pmeta">{inr(l["kist_amount"])} × {int(l["total_kists"])} kist · {nxt_txt}</div>'
                    f'</div></div>'
                    f'<div class="pmeta" style="margin-top:8px">Baaki (bayaj ke sath)</div>'
                    f'<div class="pamt" style="margin-top:0">{inr(i["pending"])}</div>'
                    f'<span class="chip {cls}">{label}</span>'
                    f'<div class="pmeta" style="margin-top:6px">{i["paid_cnt"]}/{int(l["total_kists"])} kist bhari</div>',
                    unsafe_allow_html=True,
                )
                if i["pen_due"] > 0.005:
                    st.markdown(
                        f'<div class="neg" style="font-weight:700;font-size:.85rem">'
                        f'⚠️ Penalty baaki: {inr(i["pen_due"])}</div>',
                        unsafe_allow_html=True,
                    )
                if i["interest"] is not None:
                    st.caption(
                        f"Loan {inr(i['principal'])} + bayaj {inr(i['interest'])} = kul {inr(i['total'])}"
                    )
                    st.caption(
                        f"Baaki me: mool {inr(i['pend_principal'])} + bayaj {inr(i['pend_interest'])}"
                    )
                else:
                    st.caption(f"Kul wapas karna: {inr(i['total'])} (bayaj ke liye loan ki rakam chahiye)")
                if i["pen_due"] > 0.005:
                    st.caption(f"Penalty ke sath kul dena: {inr(i['pending'] + i['pen_due'])}")
                st.progress(min(i["paid"] / i["total"], 1.0) if i["total"] else 0.0)
                with st.expander("Kist ki list"):
                    tbl = pd.DataFrame([
                        {
                            "Kist": r["no"],
                            "Due date": r["due"].isoformat(),
                            "Bhari": r["paid_on"].isoformat() if r["paid_on"] else "—",
                            "Der (din)": r["late"],
                            "Penalty": r["penalty"],
                        }
                        for r in i["rows"]
                    ])
                    st.dataframe(
                        tbl, hide_index=True, use_container_width=True,
                        column_config={"Penalty": st.column_config.NumberColumn(format="₹%.2f")},
                    )


def page_dashboard():
    hero("📒 Udhari Khata", f"Aaj {date.today().strftime('%d %b %Y')} · aapka poora hisab ek nazar me")
    df = txns_df()
    inc = income_df()
    if df.empty and inc.empty and loans_df().empty:
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

    cash_section()
    loan_section()

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
            show_cash_left()


def loan_entry_form():
    mode = st.radio(
        "Kya karna hai?", ["➕ Naya loan jodein", "💸 Kist / penalty bhari"],
        horizontal=True, key="loan_mode",
    )
    if mode.startswith("➕"):
        # form ke bahar, taaki penalty ka label turant badle
        ptype = st.radio(
            "Late kist par penalty kaise lagti hai?", list(LOAN_PEN_TYPES.values()),
            horizontal=True, key="loan_pen_type",
        )
        daily = ptype == LOAN_PEN_TYPES["daily"]
        with st.form("loan_new", clear_on_submit=True):
            name = st.text_input("Loan ka naam", placeholder="jaise: Bank loan / Ramesh se liya")
            a, b, c = st.columns(3)
            loan_amount = a.number_input("Loan ki rakam (₹)", min_value=0.0, step=1000.0, format="%.2f")
            kist = b.number_input("Ek kist (₹)", min_value=0.0, step=100.0, format="%.2f")
            n = c.number_input("Kul kitni kist", min_value=1, value=12, step=1)
            d, e = st.columns(2)
            pen = d.number_input(
                "Penalty (₹ per din)" if daily else "Penalty (₹ har late kist par)",
                min_value=0.0, step=10.0, format="%.2f",
            )
            first = e.date_input("Pehli kist ki due date", value=date.today())
            note = st.text_input("Note (optional)", placeholder="jaise: bike loan / mahine ki 5 tarikh")
            ok = st.form_submit_button("💾 Loan save karein", type="primary", use_container_width=True)
        if ok:
            name = name.strip()
            if not name:
                st.error("Loan ka naam likhiye.")
            elif loan_amount <= 0:
                st.error("Loan ki rakam likhiye (bayaj nikalne ke liye zaroori hai).")
            elif kist <= 0:
                st.error("Ek kist ki rakam 0 se zyada honi chahiye.")
            elif kist * n < loan_amount:
                st.error("Kul kist (kist × kitni kist) loan ki rakam se kam hai, rakam check kijiye.")
            elif not query_df("SELECT 1 FROM loans WHERE name = ? COLLATE NOCASE", (name,)).empty:
                st.error("Is naam ka loan pehle se hai, doosra naam chuniye.")
            else:
                run(
                    "INSERT INTO loans(name, loan_amount, kist_amount, total_kists, first_due, "
                    "penalty_type, penalty_amount, note) VALUES (?,?,?,?,?,?,?,?)",
                    (name, float(loan_amount), float(kist), int(n), first.isoformat(),
                     "daily" if daily else "fixed", float(pen), note.strip()),
                )
                st.success(
                    f"✅ '{name}' loan save ho gaya: {int(n)} kist × {inr(kist)} = {inr(kist * n)}. "
                    f"Loan {inr(loan_amount)} par kul bayaj {inr(kist * n - loan_amount)}."
                )
                st.toast("Loan save ho gaya", icon="✅")
        return

    loans = loans_df()
    if loans.empty:
        st.info("Pehle 'Naya loan jodein' se loan banaiye.")
        return
    pick = st.selectbox("Kaun sa loan?", loans["name"].tolist(), key="loan_pick")
    l = loans[loans["name"] == pick].iloc[0].to_dict()
    pays = loan_pay_df()
    inf = loan_summary(l, pays[pays["loan_id"] == l["id"]], date.today())
    nxt = inf["next"]
    st.caption(
        f"Baaki kist rakam: {inr(inf['pending'])} · Penalty baaki: {inr(inf['pen_due'])}"
        + (f" · Agli kist: {nxt['due'].strftime('%d %b %Y')}" if nxt else " · Saari kist ho gayi")
    )
    if inf["overdue"]:
        st.warning(f"{len(inf['overdue'])} kist late hai. Ab tak ki penalty: {inr(inf['pen_total'])}")

    with st.form("loan_pay", clear_on_submit=True):
        kind = st.radio("Kya bhara?", ["Kist", "Penalty"], horizontal=True)
        a, b = st.columns(2)
        amount = a.number_input(
            "Rakam (₹)", min_value=0.0, value=float(l["kist_amount"]), step=100.0,
            format="%.2f", key=f"lp_amt_{l['id']}",
        )
        pdate = b.date_input("Kis tarikh ko bhari", value=date.today())
        note = st.text_input("Note (optional)", placeholder="jaise: online / cash")
        ok = st.form_submit_button("💾 Save karein", type="primary", use_container_width=True)
    if ok:
        if amount <= 0:
            st.error("Rakam 0 se zyada honi chahiye.")
        else:
            run(
                "INSERT INTO loan_payments(loan_id, pdate, kind, amount, note) VALUES (?,?,?,?,?)",
                (int(l["id"]), pdate.isoformat(), kind.lower(), float(amount), note.strip()),
            )
            st.success(f"✅ {pick}: {kind.lower()} {inr(amount)} save ho gayi.")
            st.toast("Save ho gaya", icon="✅")
            show_cash_left()


def page_new_entry():
    hero("➕ Nayi Entry", "Len-den, income ya loan ki kist kuch hi second me likhiye")
    typ = st.radio(
        "Entry ka type", ["📒 Udhari / Len-den", "💰 Income (kamai)", "🏦 Loan / Kist"],
        horizontal=True, key="entry_type",
    )
    if typ.startswith("💰"):
        income_form()
        return
    if typ.startswith("🏦"):
        loan_entry_form()
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
            show_cash_left()


SHEETS = ["Udhari", "Income", "Loan", "Kist_Penalty"]
LOAN_COLS = ["name", "loan_amount", "kist_amount", "total_kists", "first_due",
             "penalty_type", "penalty_amount", "note"]
PAY_COLS = ["loan", "date", "kind", "amount", "note"]


def to_xlsx_multi(sheets):
    """{sheet_naam: DataFrame} ko ek Excel (.xlsx) file me badalta hai."""
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, index=False, sheet_name=name)
            ws = w.sheets[name]
            for i, col in enumerate(df.columns, start=1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width, 45)
    return buf.getvalue()


def _clean(d):
    d = d.fillna("")
    for c in ("date", "first_due"):
        if c in d.columns:
            d[c] = d[c].astype(str).str[:10]
    return d


def read_backup_all(f):
    """Ek Excel file se saari sheets padhta hai (purani CSV ho to sirf Udhari)."""
    if f.name.lower().endswith(".csv"):
        out = {k: None for k in SHEETS}
        out["Udhari"] = _clean(pd.read_csv(f))
        return out
    sheets = pd.read_excel(f, sheet_name=None, dtype={"date": str, "first_due": str})
    return {k: _clean(sheets[k]) if k in sheets else None for k in SHEETS}


def template_xlsx():
    """Restore ke liye khali Excel format (headers + dropdown + kaise bhare ki guide)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="4F46E5")
    head_font = Font(bold=True, color="FFFFFF")

    def make(ws, cols, widths, date_cols=("date",)):
        ws.append(cols)
        for i, w in enumerate(widths, start=1):
            c = ws.cell(row=1, column=i)
            c.fill, c.font = head_fill, head_font
            ws.column_dimensions[c.column_letter].width = w
        ws.freeze_panes = "A2"
        for dc in date_cols:  # tarikh ko text rakho, taaki Excel format na badle
            if dc in cols:
                for r in range(2, 1002):
                    ws.cell(row=r, column=cols.index(dc) + 1).number_format = "@"

    def dropdown(ws, options, rng, strict=True):
        dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"',
                            allow_blank=True, showErrorMessage=strict)
        dv.error, dv.errorTitle = "Dropdown se chuniye", "Galat value"
        ws.add_data_validation(dv)
        dv.add(rng)

    ws1 = wb.active
    ws1.title = "Udhari"
    make(ws1, ["party", "date", "kind", "amount", "note"], [24, 14, 28, 14, 36])
    dropdown(ws1, list(KINDS), "C2:C1000")

    ws2 = wb.create_sheet("Income")
    make(ws2, ["date", "amount", "source", "note"], [14, 14, 24, 36])
    dropdown(ws2, INCOME_SOURCES[:-1], "C2:C1000", strict=False)

    ws3 = wb.create_sheet("Loan")
    make(ws3, LOAN_COLS, [24, 16, 14, 14, 14, 14, 16, 30], date_cols=("first_due",))
    dropdown(ws3, list(LOAN_PEN_TYPES), "F2:F1000")

    ws4 = wb.create_sheet("Kist_Penalty")
    make(ws4, PAY_COLS, [24, 14, 12, 14, 30])
    dropdown(ws4, ["kist", "penalty"], "C2:C1000")

    ws5 = wb.create_sheet("Kaise bhare")
    lines = [
        ("Restore ke liye Excel kaise bhare", True),
        ("", False),
        ("1. Har sheet me heading wali pehli row mat badliye, uske neeche se data likhiye.", False),
        ("2. Saari sheet zaroori nahi - sirf jis sheet me data hai wahi judega.", False),
        ("3. Is 'Kaise bhare' sheet ko rakhein ya hata dein, koi farak nahi padta.", False),
        ("4. Tarikh hamesha YYYY-MM-DD me likhiye, jaise 2026-10-27.", False),
        ("", False),
        ("Udhari sheet", True),
        ("party  -> samne wale ka naam (nayi party ho to apne aap ban jayegi)", False),
        ("date   -> tarikh", False),
        ("kind   -> dropdown se chuniye (neeche ke 4 me se ek):", False),
    ] + [("          - " + k, False) for k in KINDS] + [
        ("amount -> rakam, 0 se zyada, jaise 1500 ya 250.50", False),
        ("note   -> optional", False),
        ("", False),
        ("Income sheet", True),
        ("date, amount, note -> upar jaisa", False),
        ("source -> kahan se (jaise Salary, Bonus, Kiraya ya apna likha hua naam)", False),
        ("", False),
        ("Loan sheet (ek loan = ek row)", True),
        ("name           -> loan ka naam (har loan ka alag naam)", False),
        ("loan_amount    -> loan ki rakam (bayaj nikalne ke liye zaroori)", False),
        ("kist_amount    -> ek kist ki rakam, 0 se zyada", False),
        ("total_kists    -> kul kitni kist", False),
        ("first_due      -> pehli kist ki due date (baaki har mahine usi tarikh ko)", False),
        ("penalty_type   -> fixed = har late kist par ek baar, daily = har din ki der par", False),
        ("penalty_amount -> penalty ki rakam (fixed ho to ek baar ki, daily ho to ek din ki)", False),
        ("note           -> optional", False),
        ("", False),
        ("Kist_Penalty sheet (loan me bhari gayi kist ya penalty)", True),
        ("loan   -> wahi naam jo Loan sheet me hai (pehle se app me ho to bhi chalega)", False),
        ("date   -> kis tarikh ko bhari", False),
        ("kind   -> kist ya penalty", False),
        ("amount -> rakam", False),
        ("note   -> optional", False),
        ("", False),
        ("Duplicate entries (bilkul same data) dobara nahi judti.", False),
    ]
    for text, bold in lines:
        ws5.append([text])
        ws5.cell(row=ws5.max_row, column=1).font = Font(bold=bold, size=12 if bold else 11)
    ws5.column_dimensions["A"].width = 95

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def wipe_all_data():
    """Saari tables ka poora data hata deta hai (ids bhi shuru se)."""
    with closing(sqlite3.connect(DB_PATH)) as c:
        c.execute("PRAGMA foreign_keys = ON")
        for t in ("loan_payments", "loans", "txns", "parties", "income"):
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM sqlite_sequence")
        c.commit()


def wipe_callback():
    wipe_all_data()
    st.session_state["wipe_sure"] = False
    st.session_state["wipe_word"] = ""
    st.session_state["wiped"] = True


def wipe_section(counts):
    st.divider()
    st.markdown("#### 🗑️ Saara data delete karein")
    st.caption(counts)
    with st.expander("Khatarnak: poora data mitane ke liye kholiye"):
        st.error(
            "Ye udhari, parties, income, loan aur kist ka **poora data hamesha ke liye** hata dega. "
            "Wapas nahi aayega. Pehle upar se Excel backup download kar lijiye."
        )
        sure = st.checkbox("Haan, mujhe pata hai ki saara data delete ho jayega", key="wipe_sure")
        word = st.text_input("Confirm ke liye DELETE likhiye", key="wipe_word", placeholder="DELETE")
        st.button(
            "🗑️ Saara data delete karein", type="primary",
            disabled=not (sure and word.strip().upper() == "DELETE"),
            on_click=wipe_callback,
        )


def page_backup():
    hero("💾 Backup / Restore", "Apna data surakshit rakhiye")
    if st.session_state.pop("wiped", False):
        st.success("✅ Saara data delete ho gaya.")
    st.warning(
        "Streamlit Cloud par app restart hone par database file mit sakti hai. "
        "Isliye time-time par Excel backup download kar lijiye."
    )
    df = txns_df()
    export = df[["party", "date", "kind", "amount", "note"]]
    inc = income_df()
    inc_export = inc[["date", "amount", "source", "note"]]
    loans = loans_df()
    loan_export = loans[LOAN_COLS]
    pays = loan_pay_df()
    pay_export = pays[PAY_COLS[:1] + PAY_COLS[1:]]
    phones = parties_df()
    empty = export.empty and inc_export.empty and loan_export.empty

    c1, c2 = st.columns(2)
    # restore me error aane par bhi ye hissa dikhta rahe, isliye pehle hi bana liya
    wipe_box = st.container()
    with wipe_box:
        wipe_section(
            f"Abhi: {len(export)} udhari entries, {len(phones)} parties, "
            f"{len(inc_export)} income entries, {len(loan_export)} loan, {len(pay_export)} kist/penalty"
        )
    with c1:
        st.markdown("#### ⬇️ Backup lein")
        st.caption(
            f"{len(export)} udhari entries, {len(phones)} parties, "
            f"{len(inc_export)} income entries, {len(loan_export)} loan"
        )
        st.download_button(
            "Excel backup download karein",
            to_xlsx_multi({
                "Udhari": export, "Income": inc_export,
                "Loan": loan_export, "Kist_Penalty": pay_export,
            }),
            file_name=f"udhari_backup_{date.today().isoformat()}.xlsx",
            mime=XLSX_MIME, disabled=empty, type="primary",
        )
    with c2:
        st.markdown("#### ⬆️ Restore karein")
        st.download_button(
            "📄 Restore ka format download karein (khali Excel)",
            template_xlsx(),
            file_name="udhari_restore_format.xlsx",
            mime=XLSX_MIME,
            help="Isme data bharkar neeche upload karein. Andar 'Kaise bhare' sheet me poori guide hai.",
        )
        up = st.file_uploader("Backup Excel chuniye", type=["xlsx", "csv"], label_visibility="collapsed")
        if up is not None and st.button("Restore karein"):
            sheets = read_backup_all(up)
            ud, ic, lo, kp = (sheets[k] for k in SHEETS)
            if all(x is None for x in (ud, ic, lo, kp)):
                st.error("File me 'Udhari', 'Income', 'Loan' ya 'Kist_Penalty' sheet honi chahiye.")
                return

            msgs = []
            if ud is not None:
                need = {"party", "date", "kind", "amount", "note"}
                if not need.issubset(ud.columns):
                    st.error("Udhari sheet me ye columns hone chahiye: party, date, kind, amount, note")
                    return
                bad = set(ud["kind"]) - set(KINDS)
                if bad:
                    st.error(f"Anjaan 'kind' values: {', '.join(map(str, bad))}")
                    return
                seen = {
                    (r.party, str(r.date), r.kind, round(float(r.amount), 2), str(r.note or ""))
                    for r in export.itertuples()
                }
                added = skipped = 0
                for _, r in ud.iterrows():
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
                msgs.append(f"Udhari: {added} entries jodi gayi, {skipped} pehle se maujood thi.")

            if ic is not None:
                if not {"date", "amount", "source", "note"}.issubset(ic.columns):
                    st.error("Income sheet me ye columns hone chahiye: date, amount, source, note")
                    return
                have = {(str(r.date), round(float(r.amount), 2), str(r.source), str(r.note)) for r in inc.itertuples()}
                added = skipped = 0
                for _, r in ic.iterrows():
                    key = (str(r["date"]), round(float(r["amount"]), 2), str(r["source"]), str(r["note"]))
                    if key in have:
                        skipped += 1
                        continue
                    run("INSERT INTO income(idate, amount, source, note) VALUES (?,?,?,?)",
                        (key[0], float(r["amount"]), key[2], key[3]))
                    have.add(key)
                    added += 1
                msgs.append(f"Income: {added} entries jodi gayi, {skipped} pehle se maujood thi.")

            if lo is not None:
                if not set(LOAN_COLS).issubset(lo.columns):
                    st.error("Loan sheet me ye columns hone chahiye: " + ", ".join(LOAN_COLS))
                    return
                names = {str(n).lower() for n in loans["name"]}
                added = skipped = bad = 0
                for _, r in lo.iterrows():
                    nm = str(r["name"]).strip()
                    if not nm or nm.lower() in names:
                        skipped += 1
                        continue
                    try:
                        kist, n = float(r["kist_amount"]), int(float(r["total_kists"]))
                        date.fromisoformat(str(r["first_due"])[:10])
                        if kist <= 0 or n < 1:
                            raise ValueError
                        ptype = str(r["penalty_type"]).strip().lower()
                        ptype = ptype if ptype in LOAN_PEN_TYPES else "fixed"
                        run(
                            "INSERT INTO loans(name, loan_amount, kist_amount, total_kists, first_due, "
                            "penalty_type, penalty_amount, note) VALUES (?,?,?,?,?,?,?,?)",
                            (nm, float(r["loan_amount"] or 0), kist, n, str(r["first_due"])[:10],
                             ptype, float(r["penalty_amount"] or 0), str(r["note"])),
                        )
                    except (ValueError, TypeError):
                        bad += 1
                        continue
                    names.add(nm.lower())
                    added += 1
                msgs.append(
                    f"Loan: {added} jode gaye, {skipped} pehle se maujood, {bad} galat row chhodi."
                )

            if kp is not None:
                if not set(PAY_COLS).issubset(kp.columns):
                    st.error("Kist_Penalty sheet me ye columns hone chahiye: " + ", ".join(PAY_COLS))
                    return
                ids = {str(r["name"]).lower(): int(r["id"]) for r in loans_df().to_dict("records")}
                have = {
                    (str(r.loan).lower(), str(r.date), r.kind, round(float(r.amount), 2), str(r.note))
                    for r in loan_pay_df().itertuples()
                }
                added = skipped = bad = 0
                for _, r in kp.iterrows():
                    try:
                        nm = str(r["loan"]).strip().lower()
                        kind = str(r["kind"]).strip().lower()
                        amt = float(r["amount"])
                        date.fromisoformat(str(r["date"])[:10])
                        if nm not in ids or kind not in ("kist", "penalty") or amt <= 0:
                            raise ValueError
                    except (ValueError, TypeError):
                        bad += 1
                        continue
                    key = (nm, str(r["date"])[:10], kind, round(amt, 2), str(r["note"]))
                    if key in have:
                        skipped += 1
                        continue
                    run(
                        "INSERT INTO loan_payments(loan_id, pdate, kind, amount, note) VALUES (?,?,?,?,?)",
                        (ids[nm], key[1], kind, amt, key[4]),
                    )
                    have.add(key)
                    added += 1
                msgs.append(
                    f"Kist/Penalty: {added} jodi gayi, {skipped} pehle se maujood, {bad} galat row chhodi."
                )

            st.success("  \n".join(msgs))


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
