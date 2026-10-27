"""Udhari Khata - personal ledger for lending, borrowing, income and loan instalments.

Three pages: Dashboard, New entry, Backup & restore.
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

# +1 increases the amount receivable from the party, -1 reduces it.
KINDS = {
    "Money lent": 1,
    "Repayment received": -1,
    "Money borrowed": -1,
    "Repayment made": 1,
}
# Older versions stored Hinglish labels. They are converted on startup and on restore.
LEGACY_KINDS = {
    "Maine udhar diya": "Money lent",
    "Mujhe paise wapas mile": "Repayment received",
    "Maine udhar liya": "Money borrowed",
    "Maine paise wapas diye": "Repayment made",
}

INCOME_SOURCES = [
    "Salary", "Business", "Bonus", "Overtime", "Commission",
    "Rent", "Interest", "Gift", "Other",
]

GREEN = "#1e7a4f"
RED = "#b4372f"
BLUE = "#0f3d4c"

P_DASH = "Dashboard"
P_NEW = "New entry"
P_EDIT = "Admin panel"
P_BACKUP = "Backup & restore"
PAGES = [P_DASH, P_NEW, P_EDIT, P_BACKUP]

# Password needed to edit or delete old records. Override with EDIT_PASSWORD in Streamlit secrets.
EDIT_PASSWORD_DEFAULT = "0610"

st.set_page_config(page_title="Udhari Khata", page_icon="📒", layout="wide")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=Source+Serif+4:wght@600;700&display=swap');

.stApp { font-family: 'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif; }
h1, h2, h3, h4 {
    font-family: 'Source Serif 4', Georgia, serif !important;
    font-weight: 600 !important; letter-spacing: -0.01em; color: #14202b;
}
.block-container { padding-top: 1.4rem; max-width: 1180px; }
#MainMenu, footer { visibility: hidden; }

/* Page header: flat navy band closed by an accountant's double rule */
.hero {
    background: #0f3d4c; color: #fff; border-radius: 6px;
    padding: 22px 28px 20px; margin-bottom: 22px;
    border-bottom: 5px double rgba(255,255,255,.55);
}
.hero h1 { margin: 0; padding: 0; font-size: 1.7rem; color: #fff !important; }
.hero p { margin: 6px 0 0; color: rgba(255,255,255,.78); font-size: .95rem; }

/* Key figures */
.kpi {
    border-radius: 6px; padding: 16px 18px 14px; height: 100%;
    background: #f6f8f9; border: 1px solid #d9dfe4; border-top: 3px solid #5b6975;
}
.kpi .lbl { font-size: .82rem; color: #5b6975; font-weight: 500; }
.kpi .val {
    font-family: 'Source Serif 4', Georgia, serif; font-size: 1.75rem; font-weight: 700;
    margin-top: 4px; line-height: 1.2; font-variant-numeric: tabular-nums;
}
.kpi .sub { font-size: .78rem; color: #5b6975; margin-top: 3px; }
.kpi.g { border-top-color: #1e7a4f; } .kpi.g .val { color: #1e7a4f; }
.kpi.r { border-top-color: #b4372f; } .kpi.r .val { color: #b4372f; }
.kpi.b { border-top-color: #0f3d4c; } .kpi.b .val { color: #0f3d4c; }

/* Party and loan cards */
.pcard-top { display: flex; align-items: center; gap: 12px; }
.avatar {
    width: 40px; height: 40px; border-radius: 8px; display: flex; align-items: center;
    justify-content: center; color: #fff; font-weight: 600; font-size: 1.05rem; flex: none;
}
.pname { font-weight: 600; font-size: 1rem; line-height: 1.25; }
.pmeta { font-size: .78rem; color: #5b6975; }
.pamt {
    font-family: 'Source Serif 4', Georgia, serif; font-size: 1.45rem; font-weight: 700;
    margin: 10px 0 6px; font-variant-numeric: tabular-nums;
}
.chip {
    display: inline-block; padding: 2px 9px; border-radius: 4px; font-size: .75rem;
    font-weight: 600;
}
.chip.g { background: #e3f1ea; color: #1e7a4f; }
.chip.r { background: #f6e4e2; color: #b4372f; }
.chip.z { background: #e7ebee; color: #5b6975; }

/* Recent activity: ruled rows instead of cards */
.act {
    display: flex; justify-content: space-between; align-items: center; gap: 10px;
    padding: 10px 2px; border-bottom: 1px solid #d9dfe4;
}
.act .l { font-size: .92rem; font-weight: 600; }
.act .s { font-size: .76rem; color: #5b6975; }
.act .a { font-weight: 600; white-space: nowrap; font-variant-numeric: tabular-nums; }
.pos { color: #1e7a4f; } .neg { color: #b4372f; }

section[data-testid="stSidebar"] .brand {
    font-family: 'Source Serif 4', Georgia, serif; font-size: 1.4rem; font-weight: 700;
    color: #0f3d4c; margin-bottom: 2px;
}
div[data-testid="stForm"] { border-radius: 6px; }
.stButton > button, .stDownloadButton > button { border-radius: 4px; font-weight: 500; }
:focus-visible { outline: 2px solid #0f3d4c; outline-offset: 2px; }
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


AV_COLORS = ["#0f3d4c", "#2f6f8f", "#1e7a4f", "#8a6d1f", "#8c4a5e", "#556b8d", "#a24c3b", "#3f7d6e"]


def avatar(name):
    ch = escape(name.strip()[:1].upper() or "?")
    color = AV_COLORS[sum(map(ord, name)) % len(AV_COLORS)]
    return f'<div class="avatar" style="background:{color}">{ch}</div>'


def status_of(b):
    if b > 0:
        return "g", "Receivable"
    if b < 0:
        return "r", "Payable"
    return "z", "Settled"


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
        for old, new in LEGACY_KINDS.items():
            c.execute("UPDATE txns SET kind = ? WHERE kind = ?", (new, old))
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
    "fixed": "Fixed amount per late instalment (repeats for each extra month it stays unpaid)",
    "daily": "Fixed amount per day of delay",
    "pct": "% interest per month on the late instalment (pro rata by day)",
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
    """Due date, payment date, days late and penalty for each instalment."""
    kist = float(loan["kist_amount"])
    n = int(loan["total_kists"])
    first = date.fromisoformat(str(loan["first_due"])[:10])
    pen = float(loan["penalty_amount"])
    ptype = loan["penalty_type"]
    events, cum = [], 0.0
    for r in pays[pays["kind"] == "kist"].itertuples():
        cum += float(r.amount)
        events.append((date.fromisoformat(str(r.date)[:10]), cum))
    rows = []
    for i in range(1, n + 1):
        due = add_months(first, i - 1)
        # Instalment i counts as paid once cumulative instalment payments reach i * instalment amount
        paid_on = next((d for d, c in events if c >= kist * i - 0.005), None)
        late = max(((paid_on or today) - due).days, 0)
        if late <= 0:
            penalty = 0.0
        elif ptype == "daily":
            penalty = pen * late
        elif ptype == "pct":
            penalty = kist * pen / 100 * late / 30
        else:
            # Fixed: one penalty if paid late within the due month, +1 more for every later month
            ref = paid_on or today
            months_over = (ref.year - due.year) * 12 + (ref.month - due.month)
            penalty = pen * (1 + max(months_over, 0))
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
    return {
        "rows": rows,
        "paid": paid,
        "total": total,
        "pending": pending,
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
        hero("Udhari Khata", "Sign in to access your ledger.")
        with st.form("login"):
            entered = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", use_container_width=True, type="primary")
        if ok:
            if hmac.compare_digest(entered.encode(), str(pw).encode()):
                st.session_state["logged_in"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


# ---------------------------------------------------------------- navigation
def go(page, party=None):
    st.session_state["page"] = page
    if party is not None:
        st.session_state["prefill_party"] = party


# ---------------------------------------------------------------- pages
def party_card(r, key):
    cls, label = status_of(r["balance"])
    last = f"last entry {r['last']}" if r["last"] else "no entries yet"
    with st.container(border=True):
        st.markdown(
            f'<div class="pcard-top">{avatar(r["name"])}<div>'
            f'<div class="pname">{escape(r["name"])}</div>'
            f'<div class="pmeta">{r["entries"]} entries, {last}</div></div></div>'
            f'<div class="pamt {"pos" if cls == "g" else "neg" if cls == "r" else ""}">'
            f'{inr(abs(r["balance"]))}</div><span class="chip {cls}">{label}</span>',
            unsafe_allow_html=True,
        )
        st.button(
            "Add entry", key=key, use_container_width=True,
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
            "Udhar diya": amt.where(kind == "Money lent", 0.0),
            "Udhar wapas diya": amt.where(kind == "Repayment made", 0.0),
            "Wapas mile": amt.where(kind == "Repayment received", 0.0),
            "Udhar liya": amt.where(kind == "Money borrowed", 0.0),
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
    st.caption(f"Net cash position: {inr(cash_total())}")


def cash_section():
    cf = cash_flow()
    if cf.empty:
        return
    income = float(cf["Income"].sum())
    gaya = float(cf["Gaya"].sum())
    other_in = float((cf["Wapas mile"] + cf["Udhar liya"]).sum())
    bacha = float(cf["Bacha"].sum())
    st.subheader("Cash flow")
    k1, k2, k3 = st.columns(3)
    k1.markdown(kpi("Total income", inr(income), "to date", "g"), unsafe_allow_html=True)
    k2.markdown(
        kpi("Total outflow", inr(gaya), "lent, repaid, instalments, penalties", "r"),
        unsafe_allow_html=True,
    )
    k3.markdown(
        kpi("Net cash position", inr(bacha), f"income + {inr(other_in)} other inflow − outflow",
            "g" if bacha >= 0 else "r"),
        unsafe_allow_html=True,
    )
    st.caption(
        f"Outflow: lent {inr(cf['Udhar diya'].sum())}, repaid {inr(cf['Udhar wapas diya'].sum())}, "
        f"instalments {inr(cf['Kist'].sum())}, penalties {inr(cf['Penalty'].sum())}. "
        f"Other inflow: repayments received {inr(cf['Wapas mile'].sum())}, borrowed {inr(cf['Udhar liya'].sum())}."
    )
    with st.expander("Monthly breakdown"):
        tbl = pd.DataFrame({
            "Income": cf["Income"],
            "Other inflow": cf["Wapas mile"] + cf["Udhar liya"],
            "Outflow": cf["Gaya"],
            "Net": cf["Bacha"],
            "Cumulative": cf["Bacha"].cumsum(),
        }).iloc[::-1].reset_index().rename(columns={"month": "Month"})
        money = st.column_config.NumberColumn(format="₹%.2f")
        st.dataframe(
            tbl, hide_index=True, use_container_width=True,
            column_config={c: money for c in ["Income", "Other inflow", "Outflow", "Net", "Cumulative"]},
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
    st.subheader("Loans and instalments")
    pending = sum(i["pending"] for _, i in items)
    pen_due = sum(i["pen_due"] for _, i in items)
    n_late = sum(len(i["overdue"]) for _, i in items)
    k1, k2, k3 = st.columns(3)
    k1.markdown(
        kpi("Loan outstanding", inr(pending + pen_due),
            f"instalments {inr(pending)} + penalty {inr(pen_due)}", "b"),
        unsafe_allow_html=True,
    )
    k2.markdown(
        kpi("Penalty outstanding", inr(pen_due), "charged on late instalments", "r" if pen_due > 0.005 else "g"),
        unsafe_allow_html=True,
    )
    k3.markdown(
        kpi("Overdue instalments", str(n_late), "not paid on time", "r" if n_late else "g"),
        unsafe_allow_html=True,
    )
    st.write("")
    for start in range(0, len(items), 3):
        cols = st.columns(3)
        for col, (l, i) in zip(cols, items[start:start + 3]):
            with col, st.container(border=True):
                if i["overdue"]:
                    cls, label = "r", f"{len(i['overdue'])} overdue"
                elif i["pending"] <= 0.005 and i["pen_due"] > 0.005:
                    cls, label = "r", "Penalty due"
                elif i["pending"] <= 0.005:
                    cls, label = "g", "Fully paid"
                else:
                    cls, label = "g", "On schedule"
                nxt = i["next"]
                nxt_txt = f"next due {nxt['due'].strftime('%d %b %Y')}" if nxt else "all instalments paid"
                st.markdown(
                    f'<div class="pcard-top">{avatar(l["name"])}<div>'
                    f'<div class="pname">{escape(l["name"])}</div>'
                    f'<div class="pmeta">{inr(l["kist_amount"])} × {int(l["total_kists"])} instalments, {nxt_txt}</div>'
                    f'</div></div>'
                    f'<div class="pmeta" style="margin-top:8px">Outstanding (incl. penalty)</div>'
                    f'<div class="pamt" style="margin-top:0">{inr(i["pending"] + i["pen_due"])}</div>'
                    f'<span class="chip {cls}">{label}</span>'
                    f'<div class="pmeta" style="margin-top:6px">{i["paid_cnt"]} of {int(l["total_kists"])} instalments paid</div>',
                    unsafe_allow_html=True,
                )
                if i["pen_due"] > 0.005:
                    st.markdown(
                        f'<div class="neg" style="font-weight:700;font-size:.85rem">'
                        f'Penalty due: {inr(i["pen_due"])}</div>',
                        unsafe_allow_html=True,
                    )
                st.caption(
                    f"Instalments due {inr(i['pending'])} + penalty {inr(i['pen_due'])}"
                )
                st.progress(min(i["paid"] / i["total"], 1.0) if i["total"] else 0.0)
                with st.expander("Instalment schedule"):
                    tbl = pd.DataFrame([
                        {
                            "No.": r["no"],
                            "Due date": r["due"].isoformat(),
                            "Paid on": r["paid_on"].isoformat() if r["paid_on"] else "—",
                            "Days late": r["late"],
                            "Penalty": r["penalty"],
                        }
                        for r in i["rows"]
                    ])
                    st.dataframe(
                        tbl, hide_index=True, use_container_width=True,
                        column_config={"Penalty": st.column_config.NumberColumn(format="₹%.2f")},
                    )


def page_dashboard():
    hero("Dashboard", f"Your financial position as of {date.today().strftime('%d %b %Y')}")
    df = txns_df()
    inc = income_df()
    if df.empty and inc.empty and loans_df().empty:
        st.info("No records yet. Add your first entry to get started.")
        st.button("Add first entry", on_click=go, args=(P_NEW,), type="primary")
        return

    s = summary_df()
    milna = s.loc[s["balance"] > 0, "balance"].sum()
    dena = -s.loc[s["balance"] < 0, "balance"].sum()
    n_mil = int((s["balance"] > 0).sum())
    n_den = int((s["balance"] < 0).sum())

    this_month = inc.loc[inc["month"] == date.today().strftime("%Y-%m"), "amount"].sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(kpi("Receivable", inr(milna), f"from {n_mil} parties", "g"), unsafe_allow_html=True)
    c2.markdown(kpi("Payable", inr(dena), f"to {n_den} parties", "r"), unsafe_allow_html=True)
    c3.markdown(
        kpi("Net balance", inr(milna - dena), "receivable − payable", "b"), unsafe_allow_html=True
    )
    c4.markdown(
        kpi("Income this month", inr(this_month), date.today().strftime("%B %Y"), "g"),
        unsafe_allow_html=True,
    )
    st.write("")

    cash_section()
    loan_section()

    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("Largest balances")
        top = s[s["balance"] != 0].copy()
        top["Amount"] = top["balance"].abs()
        top["Status"] = top["balance"].apply(lambda b: "Receivable" if b > 0 else "Payable")
        top = top.sort_values("Amount", ascending=False).head(8)
        if top.empty:
            st.success("All balances are settled.")
        else:
            chart = (
                alt.Chart(top)
                .mark_bar(cornerRadiusEnd=2, size=20)
                .encode(
                    y=alt.Y("name:N", sort="-x", title=None),
                    x=alt.X("Amount:Q", title="Amount (₹)"),
                    color=alt.Color(
                        "Status:N",
                        scale=alt.Scale(domain=["Receivable", "Payable"], range=[GREEN, RED]),
                        legend=alt.Legend(orient="bottom", title=None),
                    ),
                    tooltip=[alt.Tooltip("name:N", title="Name"), "Status:N",
                             alt.Tooltip("Amount:Q", format=",.2f")],
                )
                .properties(height=max(120, 38 * len(top)))
            )
            st.altair_chart(chart, use_container_width=True)
    with right:
        st.subheader("Recent activity")
        for _, r in df.sort_values(["date", "id"], ascending=False).head(6).iterrows():
            pos = r["signed"] > 0
            st.markdown(
                f'<div class="act"><div><div class="l">{escape(r["party"])}</div>'
                f'<div class="s">{escape(r["kind"])}, {r["date"]}</div></div>'
                f'<div class="a {"pos" if pos else "neg"}">{"+" if pos else "−"}{inr(r["amount"])}</div></div>',
                unsafe_allow_html=True,
            )

    if not inc.empty:
        st.subheader("Monthly income")
        monthly = inc.groupby("month")["amount"].sum().reset_index().tail(12)
        ichart = (
            alt.Chart(monthly)
            .mark_bar(cornerRadiusEnd=2, color=GREEN)
            .encode(
                x=alt.X("month:N", title=None, sort=None),
                y=alt.Y("amount:Q", title="Amount (₹)"),
                tooltip=[alt.Tooltip("month:N", title="Month"),
                         alt.Tooltip("amount:Q", title="Income", format=",.2f")],
            )
            .properties(height=220)
        )
        st.altair_chart(ichart, use_container_width=True)
        st.caption(f"Total income to date: {inr(inc['amount'].sum())} across {len(inc)} entries")

    st.subheader("All parties")
    f1, f2 = st.columns([2, 1])
    q = f1.text_input("Search by name", placeholder="Search by name", label_visibility="collapsed")
    flt = f2.selectbox("Filter", ["All", "Receivable", "Payable", "Settled"],
                       label_visibility="collapsed")
    v = s.copy()
    if q.strip():
        v = v[v["name"].str.contains(q.strip(), case=False, regex=False)]
    if flt == "Receivable":
        v = v[v["balance"] > 0]
    elif flt == "Payable":
        v = v[v["balance"] < 0]
    elif flt == "Settled":
        v = v[v["balance"] == 0]
    v = v.reindex(v["balance"].abs().sort_values(ascending=False).index)
    if v.empty:
        st.caption("No matching parties.")
    rows = list(v.iterrows())
    for i in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, (_, r) in zip(cols, rows[i:i + 3]):
            with col:
                party_card(r, key=f"open_{r['id']}")


def income_form():
    # form ke bahar, taaki 'Other' chunte hi neeche naam likhne ka box turant aa jaye
    source = st.selectbox("Source", INCOME_SOURCES, key="inc_source")
    other = ""
    if source == "Other":
        other = st.text_input("Specify source", placeholder="e.g. Tuition, Freelance", key="inc_other")
    with st.form("income_form", clear_on_submit=True):
        a, b = st.columns(2)
        amount = a.number_input("Amount (₹)", min_value=0.0, step=500.0, format="%.2f")
        idate = b.date_input("Date received", value=date.today())
        note = st.text_input("Note (optional)", placeholder="e.g. overtime, commission")
        ok = st.form_submit_button("Save income", type="primary", use_container_width=True)
    if ok:
        final_source = other.strip() if source == "Other" else source
        if amount <= 0:
            st.error("Amount must be greater than 0.")
        elif not final_source:
            st.error("Specify the source when 'Other' is selected.")
        else:
            run(
                "INSERT INTO income(idate, amount, source, note) VALUES (?,?,?,?)",
                (idate.isoformat(), float(amount), final_source, note.strip()),
            )
            st.success(f"Income of {inr(amount)} saved.")
            st.toast("Income saved")
            show_cash_left()


def loan_entry_form():
    mode = st.radio(
        "Action", ["Add new loan", "Record payment"],
        horizontal=True, key="loan_mode",
    )
    if mode == "Add new loan":
        # form ke bahar, taaki bayaj ka label turant badle
        ptype = st.radio(
            "How is penalty charged on late instalments?", list(LOAN_PEN_TYPES.values()),
            horizontal=True, key="loan_pen_type",
        )
        pkey = next(k for k, v in LOAN_PEN_TYPES.items() if v == ptype)
        with st.form("loan_new", clear_on_submit=True):
            name = st.text_input("Loan name", placeholder="e.g. Bank loan, Personal loan from Ramesh")
            a, b, c = st.columns(3)
            loan_amount = a.number_input("Loan amount (₹, optional)", min_value=0.0, step=1000.0, format="%.2f")
            kist = b.number_input("Instalment amount (₹)", min_value=0.0, step=100.0, format="%.2f")
            n = c.number_input("Number of instalments", min_value=1, value=12, step=1)
            d, e = st.columns(2)
            pen = d.number_input(
                {"daily": "Penalty (₹ per day)",
                 "pct": "Interest (% per month)"}.get(pkey, "Penalty (₹ per late instalment)"),
                min_value=0.0, step=0.5 if pkey == "pct" else 10.0, format="%.2f",
            )
            first = e.date_input("First due date", value=date.today())
            note = st.text_input("Note (optional)", placeholder="e.g. vehicle loan, due on the 5th")
            ok = st.form_submit_button("Save loan", type="primary", use_container_width=True)
        if ok:
            name = name.strip()
            if not name:
                st.error("Enter a loan name.")
            elif kist <= 0:
                st.error("Instalment amount must be greater than 0.")
            elif not query_df("SELECT 1 FROM loans WHERE name = ? COLLATE NOCASE", (name,)).empty:
                st.error("A loan with this name already exists. Use a different name.")
            else:
                run(
                    "INSERT INTO loans(name, loan_amount, kist_amount, total_kists, first_due, "
                    "penalty_type, penalty_amount, note) VALUES (?,?,?,?,?,?,?,?)",
                    (name, float(loan_amount), float(kist), int(n), first.isoformat(),
                     pkey, float(pen), note.strip()),
                )
                st.success(
                    f"Loan '{name}' saved: {int(n)} instalments × {inr(kist)} = {inr(kist * n)}."
                )
                st.toast("Loan saved")
        return

    loans = loans_df()
    if loans.empty:
        st.info("Add a loan first, using 'Add new loan'.")
        return
    pick = st.selectbox("Loan", loans["name"].tolist(), key="loan_pick")
    l = loans[loans["name"] == pick].iloc[0].to_dict()
    pays = loan_pay_df()
    inf = loan_summary(l, pays[pays["loan_id"] == l["id"]], date.today())
    nxt = inf["next"]
    st.caption(
        f"Instalments due: {inr(inf['pending'])}, penalty due: {inr(inf['pen_due'])}"
        + (f", next due {nxt['due'].strftime('%d %b %Y')}" if nxt else ", all instalments paid")
    )
    if inf["overdue"]:
        st.warning(f"{len(inf['overdue'])} instalment(s) overdue. Penalty accrued to date: {inr(inf['pen_total'])}")

    with st.form("loan_pay", clear_on_submit=True):
        kind = st.radio("Payment type", ["Instalment", "Penalty"], horizontal=True)
        a, b = st.columns(2)
        amount = a.number_input(
            "Amount (₹)", min_value=0.0, value=float(l["kist_amount"]), step=100.0,
            format="%.2f", key=f"lp_amt_{l['id']}",
        )
        pdate = b.date_input("Payment date", value=date.today())
        note = st.text_input("Note (optional)", placeholder="e.g. online, cash")
        ok = st.form_submit_button("Save payment", type="primary", use_container_width=True)
    if ok:
        if amount <= 0:
            st.error("Amount must be greater than 0.")
        else:
            run(
                "INSERT INTO loan_payments(loan_id, pdate, kind, amount, note) VALUES (?,?,?,?,?)",
                (int(l["id"]), pdate.isoformat(), "kist" if kind == "Instalment" else "penalty", float(amount), note.strip()),
            )
            st.success(f"{pick}: {kind.lower()} of {inr(amount)} saved.")
            st.toast("Payment saved")
            show_cash_left()


def page_new_entry():
    hero("New entry", "Record a transaction, income or loan payment")
    typ = st.radio(
        "Entry type", ["Lending / borrowing", "Income", "Loan / instalment"],
        horizontal=True, key="entry_type",
    )
    if typ == "Income":
        income_form()
        return
    if typ == "Loan / instalment":
        loan_entry_form()
        return
    parties = parties_df()
    pre = st.session_state.pop("prefill_party", None)
    options = ["-- New party --"] + parties["name"].tolist()
    idx = options.index(pre) if pre in options else 0

    with st.form("entry_form", clear_on_submit=True):
        kind = st.radio("Transaction type", list(KINDS.keys()), horizontal=True)
        a, b = st.columns(2)
        existing = a.selectbox("Existing party", options, index=idx)
        new_name = b.text_input("Or new party name", placeholder="e.g. Ramesh Sharma")
        c, d, e = st.columns(3)
        amount = c.number_input("Amount (₹)", min_value=0.0, step=100.0, format="%.2f")
        tdate = d.date_input("Date", value=date.today())
        phone = e.text_input("Phone (optional)", placeholder="98xxxxxx10")
        note = st.text_input("Note (optional)", placeholder="e.g. shop supplies, wedding expenses")
        submitted = st.form_submit_button("Save payment", type="primary", use_container_width=True)

    if submitted:
        name = new_name.strip() or ("" if existing.startswith("--") else existing)
        if not name:
            st.error("Select or enter a party name.")
        elif amount <= 0:
            st.error("Amount must be greater than 0.")
        else:
            pid = get_or_create_party(name, phone)
            run(
                "INSERT INTO txns(party_id, tdate, kind, amount, note) VALUES (?,?,?,?,?)",
                (pid, tdate.isoformat(), kind, float(amount), note.strip()),
            )
            st.success(f"Entry saved: {inr(amount)} with {name}.")
            st.toast("Entry saved")
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
        dv.error, dv.errorTitle = "Select a value from the dropdown", "Invalid value"
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

    ws5 = wb.create_sheet("Instructions")
    lines = [
        ("How to prepare the restore file", True),
        ("", False),
        ("1. Do not change the header row on any sheet. Enter data below it.", False),
        ("2. Not every sheet is required. Only sheets that contain data are imported.", False),
        ("3. You may keep or remove this Instructions sheet. It has no effect.", False),
        ("4. Enter dates as YYYY-MM-DD, for example 2026-10-27.", False),
        ("", False),
        ("Udhari sheet (lending and borrowing)", True),
        ("party  -> name of the other party (created automatically if new)", False),
        ("date   -> transaction date", False),
        ("kind   -> select from the dropdown (one of the values below):", False),
    ] + [("          - " + k, False) for k in KINDS] + [
        ("amount -> amount greater than 0, for example 1500 or 250.50", False),
        ("note   -> optional", False),
        ("", False),
        ("Income sheet", True),
        ("date, amount, note -> as above", False),
        ("source -> where the income came from (for example Salary, Bonus, Rent, or your own label)", False),
        ("", False),
        ("Loan sheet (one loan per row)", True),
        ("name           -> loan name (must be unique)", False),
        ("loan_amount    -> loan amount (optional, may be blank or 0)", False),
        ("kist_amount    -> amount of one instalment, greater than 0", False),
        ("total_kists    -> total number of instalments", False),
        ("first_due      -> due date of the first instalment (later ones fall on the same day each month)", False),
        ("penalty_type   -> fixed = once per late instalment, daily = per day of delay, pct = % interest per month", False),
        ("penalty_amount -> fixed: amount per late instalment, daily: amount per day, pct: % per month", False),
        ("note           -> optional", False),
        ("", False),
        ("Kist_Penalty sheet (instalments and penalties paid against a loan)", True),
        ("loan   -> loan name, as on the Loan sheet (loans already in the app also work)", False),
        ("date   -> payment date", False),
        ("kind   -> kist or penalty", False),
        ("amount -> amount paid", False),
        ("note   -> optional", False),
        ("", False),
        ("Exact duplicate rows are skipped, so restoring the same file twice is safe.", False),
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
    st.markdown("#### Delete all data")
    st.caption(counts)
    with st.expander("Danger zone"):
        st.error(
            "This permanently deletes all lending records, parties, income, loans and instalments. "
            "It cannot be undone. Download an Excel backup first."
        )
        sure = st.checkbox("I understand that all data will be deleted", key="wipe_sure")
        word = st.text_input("Type DELETE to confirm", key="wipe_word", placeholder="DELETE")
        st.button(
            "Delete all data", type="primary",
            disabled=not (sure and word.strip().upper() == "DELETE"),
            on_click=wipe_callback,
        )


def page_backup():
    hero("Backup & restore", "Keep a safe copy of your records")
    if st.session_state.pop("wiped", False):
        st.success("All data has been deleted.")
    st.warning(
        "On Streamlit Cloud the database file can be lost when the app restarts. "
        "Download an Excel backup regularly."
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
            f"Currently stored: {len(export)} lending entries, {len(phones)} parties, "
            f"{len(inc_export)} income entries, {len(loan_export)} loans, {len(pay_export)} instalment/penalty payments"
        )
    with c1:
        st.markdown("#### Backup")
        st.caption(
            f"{len(export)} lending entries, {len(phones)} parties, "
            f"{len(inc_export)} income entries, {len(loan_export)} loans"
        )
        st.download_button(
            "Download Excel backup",
            to_xlsx_multi({
                "Udhari": export, "Income": inc_export,
                "Loan": loan_export, "Kist_Penalty": pay_export,
            }),
            file_name=f"udhari_backup_{date.today().isoformat()}.xlsx",
            mime=XLSX_MIME, disabled=empty, type="primary",
        )
    with c2:
        st.markdown("#### Restore")
        st.download_button(
            "Download blank restore template",
            template_xlsx(),
            file_name="udhari_restore_format.xlsx",
            mime=XLSX_MIME,
            help="Fill in this template and upload it below. The Instructions sheet explains each column.",
        )
        up = st.file_uploader("Select a backup file", type=["xlsx", "csv"], label_visibility="collapsed")
        if up is not None and st.button("Restore"):
            sheets = read_backup_all(up)
            ud, ic, lo, kp = (sheets[k] for k in SHEETS)
            if all(x is None for x in (ud, ic, lo, kp)):
                st.error("The file must contain at least one of these sheets: Udhari, Income, Loan, Kist_Penalty.")
                return

            msgs = []
            if ud is not None:
                if "kind" in ud.columns:
                    ud["kind"] = ud["kind"].replace(LEGACY_KINDS)
                need = {"party", "date", "kind", "amount", "note"}
                if not need.issubset(ud.columns):
                    st.error("The Udhari sheet must have these columns: party, date, kind, amount, note")
                    return
                bad = set(ud["kind"]) - set(KINDS)
                if bad:
                    st.error(f"Unrecognised 'kind' values: {', '.join(map(str, bad))}")
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
                msgs.append(f"Udhari: {added} entries added, {skipped} already present.")

            if ic is not None:
                if not {"date", "amount", "source", "note"}.issubset(ic.columns):
                    st.error("The Income sheet must have these columns: date, amount, source, note")
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
                msgs.append(f"Income: {added} entries added, {skipped} already present.")

            if lo is not None:
                if not set(LOAN_COLS).issubset(lo.columns):
                    st.error("The Loan sheet must have these columns: " + ", ".join(LOAN_COLS))
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
                    f"Loan: {added} added, {skipped} already present, {bad} invalid rows skipped."
                )

            if kp is not None:
                if not set(PAY_COLS).issubset(kp.columns):
                    st.error("The Kist_Penalty sheet must have these columns: " + ", ".join(PAY_COLS))
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
                    f"Instalments/penalties: {added} added, {skipped} already present, {bad} invalid rows skipped."
                )

            st.success("  \n".join(msgs))


# ---------------------------------------------------------------- edit records
def edit_password():
    try:
        pw = st.secrets.get("EDIT_PASSWORD")
    except Exception:
        pw = None
    return str(pw or EDIT_PASSWORD_DEFAULT)


def edit_gate():
    """Editing is locked until the edit password is entered."""
    if st.session_state.get("edit_ok"):
        return True
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.info("Editing old records is protected. Enter the edit password to continue.")
        with st.form("edit_login"):
            entered = st.text_input("Edit password", type="password")
            ok = st.form_submit_button("Unlock editing", use_container_width=True, type="primary")
        if ok:
            if hmac.compare_digest(entered.encode(), edit_password().encode()):
                st.session_state["edit_ok"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


def lock_edit():
    """Lock the admin panel and go back to the dashboard."""
    st.session_state["edit_ok"] = False
    st.session_state["page"] = P_DASH


def cleanup_parties():
    """Remove parties that no longer have any entries."""
    run("DELETE FROM parties WHERE id NOT IN (SELECT DISTINCT party_id FROM txns)")


def delete_block(table, rid, key, warn=""):
    with st.expander("Delete this record"):
        if warn:
            st.warning(warn)
        sure = st.checkbox("Yes, delete this record permanently", key=f"del_ok_{key}_{rid}")
        if st.button("Delete", key=f"del_{key}_{rid}", disabled=not sure):
            run(f"DELETE FROM {table} WHERE id = ?", (int(rid),))
            cleanup_parties()
            st.session_state["flash"] = "Record deleted."
            st.rerun()


def _d(v):
    return date.fromisoformat(str(v)[:10])


def edit_txns():
    df = txns_df()
    if df.empty:
        st.info("No lending or borrowing entries yet.")
        return
    df = df.sort_values(["date", "id"], ascending=False)
    labels = {
        int(r["id"]): f"{r['date']} | {r['party']} | {r['kind']} | {inr(r['amount'])}"
        for _, r in df.iterrows()
    }
    rid = st.selectbox("Select entry", list(labels), format_func=labels.get, key="edit_txn_pick")
    r = df[df["id"] == rid].iloc[0]
    kinds = list(KINDS)
    with st.form(f"edit_txn_{rid}"):
        name = st.text_input("Party name (change it to move this entry to another party)", value=r["party"])
        kind = st.selectbox("Transaction type", kinds, index=kinds.index(r["kind"]) if r["kind"] in kinds else 0)
        a, b = st.columns(2)
        amount = a.number_input("Amount (₹)", min_value=0.0, value=float(r["amount"]), step=100.0, format="%.2f")
        tdate = b.date_input("Date", value=_d(r["date"]))
        note = st.text_input("Note (optional)", value=r["note"] or "")
        ok = st.form_submit_button("Save changes", type="primary", use_container_width=True)
    if ok:
        if not name.strip():
            st.error("Party name cannot be empty.")
        elif amount <= 0:
            st.error("Amount must be greater than 0.")
        else:
            pid = get_or_create_party(name)
            run(
                "UPDATE txns SET party_id=?, tdate=?, kind=?, amount=?, note=? WHERE id=?",
                (pid, tdate.isoformat(), kind, float(amount), note.strip(), int(rid)),
            )
            cleanup_parties()
            st.session_state["flash"] = "Entry updated."
            st.rerun()
    delete_block("txns", rid, "txn")


def edit_income():
    df = income_df()
    if df.empty:
        st.info("No income entries yet.")
        return
    df = df.sort_values(["date", "id"], ascending=False)
    labels = {
        int(r["id"]): f"{r['date']} | {r['source']} | {inr(r['amount'])}" for _, r in df.iterrows()
    }
    rid = st.selectbox("Select income entry", list(labels), format_func=labels.get, key="edit_inc_pick")
    r = df[df["id"] == rid].iloc[0]
    with st.form(f"edit_inc_{rid}"):
        a, b = st.columns(2)
        amount = a.number_input("Amount (₹)", min_value=0.0, value=float(r["amount"]), step=500.0, format="%.2f")
        idate = b.date_input("Date received", value=_d(r["date"]))
        source = st.text_input("Source", value=r["source"] or "")
        note = st.text_input("Note (optional)", value=r["note"] or "")
        ok = st.form_submit_button("Save changes", type="primary", use_container_width=True)
    if ok:
        if amount <= 0:
            st.error("Amount must be greater than 0.")
        elif not source.strip():
            st.error("Source cannot be empty.")
        else:
            run(
                "UPDATE income SET idate=?, amount=?, source=?, note=? WHERE id=?",
                (idate.isoformat(), float(amount), source.strip(), note.strip(), int(rid)),
            )
            st.session_state["flash"] = "Income entry updated."
            st.rerun()
    delete_block("income", rid, "inc")


def loan_total_note(loan):
    """Show instalments due + penalty = total outstanding for a loan (penalty is recalculated live)."""
    pays = loan_pay_df()
    inf = loan_summary(dict(loan), pays[pays["loan_id"] == int(loan["id"])], date.today())
    st.info(
        f"Instalments due {inr(inf['pending'])} + penalty due {inr(inf['pen_due'])} "
        f"= total outstanding {inr(inf['pending'] + inf['pen_due'])}  \n"
        f"Penalty accrued so far {inr(inf['pen_total'])}, penalty paid {inr(inf['pen_paid'])}."
    )


def edit_loans():
    df = loans_df()
    if df.empty:
        st.info("No loans yet.")
        return
    labels = {int(r["id"]): f"{r['name']} | {inr(r['kist_amount'])} × {int(r['total_kists'])}" for _, r in df.iterrows()}
    rid = st.selectbox("Select loan", list(labels), format_func=labels.get, key="edit_loan_pick")
    r = df[df["id"] == rid].iloc[0]
    loan_total_note(r)
    ptypes = list(LOAN_PEN_TYPES)
    with st.form(f"edit_loan_{rid}"):
        name = st.text_input("Loan name", value=r["name"])
        a, b, c = st.columns(3)
        loan_amount = a.number_input("Loan amount (₹, optional)", min_value=0.0, value=float(r["loan_amount"] or 0), step=1000.0, format="%.2f")
        kist = b.number_input("Instalment amount (₹)", min_value=0.0, value=float(r["kist_amount"]), step=100.0, format="%.2f")
        n = c.number_input("Number of instalments", min_value=1, value=int(r["total_kists"]), step=1)
        d, e, f = st.columns(3)
        ptype = d.selectbox(
            "Penalty type", ptypes, format_func=LOAN_PEN_TYPES.get,
            index=ptypes.index(r["penalty_type"]) if r["penalty_type"] in ptypes else 0,
        )
        pen = e.number_input("Penalty amount / % ", min_value=0.0, value=float(r["penalty_amount"]), step=10.0, format="%.2f")
        first = f.date_input("First due date", value=_d(r["first_due"]))
        note = st.text_input("Note (optional)", value=r["note"] or "")
        ok = st.form_submit_button("Save changes", type="primary", use_container_width=True)
    if ok:
        name = name.strip()
        if not name:
            st.error("Enter a loan name.")
        elif kist <= 0:
            st.error("Instalment amount must be greater than 0.")
        elif not query_df(
            "SELECT 1 FROM loans WHERE name = ? COLLATE NOCASE AND id != ?", (name, int(rid))
        ).empty:
            st.error("Another loan already has this name.")
        else:
            run(
                "UPDATE loans SET name=?, loan_amount=?, kist_amount=?, total_kists=?, first_due=?, "
                "penalty_type=?, penalty_amount=?, note=? WHERE id=?",
                (name, float(loan_amount), float(kist), int(n), first.isoformat(),
                 ptype, float(pen), note.strip(), int(rid)),
            )
            st.session_state["flash"] = "Loan updated."
            st.rerun()
    delete_block("loans", rid, "loan", "Deleting a loan also deletes all its instalment and penalty payments.")


def edit_loan_payments():
    df = loan_pay_df()
    if df.empty:
        st.info("No instalment or penalty payments yet.")
        return
    df = df.sort_values(["date", "id"], ascending=False)
    labels = {
        int(r["id"]): f"{r['date']} | {r['loan']} | {r['kind']} | {inr(r['amount'])}"
        for _, r in df.iterrows()
    }
    rid = st.selectbox("Select payment", list(labels), format_func=labels.get, key="edit_pay_pick")
    r = df[df["id"] == rid].iloc[0]
    loans = loans_df()
    loan_ids = {row["name"]: int(row["id"]) for row in loans.to_dict("records")}
    names = list(loan_ids)
    kinds = ["kist", "penalty"]
    if r["loan"] in names:
        loan_total_note(loans[loans["id"] == r["loan_id"]].iloc[0])
    with st.form(f"edit_pay_{rid}"):
        loan = st.selectbox("Loan", names, index=names.index(r["loan"]) if r["loan"] in names else 0)
        kind = st.radio(
            "Payment type", kinds, horizontal=True,
            format_func=lambda k: "Instalment" if k == "kist" else "Penalty",
            index=kinds.index(r["kind"]) if r["kind"] in kinds else 0,
        )
        a, b = st.columns(2)
        amount = a.number_input("Amount (₹)", min_value=0.0, value=float(r["amount"]), step=100.0, format="%.2f")
        pdate = b.date_input("Payment date", value=_d(r["date"]))
        note = st.text_input("Note (optional)", value=r["note"] or "")
        ok = st.form_submit_button("Save changes", type="primary", use_container_width=True)
    if ok:
        if amount <= 0:
            st.error("Amount must be greater than 0.")
        else:
            run(
                "UPDATE loan_payments SET loan_id=?, pdate=?, kind=?, amount=?, note=? WHERE id=?",
                (loan_ids[loan], pdate.isoformat(), kind, float(amount), note.strip(), int(rid)),
            )
            st.session_state["flash"] = "Payment updated."
            st.rerun()
    delete_block("loan_payments", rid, "pay")


IN_KINDS = ("Repayment received", "Money borrowed")


def all_transactions():
    """Every money movement (lending, income, loan payments) in one table."""
    rows = []
    for r in txns_df().itertuples():
        rows.append({
            "Date": r.date, "Group": "Lending / borrowing", "Type": r.kind, "Party / loan": r.party,
            "Direction": "In" if r.kind in IN_KINDS else "Out", "Amount": float(r.amount), "Note": r.note or "",
        })
    for r in income_df().itertuples():
        rows.append({
            "Date": r.date, "Group": "Income", "Type": "Income", "Party / loan": r.source,
            "Direction": "In", "Amount": float(r.amount), "Note": r.note or "",
        })
    for r in loan_pay_df().itertuples():
        rows.append({
            "Date": r.date, "Group": "Loan payments",
            "Type": "Instalment" if r.kind == "kist" else "Penalty", "Party / loan": r.loan,
            "Direction": "Out", "Amount": float(r.amount), "Note": r.note or "",
        })
    cols = ["Date", "Group", "Type", "Party / loan", "Direction", "Amount", "Note"]
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values("Date", ascending=False, kind="stable").reset_index(drop=True)


def admin_transactions():
    df = all_transactions()
    if df.empty:
        st.info("No transactions yet.")
        return
    f1, f2 = st.columns([1, 2])
    group = f1.selectbox("Show", ["All", "Lending / borrowing", "Income", "Loan payments"], key="adm_group")
    q = f2.text_input("Search party, loan or note", key="adm_q")
    if group != "All":
        df = df[df["Group"] == group]
    if q.strip():
        s = q.strip()
        mask = (
            df["Party / loan"].str.contains(s, case=False, regex=False)
            | df["Note"].str.contains(s, case=False, regex=False)
        )
        df = df[mask]
    money_in = float(df.loc[df["Direction"] == "In", "Amount"].sum())
    money_out = float(df.loc[df["Direction"] == "Out", "Amount"].sum())
    k1, k2, k3 = st.columns(3)
    k1.markdown(kpi("Money in", inr(money_in), f"{int((df['Direction'] == 'In').sum())} entries", "g"), unsafe_allow_html=True)
    k2.markdown(kpi("Money out", inr(money_out), f"{int((df['Direction'] == 'Out').sum())} entries", "r"), unsafe_allow_html=True)
    k3.markdown(kpi("Net", inr(money_in - money_out), "in − out", "g" if money_in >= money_out else "r"), unsafe_allow_html=True)
    st.write("")
    st.dataframe(
        df.drop(columns=["Group"]), hide_index=True, use_container_width=True,
        column_config={"Amount": st.column_config.NumberColumn(format="₹%.2f")},
    )
    st.caption("To correct or delete an entry, open 'Edit records' above.")


def page_admin():
    hero("Admin panel", "All transactions, and editing of older records")
    if not edit_gate():
        return
    c1, c2 = st.columns([5, 1])
    c1.caption("Admin panel is unlocked for this session.")
    c2.button("Lock", on_click=lock_edit, use_container_width=True)
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)
    section = st.radio(
        "Section", ["Transactions", "Edit records"], horizontal=True,
        key="admin_section", label_visibility="collapsed",
    )
    if section == "Transactions":
        admin_transactions()
        return
    sections = {
        "Lending / borrowing": edit_txns,
        "Income": edit_income,
        "Loans": edit_loans,
        "Instalment / penalty payments": edit_loan_payments,
    }
    pick = st.radio("Record type", list(sections), horizontal=True, key="edit_type")
    sections[pick]()


# ---------------------------------------------------------------- main
def main():
    init_db()
    st.markdown(CSS, unsafe_allow_html=True)
    if not check_password():
        return
    if "page" not in st.session_state or st.session_state["page"] not in PAGES:
        st.session_state["page"] = P_DASH
    st.sidebar.markdown('<div class="brand">Udhari Khata</div>', unsafe_allow_html=True)
    st.sidebar.caption("Personal ledger")
    st.sidebar.radio("Menu", PAGES, key="page", label_visibility="collapsed")

    s = summary_df()
    if not s.empty and s["entries"].sum() > 0:
        st.sidebar.divider()
        st.sidebar.metric("Net balance", inr(s["balance"].sum()))
        st.sidebar.caption(f"{len(s)} parties, {int(s['entries'].sum())} entries")

    {
        P_DASH: page_dashboard,
        P_NEW: page_new_entry,
        P_EDIT: page_admin,
        P_BACKUP: page_backup,
    }[st.session_state["page"]]()


main()
