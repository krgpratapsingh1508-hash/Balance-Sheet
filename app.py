"""Udhari Khata - paise ke len-den aur udhari ka hisab rakhne wala Streamlit app."""

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).with_name("udhari.db")

# Har tarah ki entry ka asar: +1 = samne wale se aapko milna badha, -1 = kam hua
KINDS = {
    "Maine udhar diya": 1,
    "Mujhe paise wapas mile": -1,
    "Maine udhar liya": -1,
    "Maine paise wapas diye": 1,
}

st.set_page_config(page_title="Udhari Khata", page_icon="📒", layout="wide")


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
            """
        )
        c.commit()


def get_or_create_party(name, phone=""):
    name = name.strip()
    row = query_df("SELECT id FROM parties WHERE name = ?", (name,))
    if not row.empty:
        return int(row.iloc[0]["id"])
    return run("INSERT INTO parties(name, phone) VALUES (?, ?)", (name, phone.strip()))


def parties_df():
    return query_df("SELECT id, name, phone FROM parties ORDER BY name")


def txns_df(party_id=None):
    sql = (
        "SELECT t.id, t.party_id, p.name AS party, t.tdate AS date, t.kind, "
        "t.amount, t.note FROM txns t JOIN parties p ON p.id = t.party_id"
    )
    params = ()
    if party_id is not None:
        sql += " WHERE t.party_id = ?"
        params = (int(party_id),)
    sql += " ORDER BY t.tdate, t.id"
    df = query_df(sql, params)
    df["signed"] = df["amount"] * df["kind"].map(KINDS)
    return df


def rupees(x):
    return f"₹{x:,.2f}"


# ---------------------------------------------------------------- login
def check_password():
    """Agar secrets me APP_PASSWORD set hai to login maangta hai."""
    try:
        pw = st.secrets.get("APP_PASSWORD")
    except Exception:
        pw = None
    if not pw or st.session_state.get("logged_in"):
        return True
    st.title("📒 Udhari Khata")
    entered = st.text_input("Password", type="password")
    if st.button("Login"):
        if entered == pw:
            st.session_state["logged_in"] = True
            st.rerun()
        else:
            st.error("Galat password")
    return False


# ---------------------------------------------------------------- pages
def page_dashboard():
    st.header("Dashboard")
    df = txns_df()
    if df.empty:
        st.info("Abhi koi entry nahi hai. 'Nayi Entry' se shuru kariye.")
        return
    bal = df.groupby("party")["signed"].sum()
    milna = bal[bal > 0].sum()
    dena = -bal[bal < 0].sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Aapko milna hai", rupees(milna))
    c2.metric("Aapko dena hai", rupees(dena))
    c3.metric("Net", rupees(milna - dena))

    table = bal.reset_index().rename(columns={"party": "Naam", "signed": "Balance"})
    table["Status"] = table["Balance"].apply(
        lambda b: "Aapko milna hai" if b > 0 else ("Aapko dena hai" if b < 0 else "Hisab barabar")
    )
    table["Rakam"] = table["Balance"].abs()
    table = table.sort_values("Rakam", ascending=False)
    st.subheader("Party-wise hisab")
    st.dataframe(
        table[["Naam", "Status", "Rakam"]],
        use_container_width=True,
        hide_index=True,
        column_config={"Rakam": st.column_config.NumberColumn(format="₹%.2f")},
    )


def page_new_entry():
    st.header("Nayi Entry")
    parties = parties_df()
    with st.form("entry_form", clear_on_submit=True):
        existing = st.selectbox("Purani party chuniye", ["-- nayi party --"] + parties["name"].tolist())
        new_name = st.text_input("Ya nayi party ka naam")
        phone = st.text_input("Phone (optional)")
        kind = st.selectbox("Kya hua?", list(KINDS.keys()))
        amount = st.number_input("Rakam (₹)", min_value=0.0, step=100.0, format="%.2f")
        tdate = st.date_input("Tarikh", value=date.today())
        note = st.text_input("Note (optional)")
        submitted = st.form_submit_button("Save karein")

    if submitted:
        name = new_name.strip() if new_name.strip() else ("" if existing.startswith("--") else existing)
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
            st.success(f"{name} ke saath {rupees(amount)} ki entry save ho gayi.")


def page_party():
    st.header("Party Khata")
    parties = parties_df()
    if parties.empty:
        st.info("Pehle koi entry daaliye.")
        return
    name = st.selectbox("Party", parties["name"].tolist())
    row = parties[parties["name"] == name].iloc[0]
    pid = int(row["id"])
    if row["phone"]:
        st.caption(f"📞 {row['phone']}")

    df = txns_df(pid)
    balance = df["signed"].sum()
    if balance > 0:
        st.success(f"{name} se aapko milna hai: {rupees(balance)}")
    elif balance < 0:
        st.error(f"Aapko {name} ko dena hai: {rupees(-balance)}")
    else:
        st.info("Hisab barabar hai.")

    if df.empty:
        return
    view = df.copy()
    view["Balance"] = view["signed"].cumsum()
    view = view[["id", "date", "kind", "amount", "note", "Balance"]].rename(
        columns={"id": "ID", "date": "Tarikh", "kind": "Kism", "amount": "Rakam", "note": "Note"}
    )
    st.dataframe(
        view.iloc[::-1],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rakam": st.column_config.NumberColumn(format="₹%.2f"),
            "Balance": st.column_config.NumberColumn(format="₹%.2f"),
        },
    )

    with st.expander("Entry delete karein"):
        del_id = st.selectbox("Entry ID", df["id"].tolist()[::-1])
        if st.button("Delete"):
            run("DELETE FROM txns WHERE id = ?", (int(del_id),))
            st.rerun()


def page_all():
    st.header("Saari Entries")
    df = txns_df()
    if df.empty:
        st.info("Koi entry nahi hai.")
        return
    st.dataframe(
        df.drop(columns=["party_id", "signed"]).iloc[::-1],
        use_container_width=True,
        hide_index=True,
        column_config={"amount": st.column_config.NumberColumn("Rakam", format="₹%.2f")},
    )


def page_backup():
    st.header("Backup / Restore")
    st.warning(
        "Streamlit Cloud par app restart hone par database file mit sakti hai. "
        "Isliye time-time par CSV backup download kar lijiye."
    )
    df = txns_df()
    export = df[["party", "date", "kind", "amount", "note"]]
    st.download_button(
        "⬇️ CSV backup download karein",
        export.to_csv(index=False).encode("utf-8"),
        file_name="udhari_backup.csv",
        mime="text/csv",
        disabled=export.empty,
    )

    st.subheader("Backup se restore")
    up = st.file_uploader("Backup CSV chuniye", type="csv")
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
        for _, r in data.iterrows():
            pid = get_or_create_party(str(r["party"]))
            run(
                "INSERT INTO txns(party_id, tdate, kind, amount, note) VALUES (?,?,?,?,?)",
                (pid, str(r["date"]), r["kind"], float(r["amount"]), str(r["note"])),
            )
        st.success(f"{len(data)} entries jod di gayi.")


# ---------------------------------------------------------------- main
def main():
    init_db()
    if not check_password():
        return
    st.sidebar.title("📒 Udhari Khata")
    pages = {
        "Dashboard": page_dashboard,
        "Nayi Entry": page_new_entry,
        "Party Khata": page_party,
        "Saari Entries": page_all,
        "Backup / Restore": page_backup,
    }
    choice = st.sidebar.radio("Menu", list(pages.keys()))
    pages[choice]()


main()
