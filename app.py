"""Balance Sheet - personal ledger for lending, borrowing, income and loan instalments.

Pages: Dashboard, My Savings, New entry, Settings (Edit records, Backup & restore, Profile update are inside it).
"""

import base64
import calendar
import hashlib
import json
import re
import hmac
import secrets
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
import zipfile
from contextlib import closing
from datetime import date, timedelta
from html import escape
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import altair as alt
import pandas as pd
import streamlit as st

# Har user ka alag database: data/user_<id>.db ; sabki profile: data/users.db
DATA_DIR = Path(__file__).with_name("data")
USERS_DB = DATA_DIR / "users.db"
LEGACY_DB = Path(__file__).with_name("udhari.db")  # purana single-user data (admin kholta hai)
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECS = 600
MIN_PASSWORD = 6
MAX_PHOTO_BYTES = 8 * 1024 * 1024

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

MODES = ["Cash", "Online"]  # how the money moved

INCOME_SOURCES = [
    "Salary", "Business", "Lottery", "Bonus", "Overtime", "Commission",
    "Rent", "Interest", "Gift", "Prize / Inaam", "Refund", "Other",
]

EXPENSE_CATS = [
    "Ghar / Ration", "Khana-Peena", "Petrol / Travel", "Bijli / Pani / Bill",
    "Dawai / Ilaaj", "Shopping", "Padhai / Fees", "Dukaan / Business",
    "Shaadi / Function", "Cash", "Other",
]

GREEN = "#1e7a4f"
RED = "#b4372f"
BLUE = "#0f3d4c"

P_DASH = "Dashboard"
P_NEW = "New entry"
P_EDIT = "Settings"
P_SAVE = "My Savings"
PAGES = [P_DASH, P_SAVE, P_NEW, P_EDIT]  # Admin panel is always last

# Password needed to edit or delete old records. Override with EDIT_PASSWORD in Streamlit secrets.
EDIT_PASSWORD_DEFAULT = "0610"

# ---------------------------------------------------------------- language (English / Hindi)
LANGS = {"en": "English", "hi": "हिन्दी"}

# Stored values stay as they are in the database. These only change how they are shown in English.
EN_FIX = {
    "Ghar / Ration": "Home / Groceries",
    "Khana-Peena": "Food & Drinks",
    "Petrol / Travel": "Fuel / Travel",
    "Bijli / Pani / Bill": "Electricity / Water / Bills",
    "Dawai / Ilaaj": "Medicine / Treatment",
    "Padhai / Fees": "Education / Fees",
    "Dukaan / Business": "Shop / Business",
    "Shaadi / Function": "Wedding / Function",
    "Prize / Inaam": "Prize",
}

HI = {
    # brand, pages, navigation
    "Balance Sheet": "बैलेंस शीट",
    "Personal ledger": "निजी लेन-देन खाता",
    "Dashboard": "डैशबोर्ड",
    "New entry": "नई एंट्री",
    # savings page
    "My Savings": "मेरी बचत",
    "See where your money goes and save more": "देखें पैसा कहाँ जा रहा है और ज़्यादा बचत करें",
    "Monthly savings goal (₹)": "महीने की बचत का लक्ष्य (₹)",
    "Save goal": "लक्ष्य सेव करें",
    "Goal saved.": "लक्ष्य सेव हो गया।",
    "Set a monthly savings goal to track it here.": "यहाँ ट्रैक करने के लिए महीने की बचत का लक्ष्य डालें।",
    "Earned": "कमाई",
    "Spent": "खर्च",
    "Saved": "बचत",
    "Given as udhaar": "उधार दिया",
    "income this month": "इस महीने की आय",
    "expenses + instalments + penalties": "खर्च + किस्तें + जुर्माना",
    "earned − spent − udhaar given": "कमाई − खर्च − दिया हुआ उधार",
    "lent minus repayments received": "उधार दिया − वापस मिले",
    "Where did your income go?": "आपकी कमाई कहाँ गई?",
    "Out of every ₹100 you earned this month:": "इस महीने की हर ₹100 कमाई में से:",
    "Spent on expenses": "खर्च पर गया",
    "Loan instalments / penalty": "लोन किस्त / जुर्माना",
    "Lent to others": "दूसरों को उधार",
    "Saved (kept)": "बचा हुआ",
    "Overspent": "ज़्यादा खर्च हुआ",
    "₹{v} out of every ₹100": "हर ₹100 में से ₹{v}",
    "Goal progress": "लक्ष्य की प्रगति",
    "{s} saved of {g} goal": "{g} के लक्ष्य में से {s} बचे",
    "Goal reached. Well done!": "लक्ष्य पूरा हुआ। शाबाश!",
    "You can still spend {v} per day (for {n} more days) and reach your goal.":
        "लक्ष्य पाने के लिए आप रोज़ {v} तक खर्च कर सकते हैं (बाकी {n} दिन)।",
    "Your goal is out of reach this month. Try to keep spending low for the remaining days.":
        "इस महीने लक्ष्य दूर है। बाकी दिनों में खर्च कम रखने की कोशिश करें।",
    "You have spent more than you earned this month.": "इस महीने आपने कमाई से ज़्यादा खर्च किया है।",
    "Biggest spending categories this month": "इस महीने सबसे ज़्यादा खर्च की श्रेणियाँ",
    "No expenses recorded this month.": "इस महीने कोई खर्च दर्ज नहीं है।",
    "Tip: cutting {c} by 10% would save you {v} every month.":
        "सुझाव: {c} में 10% कम करने से हर महीने {v} बचेंगे।",
    "Last 6 months: saved vs spent": "पिछले 6 महीने: बचत बनाम खर्च",
    "Total saved over all months: {v}": "सभी महीनों की कुल बचत: {v}",
    "Monthly limit for a category": "किसी श्रेणी की महीने की सीमा",
    "Category limits": "श्रेणी की सीमाएँ",
    "Set a monthly limit per category (0 = no limit). You will see a warning when you cross it.":
        "हर श्रेणी की महीने की सीमा तय करें (0 = कोई सीमा नहीं)। सीमा पार होने पर चेतावनी दिखेगी।",
    "Save limits": "सीमाएँ सेव करें",
    "Limits saved.": "सीमाएँ सेव हो गईं।",
    "Limit crossed: {c} spent {s} of {l}": "सीमा पार: {c} में {l} में से {s} खर्च हो गए",
    "{c}: {s} of {l}": "{c}: {l} में से {s}",
    "Add some income and expenses first to see your savings.":
        "बचत देखने के लिए पहले कुछ आय और खर्च दर्ज करें।",
    "Admin panel": "एडमिन पैनल",
    "Backup & restore": "बैकअप और रिस्टोर",
    "Sign in to access your ledger.": "अपना खाता खोलने के लिए साइन इन करें।",
    "Password": "पासवर्ड",
    "Sign in": "साइन इन",
    "Incorrect password.": "गलत पासवर्ड।",
    "Language / भाषा": "Language / भाषा",
    "Payment mode": "भुगतान का तरीका",
    "Online": "ऑनलाइन",
    "Mode": "तरीका",
    "Not specified": "तय नहीं",
    "Cash vs Online": "नकद बनाम ऑनलाइन",
    "Cash left": "नकद बचा",
    "Online left": "ऑनलाइन बचा",
    "Entries saved before the payment mode was added show as Not specified. Edit them in the Admin panel.":
        "पेमेंट मोड जुड़ने से पहले की एंट्रियाँ 'तय नहीं' दिखती हैं। उन्हें एडमिन पैनल में बदल सकते हैं।",
    # common labels
    "Amount": "राशि",
    "Amount (₹)": "राशि (₹)",
    "Date": "तारीख",
    "Note": "नोट",
    "Note (optional)": "नोट (वैकल्पिक)",
    "Name": "नाम",
    "Status": "स्थिति",
    "Month": "महीना",
    "Category": "श्रेणी",
    "Place": "जगह",
    "Entries": "एंट्रियाँ",
    "Total": "कुल",
    "Last": "आखिरी",
    "Share %": "हिस्सा %",
    "Type": "प्रकार",
    "Group": "समूह",
    "Direction": "दिशा",
    "In": "आया",
    "Out": "गया",
    "All": "सभी",
    "Other": "अन्य",
    "Phone": "फ़ोन",
    "Phone (required)": "फ़ोन (ज़रूरी)",
    "Save changes": "बदलाव सेव करें",
    "Delete": "हटाएँ",
    "Lock": "लॉक करें",
    # statuses and kinds
    "Receivable": "मिलना बाकी",
    "Payable": "देना बाकी",
    "Settled": "चुकता",
    "Money lent": "उधार दिया",
    "Repayment received": "पैसे वापस मिले",
    "Money borrowed": "उधार लिया",
    "Repayment made": "पैसे वापस दिए",
    "Income": "आय",
    "Instalment": "किस्त",
    "Penalty": "जुर्माना",
    "Lending / borrowing": "उधार लेन-देन",
    "Loan payments": "लोन भुगतान",
    "Expense": "खर्च",
    "Expenses": "खर्च",
    "Loan": "लोन",
    "Loans": "लोन",
    "Loan / instalment": "लोन / किस्त",
    # income sources and expense categories
    "Salary": "वेतन",
    "Business": "व्यापार",
    "Lottery": "लॉटरी",
    "Bonus": "बोनस",
    "Overtime": "ओवरटाइम",
    "Commission": "कमीशन",
    "Rent": "किराया",
    "Interest": "ब्याज",
    "Gift": "उपहार",
    "Prize / Inaam": "इनाम",
    "Refund": "रिफ़ंड",
    "Ghar / Ration": "घर / राशन",
    "Khana-Peena": "खाना-पीना",
    "Petrol / Travel": "पेट्रोल / यात्रा",
    "Bijli / Pani / Bill": "बिजली / पानी / बिल",
    "Dawai / Ilaaj": "दवाई / इलाज",
    "Shopping": "शॉपिंग",
    "Padhai / Fees": "पढ़ाई / फ़ीस",
    "Dukaan / Business": "दुकान / व्यापार",
    "Shaadi / Function": "शादी / समारोह",
    # dashboard
    "No records yet. Add your first entry to get started.": "अभी कोई रिकॉर्ड नहीं है। शुरू करने के लिए पहली एंट्री जोड़ें।",
    "Add first entry": "पहली एंट्री जोड़ें",
    "Your financial position as of {d}": "{d} तक आपकी आर्थिक स्थिति",
    "from {n} parties": "{n} पार्टियों से",
    "from 1 party": "1 पार्टी से",
    "to 1 party": "1 पार्टी को",
    "1 entry, {last}": "1 एंट्री, {last}",
    "Contact": "संपर्क",
    "Call": "कॉल करें",
    "No phone number saved for this party.": "इस पार्टी का फ़ोन नंबर सेव नहीं है।",
    "to {n} parties": "{n} पार्टियों को",
    "Net balance": "शुद्ध बैलेंस",
    "receivable − payable": "मिलना बाकी − देना बाकी",
    "Income this month": "इस महीने की आय",
    "Largest balances": "सबसे बड़े बैलेंस",
    "All balances are settled.": "सभी बैलेंस चुकता हैं।",
    "Recent activity": "हाल की गतिविधि",
    "Monthly income": "मासिक आय",
    "Total income to date: {a} across {n} entries": "अब तक की कुल आय: {a} ({n} एंट्रियों में)",
    "All parties": "सभी पार्टियाँ",
    "Search by name": "नाम से खोजें",
    "Filter": "फ़िल्टर",
    "No matching parties.": "कोई मिलती-जुलती पार्टी नहीं मिली।",
    "Add entry": "एंट्री जोड़ें",
    "last entry {d}": "आखिरी एंट्री {d}",
    "no entries yet": "अभी कोई एंट्री नहीं",
    "{n} entries, {last}": "{n} एंट्रियाँ, {last}",
    "{n} entries": "{n} एंट्रियाँ",
    # cash flow
    "Cash flow": "नकद प्रवाह",
    "Total income": "कुल आय",
    "to date": "अब तक",
    "Total outflow": "कुल गया हुआ पैसा",
    "lent, repaid, instalments, penalties, expenses": "उधार दिया, चुकाया, किस्तें, जुर्माना, खर्च",
    "Net cash position": "शुद्ध नकद स्थिति",
    "income + {v} other inflow − outflow": "आय + {v} अन्य आमद − गया हुआ पैसा",
    "Net cash position: {v}": "शुद्ध नकद स्थिति: {v}",
    "Outflow: lent {a}, repaid {b}, instalments {c}, penalties {d}, expenses {e}. Other inflow: repayments received {f}, borrowed {g}.":
        "गया हुआ पैसा: उधार दिया {a}, वापस दिया {b}, किस्तें {c}, जुर्माना {d}, खर्च {e}। अन्य आमद: वापस मिले {f}, उधार लिया {g}।",
    "Monthly breakdown": "महीने का हिसाब",
    "Other inflow": "अन्य आमद",
    "Outflow": "गया हुआ पैसा",
    "Net": "शुद्ध",
    "Cumulative": "कुल जमा",
    # expenses
    "Expenses: where the money went": "खर्च: पैसा कहाँ-कहाँ गया",
    "Period": "अवधि",
    "Money in and out": "पैसा कितना आया और कितना गया",
    "Money came in": "पैसा आया",
    "Money went out": "पैसा गया",
    "Left": "बचा",
    "Left this month": "इस महीने बचा",
    "In {a} · Out {b}": "आया {a} · गया {b}",
    "came in − went out": "आया − गया",
    "This month": "इस महीने",
    "Last month": "पिछला महीना",
    "Last 3 months": "पिछले 3 महीने",
    "Last 6 months": "पिछले 6 महीने",
    "Last 12 months": "पिछले 12 महीने",
    "Choose a month": "कोई एक महीना चुनें",
    "Choose a range": "महीनों की रेंज चुनें",
    "From month": "शुरू का महीना",
    "To month": "आखिरी महीना",
    "'From month' is after 'To month'. Showing them in the right order.": "शुरू का महीना आखिरी महीने के बाद है। सही क्रम में दिखा रहे हैं।",
    "Month by month": "महीने-दर-महीने",
    "Came in": "आया",
    "Went out": "गया",
    "Came in: income {a}, repayments received {b}, borrowed {c}. Went out: lent {d}, repaid {e}, instalments {f}, penalties {g}, expenses {h}.":
        "आया: आय {a}, वापस मिले {b}, उधार लिया {c}। गया: उधार दिया {d}, वापस दिया {e}, किस्तें {f}, जुर्माना {g}, खर्च {h}।",
    "All time": "पूरा समय",
    "No expenses in this period.": "इस अवधि में कोई खर्च नहीं है।",
    "Total expenses": "कुल खर्च",
    "Biggest spend": "सबसे ज़्यादा खर्च",
    "Top category": "सबसे ऊपर की श्रेणी",
    "**Spent where**": "**कहाँ कितना गया**",
    "**Category-wise**": "**श्रेणी के अनुसार**",
    "Place-wise full list": "जगह के अनुसार पूरी सूची",
    "All expense entries": "सभी खर्च एंट्रियाँ",
    # loans
    "Loans and instalments": "लोन और किस्तें",
    "Loan outstanding": "लोन बकाया",
    "Penalty outstanding": "जुर्माना बकाया",
    "charged on late instalments": "देर से दी गई किस्तों पर लगा",
    "Overdue instalments": "देर हो चुकी किस्तें",
    "not paid on time": "समय पर नहीं चुकाई गईं",
    "instalments {a} + penalty {b}": "किस्तें {a} + जुर्माना {b}",
    "{n} overdue": "{n} की देर",
    "Penalty due": "जुर्माना बाकी",
    "Fully paid": "पूरा चुकाया",
    "On schedule": "समय पर",
    "next due {d}": "अगली किस्त {d}",
    "all instalments paid": "सभी किस्तें चुकाई गईं",
    "{k} × {n} instalments, {nxt}": "{k} × {n} किस्तें, {nxt}",
    "Outstanding (incl. penalty)": "बकाया (जुर्माना मिलाकर)",
    "{a} of {b} instalments paid": "{b} में से {a} किस्तें चुकाई गईं",
    "Penalty due: {v}": "जुर्माना बाकी: {v}",
    "Instalments due {a} + penalty {b}": "बकाया किस्तें {a} + जुर्माना {b}",
    "Instalment schedule": "किस्तों का कार्यक्रम",
    "No.": "क्र.",
    "Due date": "देय तारीख",
    "Paid on": "चुकाने की तारीख",
    "Days late": "देर के दिन",
    # income form
    "Source": "स्रोत",
    "Specify source": "स्रोत लिखें",
    "e.g. Tuition, Freelance": "जैसे: ट्यूशन, फ़्रीलांस",
    "Date received": "पैसे मिलने की तारीख",
    "e.g. overtime, commission": "जैसे: ओवरटाइम, कमीशन",
    "Save income": "आय सेव करें",
    "Amount must be greater than 0.": "राशि 0 से ज़्यादा होनी चाहिए।",
    "Specify the source when 'Other' is selected.": "'अन्य' चुनने पर स्रोत लिखना ज़रूरी है।",
    "Income of {a} saved.": "{a} की आय सेव हो गई।",
    "Income saved": "आय सेव हो गई",
    # expense form
    "Specify category": "श्रेणी लिखें",
    "e.g. Gift, Repair": "जैसे: उपहार, मरम्मत",
    "Where was it spent?": "कहाँ खर्च किया?",
    "e.g. Big Bazaar, Petrol pump, Medical store": "जैसे: बिग बाज़ार, पेट्रोल पंप, मेडिकल स्टोर",
    "e.g. monthly ration, bike petrol": "जैसे: महीने का राशन, बाइक का पेट्रोल",
    "Save expense": "खर्च सेव करें",
    "Previous places: ": "पहले की जगहें: ",
    "Enter where the money was spent.": "लिखें कि पैसा कहाँ खर्च हुआ।",
    "Specify the category when 'Other' is selected.": "'अन्य' चुनने पर श्रेणी लिखना ज़रूरी है।",
    "Expense of {a} at {p} saved.": "{p} पर {a} का खर्च सेव हो गया।",
    "Expense saved": "खर्च सेव हो गया",
    # cash spending
    "Cash": "नकद",
    "Where did the cash come from?": "नकद कहाँ से लिया?",
    "e.g. ATM, Bank, Home savings": "जैसे: ATM, बैंक, घर की बचत",
    "Cash saved. Open it under 'Cash spending' below and record where it was spent.":
        "नकद सेव हो गया। नीचे 'नकद का खर्च' में इसे खोलकर लिखें कि यह कहाँ खर्च हुआ।",
    "#### Cash spending": "#### नकद का खर्च",
    "Click a cash entry to record where that cash was spent.":
        "किसी नकद एंट्री पर क्लिक करके लिखें कि वह नकद कहाँ खर्च हुआ।",
    "{v} left": "{v} बाकी",
    "Finished": "खत्म",
    "Overspent by {v}": "{v} ज़्यादा खर्च",
    "Spent {s} of {a}": "{a} में से {s} खर्च हुआ",
    "Where was this cash spent?": "यह नकद कहाँ खर्च हुआ?",
    "e.g. Vegetables, Auto fare, Tea stall": "जैसे: सब्ज़ी, ऑटो किराया, चाय की दुकान",
    "Save cash spending": "नकद खर्च सेव करें",
    "Cash spending of {a} at {p} saved.": "{p} पर {a} का नकद खर्च सेव हो गया।",
    "Only {v} is left in this cash.": "इस नकद में सिर्फ़ {v} बाकी है।",
    "Enter where the cash was spent.": "लिखें कि नकद कहाँ खर्च हुआ।",
    "Remove a spending entry": "खर्च की कोई एंट्री हटाएँ",
    "Delete selected": "चुनी हुई हटाएँ",
    # loan form
    "Action": "क्या करना है",
    "Add new loan": "नया लोन जोड़ें",
    "Record payment": "भुगतान दर्ज करें",
    "How is penalty charged on late instalments?": "देर से दी गई किस्त पर जुर्माना कैसे लगता है?",
    "Fixed amount per late instalment (repeats for each extra month it stays unpaid)":
        "हर देर वाली किस्त पर तय रकम (जितने ज़्यादा महीने बकाया रहे, हर महीने दोहराई जाती है)",
    "Fixed amount per day of delay": "देरी के हर दिन पर तय रकम",
    "% interest per month on the late instalment (pro rata by day)": "देर वाली किस्त पर हर महीने % ब्याज (दिन के हिसाब से)",
    "Loan name": "लोन का नाम",
    "e.g. Bank loan, Personal loan from Ramesh": "जैसे: बैंक लोन, रमेश से लिया निजी लोन",
    "Loan amount (₹, optional)": "लोन की राशि (₹, वैकल्पिक)",
    "Instalment amount (₹)": "किस्त की राशि (₹)",
    "Number of instalments": "किस्तों की संख्या",
    "Penalty (₹ per day)": "जुर्माना (₹ प्रति दिन)",
    "Interest (% per month)": "ब्याज (% प्रति माह)",
    "Penalty (₹ per late instalment)": "जुर्माना (₹ प्रति देर वाली किस्त)",
    "First due date": "पहली किस्त की तारीख",
    "e.g. vehicle loan, due on the 5th": "जैसे: गाड़ी का लोन, हर महीने 5 तारीख को देय",
    "Save loan": "लोन सेव करें",
    "Enter a loan name.": "लोन का नाम लिखें।",
    "Instalment amount must be greater than 0.": "किस्त की राशि 0 से ज़्यादा होनी चाहिए।",
    "A loan with this name already exists. Use a different name.": "इस नाम का लोन पहले से मौजूद है। कोई दूसरा नाम रखें।",
    "Loan '{name}' saved: {n} instalments × {k} = {tot}.": "लोन '{name}' सेव हो गया: {n} किस्तें × {k} = {tot}।",
    "Loan saved": "लोन सेव हो गया",
    "Add a loan first, using 'Add new loan'.": "पहले 'नया लोन जोड़ें' से एक लोन जोड़ें।",
    "Instalments due: {a}, penalty due: {b}": "बकाया किस्तें: {a}, बकाया जुर्माना: {b}",
    ", next due {d}": ", अगली किस्त {d}",
    ", all instalments paid": ", सभी किस्तें चुकाई गईं",
    "{n} instalment(s) overdue. Penalty accrued to date: {p}": "{n} किस्त(ें) देर से हैं। अब तक का जुर्माना: {p}",
    "Payment type": "भुगतान का प्रकार",
    "Payment date": "भुगतान की तारीख",
    "e.g. online, cash": "जैसे: ऑनलाइन, नकद",
    "Save payment": "भुगतान सेव करें",
    "{loan}: {kind} of {a} saved.": "{loan}: {a} की {kind} सेव हो गई।",
    "Payment saved": "भुगतान सेव हो गया",
    # new entry page
    "Record a transaction, income or loan payment": "लेन-देन, आय या लोन का भुगतान दर्ज करें",
    "Entry type": "एंट्री का प्रकार",
    "-- New party --": "-- नई पार्टी --",
    "Entry saved": "एंट्री सेव हो गई",
    "Existing party": "पहले से मौजूद पार्टी",
    "Or new party name": "या नई पार्टी का नाम",
    "e.g. Ramesh Sharma": "जैसे: रमेश शर्मा",
    "This party's saved number. It is used for every entry.": "इस पार्टी का सेव किया हुआ नंबर। हर एंट्री में यही इस्तेमाल होगा।",
    "Transaction type": "लेन-देन का प्रकार",
    "e.g. shop supplies, wedding expenses": "जैसे: दुकान का सामान, शादी का खर्च",
    "Select or enter a party name.": "पार्टी चुनें या उसका नाम लिखें।",
    "Phone number is required (at least 10 digits).": "फ़ोन नंबर ज़रूरी है (कम से कम 10 अंक)।",
    "Entry saved: {a} with {n}.": "एंट्री सेव हो गई: {n} के साथ {a}।",
    # backup & restore
    "Keep a safe copy of your records": "अपने रिकॉर्ड की सुरक्षित कॉपी रखें",
    "All data has been deleted.": "सारा डेटा हटा दिया गया है।",
    "On Streamlit Cloud the database file can be lost when the app restarts. Download an Excel backup regularly.":
        "Streamlit Cloud पर ऐप रीस्टार्ट होने पर डेटाबेस फ़ाइल खो सकती है। नियमित रूप से Excel बैकअप डाउनलोड करें।",
    "#### Delete all data": "#### सारा डेटा हटाएँ",
    "Delete all data": "सारा डेटा हटाएँ",
    "Danger zone": "खतरे वाला हिस्सा",
    "This permanently deletes all lending records, parties, income, expenses, loans and instalments. It cannot be undone. Download an Excel backup first.":
        "यह उधार रिकॉर्ड, पार्टियाँ, आय, खर्च, लोन और किस्तें हमेशा के लिए हटा देगा। इसे वापस नहीं किया जा सकता। पहले Excel बैकअप डाउनलोड कर लें।",
    "I understand that all data will be deleted": "मैं समझता/समझती हूँ कि सारा डेटा हट जाएगा",
    "Type DELETE to confirm": "पुष्टि के लिए DELETE टाइप करें",
    "Currently stored: {a} lending entries, {b} parties, {c} income entries, {d} expense entries, {e} loans, {f} instalment/penalty payments":
        "अभी सेव है: {a} उधार एंट्रियाँ, {b} पार्टियाँ, {c} आय एंट्रियाँ, {d} खर्च एंट्रियाँ, {e} लोन, {f} किस्त/जुर्माना भुगतान",
    "{a} lending entries, {b} parties, {c} income entries, {d} expense entries, {e} loans":
        "{a} उधार एंट्रियाँ, {b} पार्टियाँ, {c} आय एंट्रियाँ, {d} खर्च एंट्रियाँ, {e} लोन",
    "#### Backup": "#### बैकअप",
    "Download Excel backup": "Excel बैकअप डाउनलोड करें",
    "#### Restore": "#### रिस्टोर",
    "Download blank restore template": "खाली रिस्टोर टेम्पलेट डाउनलोड करें",
    "Fill in this template and upload it below. The Instructions sheet explains each column.":
        "यह टेम्पलेट भरकर नीचे अपलोड करें। Instructions शीट में हर कॉलम समझाया गया है।",
    "Select a backup file": "बैकअप फ़ाइल चुनें",
    "Restore": "रिस्टोर करें",
    "Download master backup (one sheet)": "मास्टर बैकअप डाउनलोड करें (एक शीट)",
    "All records on a single 'Master' sheet. It can be restored directly.":
        "सारे रिकॉर्ड एक ही 'Master' शीट में। इसे सीधे रिस्टोर किया जा सकता है।",
    "Download master restore template (one sheet)": "मास्टर रिस्टोर टेम्पलेट डाउनलोड करें (एक शीट)",
    "One sheet holds everything. The 'type' column says what each row is. See the Instructions sheet.":
        "एक ही शीट में सब कुछ। 'type' कॉलम बताता है कि हर पंक्ति क्या है। Instructions शीट देखें।",
    "Master sheet: {n} rows skipped because the 'type' value was not recognised.":
        "Master शीट: {n} पंक्तियाँ छोड़ी गईं क्योंकि 'type' पहचाना नहीं गया।",
    "The file must contain at least one of these sheets: Master, Udhari, Income, Loan, Kist_Penalty, Kharcha, Parties, Cash_Kharch, Followup.":
        "फ़ाइल में इन शीट्स में से कम से कम एक होनी चाहिए: Master, Udhari, Income, Loan, Kist_Penalty, Kharcha, Parties, Cash_Kharch, Followup।",
    "The Parties sheet must have these columns: ": "Parties शीट में ये कॉलम होने चाहिए: ",
    "The Cash_Kharch sheet must have these columns: ": "Cash_Kharch शीट में ये कॉलम होने चाहिए: ",
    "The Followup sheet must have these columns: ": "Followup शीट में ये कॉलम होने चाहिए: ",
    "Parties: {a} parties restored with their phone numbers.": "पार्टियाँ: {a} पार्टियाँ फ़ोन नंबर सहित वापस आ गईं।",
    "Cash spending: {a} added, {s} already present, {b} invalid rows skipped.":
        "नकद खर्च: {a} जुड़े, {s} पहले से थे, {b} गलत पंक्तियाँ छोड़ी गईं।",
    "Follow-ups: {a} added, {s} already present.": "फ़ॉलो-अप: {a} जुड़े, {s} पहले से थे।",
    "The Udhari sheet must have these columns: party, date, kind, amount, note":
        "Udhari शीट में ये कॉलम होने चाहिए: party, date, kind, amount, note",
    "The Income sheet must have these columns: date, amount, source, note":
        "Income शीट में ये कॉलम होने चाहिए: date, amount, source, note",
    "The Kharcha sheet must have these columns: ": "Kharcha शीट में ये कॉलम होने चाहिए: ",
    "The Loan sheet must have these columns: ": "Loan शीट में ये कॉलम होने चाहिए: ",
    "The Kist_Penalty sheet must have these columns: ": "Kist_Penalty शीट में ये कॉलम होने चाहिए: ",
    "Unrecognised 'kind' values: {v}": "'kind' के ये मान पहचाने नहीं गए: {v}",
    "Udhari: {a} entries added, {s} already present.": "Udhari: {a} एंट्रियाँ जुड़ीं, {s} पहले से मौजूद थीं।",
    "Income: {a} entries added, {s} already present.": "Income: {a} एंट्रियाँ जुड़ीं, {s} पहले से मौजूद थीं।",
    "Expenses: {a} added, {s} already present, {b} invalid rows skipped.":
        "खर्च: {a} जुड़े, {s} पहले से मौजूद थे, {b} गलत पंक्तियाँ छोड़ी गईं।",
    "Loan: {a} added, {s} already present, {b} invalid rows skipped.":
        "लोन: {a} जुड़े, {s} पहले से मौजूद थे, {b} गलत पंक्तियाँ छोड़ी गईं।",
    "Instalments/penalties: {a} added, {s} already present, {b} invalid rows skipped.":
        "किस्तें/जुर्माना: {a} जुड़े, {s} पहले से मौजूद थे, {b} गलत पंक्तियाँ छोड़ी गईं।",
    # admin panel
    "All transactions and editing of older records": "सभी लेन-देन और पुराने रिकॉर्ड में बदलाव",
    "Transactions, editing of older records, backup & restore": "लेन-देन, पुराने रिकॉर्ड में बदलाव, बैकअप और रिस्टोर",
    "Editing old records is protected. Enter the edit password to continue.":
        "पुराने रिकॉर्ड में बदलाव सुरक्षित है। आगे बढ़ने के लिए एडिट पासवर्ड डालें।",
    "Edit password": "एडिट पासवर्ड",
    "Unlock editing": "बदलाव खोलें",
    "Admin panel is unlocked for this session.": "इस सत्र के लिए एडमिन पैनल खुला है।",
    "Transactions": "लेन-देन",
    "Edit records": "रिकॉर्ड बदलें",
    "Record type": "रिकॉर्ड का प्रकार",
    "Instalment / penalty payments": "किस्त / जुर्माना भुगतान",
    "Delete this record": "यह रिकॉर्ड हटाएँ",
    "Yes, delete this record permanently": "हाँ, यह रिकॉर्ड हमेशा के लिए हटाएँ",
    "Record deleted.": "रिकॉर्ड हटा दिया गया।",
    "No lending or borrowing entries yet.": "अभी कोई उधार लेन-देन एंट्री नहीं है।",
    "Select entry": "एंट्री चुनें",
    "Party name (change it to move this entry to another party)": "पार्टी का नाम (इसे बदलकर एंट्री दूसरी पार्टी में ले जा सकते हैं)",
    "This party's phone number. Changing it here updates the party's number. If you move this entry to another saved party, that party's saved number is used.":
        "इस पार्टी का फ़ोन नंबर। यहाँ बदलने पर पार्टी का नंबर अपडेट हो जाएगा। अगर एंट्री किसी दूसरी सेव पार्टी में ले जाएँ तो उसी पार्टी का सेव किया नंबर इस्तेमाल होगा।",
    "Party name cannot be empty.": "पार्टी का नाम खाली नहीं हो सकता।",
    "Entry updated.": "एंट्री अपडेट हो गई।",
    "No income entries yet.": "अभी कोई आय एंट्री नहीं है।",
    "Select income entry": "आय एंट्री चुनें",
    "Income entry updated.": "आय एंट्री अपडेट हो गई।",
    "Instalments due {a} + penalty due {b} = total outstanding {c}": "बकाया किस्तें {a} + बकाया जुर्माना {b} = कुल बकाया {c}",
    "Penalty accrued so far {d}, penalty paid {e}.": "अब तक का जुर्माना {d}, चुकाया गया जुर्माना {e}।",
    "No expense entries yet.": "अभी कोई खर्च एंट्री नहीं है।",
    "Select expense entry": "खर्च एंट्री चुनें",
    "Place cannot be empty.": "जगह खाली नहीं हो सकती।",
    "Expense updated.": "खर्च अपडेट हो गया।",
    "No loans yet.": "अभी कोई लोन नहीं है।",
    "Select loan": "लोन चुनें",
    "Penalty type": "जुर्माने का प्रकार",
    "Penalty amount / %": "जुर्माने की राशि / %",
    "Another loan already has this name.": "किसी दूसरे लोन का यही नाम है।",
    "Loan updated.": "लोन अपडेट हो गया।",
    "Deleting a loan also deletes all its instalment and penalty payments.": "लोन हटाने पर उसकी सभी किस्तें और जुर्माना भुगतान भी हट जाएँगे।",
    "No instalment or penalty payments yet.": "अभी कोई किस्त या जुर्माना भुगतान नहीं है।",
    "Select payment": "भुगतान चुनें",
    "Payment updated.": "भुगतान अपडेट हो गया।",
    "Show": "दिखाएँ",
    "Search party, loan or note": "पार्टी, लोन या नोट खोजें",
    "Party / loan": "पार्टी / लोन",
    "No transactions yet.": "अभी कोई लेन-देन नहीं है।",
    "Money in": "आया हुआ पैसा",
    "Money out": "गया हुआ पैसा",
    "in − out": "आया − गया",
    "To correct or delete an entry, open 'Edit records' above.": "किसी एंट्री को सुधारने या हटाने के लिए ऊपर 'रिकॉर्ड बदलें' खोलें।",
    "{p} parties, {n} entries": "{p} पार्टियाँ, {n} एंट्रियाँ",
    # follow-up alerts
    "Follow-ups": "फ़ॉलो-अप",
    "Return dates of unpaid entries": "बाकी एंट्रियों की वापसी की तारीखें",
    "No return date": "वापसी की तारीख नहीं (अलर्ट नहीं आएगा)",
    "After sending, press Done to clear this alert.": "संदेश भेजने के बाद 'Done' दबाएँ, तब यह अलर्ट हटेगा।",
    "OK, I have seen this": "ठीक है, मैंने देख लिया",
    "Open the Dashboard to see them.": "देखने के लिए Dashboard खोलें।",
    "In {n} days": "{n} दिन बाद",
    "Party": "पार्टी",
    "Entry date": "एंट्री की तारीख",
    "Return date": "वापसी की तारीख",
    "{name} was to return {amt} to you on {due}.": "{name} को {due} तक आपके {amt} लौटाने थे।",
    "You were to return {amt} to {name} on {due}.": "आपको {due} तक {name} के {amt} लौटाने थे।",
    "{n} days overdue": "{n} दिन की देर",
    "Due today": "आज की तारीख है",
    "Return date (lent: when they will return it, borrowed: when you will return it)":
        "वापसी की तारीख (उधार दिया: वह कब लौटाएगा, उधार लिया: आप कब लौटाओगे)",
    "Used only for 'Money lent' and 'Money borrowed'. You get an alert when this date arrives.":
        "सिर्फ़ 'उधार दिया' और 'उधार लिया' के लिए। यह तारीख आने पर आपको अलर्ट मिलेगा।",
    "Return date cannot be before the entry date.": "वापसी की तारीख एंट्री की तारीख से पहले नहीं हो सकती।",
    "Hello {name}, a gentle reminder about the {amt} I gave you. Please return it by {d}. Thank you.":
        "नमस्ते {name}, मैंने आपको जो {amt} दिए थे, उनकी याद दिलाना चाहता हूँ। कृपया {d} तक लौटा दीजिए। धन्यवाद।",
    "{n} follow-up(s) pending": "{n} फ़ॉलो-अप बाकी",
    "{name} owes you {amt}, unpaid for {days} days (since {since}).":
        "{name} को आपने {amt} दिए थे, {days} दिन हो गए (तारीख {since} से)।",
    "You owe {name} {amt}, unpaid for {days} days (since {since}).":
        "आपको {name} को {amt} देने हैं, {days} दिन हो गए (तारीख {since} से)।",
    "The date promised earlier ({d}) has passed.": "पहले बताई गई तारीख ({d}) निकल चुकी है।",
    "When will they pay?": "वह पैसे कब देगा/देगी?",
    "When will you pay?": "आप पैसे कब दोगे?",
    "Save date": "तारीख सेव करें",
    "Will never pay": "कभी नहीं देगा/देगी",
    "Make message": "मैसेज बनाएँ",
    "Message to send": "भेजने वाला मैसेज",
    "OK, send on WhatsApp": "ठीक है, WhatsApp पर भेजें",
    "WhatsApp opens with this message ready. Tap send there.":
        "WhatsApp इसी मैसेज के साथ खुलेगा। वहाँ सेंड दबा दें।",
    "Done": "हो गया",
    "No phone number saved for this party, so WhatsApp cannot be opened.":
        "इस पार्टी का फ़ोन नंबर सेव नहीं है, इसलिए WhatsApp नहीं खुल सकता।",
    "Marked as 'will never pay' ({n})": "'कभी नहीं देगा' चिह्नित ({n})",
    "Ask again": "फिर से पूछें",
    "Hello {name}, I owe you {amt}. It will be paid by {d}. Thank you for your patience.":
        "नमस्ते {name}, मुझे आपके {amt} देने हैं। यह राशि {d} तक चुका दी जाएगी। धैर्य रखने के लिए धन्यवाद।",
}

NEW_HI = {
    "Settings": "सेटिंग्स",
    "Profile": "प्रोफ़ाइल",
    "Profile update": "प्रोफ़ाइल अपडेट",
    "This replaces the current data of all users in the zip.": "इससे zip में मौजूद सभी यूज़र का मौजूदा डेटा बदल जाएगा।",
    "Type RESTORE to confirm": "पुष्टि के लिए RESTORE लिखें",
    "Type RESTORE in the box to confirm.": "पुष्टि के लिए बॉक्स में RESTORE लिखें।",
    "First choose the backup zip file.": "पहले बैकअप zip फ़ाइल चुनें।",
    "Please tick the box to confirm.": "पुष्टि के लिए बॉक्स पर टिक करें।",
    "Photo": "फ़ोटो",
    "Change admin password": "एडमिन पासवर्ड बदलें",
    "Admin password updated.": "एडमिन पासवर्ड बदल गया।",
    "Update profile details": "प्रोफ़ाइल की जानकारी बदलें",
    "Your current details": "आपकी मौजूदा जानकारी",
    "#### 🔒 Change password": "#### 🔒 पासवर्ड बदलें",
    "#### 👤 Update profile details": "#### 👤 प्रोफ़ाइल की जानकारी बदलें",
    "Current password": "मौजूदा पासवर्ड",
    "New password": "नया पासवर्ड",
    "Current password is incorrect.": "मौजूदा पासवर्ड गलत है।",
    "New password must be different from the current one.": "नया पासवर्ड मौजूदा पासवर्ड से अलग होना चाहिए।",
    "Password updated.": "पासवर्ड बदल गया।",
    "Password changes take effect immediately.": "पासवर्ड तुरंत बदल जाता है।",
    "Name, father's name, age and photo changes are applied only after the admin verifies them. Until then your old details stay.":
        "नाम, पिता का नाम, उम्र और फ़ोटो में बदलाव एडमिन के जाँचने के बाद ही लागू होते हैं। तब तक पुरानी जानकारी ही रहेगी।",
    "Your photo (leave empty to keep the current one)": "आपकी फ़ोटो (खाली छोड़ें तो पुरानी रहेगी)",
    "Send for verification": "जाँच के लिए भेजें",
    "No change found. Edit a detail first.": "कोई बदलाव नहीं मिला। पहले कोई जानकारी बदलें।",
    "Your update request has been sent to the admin. Until it is approved, your old details stay.":
        "आपकी बदलाव रिक्वेस्ट एडमिन को भेज दी गई है। मंज़ूर होने तक पुरानी जानकारी रहेगी।",
    "Waiting for admin approval": "एडमिन की मंज़ूरी का इंतज़ार",
    "Requested details": "माँगी गई नई जानकारी",
    "Cancel request": "रिक्वेस्ट रद्द करें",
    "Request cancelled.": "रिक्वेस्ट रद्द हो गई।",
    "Profile settings are only for user accounts.": "प्रोफ़ाइल सेटिंग सिर्फ़ यूज़र खाते के लिए है।",
    "#### ✏️ Profile update requests": "#### ✏️ प्रोफ़ाइल बदलाव रिक्वेस्ट",
    "No profile update requests.": "कोई प्रोफ़ाइल बदलाव रिक्वेस्ट नहीं है।",
    "{n} profile update request(s) are waiting for your verification.":
        "{n} प्रोफ़ाइल बदलाव रिक्वेस्ट आपकी जाँच का इंतज़ार कर रही हैं।",
    "Old": "पुराना", "New": "नया",
    "Profile update approved.": "प्रोफ़ाइल बदलाव मंज़ूर हो गया।",
    "Profile update rejected.": "प्रोफ़ाइल बदलाव अस्वीकार हो गया।",
    "Section": "विभाग",
    "Transactions, editing of older records, backup & restore, profile":
        "लेन-देन, पुराने रिकॉर्ड में बदलाव, बैकअप और रिस्टोर, प्रोफ़ाइल",
    "Sign in, or create your own account.": "साइन इन करें, या अपना खाता बनाएँ।",
    "Login": "लॉगिन", "Create account": "खाता बनाएँ", "Forgot password": "पासवर्ड भूल गए",
    "Account": "खाता",
    "A new account is created only after the admin verifies it.": "नया खाता तभी बनता है जब एडमिन उसे जाँच लेता है।",
    "Your photo": "आपकी फ़ोटो",
    "Take a clear photo of your face, or choose one from the gallery.": "अपने चेहरे की साफ़ फ़ोटो खींचें, या गैलरी से चुनें।",
    "Please add your photo.": "कृपया अपनी फ़ोटो जोड़ें।",
    "This photo could not be read. Please choose a JPG or PNG image.": "यह फ़ोटो पढ़ी नहीं जा सकी। कृपया JPG या PNG फ़ोटो चुनें।",
    "OK, send my request": "ठीक है, मेरी रिक्वेस्ट भेजें",
    "Your request has been sent to the admin. You can log in after the admin approves it.":
        "आपकी रिक्वेस्ट एडमिन को भेज दी गई है। एडमिन के मंज़ूर करने के बाद आप लॉगिन कर सकेंगे।",
    "Go to Login": "लॉगिन पर जाएँ",
    "Your account is waiting for admin approval. Please try again after the admin approves it.":
        "आपका खाता एडमिन की मंज़ूरी का इंतज़ार कर रहा है। एडमिन के मंज़ूर करने के बाद फिर कोशिश करें।",
    "Your account request was not approved. Please contact the admin.": "आपकी खाता रिक्वेस्ट मंज़ूर नहीं हुई। कृपया एडमिन से संपर्क करें।",
    "A request for this number is already waiting for admin approval.": "इस नंबर की रिक्वेस्ट पहले से एडमिन की मंज़ूरी का इंतज़ार कर रही है।",
    "#### 🕒 Pending requests": "#### 🕒 लंबित रिक्वेस्ट", "No pending requests.": "कोई लंबित रिक्वेस्ट नहीं है।",
    "{n} account request(s) are waiting for your approval.": "{n} खाता रिक्वेस्ट आपकी मंज़ूरी का इंतज़ार कर रही हैं।",
    "Approve": "मंज़ूर करें", "Reject": "अस्वीकार करें", "Block": "ब्लॉक करें", "Status": "स्थिति",
    "approved": "मंज़ूर", "pending": "प्रतीक्षा में", "rejected": "अस्वीकृत",
    "User approved.": "यूज़र मंज़ूर हो गया।", "User blocked.": "यूज़र ब्लॉक हो गया।", "Request rejected.": "रिक्वेस्ट अस्वीकार हो गई।",
    "Continue": "आगे बढ़ें", "Step {n} of 3": "चरण {n} / 3",
    "To reset your password, please contact the admin. The admin can set a new password for you.":
        "पासवर्ड रीसेट करने के लिए एडमिन से संपर्क करें। एडमिन आपके लिए नया पासवर्ड सेट कर सकता है।",
    "Free mode: OTP is off. New users register without OTP, and you reset forgotten passwords from here. Add FAST2SMS_KEY in Secrets to turn OTP on.":
        "फ्री मोड: OTP बंद है। नए यूज़र बिना OTP के रजिस्टर होते हैं, और भूले हुए पासवर्ड आप यहीं से रीसेट करें। OTP चालू करने के लिए Secrets में FAST2SMS_KEY जोड़ें।",
    "The SMS service is not set up yet, so OTP cannot be sent. Please contact the admin.":
        "SMS सेवा अभी चालू नहीं है, इसलिए OTP नहीं भेजा जा सकता। कृपया एडमिन से संपर्क करें।",
    "SMS is not set up: new users cannot register and nobody can reset a password. Add FAST2SMS_KEY in the app Secrets.":
        "SMS चालू नहीं है: नए यूज़र रजिस्टर नहीं कर सकते और कोई पासवर्ड रीसेट नहीं कर सकता। ऐप के Secrets में FAST2SMS_KEY जोड़ें।", "Login as": "इस रूप में लॉगिन करें", "User": "यूज़र",
    "#### 🔑 Login": "#### 🔑 लॉगिन",
    "#### 🆕 Create account": "#### 🆕 खाता बनाएँ",
    "#### 🔁 Forgot password": "#### 🔁 पासवर्ड भूल गए",
    "#### 📱 Mobile number": "#### 📱 मोबाइल नंबर",
    "Mobile number (your username)": "मोबाइल नंबर (यही आपका यूज़र नाम है)",
    "Mobile number": "मोबाइल नंबर",
    "This number will be your username.": "यही नंबर आपका यूज़र नाम होगा।",
    "Enter your mobile number and password.": "अपना मोबाइल नंबर और पासवर्ड डालें।",
    "Incorrect mobile number or password.": "मोबाइल नंबर या पासवर्ड गलत है।",
    "Too many wrong attempts. Try again after 10 minutes.": "बहुत ज़्यादा गलत कोशिशें। 10 मिनट बाद फिर कोशिश करें।",
    "Enter a valid 10-digit mobile number.": "सही 10 अंकों का मोबाइल नंबर डालें।",
    "This number is already registered. Please log in.": "यह नंबर पहले से रजिस्टर है। कृपया लॉगिन करें।",
    "This number is not registered. Please create an account.": "यह नंबर रजिस्टर नहीं है। कृपया खाता बनाएँ।",
    "Send OTP": "OTP भेजें", "Verify OTP": "OTP जाँचें", "Resend OTP": "OTP दोबारा भेजें",
    "Change number": "नंबर बदलें",
    "Enter the 6-digit OTP": "6 अंकों का OTP डालें",
    "OTP sent to +91 {p}": "+91 {p} पर OTP भेजा गया",
    "Demo mode: the SMS service is not set up, so the OTP is shown here: {o}":
        "डेमो मोड: SMS सेवा चालू नहीं है, इसलिए OTP यहाँ दिख रहा है: {o}",
    "Wrong OTP. {n} tries left.": "OTP गलत है। {n} कोशिशें बाकी हैं।",
    "Too many wrong OTPs. Tap Resend OTP to get a new one.": "बहुत ज़्यादा गलत OTP। नया OTP पाने के लिए 'OTP दोबारा भेजें' दबाएँ।",
    "OTP expired. Tap Resend OTP to get a new one.": "OTP की समय सीमा खत्म। नया OTP पाने के लिए 'OTP दोबारा भेजें' दबाएँ।",
    "OTP could not be sent. Please try again in a minute.": "OTP नहीं भेजा जा सका। एक मिनट बाद फिर कोशिश करें।",
    "Please wait 30 seconds before asking for a new OTP.": "नया OTP माँगने से पहले 30 सेकंड रुकें।",
    "Too many OTP requests for this number. Try again after 1 hour.": "इस नंबर पर बहुत OTP माँगे गए। 1 घंटे बाद कोशिश करें।",
    "Step {n} of 4": "चरण {n} / 4",
    "Number verified: {p}": "नंबर सत्यापित: {p}",
    "Full name": "पूरा नाम", "Father's name": "पिता का नाम", "Age": "उम्र",
    "Save and continue": "सेव करें और आगे बढ़ें",
    "Enter a valid name and father's name.": "सही नाम और पिता का नाम डालें।",
    "Username: {p}": "यूज़र नाम: {p}",
    "Create password": "पासवर्ड बनाएँ", "Confirm password": "पासवर्ड दोबारा डालें",
    "At least 6 characters.": "कम से कम 6 अक्षर।",
    "OK, create my account": "ठीक है, मेरा खाता बनाएँ",
    "Password must be at least 6 characters.": "पासवर्ड कम से कम 6 अक्षर का होना चाहिए।",
    "Both passwords must be the same.": "दोनों पासवर्ड एक जैसे होने चाहिए।",
    "Account created. Your username is {p}.": "खाता बन गया। आपका यूज़र नाम {p} है।",
    "New password": "नया पासवर्ड", "Change password": "पासवर्ड बदलें",
    "Password changed. Please log in.": "पासवर्ड बदल गया। कृपया लॉगिन करें।",
    "Password changed.": "पासवर्ड बदल गया।",
    "🛠 Admin login": "🛠 एडमिन लॉगिन", "Admin ID": "एडमिन आईडी", "Admin password": "एडमिन पासवर्ड",
    "Admin sign in": "एडमिन साइन इन", "Admin": "एडमिन",
    "Incorrect admin ID or password.": "एडमिन आईडी या पासवर्ड गलत है।",
    "A default admin password is in use. Set ADMIN_PASSWORD in the app Secrets.":
        "डिफ़ॉल्ट एडमिन पासवर्ड चल रहा है। ऐप के Secrets में ADMIN_PASSWORD सेट करें।",
    "Logout": "लॉगआउट",
    "Editing old records is protected. Enter your account password to continue.":
        "पुराने रिकॉर्ड बदलना सुरक्षित है। आगे बढ़ने के लिए अपना खाता पासवर्ड डालें।",
    "Account password": "खाता पासवर्ड",
    "Admin — all users": "एडमिन — सभी यूज़र", "Every person's profile and ledger": "हर व्यक्ति की प्रोफ़ाइल और खाता-बही",
    "On Streamlit Cloud the files can be lost when the app restarts. Download a full backup regularly.":
        "Streamlit Cloud पर ऐप रीस्टार्ट होने पर फ़ाइलें मिट सकती हैं। नियमित रूप से पूरा बैकअप डाउनलोड करें।",
    "Total users": "कुल यूज़र", "Joined today": "आज जुड़े",
    "#### All users": "#### सभी यूज़र", "No users yet.": "अभी कोई यूज़र नहीं है।",
    "ID": "आईडी", "Mobile": "मोबाइल", "Joined": "जुड़ने की तारीख",
    "Last login": "आखिरी लॉगिन", "Entries": "एंट्री",
    "#### Manage a user": "#### यूज़र संभालें", "Select user": "यूज़र चुनें",
    "Open this user's ledger": "इस यूज़र की खाता-बही खोलें",
    "Reset this user's password": "इस यूज़र का पासवर्ड रीसेट करें",
    "Delete this user": "इस यूज़र को हटाएँ",
    "This permanently deletes the user and all of their data.": "इससे यूज़र और उसका सारा डेटा हमेशा के लिए हट जाएगा।",
    "Type the mobile number {p} to confirm": "पुष्टि के लिए मोबाइल नंबर {p} लिखें",
    "Delete user": "यूज़र हटाएँ", "User deleted.": "यूज़र हटा दिया गया।",
    "Old data (from before accounts)": "पुराना डेटा (खाते बनने से पहले का)",
    "{n} entries in the old single-user file.": "पुरानी फ़ाइल में {n} एंट्री हैं।",
    "Open old data": "पुराना डेटा खोलें", "Old data": "पुराना डेटा",
    "Copy the old data to the selected user (replaces that user's current data)":
        "पुराना डेटा चुने हुए यूज़र को दें (उसका मौजूदा डेटा बदल जाएगा)",
    "Give old data to selected user": "पुराना डेटा चुने हुए यूज़र को दें",
    "Old data copied.": "पुराना डेटा कॉपी हो गया।",
    "#### Backup & restore of everything": "#### सबका बैकअप और रिस्टोर",
    "Download full backup (zip)": "पूरा बैकअप डाउनलोड करें (zip)",
    "Restore full backup": "पूरा बैकअप रिस्टोर करें", "Backup zip": "बैकअप zip",
    "I understand this replaces the current data of all users in the zip":
        "मैं समझता/समझती हूँ कि zip में मौजूद सभी यूज़र का मौजूदा डेटा बदल जाएगा",
    "Restore": "रिस्टोर", "Backup restored.": "बैकअप रिस्टोर हो गया।",
    "This file is not a valid backup of this app.": "यह फ़ाइल इस ऐप का सही बैकअप नहीं है।",
    "Viewing: {n}": "देख रहे हैं: {n}", "Back to all users": "सभी यूज़र पर वापस",
}
HI.update(NEW_HI)

HI_MONTHS = {
    "January": "जनवरी", "February": "फ़रवरी", "March": "मार्च", "April": "अप्रैल",
    "May": "मई", "June": "जून", "July": "जुलाई", "August": "अगस्त",
    "September": "सितंबर", "October": "अक्टूबर", "November": "नवंबर", "December": "दिसंबर",
    "Jan": "जन", "Feb": "फ़र", "Mar": "मार्च", "Apr": "अप्रै", "Jun": "जून",
    "Jul": "जुल", "Aug": "अग", "Sep": "सित", "Oct": "अक्टू", "Nov": "नव", "Dec": "दिस",
}
_MONTH_RE = re.compile(r"\b(" + "|".join(sorted(HI_MONTHS, key=len, reverse=True)) + r")\b")


def lang():
    code = st.session_state.get("lang", "en")
    return code if code in LANGS else "en"


def t(s):
    """Translate a UI string. Unknown strings (names, numbers, user data) pass through unchanged."""
    if not isinstance(s, str):
        return s
    if lang() == "hi":
        return HI.get(s, s)
    return EN_FIX.get(s, s)


def tf(template, **kw):
    """Translate a template that has {placeholders}, then fill the values in."""
    return t(template).format(**kw)


def fdate(d, fmt="%d %b %Y"):
    out = d.strftime(fmt)
    if lang() == "hi":
        out = _MONTH_RE.sub(lambda m: HI_MONTHS[m.group(1)], out)
    return out


def show_df(df, column_config=None, **kw):
    """st.dataframe with translated column names and translated text cells."""
    df = df.copy()
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            df[c] = df[c].map(lambda v: t(v) if isinstance(v, str) else v)
    df = df.rename(columns=lambda c: t(c) if isinstance(c, str) else c)
    if column_config:
        column_config = {(t(k) if isinstance(k, str) else k): v for k, v in column_config.items()}
    st.dataframe(df, column_config=column_config, **kw)


def get_setting(key, default=""):
    row = query_df("SELECT value FROM settings WHERE key = ?", (key,))
    return row.iloc[0]["value"] if not row.empty else default


def set_setting(key, value):
    run(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def load_language():
    if "lang" not in st.session_state:
        saved = get_setting("lang", "en")
        st.session_state["lang"] = saved if saved in LANGS else "en"


def language_picker(save=True):
    """English / Hindi switch. The choice is saved, so it applies to the whole app."""
    codes = list(LANGS)
    cur = lang()
    pick = st.radio(
        "Language / भाषा", codes, index=codes.index(cur),
        format_func=LANGS.get, horizontal=True, key="lang_pick",
    )
    if pick != cur:
        st.session_state["lang"] = pick
        if save:
            set_setting("lang", pick)
        st.rerun()


st.set_page_config(page_title="Balance Sheet", page_icon="📒", layout="wide",
                   initial_sidebar_state="collapsed")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=Source+Serif+4:wght@600;700&display=swap');

.stApp { font-family: 'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif; }
h1, h2, h3, h4 {
    font-family: 'Source Serif 4', Georgia, serif !important;
    font-weight: 600 !important; letter-spacing: -0.01em; color: #14202b;
}
.block-container { padding-top: 4.6rem; max-width: 1180px; }
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
/* Easy tapping: big buttons, big pill choices, roomy inputs */
.stButton > button, .stDownloadButton > button, .stLinkButton > a,
div[data-testid="stFormSubmitButton"] > button {
    min-height: 3.2rem; font-size: 1.05rem; padding: 0.6rem 1.1rem; border-radius: 10px;
}
.stButton > button:active, div[data-testid="stFormSubmitButton"] > button:active { transform: scale(0.98); }
div[role="radiogroup"] { gap: 0.5rem !important; flex-wrap: wrap; }
button[kind="primary"], button[kind="secondary"] { font-weight: 600; }
div[role="radiogroup"] > label {
    min-height: 3rem; padding: 0.55rem 1rem; border: 1.5px solid #cdd5db; border-radius: 10px;
    background: #fff; cursor: pointer; align-items: center; font-size: 1.02rem;
}
div[role="radiogroup"] > label:hover { border-color: #0f3d4c; background: #f1f6f8; }
div[role="radiogroup"] > label:has(input:checked) {
    background: #0f3d4c; border-color: #0f3d4c;
}
div[role="radiogroup"] > label:has(input:checked) * { color: #fff !important; }
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div, div[data-baseweb="base-input"] {
    min-height: 3rem; font-size: 1.02rem;
}
div[data-testid="stNumberInput"] button { min-width: 2.6rem; }
div[data-testid="stExpander"] summary { padding: 0.9rem 0.8rem; font-size: 1.02rem; }
label[data-baseweb="checkbox"] { min-height: 2.8rem; align-items: center; }
section[data-testid="stSidebar"] div[role="radiogroup"] > label { width: 100%; }
@media (max-width: 640px) {
    .block-container { padding-left: 0.8rem; padding-right: 0.8rem; }
    .hero { padding: 16px 18px; }
    .kpi .val { font-size: 1.5rem; }
}

/* ================= NAYA DESIGN ================= */
:root { --navy:#0f3d4c; --teal:#1d6075; --ink:#14202b; --mut:#6b7885; --line:#d6e0e6; --card:#ffffff; }
.stApp { background: linear-gradient(180deg,#e9f1f5 0, #f6f9fb 360px, #f6f9fb 100%); line-height: 1.6; }
.stMarkdown p, .stMarkdown li { font-size: 1rem; line-height: 1.65; color: var(--ink); }

/* ---- Header band ---- */
.hero {
    background: linear-gradient(120deg,#0f3d4c 0%,#1d6075 70%,#2a8196 100%) !important;
    border-radius: 20px !important; border-bottom: 0 !important; padding: 26px 30px !important;
    box-shadow: 0 10px 28px rgba(15,61,76,.28); position: relative; overflow: hidden;
}
.hero::after { content:""; position:absolute; right:-40px; top:-60px; width:200px; height:200px;
    border-radius:50%; background: rgba(255,255,255,.08); }
.hero h1 { color:#fff !important; font-size: 2rem !important; }
.hero p, .stMarkdown .hero p { color:#d5e8ee !important; font-size:1rem !important; }

/* ---- Titles: sabse bada -> chhota ---- */
h3 { font-size:1.45rem !important; color:var(--navy) !important; }
h4 { font-size:1.3rem !important; color:var(--navy) !important; border-left:6px solid #2a8196;
     padding-left:12px; margin:.8rem 0 .3rem; }
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] label {
    border:0 !important; background:transparent !important; box-shadow:none !important;
    padding:0 !important; min-height:0 !important; display:block !important;
}
[data-testid="stWidgetLabel"] p { font-size:1.08rem !important; font-weight:700 !important; color:var(--navy) !important; margin-bottom:2px; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {
    font-size:.88rem !important; line-height:1.5 !important; color:var(--mut) !important; font-weight:400 !important;
}

/* ---- Cards: form, expander, metric ---- */
[data-testid="stForm"], [data-testid="stExpander"], [data-testid="stMetric"] {
    background:var(--card) !important; border:1px solid var(--line) !important;
    border-radius:18px !important; box-shadow:0 4px 14px rgba(15,61,76,.07);
}
[data-testid="stForm"] { padding:18px 20px !important; }
[data-testid="stMetric"] { padding:14px 18px; }
[data-testid="stMetricLabel"] p { font-size:.95rem !important; font-weight:600; color:var(--mut); }
[data-testid="stMetricValue"] { font-size:1.7rem !important; color:var(--navy); }
[data-testid="stExpander"] summary p { font-size:1.05rem !important; font-weight:700; color:var(--navy); }

/* ---- Input boxes ---- */
[data-baseweb="input"] > div, [data-baseweb="base-input"], [data-baseweb="select"] > div, textarea {
    background:#f3f7f9 !important; border:1.5px solid #cfdbe2 !important; border-radius:12px !important;
    min-height:3.1rem; transition:all .15s ease;
}
[data-baseweb="input"] input, [data-baseweb="base-input"] input, [data-baseweb="select"] div, textarea {
    font-size:1.05rem !important; color:var(--ink) !important; font-weight:500;
}
[data-baseweb="input"] > div:focus-within, [data-baseweb="select"] > div:focus-within, textarea:focus {
    background:#fff !important; border-color:var(--teal) !important; box-shadow:0 0 0 4px rgba(29,96,117,.15) !important;
}

/* ---- Choices: ek 'tab bar' ke andar badi goliyan ---- */
[data-testid="stRadio"] [role="radiogroup"] {
    background:#dfe9ee; padding:6px; border-radius:18px; gap:6px !important;
    display:inline-flex !important; flex-wrap:wrap !important; max-width:100%;
    box-shadow: inset 0 1px 3px rgba(15,61,76,.12);
}
[data-testid="stRadio"] label[data-baseweb="radio"] {
    position:relative; margin:0 !important; cursor:pointer; user-select:none;
    min-height:3.1rem !important; padding:.4rem 1.2rem !important;
    border:0 !important; border-radius:13px !important; background:transparent !important; box-shadow:none !important;
    display:inline-flex !important; align-items:center; justify-content:center; flex:1 1 auto;
    transition:all .15s ease; -webkit-tap-highlight-color:transparent;
}
[data-testid="stRadio"] label[data-baseweb="radio"]::before { content:none !important; }
[data-testid="stRadio"] label[data-baseweb="radio"] > div:first-of-type { display:none !important; }
[data-testid="stRadio"] label[data-baseweb="radio"] > div:nth-of-type(2) { display:block !important; }
[data-testid="stRadio"] label[data-baseweb="radio"] input {
    position:absolute !important; inset:0 !important; width:100% !important; height:100% !important;
    opacity:0 !important; margin:0 !important; cursor:pointer; z-index:2;
}
[data-testid="stRadio"] label[data-baseweb="radio"] p, [data-testid="stRadio"] label[data-baseweb="radio"] div {
    font-size:1rem !important; font-weight:600 !important; color:#4a5a66; line-height:1.35; text-align:center;
}
[data-testid="stRadio"] label[data-baseweb="radio"]:hover { background:rgba(255,255,255,.65) !important; }
[data-testid="stRadio"] label[data-baseweb="radio"]:active { transform:scale(.96); }
[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
    background:linear-gradient(135deg,#0f3d4c,#1d6075) !important; box-shadow:0 4px 12px rgba(15,61,76,.35) !important;
}
[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) p,
[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) div { color:#fff !important; font-weight:700 !important; }
[class*="st-key-admin_section"] [data-testid="stRadio"] label[data-baseweb="radio"] p { font-size:1.1rem !important; }
[class*="st-key-edit_type"] [data-testid="stRadio"] [role="radiogroup"] { background:transparent; box-shadow:none; padding:0; gap:8px !important; }
[class*="st-key-edit_type"] [data-testid="stRadio"] label[data-baseweb="radio"] {
    min-height:2.6rem !important; padding:.25rem 1rem !important; border:1.5px solid #b9c9d2 !important;
    background:#fff !important; border-radius:999px !important; flex:0 0 auto;
}
[class*="st-key-edit_type"] [data-testid="stRadio"] label[data-baseweb="radio"] p { font-size:.92rem !important; }
[class*="st-key-edit_type"] [data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
    background:#d4e9ef !important; border-color:#1d6075 !important; box-shadow:none !important;
}
[class*="st-key-edit_type"] [data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) p,
[class*="st-key-edit_type"] [data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) div { color:#0f3d4c !important; }

/* ---- Buttons ---- */
.stButton > button, .stDownloadButton > button, .stLinkButton > a, [data-testid="stFormSubmitButton"] > button {
    min-height:3.3rem !important; border:1.5px solid #bccbd4; border-radius:14px !important; background:#fff;
    font-weight:700 !important; box-shadow:0 2px 6px rgba(15,61,76,.10); transition:all .15s ease;
}
.stButton > button p, .stDownloadButton > button p, [data-testid="stFormSubmitButton"] > button p { font-size:1.05rem !important; font-weight:700 !important; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color:var(--teal); transform:translateY(-2px); box-shadow:0 8px 18px rgba(15,61,76,.18); }
.stButton > button:active, [data-testid="stFormSubmitButton"] > button:active { transform:scale(.97); }
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
    background:linear-gradient(135deg,#0f3d4c,#1d6075) !important; border-color:#0f3d4c !important; box-shadow:0 8px 20px rgba(15,61,76,.32);
}
.stButton > button[kind="primary"] *, [data-testid="stFormSubmitButton"] > button[kind="primary"] *, .stDownloadButton > button[kind="primary"] * { color:#fff !important; }

/* ---- Messages ---- */
[data-testid="stAlert"] { border-radius:14px; box-shadow:0 3px 10px rgba(15,61,76,.07); }
[data-testid="stAlert"] p { font-size:.98rem !important; line-height:1.55; font-weight:500; }
button[data-baseweb="tab"] p { font-size:1.05rem !important; font-weight:700; }
hr { border-color:var(--line) !important; }

/* ---- Dashboard cards ---- */
.kpi { border-radius:16px !important; box-shadow:0 4px 14px rgba(15,61,76,.08); background:#fff !important; }
.kpi .lbl { font-size:.92rem; } .kpi .sub { font-size:.86rem; }
.pmeta { font-size:.88rem; } .act .s { font-size:.86rem; } .chip { font-size:.84rem; border-radius:999px !important; }

@media (max-width:640px){
    .hero { padding:20px 20px !important; border-radius:16px !important; }
    [data-testid="stRadio"] [role="radiogroup"] { display:flex !important; width:100%; }
    [data-testid="stRadio"] label[data-baseweb="radio"] { padding:.4rem .8rem !important; }
}
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
    label, sub = t(label), t(sub)
    return (
        f'<div class="kpi {cls}"><div class="lbl">{label}</div>'
        f'<div class="val">{value}</div><div class="sub">{sub}</div></div>'
    )


def hero(title, subtitle):
    title, subtitle = t(title), t(subtitle)
    st.markdown(
        f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True
    )


def mode_pick(current="", key=None):
    """Cash / Online choice shown on every entry form."""
    idx = MODES.index(current) if current in MODES else 0
    return st.radio(t("Payment mode"), MODES, index=idx, horizontal=True, format_func=t, key=key)


def _mode_of(r, df):
    """Mode from a restored row; empty when the sheet has no mode column or the value is unknown."""
    if "mode" not in df.columns:
        return ""
    m = str(r["mode"]).strip().capitalize()
    return m if m in MODES else ""


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------- database
def run(sql, params=()):
    with closing(sqlite3.connect(db_path())) as c:
        c.execute("PRAGMA foreign_keys = ON")
        cur = c.execute(sql, params)
        c.commit()
        return cur.lastrowid


def query_df(sql, params=()):
    with closing(sqlite3.connect(db_path())) as c:
        return pd.read_sql_query(sql, c, params=params)


def init_db():
    with closing(sqlite3.connect(db_path())) as c:
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
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS expenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edate TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                place TEXT NOT NULL,
                category TEXT DEFAULT 'Other',
                note TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS cash_spends(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
                sdate TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                place TEXT NOT NULL,
                note TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS alert_acks(
                party_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
                due TEXT NOT NULL,
                PRIMARY KEY(party_id, due)
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
            CREATE TABLE IF NOT EXISTS followups(
                party_id INTEGER PRIMARY KEY REFERENCES parties(id) ON DELETE CASCADE,
                mode TEXT NOT NULL,
                promise_date TEXT DEFAULT '',
                set_on TEXT NOT NULL
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
        if "due_date" not in [row[1] for row in c.execute("PRAGMA table_info(txns)")]:
            c.execute("ALTER TABLE txns ADD COLUMN due_date TEXT DEFAULT ''")
        for tbl in ("txns", "income", "expenses", "loan_payments"):
            if "mode" not in [row[1] for row in c.execute(f"PRAGMA table_info({tbl})")]:
                c.execute(f"ALTER TABLE {tbl} ADD COLUMN mode TEXT DEFAULT ''")
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
        "t.amount, t.note, t.due_date, t.mode FROM txns t JOIN parties p ON p.id = t.party_id "
        "ORDER BY t.tdate, t.id"
    )
    df["signed"] = df["amount"] * df["kind"].map(KINDS)
    df["due_date"] = df["due_date"].fillna("")
    df["mode"] = df["mode"].fillna("")
    return df


def income_df():
    df = query_df("SELECT id, idate AS date, amount, source, note, COALESCE(mode, '') AS mode FROM income ORDER BY idate, id")
    df["month"] = df["date"].str[:7]
    return df


def expenses_df():
    df = query_df(
        "SELECT id, edate AS date, amount, place, category, note, COALESCE(mode, '') AS mode FROM expenses ORDER BY edate, id"
    )
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
        "SELECT p.id, p.loan_id, l.name AS loan, p.pdate AS date, p.kind, p.amount, p.note, COALESCE(p.mode, '') AS mode "
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


# ---------------------------------------------------------------- accounts (multi-user)
# Har user ka apna alag database (data/user_<id>.db). Sab users ki profile data/users.db me.
# Admin kisi bhi user ka data khol sakta hai. User sirf apna data dekhta hai.
AUTH_MODES = ["Login", "Create account"]
AUTH_ICONS = {"Login": "🔑 ", "Create account": "🆕 "}


def db_path():
    p = st.session_state.get("db_path")
    if not p:
        raise RuntimeError("No user data file is selected.")
    return p


def user_db_path(uid):
    return DATA_DIR / f"user_{int(uid)}.db"


def users_conn():
    DATA_DIR.mkdir(exist_ok=True)
    c = sqlite3.connect(USERS_DB)
    c.row_factory = sqlite3.Row
    return c


def init_users_db():
    with closing(users_conn()) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                father_name TEXT NOT NULL,
                age INTEGER NOT NULL,
                pw_salt TEXT NOT NULL,
                pw_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login TEXT DEFAULT '',
                fails INTEGER DEFAULT 0,
                locked_until REAL DEFAULT 0,
                status TEXT DEFAULT 'approved',
                photo BLOB
            );
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_requests(
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                father_name TEXT NOT NULL,
                age INTEGER NOT NULL,
                photo BLOB,
                requested_at TEXT NOT NULL
            )
            """
        )
        c.execute("CREATE TABLE IF NOT EXISTS admin_settings(key TEXT PRIMARY KEY, value TEXT)")
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
        if "status" not in cols:  # purane users pehle se approved maane jayenge
            c.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'approved'")
        if "photo" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN photo BLOB")
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
        if "aadhaar" in cols:  # purana version: Aadhaar column hata do
            c.executescript(
                """
                CREATE TABLE users_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    father_name TEXT NOT NULL,
                    age INTEGER NOT NULL,
                    pw_salt TEXT NOT NULL,
                    pw_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_login TEXT DEFAULT '',
                    fails INTEGER DEFAULT 0,
                    locked_until REAL DEFAULT 0,
                    status TEXT DEFAULT 'approved',
                    photo BLOB
                );
                INSERT INTO users_new(id, phone, name, father_name, age, pw_salt, pw_hash,
                                      created_at, last_login, fails, locked_until, status, photo)
                    SELECT id, phone, name, father_name, age, pw_salt, pw_hash,
                           created_at, last_login, fails, locked_until, status, photo FROM users;
                DROP TABLE users;
                ALTER TABLE users_new RENAME TO users;
                """
            )
        c.commit()


# ---- helpers: phone, password
def norm_phone(s):
    d = re.sub(r"\D", "", str(s or ""))
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d


def valid_phone(p):
    return bool(re.fullmatch(r"[6-9]\d{9}", p or ""))


def mask_phone(p):
    return "XXXXXX" + p[-4:] if p else ""


def hash_pw(password, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
    return salt, h


def check_pw(password, salt, h):
    return hmac.compare_digest(hash_pw(password, salt)[1], h)


def clean_name(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def valid_name(s):
    return len(s) >= 2 and not re.search(r"\d", s)


# ---- photo
def process_photo(raw):
    """Photo ko chhota (320x320, gol karne layak) JPEG bana deta hai. Galat file par ValueError."""
    try:
        from PIL import Image, ImageOps
        if len(raw) > MAX_PHOTO_BYTES:
            raise ValueError("too big")
        im = Image.open(BytesIO(raw))
        if im.size[0] * im.size[1] > 40_000_000:
            raise ValueError("too many pixels")
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        m = min(w, h)
        left, top = (w - m) // 2, (h - m) // 2
        im = im.crop((left, top, left + m, top + m)).resize((320, 320))
        out = BytesIO()
        im.save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception as e:
        raise ValueError("bad photo") from e


def photo_html(photo, size=56, name=""):
    """Gol photo (ya photo na ho to naam ka pehla akshar)."""
    if photo:
        b64 = base64.b64encode(bytes(photo)).decode()
        return (
            f'<img src="data:image/jpeg;base64,{b64}" style="width:{size}px;height:{size}px;'
            f'border-radius:50%;object-fit:cover;border:3px solid #fff;box-shadow:0 2px 8px rgba(15,61,76,.3);">'
        )
    ini = escape((name or "?").strip()[:1].upper() or "?")
    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:50%;background:#1d6075;color:#fff;'
        f'display:flex;align-items:center;justify-content:center;font-size:{size // 2}px;font-weight:700;">{ini}</div>'
    )


def user_photo(uid):
    with closing(users_conn()) as c:
        row = c.execute("SELECT photo FROM users WHERE id = ?", (int(uid),)).fetchone()
    return row["photo"] if row else None


# ---- users
def user_exists(phone):
    with closing(users_conn()) as c:
        return c.execute("SELECT 1 FROM users WHERE phone = ?", (phone,)).fetchone() is not None


def user_status(phone):
    with closing(users_conn()) as c:
        row = c.execute("SELECT status FROM users WHERE phone = ?", (phone,)).fetchone()
    return (row["status"] or "approved") if row else None


def set_user_status(uid, status):
    assert status in ("approved", "rejected", "pending")
    with closing(users_conn()) as c:
        c.execute("UPDATE users SET status = ? WHERE id = ?", (status, int(uid)))
        c.commit()


def create_user(phone, name, father, age, password, photo=None, status="pending"):
    """Naya account 'pending' banta hai. Admin approve kare tabhi login chalega."""
    salt, h = hash_pw(password)
    with closing(users_conn()) as c:
        try:
            cur = c.execute(
                "INSERT INTO users(phone, name, father_name, age, pw_salt, pw_hash, created_at, status, photo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (phone, name, father, int(age), salt, h, date.today().isoformat(), status, photo),
            )
            c.commit()
        except sqlite3.IntegrityError:
            return None
        return c.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()


def login_user(phone, password):
    """('ok', row) | ('locked', None) | ('bad', None) | ('pending', None) | ('rejected', None)"""
    with closing(users_conn()) as c:
        row = c.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
        if row is None:
            hash_pw(password, "00" * 16)  # same time lagta hai
            return "bad", None
        if row["locked_until"] and row["locked_until"] > time.time():
            return "locked", None
        if check_pw(password, row["pw_salt"], row["pw_hash"]):
            if (row["status"] or "approved") != "approved":
                return (row["status"] or "pending"), None
            c.execute("UPDATE users SET fails = 0, locked_until = 0, last_login = ? WHERE id = ?",
                      (date.today().isoformat(), row["id"]))
            c.commit()
            return "ok", row
        fails = int(row["fails"] or 0) + 1
        lock = time.time() + LOGIN_LOCK_SECS if fails >= LOGIN_MAX_FAILS else 0
        c.execute("UPDATE users SET fails = ?, locked_until = ? WHERE id = ?",
                  (0 if lock else fails, lock, row["id"]))
        c.commit()
        return ("locked" if lock else "bad"), None


def set_user_password(uid, password):
    salt, h = hash_pw(password)
    with closing(users_conn()) as c:
        c.execute("UPDATE users SET pw_salt = ?, pw_hash = ?, fails = 0, locked_until = 0 WHERE id = ?",
                  (salt, h, int(uid)))
        c.commit()


def verify_user_password(uid, password):
    with closing(users_conn()) as c:
        row = c.execute("SELECT pw_salt, pw_hash FROM users WHERE id = ?", (int(uid),)).fetchone()
    return bool(row) and check_pw(password, row["pw_salt"], row["pw_hash"])


def start_session(row):
    keep = st.session_state.get("lang")
    st.session_state.clear()
    if keep:
        st.session_state["lang"] = keep
    st.session_state["auth"] = {"role": "user", "uid": int(row["id"]), "phone": row["phone"], "name": row["name"]}
    st.session_state["db_path"] = str(user_db_path(row["id"]))
    init_db()
    saved = get_setting("lang", "")
    if saved in LANGS:
        st.session_state["lang"] = saved
    st.session_state["page"] = P_DASH


def logout():
    keep = st.session_state.get("lang")
    st.session_state.clear()
    if keep:
        st.session_state["lang"] = keep


# ---- login page
LOGIN_ROLES = ["User", "Admin"]


def user_login_form():
    with st.form("login_form"):
        phone = st.text_input(t("Mobile number (your username)"), max_chars=15, placeholder="98XXXXXXXX")
        pw = st.text_input(t("Password"), type="password")
        ok = st.form_submit_button(t("Sign in"), use_container_width=True, type="primary")
    if ok:
        ph = norm_phone(phone)
        if not valid_phone(ph) or not pw:
            st.error(t("Enter your mobile number and password."))
            return
        status, row = login_user(ph, pw)
        if status == "ok":
            start_session(row)
            st.rerun()
        elif status == "locked":
            st.error(t("Too many wrong attempts. Try again after 10 minutes."))
        elif status == "pending":
            st.warning(t("Your account is waiting for admin approval. Please try again after the admin approves it."))
        elif status == "rejected":
            st.error(t("Your account request was not approved. Please contact the admin."))
        else:
            st.error(t("Incorrect mobile number or password."))


def login_ui():
    """Upar dropdown: User ya Admin. User = mobile + password, Admin = admin ID + password."""
    st.markdown(t("#### 🔑 Login"))
    role = st.selectbox(
        t("Login as"), LOGIN_ROLES, key="login_role",
        format_func=lambda x: {"User": "👤 " + t("User"), "Admin": "🛠 " + t("Admin")}[x],
    )
    if role == "Admin":
        admin_login_ui()
    else:
        user_login_form()


def _reg_reset():
    st.session_state.pop("reg", None)


def goto_login():
    st.session_state["auth_mode"] = "Login"
    st.session_state.pop("reg_done", None)


def register_ui():
    """Naya account: phone -> details + photo -> password -> admin ki manzoori ka intezaar."""
    if st.session_state.get("reg_done"):
        st.success(t("Your request has been sent to the admin. You can log in after the admin approves it."))
        st.button("🔑 " + t("Go to Login"), key="go_login", on_click=goto_login, use_container_width=True)
        return
    reg = st.session_state.setdefault("reg", {"step": 1})
    step = reg["step"]
    if step >= 2 and not reg.get("phone"):
        _reg_reset()
        st.rerun()
    st.markdown(t("#### 🆕 Create account"))
    st.caption(tf("Step {n} of 3", n=step))
    st.info(t("A new account is created only after the admin verifies it."))

    if step == 1:
        with st.form("reg_phone"):
            phone = st.text_input(t("Mobile number"), max_chars=15, placeholder="98XXXXXXXX",
                                  help=t("This number will be your username."))
            ok = st.form_submit_button(t("Continue"), use_container_width=True, type="primary")
        if ok:
            ph = norm_phone(phone)
            st_ = user_status(ph) if valid_phone(ph) else None
            if not valid_phone(ph):
                st.error(t("Enter a valid 10-digit mobile number."))
            elif st_ == "pending":
                st.warning(t("A request for this number is already waiting for admin approval."))
            elif st_ == "rejected":
                st.error(t("Your account request was not approved. Please contact the admin."))
            elif st_:
                st.error(t("This number is already registered. Please log in."))
            else:
                reg.update(phone=ph, step=2)
                st.rerun()

    elif step == 2:
        st.info(tf("Username: {p}", p=reg["phone"]))
        with st.form("reg_profile"):
            name = st.text_input(t("Full name"))
            father = st.text_input(t("Father's name"))
            age = st.number_input(t("Age"), min_value=18, max_value=100, value=18, step=1)
            pic = st.file_uploader(t("Your photo"), type=["jpg", "jpeg", "png"],
                                   help=t("Take a clear photo of your face, or choose one from the gallery."))
            ok = st.form_submit_button(t("Save and continue"), use_container_width=True, type="primary")
        if ok:
            name, father = clean_name(name), clean_name(father)
            photo = None
            if pic is not None:
                try:
                    photo = process_photo(pic.getvalue())
                except ValueError:
                    photo = None
            if not valid_name(name) or not valid_name(father):
                st.error(t("Enter a valid name and father's name."))
            elif pic is None:
                st.error(t("Please add your photo."))
            elif photo is None:
                st.error(t("This photo could not be read. Please choose a JPG or PNG image."))
            else:
                reg.update(profile={"name": name, "father": father, "age": int(age), "photo": photo}, step=3)
                st.rerun()

    else:
        p = reg.get("profile")
        if not p:
            _reg_reset()
            st.rerun()
        c1, c2 = st.columns([1, 4])
        c1.markdown(photo_html(p["photo"], 72, p["name"]), unsafe_allow_html=True)
        c2.markdown(f"**{escape(p['name'])}**  \n{escape(reg['phone'])}")
        with st.form("reg_password"):
            pw = st.text_input(t("Create password"), type="password", help=t("At least 6 characters."))
            pw2 = st.text_input(t("Confirm password"), type="password")
            ok = st.form_submit_button(t("OK, send my request"), use_container_width=True, type="primary")
        if ok:
            if len(pw) < MIN_PASSWORD:
                st.error(t("Password must be at least 6 characters."))
            elif pw != pw2:
                st.error(t("Both passwords must be the same."))
            else:
                row = create_user(reg["phone"], p["name"], p["father"], p["age"], pw, photo=p["photo"])
                if row is None:
                    st.error(t("This number is already registered. Please log in."))
                else:
                    _reg_reset()
                    st.session_state["reg_done"] = True
                    st.rerun()


def admin_credentials():
    try:
        u = st.secrets.get("ADMIN_USER")
        p = st.secrets.get("ADMIN_PASSWORD") or st.secrets.get("EDIT_PASSWORD")
    except Exception:
        u = p = None
    return str(u or "admin"), str(p or EDIT_PASSWORD_DEFAULT), bool(p)


def _admin_override():
    """Admin panel se badla hua password (salt, hash). Na ho to None."""
    with closing(users_conn()) as c:
        rows = dict(c.execute("SELECT key, value FROM admin_settings WHERE key IN ('pw_salt','pw_hash')").fetchall())
    return (rows["pw_salt"], rows["pw_hash"]) if "pw_salt" in rows and "pw_hash" in rows else None


def verify_admin_password(pw):
    ov = _admin_override()
    if ov:
        return check_pw(pw, ov[0], ov[1])
    return hmac.compare_digest(pw.encode(), admin_credentials()[1].encode())


def set_admin_password(new_pw):
    salt, h = hash_pw(new_pw)
    with closing(users_conn()) as c:
        c.execute("INSERT INTO admin_settings(key, value) VALUES('pw_salt', ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (salt,))
        c.execute("INSERT INTO admin_settings(key, value) VALUES('pw_hash', ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (h,))
        c.commit()


def admin_login_ui():
    user, pw, custom = admin_credentials()
    if not custom and not _admin_override():
        st.warning(t("A default admin password is in use. Set ADMIN_PASSWORD in the app Secrets."))
    with st.form("admin_login"):
        a_user = st.text_input(t("Admin ID"))
        a_pw = st.text_input(t("Admin password"), type="password")
        ok = st.form_submit_button(t("Admin sign in"), use_container_width=True, type="primary")
    if ok:
        if time.time() < st.session_state.get("admin_lock", 0):
            st.error(t("Too many wrong attempts. Try again after 10 minutes."))
        elif (hmac.compare_digest(a_user.strip().encode(), user.encode())
              and verify_admin_password(a_pw)):
            keep = st.session_state.get("lang")
            st.session_state.clear()
            if keep:
                st.session_state["lang"] = keep
            st.session_state["auth"] = {"role": "admin"}
            st.rerun()
        else:
            n = st.session_state.get("admin_fails", 0) + 1
            st.session_state["admin_fails"] = 0 if n >= LOGIN_MAX_FAILS else n
            if n >= LOGIN_MAX_FAILS:
                st.session_state["admin_lock"] = time.time() + LOGIN_LOCK_SECS
            time.sleep(1)
            st.error(t("Incorrect admin ID or password."))


def auth_gate():
    """Sabse pehla page: Login / Create account / Admin. True = login ho chuka."""
    if st.session_state.get("auth"):
        return True
    _, mid, _ = st.columns([0.5, 2, 0.5])
    with mid:
        hero("Balance Sheet", "Sign in, or create your own account.")
        language_picker(save=False)
        mode = st.radio(
            t("Account"), AUTH_MODES, horizontal=True, key="auth_mode", label_visibility="collapsed",
            format_func=lambda x: AUTH_ICONS[x] + t(x),
        )
        {"Login": login_ui, "Create account": register_ui}[mode]()
    return False


def user_profile(uid):
    with closing(users_conn()) as c:
        return c.execute(
            "SELECT id, phone, name, father_name, age, photo FROM users WHERE id = ?", (int(uid),)
        ).fetchone()


def get_profile_request(uid):
    with closing(users_conn()) as c:
        return c.execute("SELECT * FROM profile_requests WHERE user_id = ?", (int(uid),)).fetchone()


def save_profile_request(uid, name, father, age, photo):
    """Naya request pehle wale ko replace karta hai. photo None ho to purani photo hi rahegi."""
    with closing(users_conn()) as c:
        c.execute(
            "INSERT INTO profile_requests(user_id, name, father_name, age, photo, requested_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, "
            "father_name = excluded.father_name, age = excluded.age, photo = excluded.photo, "
            "requested_at = excluded.requested_at",
            (int(uid), name, father, int(age), photo, date.today().isoformat()),
        )
        c.commit()


def delete_profile_request(uid):
    with closing(users_conn()) as c:
        c.execute("DELETE FROM profile_requests WHERE user_id = ?", (int(uid),))
        c.commit()


def apply_profile_request(uid):
    """Admin ke approve karne par naya data asli profile me chala jata hai."""
    req = get_profile_request(uid)
    if req is None:
        return
    with closing(users_conn()) as c:
        if req["photo"] is not None:
            c.execute("UPDATE users SET name=?, father_name=?, age=?, photo=? WHERE id=?",
                      (req["name"], req["father_name"], int(req["age"]), req["photo"], int(uid)))
        else:
            c.execute("UPDATE users SET name=?, father_name=?, age=? WHERE id=?",
                      (req["name"], req["father_name"], int(req["age"]), int(uid)))
        c.execute("DELETE FROM profile_requests WHERE user_id = ?", (int(uid),))
        c.commit()


def account_bar():
    a = st.session_state["auth"]
    prof = user_profile(a["uid"])
    shown_name = prof["name"] if prof else a["name"]  # admin ke approve karne ke baad naya naam dikhe
    c1, c2 = st.columns([4, 1])
    c1.markdown(
        '<div style="display:flex;align-items:center;gap:12px;">'
        + photo_html(user_photo(a["uid"]), 52, shown_name)
        + f'<div><div style="font-weight:700;font-size:1.1rem;color:#0f3d4c;">{escape(shown_name)}</div>'
        + f'<div style="font-size:.9rem;color:#6b7885;">📱 {escape(a["phone"])}</div></div></div>',
        unsafe_allow_html=True,
    )
    c2.button(t("Logout"), key="logout_btn", on_click=logout, use_container_width=True)


# ---- admin console: sab users ka data
def users_df():
    with closing(sqlite3.connect(USERS_DB)) as c:
        return pd.read_sql_query(
            "SELECT id, phone, name, father_name, age, status, created_at, last_login "
            "FROM users ORDER BY id DESC", c)


def count_entries(path):
    if not Path(path).exists():
        return 0
    try:
        with closing(sqlite3.connect(path)) as c:
            return sum(c.execute(f"SELECT COUNT(*) FROM {tb}").fetchone()[0]
                       for tb in ("txns", "income", "expenses", "loans", "loan_payments"))
    except Exception:
        return 0


def open_ledger(path, label):
    st.session_state["db_path"] = str(path)
    st.session_state["viewing"] = label
    st.session_state["page"] = P_DASH
    init_db()


def close_ledger():
    for k in ("db_path", "viewing", "edit_ok"):
        st.session_state.pop(k, None)


def zip_all_data():
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(DATA_DIR.glob("*.db")):
            z.write(p, p.name)
        if LEGACY_DB.exists():
            z.write(LEGACY_DB, "legacy_udhari.db")
    return buf.getvalue()


_RESTORE_OK = re.compile(r"^(users|user_\d+)\.db$|^legacy_udhari\.db$")


def restore_all_data(raw):
    """Zip ke andar sirf users.db, user_<n>.db, legacy_udhari.db hi allowed. Returns number of files."""
    n = 0
    with zipfile.ZipFile(BytesIO(raw)) as z:
        names = [i for i in z.namelist() if not i.endswith("/")]
        if not names or any(not _RESTORE_OK.match(i) for i in names):
            raise ValueError("bad zip")
        blobs = {i: z.read(i) for i in names}
    if any(not b.startswith(b"SQLite format 3\x00") for b in blobs.values()):
        raise ValueError("bad db")
    DATA_DIR.mkdir(exist_ok=True)
    for name, b in blobs.items():
        (LEGACY_DB if name == "legacy_udhari.db" else DATA_DIR / name).write_bytes(b)
        n += 1
    return n


def admin_pending_section():
    """Naye account ki requests: photo aur details dekhkar Approve / Reject."""
    with closing(users_conn()) as c:
        rows = c.execute(
            "SELECT id, phone, name, father_name, age, created_at, photo FROM users "
            "WHERE status = 'pending' ORDER BY id"
        ).fetchall()
    st.markdown(t("#### 🕒 Pending requests") + f" ({len(rows)})")
    if not rows:
        st.caption(t("No pending requests."))
        return
    st.warning(tf("{n} account request(s) are waiting for your approval.", n=len(rows)))
    father_label = t("Father's name")
    for r in rows:
        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            c1.markdown(photo_html(r["photo"], 96, r["name"]), unsafe_allow_html=True)
            c2.markdown(
                f"**{escape(r['name'])}**  \n"
                f"{father_label}: {escape(r['father_name'])}  \n"
                f"{t('Age')}: {r['age']} · 📱 {escape(r['phone'])} · {r['created_at']}"
            )
            b1, b2 = st.columns(2)
            if b1.button("✅ " + t("Approve"), key=f"ap_{r['id']}", type="primary", use_container_width=True):
                set_user_status(r["id"], "approved")
                st.session_state["admin_flash"] = "User approved."
                st.rerun()
            if b2.button("❌ " + t("Reject"), key=f"rj_{r['id']}", use_container_width=True):
                set_user_status(r["id"], "rejected")
                st.session_state["admin_flash"] = "Request rejected."
                st.rerun()


def admin_profile_requests_section():
    """Users ke profile badlav (naam, pita ka naam, umar, photo): admin verify kare tabhi lagu hote hain."""
    with closing(users_conn()) as c:
        rows = c.execute(
            "SELECT r.user_id, r.name, r.father_name, r.age, r.photo, r.requested_at, "
            "u.phone, u.name AS old_name, u.father_name AS old_father, u.age AS old_age, u.photo AS old_photo "
            "FROM profile_requests r JOIN users u ON u.id = r.user_id ORDER BY r.requested_at, r.user_id"
        ).fetchall()
    st.markdown(t("#### ✏️ Profile update requests") + f" ({len(rows)})")
    if not rows:
        st.caption(t("No profile update requests."))
        return
    st.warning(tf("{n} profile update request(s) are waiting for your verification.", n=len(rows)))
    father_label = t("Father's name")
    for r in rows:
        uid = int(r["user_id"])
        with st.container(border=True):
            st.markdown(f"📱 **{escape(r['phone'])}** · {r['requested_at']}")
            o, n = st.columns(2)
            o.markdown(f"**{t('Old')}**")
            o.markdown(photo_html(r["old_photo"], 72, r["old_name"]), unsafe_allow_html=True)
            o.markdown(f"{escape(r['old_name'])}  \n{father_label}: {escape(r['old_father'])}  \n{t('Age')}: {r['old_age']}")
            n.markdown(f"**{t('New')}**")
            n.markdown(photo_html(r["photo"] if r["photo"] is not None else r["old_photo"], 72, r["name"]),
                       unsafe_allow_html=True)
            n.markdown(f"{escape(r['name'])}  \n{father_label}: {escape(r['father_name'])}  \n{t('Age')}: {r['age']}")
            b1, b2 = st.columns(2)
            if b1.button("✅ " + t("Approve"), key=f"pr_ap_{uid}", type="primary", use_container_width=True):
                apply_profile_request(uid)
                st.session_state["admin_flash"] = "Profile update approved."
                st.rerun()
            if b2.button("❌ " + t("Reject"), key=f"pr_rj_{uid}", use_container_width=True):
                delete_profile_request(uid)
                st.session_state["admin_flash"] = "Profile update rejected."
                st.rerun()


def admin_console():
    hero("Admin — all users", "Every person's profile and ledger")
    c1, c2 = st.columns([4, 1])
    c1.markdown("🛠 **" + t("Admin") + "**")
    c2.button(t("Logout"), key="admin_logout", on_click=logout, use_container_width=True)
    language_picker(save=False)
    st.info(t("On Streamlit Cloud the files can be lost when the app restarts. Download a full backup regularly."))
    flash = st.session_state.pop("admin_flash", None)
    if flash:
        st.success(t(flash))

    df = users_df()
    m1, m2 = st.columns(2)
    m1.metric(t("Total users"), len(df))
    m2.metric(t("Joined today"), int((df["created_at"] == date.today().isoformat()).sum()) if not df.empty else 0)

    with st.expander("🔒 " + t("Change admin password")):
        with st.form("adm_pw_form", clear_on_submit=True):
            cur = st.text_input(t("Current password"), type="password")
            n1 = st.text_input(t("New password"), type="password", help=t("At least 6 characters."))
            n2 = st.text_input(t("Confirm password"), type="password")
            ok = st.form_submit_button(t("Change password"), type="primary", use_container_width=True)
        if ok:
            if not verify_admin_password(cur):
                st.error(t("Current password is incorrect."))
            elif len(n1) < MIN_PASSWORD:
                st.error(t("Password must be at least 6 characters."))
            elif n1 != n2:
                st.error(t("Both passwords must be the same."))
            elif n1 == cur:
                st.error(t("New password must be different from the current one."))
            else:
                set_admin_password(n1)
                st.success(t("Admin password updated."))

    admin_pending_section()
    admin_profile_requests_section()
    st.markdown(t("#### All users"))
    if df.empty:
        st.caption(t("No users yet."))
    else:
        view = df.sort_values("id").reset_index(drop=True)  # purana user upar
        view["entries"] = [count_entries(user_db_path(i)) for i in view["id"]]
        photos = []
        for i in view["id"]:
            ph = user_photo(i)
            photos.append("data:image/jpeg;base64," + base64.b64encode(bytes(ph)).decode() if ph else None)
        view.insert(1, "photo", photos)
        view["id"] = range(1, len(view) + 1)  # dikhane ke liye 1 se serial number (asli id andar alag rehti hai)
        view = view.rename(columns={
            "id": "ID", "photo": "Photo", "phone": "Mobile", "name": "Name", "father_name": "Father's name", "age": "Age",
            "status": "Status", "created_at": "Joined", "last_login": "Last login", "entries": "Entries",
        })
        show_df(view, hide_index=True, use_container_width=True,
                column_config={"Photo": st.column_config.ImageColumn("Photo", width="small")})

        st.markdown(t("#### Manage a user"))
        ids = [int(i) for i in df["id"]]
        names = {int(r.id): f"{r.name} · {r.phone}" for r in df.itertuples()}
        uid = st.selectbox(t("Select user"), ids, format_func=lambda i: names[i], key="adm_user")
        if st.button("📂 " + t("Open this user's ledger"), type="primary", use_container_width=True, key="adm_open"):
            open_ledger(user_db_path(uid), names[uid])
            st.rerun()
        cur = df[df["id"] == uid].iloc[0]
        pc1, pc2 = st.columns([1, 4])
        pc1.markdown(photo_html(user_photo(uid), 72, cur["name"]), unsafe_allow_html=True)
        status_label = t("Status")
        pc2.markdown(f"**{escape(cur['name'])}**  \n{status_label}: {t(cur['status'] or 'approved')}")
        sb1, sb2 = st.columns(2)
        if sb1.button("✅ " + t("Approve"), key="adm_set_ok", use_container_width=True, disabled=(cur["status"] == "approved")):
            set_user_status(uid, "approved")
            st.session_state["admin_flash"] = "User approved."
            st.rerun()
        if sb2.button("⛔ " + t("Block"), key="adm_set_block", use_container_width=True, disabled=(cur["status"] == "rejected")):
            set_user_status(uid, "rejected")
            st.session_state["admin_flash"] = "User blocked."
            st.rerun()
        with st.expander(t("Reset this user's password")):
            with st.form("adm_reset"):
                npw = st.text_input(t("New password"), type="password")
                ok = st.form_submit_button(t("Change password"))
            if ok:
                if len(npw) < MIN_PASSWORD:
                    st.error(t("Password must be at least 6 characters."))
                else:
                    set_user_password(uid, npw)
                    st.success(t("Password changed."))
        with st.expander(t("Delete this user")):
            st.error(t("This permanently deletes the user and all of their data."))
            row = df[df["id"] == uid].iloc[0]
            word = st.text_input(tf("Type the mobile number {p} to confirm", p=row["phone"]), key="adm_del_word")
            if st.button(t("Delete user"), key="adm_del", disabled=norm_phone(word) != row["phone"]):
                with closing(users_conn()) as c:
                    c.execute("DELETE FROM users WHERE id = ?", (int(uid),))
                    c.execute("DELETE FROM profile_requests WHERE user_id = ?", (int(uid),))
                    c.commit()
                user_db_path(uid).unlink(missing_ok=True)
                st.session_state["admin_flash"] = "User deleted."
                st.rerun()

        if LEGACY_DB.exists():
            with st.expander(t("Old data (from before accounts)")):
                st.caption(tf("{n} entries in the old single-user file.", n=count_entries(LEGACY_DB)))
                if st.button(t("Open old data"), key="adm_open_legacy"):
                    open_ledger(LEGACY_DB, t("Old data"))
                    st.rerun()
                sure = st.checkbox(t("Copy the old data to the selected user (replaces that user's current data)"),
                                   key="adm_legacy_sure")
                if st.button(t("Give old data to selected user"), key="adm_legacy_give", disabled=not sure):
                    shutil.copyfile(LEGACY_DB, user_db_path(uid))
                    st.session_state["admin_flash"] = "Old data copied."
                    st.rerun()

    st.markdown(t("#### Backup & restore of everything"))
    st.download_button("⬇️ " + t("Download full backup (zip)"), data=zip_all_data(),
                       file_name=f"all_users_backup_{date.today().isoformat()}.zip",
                       mime="application/zip", use_container_width=True)
    with st.expander(t("Restore full backup")):
        up = st.file_uploader(t("Backup zip"), type=["zip"], key="adm_restore_file")
        st.warning(t("This replaces the current data of all users in the zip."))
        word = st.text_input(t("Type RESTORE to confirm"), key="adm_restore_word")
        if st.button(t("Restore"), key="adm_restore", type="primary"):
            if up is None:
                st.error(t("First choose the backup zip file."))
            elif word.strip().upper() != "RESTORE":
                st.error(t("Type RESTORE in the box to confirm."))
            else:
                try:
                    restore_all_data(up.getvalue())
                except Exception:
                    st.error(t("This file is not a valid backup of this app."))
                else:
                    st.session_state["admin_flash"] = "Backup restored."
                    st.rerun()


# ---------------------------------------------------------------- navigation
def go(page, party=None):
    st.session_state["page"] = page
    if party is not None:
        st.session_state["prefill_party"] = party


PAGE_ICONS = {P_DASH: "📊", P_SAVE: "💰", P_NEW: "➕", P_EDIT: "⚙️"}


def top_nav():
    """Big tap-friendly page buttons in a 2x2 grid, so the sidebar is not needed."""
    cur = st.session_state.get("page")
    for row in (PAGES[:2], PAGES[2:]):
        cols = st.columns(2)
        for col, p in zip(cols, row):
            col.button(
                f"{PAGE_ICONS[p]}  {t(p)}", key=f"nav_{p}", on_click=go, args=(p,),
                use_container_width=True, type="primary" if cur == p else "secondary",
            )
    st.write("")


# ---------------------------------------------------------------- follow-up alerts
# Every "Money lent" / "Money borrowed" entry carries a return date. The alert appears when that date arrives.
# Older entries saved without a date fall back to these limits.
DATED_KINDS = ("Money lent", "Money borrowed")


def set_followup(pid, mode, promise=""):
    run(
        "INSERT INTO followups(party_id, mode, promise_date, set_on) VALUES (?,?,?,?) "
        "ON CONFLICT(party_id) DO UPDATE SET mode = excluded.mode, "
        "promise_date = excluded.promise_date, set_on = excluded.set_on",
        (int(pid), mode, promise, date.today().isoformat()),
    )


def clear_followup(pid):
    run("DELETE FROM followups WHERE party_id = ?", (int(pid),))


def save_promise(pid):
    set_followup(pid, "date", st.session_state[f"fu_d_{pid}"].isoformat())


def never_pays(pid):
    set_followup(pid, "never")


def make_msg(pid, name, amt, sign):
    """Save the chosen date and draft the WhatsApp message (a reminder if money is to come back to you)."""
    d = st.session_state[f"fu_d_{pid}"]
    set_followup(pid, "date", d.isoformat())
    if sign > 0:
        tmpl = "Hello {name}, a gentle reminder about the {amt} I gave you. Please return it by {d}. Thank you."
    else:
        tmpl = "Hello {name}, I owe you {amt}. It will be paid by {d}. Thank you for your patience."
    st.session_state[f"fu_txt_{pid}"] = tf(tmpl, name=name, amt=inr(amt), d=fdate(d))


def close_msg(pid):
    st.session_state.pop(f"fu_txt_{pid}", None)


def ack_alert(pid, dues):
    """'OK' dabane par ye alert (in return dates ke liye) band ho jata hai. Nayi return date aane par fir aayega."""
    for d in dues:
        run("INSERT OR IGNORE INTO alert_acks(party_id, due) VALUES (?,?)", (int(pid), d))
    close_msg(pid)


def _iso(v):
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def open_entries(rows, sign):
    """Entries (oldest first) that are still unpaid, with the unpaid part of each. Oldest entries are settled first."""
    adds = rows[rows["signed"] * sign > 0].sort_values(["date", "id"])
    left = float(-(rows.loc[rows["signed"] * sign < 0, "signed"] * sign).sum())
    out = []
    for r in adds.itertuples():
        amt = float(r.amount)
        if left >= amt - 0.005:
            left -= amt
            continue
        out.append({"date": _iso(r.date), "own_due": _iso(getattr(r, "due_date", "")), "rem": amt - left})
        left = 0.0
    return out


def followup_alerts():
    """Parties with an entry whose return date has arrived, plus parties marked 'will never pay'."""
    today = date.today()
    s = summary_df()
    if s.empty:
        return [], []
    df = txns_df()
    fu = query_df("SELECT party_id, mode, promise_date, set_on FROM followups")
    fmap = {int(r.party_id): r for r in fu.itertuples()}
    acks = query_df("SELECT party_id, due FROM alert_acks")
    acked = {(int(r.party_id), str(r.due)) for r in acks.itertuples()}
    alerts, never = [], []
    for r in s.itertuples():
        pid = int(r.id)
        f = fmap.get(pid)
        if abs(r.balance) < 0.005:
            if f is not None:
                clear_followup(pid)  # settled, so the old follow-up is no longer needed
            continue
        sign = 1 if r.balance > 0 else -1
        ents = [e for e in open_entries(df[df["party_id"] == pid], sign) if e["date"]]
        if not ents:
            continue
        total = abs(float(r.balance))
        item = {
            "id": pid, "name": r.name, "phone": r.phone or "", "amt": total, "sign": sign,
            "since": ents[0]["date"], "days": (today - ents[0]["date"]).days, "dated": True, "promise_passed": None,
        }
        if f is not None and f.mode == "never" and sign > 0:
            never.append(item)
            continue
        promise = _iso(f.promise_date) if (f is not None and f.mode == "date") else None
        set_on = _iso(f.set_on) if f is not None else None
        # Alert comes on the entry's own return date and stays until the person presses OK.
        # A date saved earlier ("When will they pay?") no longer hides it; it only adds a second alert on that date.
        for e in ents:
            e["due"], e["dated"] = e["own_due"], True
        dated = [e for e in ents if e["due"]]
        due_now = [e for e in dated if e["due"] <= today and (pid, e["due"].isoformat()) not in acked]
        promise_hit = bool(promise and promise <= today and (pid, promise.isoformat()) not in acked)
        # Keep the message box open while it is being used
        if not due_now and not promise_hit and f"fu_txt_{pid}" not in st.session_state:
            continue
        if due_now:
            pick = min(due_now, key=lambda e: e["due"])
            due = pick["due"]
        elif promise_hit:
            pick, due = ents[0], promise
        else:
            pick = min(dated, key=lambda e: e["due"]) if dated else ents[0]
            due = pick["due"] or today
        keys = {e["due"].isoformat() for e in due_now}
        if promise_hit:
            keys.add(promise.isoformat())
        item.update(
            since=pick["date"], days=(today - pick["date"]).days, dated=True, due=due,
            over=(today - due).days,
            amt=sum(e["rem"] for e in due_now) if due_now else total,
            keys=sorted(keys),
        )
        if promise_hit:
            item["promise_passed"] = promise
        alerts.append(item)
    alerts.sort(key=lambda a: a["due"])
    return alerts, never


def whatsapp_url(phone, text):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return ""
    wa = ("91" + digits) if len(digits) == 10 else digits
    return f"https://wa.me/{wa}?text={quote(text)}"


def followup_section():
    alerts, never = followup_alerts()
    if alerts:
        st.subheader("⏰ " + t("Follow-ups"))
    for a in alerts:
        pid = a["id"]
        lent = a["sign"] > 0
        with st.container(border=True):
            if a["dated"]:
                tmpl = ("{name} was to return {amt} to you on {due}." if lent
                        else "You were to return {amt} to {name} on {due}.")
                head = tf(tmpl, name=a["name"], amt=inr(a["amt"]), due=fdate(a["due"]))
            else:
                tmpl = ("{name} owes you {amt}, unpaid for {days} days (since {since})." if lent
                        else "You owe {name} {amt}, unpaid for {days} days (since {since}).")
                head = tf(tmpl, name=a["name"], amt=inr(a["amt"]), days=a["days"], since=fdate(a["since"]))
            st.markdown("**" + head + "**")
            if a["dated"] and a["over"] > 0:
                st.caption(tf("{n} days overdue", n=a["over"]))
            elif a["dated"]:
                st.caption(t("Due today"))
            if a["promise_passed"]:
                st.caption(tf("The date promised earlier ({d}) has passed.", d=fdate(a["promise_passed"])))
            # pick the (new) date, then draft a WhatsApp message for the party
            if lent:
                c1, c2, c3, c4 = st.columns([2, 1.2, 1, 1.2])
            else:
                c1, c2 = st.columns([2, 1.2])
            c1.date_input(t("When will they pay?" if lent else "When will you pay?"),
                          value=date.today() + timedelta(days=7), min_value=date.today(), key=f"fu_d_{pid}")
            c2.write("")
            c2.button(t("Make message"), key=f"fu_mk_{pid}", on_click=make_msg,
                      args=(pid, a["name"], a["amt"], a["sign"]), use_container_width=True, type="primary")
            if lent:
                c3.write("")
                c3.button(t("Save date"), key=f"fu_save_{pid}", on_click=save_promise, args=(pid,),
                          use_container_width=True)
                c4.write("")
                c4.button(t("Will never pay"), key=f"fu_never_{pid}", on_click=never_pays, args=(pid,),
                          use_container_width=True)
            if f"fu_txt_{pid}" in st.session_state:
                text = st.text_area(t("Message to send"), key=f"fu_txt_{pid}", height=110)
                url = whatsapp_url(a["phone"], text)
                if url:
                    st.link_button(t("OK, send on WhatsApp"), url, type="primary")
                    st.caption(t("WhatsApp opens with this message ready. Tap send there."))
                else:
                    st.warning(t("No phone number saved for this party, so WhatsApp cannot be opened."))
                st.caption(t("After sending, press Done to clear this alert."))
                st.button(t("Done"), key=f"fu_done_{pid}", on_click=ack_alert, args=(pid, a["keys"]))
            st.button(t("OK, I have seen this"), key=f"fu_ok_{pid}", on_click=ack_alert,
                      args=(pid, a["keys"]), disabled=not a["keys"])
            if lent:
                with st.expander(t("Contact")):
                    contact_block({"name": a["name"], "phone": a["phone"]})
    if never:
        with st.expander(tf("Marked as 'will never pay' ({n})", n=len(never))):
            for a in never:
                x, y = st.columns([3, 1])
                x.write(f"{a['name']}: {inr(a['amt'])}")
                y.button(t("Ask again"), key=f"fu_again_{a['id']}", on_click=clear_followup, args=(a["id"],))
    if alerts or never:
        st.write("")


def return_dates_section():
    """List of every unpaid entry with its return date, so it is clear what the alerts are based on."""
    s = summary_df()
    if s.empty:
        return
    df = txns_df()
    today = date.today()
    rows = []
    for r in s.itertuples():
        if abs(r.balance) < 0.005:
            continue
        sign = 1 if r.balance > 0 else -1
        for e in open_entries(df[df["party_id"] == int(r.id)], sign):
            due = e["own_due"]
            if due is None:
                status = t("No return date")
            elif due < today:
                status = tf("{n} days overdue", n=(today - due).days)
            elif due == today:
                status = t("Due today")
            else:
                status = tf("In {n} days", n=(due - today).days)
            rows.append({
                "sort": due or date.max, "Party": r.name, "Type": "Receivable" if sign > 0 else "Payable",
                "Amount": e["rem"], "Entry date": e["date"].isoformat() if e["date"] else "",
                "Return date": due.isoformat() if due else "—", "Status": status,
            })
    if not rows:
        return
    rows.sort(key=lambda x: x["sort"])
    tbl = pd.DataFrame(rows).drop(columns=["sort"])
    with st.expander("📅 " + t("Return dates of unpaid entries")):
        show_df(tbl, hide_index=True, use_container_width=True,
                column_config={"Amount": st.column_config.NumberColumn(format="₹%.2f")})


# ---------------------------------------------------------------- pages
def contact_block(r):
    phone = r["phone"].strip() if isinstance(r["phone"], str) else ""
    st.markdown(f'<div class="pname">{escape(r["name"])}</div>', unsafe_allow_html=True)
    if phone:
        digits = "".join(ch for ch in phone if ch.isdigit())
        wa = ("91" + digits) if len(digits) == 10 else digits
        st.markdown(f'<div class="pname" style="font-size:1.15rem">{t("Phone")}: {escape(phone)}</div>',
                    unsafe_allow_html=True)
        st.markdown(f"[📞 {t('Call')}](tel:{digits})  ·  [💬 WhatsApp](https://wa.me/{wa})")
    else:
        st.caption(t("No phone number saved for this party."))


def party_card(r, key, inline=False):
    cls, label = status_of(r["balance"])
    cls, label = cls, t(label)
    last = tf("last entry {d}", d=r["last"]) if r["last"] else t("no entries yet")
    meta = (tf("1 entry, {last}", last=last) if r["entries"] == 1
            else tf("{n} entries, {last}", n=r["entries"], last=last))
    with st.container(border=True):
        st.markdown(
            f'<div class="pcard-top">{avatar(r["name"])}<div>'
            f'<div class="pname">{escape(r["name"])}</div>'
            f'<div class="pmeta">{meta}</div></div></div>'
            f'<div class="pamt {"pos" if cls == "g" else "neg" if cls == "r" else ""}">'
            f'{inr(abs(r["balance"]))}</div><span class="chip {cls}">{label}</span>',
            unsafe_allow_html=True,
        )
        st.button(
            t("Add entry"), key=key, use_container_width=True,
            on_click=go, args=(P_NEW, r["name"]),
        )
        if inline:
            # inside another expander, so the contact details are shown directly
            st.divider()
            contact_block(r)
        else:
            with st.expander(t("Contact")):
                contact_block(r)


CF_COLS = ["Income", "Udhar diya", "Udhar wapas diya", "Kist", "Penalty", "Kharcha", "Wapas mile", "Udhar liya"]
CF_OUT = ["Udhar diya", "Udhar wapas diya", "Kist", "Penalty", "Kharcha"]  # paisa gaya
CF_IN = ["Income", "Wapas mile", "Udhar liya"]  # paisa aaya


def cash_flow():
    """Mahine-wise: income, kitna gaya (udhari/kist/penalty), kitna aur aaya aur kitna bacha."""
    parts = []
    inc = income_df()
    if not inc.empty:
        parts.append(pd.DataFrame({"month": inc["month"], "Income": inc["amount"]}))
    tx = txns_df()
    if not tx.empty:
        amt, kind = tx["amount"], tx["kind"]
        parts.append(pd.DataFrame({
            "month": tx["date"].str[:7],
            "Udhar diya": amt.where(kind == "Money lent", 0.0),
            "Udhar wapas diya": amt.where(kind == "Repayment made", 0.0),
            "Wapas mile": amt.where(kind == "Repayment received", 0.0),
            "Udhar liya": amt.where(kind == "Money borrowed", 0.0),
        }))
    ex = expenses_df()
    if not ex.empty:
        parts.append(pd.DataFrame({"month": ex["month"], "Kharcha": ex["amount"]}))
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
    st.caption(tf("Net cash position: {v}", v=inr(cash_total())))


def _month_label(m):
    y, mo = m.split("-")
    return fdate(date(int(y), int(mo), 1), "%B %Y")


PERIOD_OPTS = ["This month", "Last month", "Last 3 months", "Last 6 months", "Last 12 months",
               "Choose a month", "Choose a range", "All time"]


def period_cash_section():
    """Kisi bhi mahine / kai mahine / range me: kitna paisa aaya, kitna gaya, kitna bacha."""
    cf = cash_flow()
    if cf.empty:
        return
    cur = pd.Period(date.today(), freq="M")
    first = min(pd.Period(cf.index[0], freq="M"), cur)
    last = max(pd.Period(cf.index[-1], freq="M"), cur)
    all_m = [str(x) for x in pd.period_range(first, last, freq="M")]
    st.subheader(t("Money in and out"))
    pick = st.selectbox(t("Period"), PERIOD_OPTS, key="cf_period", format_func=t)
    if pick == "This month":
        sel = [str(cur)]
    elif pick == "Last month":
        sel = [str(cur - 1)]
    elif pick.startswith("Last "):
        n = int(pick.split()[1])
        sel = [str(x) for x in pd.period_range(end=cur, periods=n, freq="M")]
    elif pick == "Choose a month":
        m = st.selectbox(t("Month"), all_m[::-1], key="cf_month", format_func=_month_label)
        sel = [m]
    elif pick == "Choose a range":
        a, b = st.columns(2)
        m1 = a.selectbox(t("From month"), all_m[::-1], index=min(2, len(all_m) - 1), key="cf_from", format_func=_month_label)
        m2 = b.selectbox(t("To month"), all_m[::-1], key="cf_to", format_func=_month_label)
        if m1 > m2:
            st.warning(t("'From month' is after 'To month'. Showing them in the right order."))
            m1, m2 = m2, m1
        sel = [str(x) for x in pd.period_range(m1, m2, freq="M")]
    else:
        sel = all_m
    v = cf.reindex(sel, fill_value=0.0)
    came, went = float(v["Aaya"].sum()), float(v["Gaya"].sum())
    left = came - went
    label = _month_label(sel[0]) if len(sel) == 1 else f"{_month_label(sel[0])} – {_month_label(sel[-1])}"
    k1, k2, k3 = st.columns(3)
    k1.markdown(kpi("Money came in", inr(came), label, "g"), unsafe_allow_html=True)
    k2.markdown(kpi("Money went out", inr(went), label, "r"), unsafe_allow_html=True)
    k3.markdown(kpi("Left", inr(left), "came in − went out", "g" if left >= 0 else "r"), unsafe_allow_html=True)
    st.caption(tf(
        "Came in: income {a}, repayments received {b}, borrowed {c}. Went out: lent {d}, repaid {e}, instalments {f}, penalties {g}, expenses {h}.",
        a=inr(v["Income"].sum()), b=inr(v["Wapas mile"].sum()), c=inr(v["Udhar liya"].sum()),
        d=inr(v["Udhar diya"].sum()), e=inr(v["Udhar wapas diya"].sum()),
        f=inr(v["Kist"].sum()), g=inr(v["Penalty"].sum()), h=inr(v["Kharcha"].sum()),
    ))
    if len(sel) > 1:
        with st.expander(t("Month by month"), expanded=True):
            tbl = pd.DataFrame({"Came in": v["Aaya"], "Went out": v["Gaya"], "Left": v["Bacha"]})
            tbl.index = [_month_label(x) for x in tbl.index]
            tbl = tbl.iloc[::-1].reset_index().rename(columns={"index": "Month"})
            money = st.column_config.NumberColumn(format="₹%.2f")
            show_df(tbl, hide_index=True, use_container_width=True,
                    column_config={c: money for c in ["Came in", "Went out", "Left"]})
    st.write("")


def cash_section():
    cf = cash_flow()
    if cf.empty:
        return
    income = float(cf["Income"].sum())
    gaya = float(cf["Gaya"].sum())
    other_in = float((cf["Wapas mile"] + cf["Udhar liya"]).sum())
    bacha = float(cf["Bacha"].sum())
    st.subheader(t("Cash flow"))
    k1, k2, k3 = st.columns(3)
    k1.markdown(kpi("Total income", inr(income), "to date", "g"), unsafe_allow_html=True)
    k2.markdown(
        kpi("Total outflow", inr(gaya), "lent, repaid, instalments, penalties, expenses", "r"),
        unsafe_allow_html=True,
    )
    k3.markdown(
        kpi("Net cash position", inr(bacha), tf("income + {v} other inflow − outflow", v=inr(other_in)),
            "g" if bacha >= 0 else "r"),
        unsafe_allow_html=True,
    )
    st.caption(tf(
        "Outflow: lent {a}, repaid {b}, instalments {c}, penalties {d}, expenses {e}. Other inflow: repayments received {f}, borrowed {g}.",
        a=inr(cf['Udhar diya'].sum()), b=inr(cf['Udhar wapas diya'].sum()),
        c=inr(cf['Kist'].sum()), d=inr(cf['Penalty'].sum()), e=inr(cf['Kharcha'].sum()),
        f=inr(cf['Wapas mile'].sum()), g=inr(cf['Udhar liya'].sum()),
    ))
    with st.expander(t("Monthly breakdown")):
        tbl = pd.DataFrame({
            "Income": cf["Income"],
            "Other inflow": cf["Wapas mile"] + cf["Udhar liya"],
            "Outflow": cf["Gaya"],
            "Net": cf["Bacha"],
            "Cumulative": cf["Bacha"].cumsum(),
        }).iloc[::-1].reset_index().rename(columns={"month": "Month"})
        money = st.column_config.NumberColumn(format="₹%.2f")
        show_df(
            tbl, hide_index=True, use_container_width=True,
            column_config={c: money for c in ["Income", "Other inflow", "Outflow", "Net", "Cumulative"]},
        )
    st.write("")


def mode_section():
    """Cash in hand vs online / bank: how much came in and went out through each."""
    df = all_transactions()
    if df.empty:
        return
    df = df.assign(Mode=df["Mode"].replace("", "Not specified"))
    g = df.pivot_table(index="Mode", columns="Direction", values="Amount", aggfunc="sum", fill_value=0.0)
    for c in ("In", "Out"):
        if c not in g.columns:
            g[c] = 0.0
    g["Left"] = g["In"] - g["Out"]
    st.subheader(t("Cash vs Online"))
    cols = st.columns(len(MODES))
    for col, m in zip(cols, MODES):
        i = float(g.loc[m, "In"]) if m in g.index else 0.0
        o = float(g.loc[m, "Out"]) if m in g.index else 0.0
        col.markdown(
            kpi(m + " left", inr(i - o), tf("In {a} · Out {b}", a=inr(i), b=inr(o)), "g" if i >= o else "r"),
            unsafe_allow_html=True,
        )
    if "Not specified" in g.index:
        st.caption(t("Entries saved before the payment mode was added show as Not specified. Edit them in the Admin panel."))
    with st.expander(t("Cash vs Online")):
        tbl = g.reset_index()[["Mode", "In", "Out", "Left"]]
        money = st.column_config.NumberColumn(format="₹%.2f")
        show_df(tbl, hide_index=True, use_container_width=True,
                column_config={c: money for c in ["In", "Out", "Left"]})
    st.write("")


def expense_section():
    ex = expenses_df()
    if ex.empty:
        return
    st.subheader(t("Expenses: where the money went"))
    months = sorted(ex["month"].unique(), reverse=True)
    pick = st.selectbox(t("Period"), ["All time"] + months, key="exp_period", format_func=t)
    v = ex if pick == "All time" else ex[ex["month"] == pick]
    if v.empty:
        st.info(t("No expenses in this period."))
        return
    v = v.assign(place_key=v["place"].str.strip().str.lower())
    by_place = (
        v.groupby("place_key")
        .agg(Place=("place", "first"), Category=("category", "first"),
             Entries=("id", "count"), Total=("amount", "sum"), Last=("date", "max"))
        .sort_values("Total", ascending=False).reset_index(drop=True)
    )
    total = float(v["amount"].sum())
    by_place["Share %"] = (by_place["Total"] / total * 100).round(1)
    by_cat = v.groupby("category")["amount"].sum().sort_values(ascending=False).reset_index()
    by_cat.columns = ["Category", "Total"]

    k1, k2, k3 = st.columns(3)
    k1.markdown(kpi("Total expenses", inr(total), tf("{n} entries", n=len(v)), "r"), unsafe_allow_html=True)
    k2.markdown(kpi("Biggest spend", inr(by_place.iloc[0]["Total"]), str(by_place.iloc[0]["Place"]), "r"),
                unsafe_allow_html=True)
    k3.markdown(kpi("Top category", inr(by_cat.iloc[0]["Total"]), str(by_cat.iloc[0]["Category"]), "b"),
                unsafe_allow_html=True)
    st.write("")

    l, r = st.columns([1.35, 1])
    with l:
        st.markdown(t("**Spent where**"))
        top = by_place.head(10)
        chart = (
            alt.Chart(top)
            .mark_bar(cornerRadiusEnd=2, size=18, color=RED)
            .encode(
                y=alt.Y("Place:N", sort="-x", title=None),
                x=alt.X("Total:Q", title=t("Amount (₹)")),
                tooltip=[alt.Tooltip("Place", title=t("Place")), alt.Tooltip("Category", title=t("Category")),
                         alt.Tooltip("Entries", title=t("Entries")),
                         alt.Tooltip("Total:Q", title=t("Total"), format=",.2f")],
            )
            .properties(height=max(120, 32 * len(top)))
        )
        st.altair_chart(chart, use_container_width=True)
    with r:
        st.markdown(t("**Category-wise**"))
        show_df(
            by_cat, hide_index=True, use_container_width=True,
            column_config={"Total": st.column_config.NumberColumn(format="₹%.2f")},
        )

    with st.expander(t("Place-wise full list")):
        show_df(
            by_place[["Place", "Category", "Entries", "Total", "Share %", "Last"]],
            hide_index=True, use_container_width=True,
            column_config={"Total": st.column_config.NumberColumn(format="₹%.2f")},
        )
    with st.expander(t("All expense entries")):
        show_df(
            v.sort_values(["date", "id"], ascending=False)[["date", "place", "category", "mode", "amount", "note"]]
            .rename(columns={"date": "Date", "place": "Place", "category": "Category",
                             "amount": "Amount", "note": "Note", "mode": "Mode"}),
            hide_index=True, use_container_width=True,
            column_config={"Amount": st.column_config.NumberColumn(format="₹%.2f")},
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
    st.subheader(t("Loans and instalments"))
    pending = sum(i["pending"] for _, i in items)
    pen_due = sum(i["pen_due"] for _, i in items)
    n_late = sum(len(i["overdue"]) for _, i in items)
    k1, k2, k3 = st.columns(3)
    k1.markdown(
        kpi("Loan outstanding", inr(pending + pen_due),
            tf("instalments {a} + penalty {b}", a=inr(pending), b=inr(pen_due)), "b"),
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
    def _toggle_sched(lid):
        k = f"loan_sched_{lid}"
        st.session_state[k] = not st.session_state.get(k, False)

    for l, i in items:
        col, side = st.columns([1, 1.5])
        with col, st.container(border=True):
            if i["overdue"]:
                cls, label = "r", tf("{n} overdue", n=len(i['overdue']))
            elif i["pending"] <= 0.005 and i["pen_due"] > 0.005:
                cls, label = "r", t("Penalty due")
            elif i["pending"] <= 0.005:
                cls, label = "g", t("Fully paid")
            else:
                cls, label = "g", t("On schedule")
            nxt = i["next"]
            nxt_txt = tf("next due {d}", d=fdate(nxt['due'])) if nxt else t("all instalments paid")
            meta_a = tf("{k} × {n} instalments, {nxt}", k=inr(l["kist_amount"]),
                        n=int(l["total_kists"]), nxt=nxt_txt)
            meta_b = tf("{a} of {b} instalments paid", a=i["paid_cnt"], b=int(l["total_kists"]))
            out_lbl = t("Outstanding (incl. penalty)")
            st.markdown(
                f'<div class="pcard-top">{avatar(l["name"])}<div>'
                f'<div class="pname">{escape(l["name"])}</div>'
                f'<div class="pmeta">{meta_a}</div>'
                f'</div></div>'
                f'<div class="pmeta" style="margin-top:8px">{out_lbl}</div>'
                f'<div class="pamt" style="margin-top:0">{inr(i["pending"] + i["pen_due"])}</div>'
                f'<span class="chip {cls}">{label}</span>'
                f'<div class="pmeta" style="margin-top:6px">{meta_b}</div>',
                unsafe_allow_html=True,
            )
            if i["pen_due"] > 0.005:
                st.markdown(
                    f'<div class="neg" style="font-weight:700;font-size:.85rem">'
                    f'{tf("Penalty due: {v}", v=inr(i["pen_due"]))}</div>',
                    unsafe_allow_html=True,
                )
            st.caption(
                tf("Instalments due {a} + penalty {b}", a=inr(i['pending']), b=inr(i['pen_due']))
            )
            st.progress(min(i["paid"] / i["total"], 1.0) if i["total"] else 0.0)
            is_open = st.session_state.get(f"loan_sched_{l['id']}", False)
            st.button(
                ("▼ " if is_open else "▶ ") + t("Instalment schedule"), key=f"loan_sched_btn_{l['id']}",
                on_click=_toggle_sched, args=(l["id"],), use_container_width=True,
                type="primary" if is_open else "secondary",
            )
        if is_open:
            with side, st.container(border=True):
                st.markdown(f"**{escape(l['name'])}** · " + t("Instalment schedule"))
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
                show_df(
                    tbl, hide_index=True, use_container_width=True,
                    column_config={"Penalty": st.column_config.NumberColumn(format="₹%.2f")},
                )


def page_dashboard():
    hero("Dashboard", tf("Your financial position as of {d}", d=fdate(date.today())))
    df = txns_df()
    inc = income_df()
    if df.empty and inc.empty and loans_df().empty and expenses_df().empty:
        st.info(t("No records yet. Add your first entry to get started."))
        st.button(t("Add first entry"), on_click=go, args=(P_NEW,), type="primary")
        return

    followup_section()
    return_dates_section()

    s = summary_df()
    milna = s.loc[s["balance"] > 0, "balance"].sum()
    dena = -s.loc[s["balance"] < 0, "balance"].sum()
    n_mil = int((s["balance"] > 0).sum())
    n_den = int((s["balance"] < 0).sum())

    this_month = inc.loc[inc["month"] == date.today().strftime("%Y-%m"), "amount"].sum()
    c1, c2, c3, c4 = st.columns(4)
    def kpi_with_parties(col, label, amount, n, cls, mask, one, many):
        txt = t(one) if n == 1 else tf(many, n=n)
        with col:
            st.markdown(kpi(label, inr(amount), "" if n else txt, cls), unsafe_allow_html=True)
            if n:
                with st.expander("👥 " + txt):
                    sub = s[mask]
                    sub = sub.reindex(sub["balance"].abs().sort_values(ascending=False).index)
                    for _, pr in sub.iterrows():
                        party_card(pr, key=f"kpi_{cls}_{pr['id']}", inline=True)

    kpi_with_parties(c1, "Receivable", milna, n_mil, "g", s["balance"] > 0, "from 1 party", "from {n} parties")
    kpi_with_parties(c2, "Payable", dena, n_den, "r", s["balance"] < 0, "to 1 party", "to {n} parties")
    c3.markdown(
        kpi("Net balance", inr(milna - dena), "receivable − payable", "b"), unsafe_allow_html=True
    )
    cf_now = cash_flow()
    cm = date.today().strftime("%Y-%m")
    m_in = float(cf_now.loc[cm, "Aaya"]) if cm in cf_now.index else 0.0
    m_out = float(cf_now.loc[cm, "Gaya"]) if cm in cf_now.index else 0.0
    c4.markdown(
        kpi("Left this month", inr(m_in - m_out), tf("In {a} · Out {b}", a=inr(m_in), b=inr(m_out)),
            "g" if m_in >= m_out else "r"),
        unsafe_allow_html=True,
    )
    st.write("")

    period_cash_section()
    cash_section()
    mode_section()
    expense_section()
    loan_section()

    left, right = st.columns([1.35, 1])
    with left:
        st.subheader(t("Largest balances"))
        top = s[s["balance"] != 0].copy()
        top["Amount"] = top["balance"].abs()
        rec_l, pay_l = t("Receivable"), t("Payable")
        top["Status"] = top["balance"].apply(lambda b: rec_l if b > 0 else pay_l)
        top = top.sort_values("Amount", ascending=False).head(8)
        if top.empty:
            st.success(t("All balances are settled."))
        else:
            chart = (
                alt.Chart(top)
                .mark_bar(cornerRadiusEnd=2, size=20)
                .encode(
                    y=alt.Y("name:N", sort="-x", title=None),
                    x=alt.X("Amount:Q", title=t("Amount (₹)")),
                    color=alt.Color(
                        "Status:N",
                        scale=alt.Scale(domain=[rec_l, pay_l], range=[GREEN, RED]),
                        legend=alt.Legend(orient="bottom", title=None),
                    ),
                    tooltip=[alt.Tooltip("name:N", title=t("Name")), alt.Tooltip("Status:N", title=t("Status")),
                             alt.Tooltip("Amount:Q", format=",.2f")],
                )
                .properties(height=max(120, 38 * len(top)))
            )
            st.altair_chart(chart, use_container_width=True)
    with right:
        st.subheader(t("Recent activity"))
        for _, r in df.sort_values(["date", "id"], ascending=False).head(6).iterrows():
            pos = r["signed"] > 0
            st.markdown(
                f'<div class="act"><div><div class="l">{escape(r["party"])}</div>'
                f'<div class="s">{escape(t(r["kind"]))}, {r["date"]}{(", " + escape(t(r["mode"]))) if r["mode"] else ""}</div></div>'
                f'<div class="a {"pos" if pos else "neg"}">{"+" if pos else "−"}{inr(r["amount"])}</div></div>',
                unsafe_allow_html=True,
            )

    if not inc.empty:
        st.subheader(t("Monthly income"))
        monthly = inc.groupby("month")["amount"].sum().reset_index().tail(12)
        ichart = (
            alt.Chart(monthly)
            .mark_bar(cornerRadiusEnd=2, color=GREEN)
            .encode(
                x=alt.X("month:N", title=None, sort=None),
                y=alt.Y("amount:Q", title=t("Amount (₹)")),
                tooltip=[alt.Tooltip("month:N", title=t("Month")),
                         alt.Tooltip("amount:Q", title=t("Income"), format=",.2f")],
            )
            .properties(height=220)
        )
        st.altair_chart(ichart, use_container_width=True)
        st.caption(tf("Total income to date: {a} across {n} entries", a=inr(inc['amount'].sum()), n=len(inc)))



def income_form():
    # form ke bahar, taaki 'Other' chunte hi neeche naam likhne ka box turant aa jaye
    source = st.selectbox(t("Source"), INCOME_SOURCES, key="inc_source", format_func=t)
    other = ""
    if source == "Other":
        other = st.text_input(t("Specify source"), placeholder=t("e.g. Tuition, Freelance"), key="inc_other")
    with st.form("income_form", clear_on_submit=True):
        a, b = st.columns(2)
        amount = a.number_input(t("Amount (₹)"), min_value=0.0, step=500.0, format="%.2f")
        idate = b.date_input(t("Date received"), value=date.today())
        mode = mode_pick(key="inc_mode")
        note = st.text_input(t("Note (optional)"), placeholder=t("e.g. overtime, commission"))
        ok = st.form_submit_button(t("Save income"), type="primary", use_container_width=True)
    if ok:
        final_source = other.strip() if source == "Other" else source
        if amount <= 0:
            st.error(t("Amount must be greater than 0."))
        elif not final_source:
            st.error(t("Specify the source when 'Other' is selected."))
        else:
            run(
                "INSERT INTO income(idate, amount, source, note, mode) VALUES (?,?,?,?,?)",
                (idate.isoformat(), float(amount), final_source, note.strip(), mode),
            )
            st.success(tf("Income of {a} saved.", a=inr(amount)))
            st.toast(t("Income saved"))
            show_cash_left()


def cash_spend_section():
    """Category 'Cash' wali entries: us cash me se kahan, kitna aur kab kharch hua."""
    ex = expenses_df()
    cash = ex[ex["category"] == "Cash"]
    if cash.empty:
        return
    sp = query_df("SELECT id, expense_id, sdate AS date, amount, place, note FROM cash_spends ORDER BY sdate, id")
    st.markdown(t("#### Cash spending"))
    st.caption(t("Click a cash entry to record where that cash was spent."))
    flash = st.session_state.pop("cash_flash", None)
    if flash:
        st.success(flash)
    for _, r in cash.sort_values(["date", "id"], ascending=False).iterrows():
        eid = int(r["id"])
        edate = date.fromisoformat(str(r["date"])[:10])
        mine = sp[sp["expense_id"] == eid]
        total = float(r["amount"])
        spent = float(mine["amount"].sum())
        left = total - spent
        if left > 0.005:
            status = tf("{v} left", v=inr(left))
        elif left < -0.005:
            status = tf("Overspent by {v}", v=inr(-left))
        else:
            status = t("Finished")
        title = f"💵 {inr(total)} · {fdate(edate)} · {status}"
        with st.expander(title, expanded=st.session_state.get("cash_open") == eid):
            st.progress(min(max(spent / total, 0.0), 1.0) if total > 0 else 0.0)
            st.caption(tf("Spent {s} of {a}", s=inr(spent), a=inr(total)))
            if not mine.empty:
                tbl = mine.sort_values(["date", "id"], ascending=False)[["date", "place", "amount", "note"]]
                tbl = tbl.rename(columns={"date": "Date", "place": "Place", "amount": "Amount", "note": "Note"})
                show_df(
                    tbl, hide_index=True, use_container_width=True,
                    column_config={"Amount": st.column_config.NumberColumn(format="₹%.2f")},
                )
                labels = {
                    int(x["id"]): f"{x['date']} | {x['place']} | {inr(x['amount'])}"
                    for _, x in mine.iterrows()
                }
                pick = st.selectbox(t("Remove a spending entry"), list(labels), format_func=labels.get,
                                    key=f"cash_del_pick_{eid}")
                if st.button(t("Delete selected"), key=f"cash_del_{eid}"):
                    run("DELETE FROM cash_spends WHERE id = ?", (int(pick),))
                    st.session_state["cash_open"] = eid
                    st.rerun()
            if left > 0.005:
                with st.form(f"cash_spend_{eid}", clear_on_submit=True):
                    place = st.text_input(
                        t("Where was this cash spent?"),
                        placeholder=t("e.g. Vegetables, Auto fare, Tea stall"),
                    )
                    a, b = st.columns(2)
                    amount = a.number_input(t("Amount (₹)"), min_value=0.0, max_value=round(left, 2),
                                            step=50.0, format="%.2f")
                    sdate = b.date_input(t("Date"), value=max(date.today(), edate), min_value=edate)
                    note = st.text_input(t("Note (optional)"))
                    ok = st.form_submit_button(t("Save cash spending"), type="primary", use_container_width=True)
                if ok:
                    if not place.strip():
                        st.error(t("Enter where the cash was spent."))
                    elif amount <= 0:
                        st.error(t("Amount must be greater than 0."))
                    elif amount > left + 0.005:
                        st.error(tf("Only {v} is left in this cash.", v=inr(left)))
                    else:
                        run(
                            "INSERT INTO cash_spends(expense_id, sdate, amount, place, note) VALUES (?,?,?,?,?)",
                            (eid, sdate.isoformat(), float(amount), place.strip(), note.strip()),
                        )
                        st.session_state["cash_open"] = eid
                        st.session_state["cash_flash"] = tf(
                            "Cash spending of {a} at {p} saved.", a=inr(amount), p=place.strip())
                        st.rerun()


def expense_form():
    # form ke bahar, taaki 'Other' chunte hi naam likhne ka box turant aa jaye
    cat = st.selectbox(t("Category"), EXPENSE_CATS, key="exp_cat", format_func=t)
    other = ""
    if cat == "Other":
        other = st.text_input(t("Specify category"), placeholder=t("e.g. Gift, Repair"), key="exp_other")
    known = expenses_df()["place"].str.strip()
    known = sorted({p for p in known if p}, key=str.lower)
    with st.form("expense_form", clear_on_submit=True):
        if cat == "Cash":
            place = st.text_input(t("Where did the cash come from?"), placeholder=t("e.g. ATM, Bank, Home savings"))
        else:
            place = st.text_input(t("Where was it spent?"), placeholder=t("e.g. Big Bazaar, Petrol pump, Medical store"))
        a, b = st.columns(2)
        amount = a.number_input(t("Amount (₹)"), min_value=0.0, step=100.0, format="%.2f")
        edate = b.date_input(t("Date"), value=date.today())
        mode = mode_pick(key="exp_mode")
        note = st.text_input(t("Note (optional)"), placeholder=t("e.g. monthly ration, bike petrol"))
        ok = st.form_submit_button(t("Save expense"), type="primary", use_container_width=True)
    if known:
        st.caption(t("Previous places: ") + ", ".join(known[:12]))
    if ok:
        final_cat = other.strip() if cat == "Other" else cat
        if not place.strip():
            st.error(t("Enter where the money was spent."))
        elif amount <= 0:
            st.error(t("Amount must be greater than 0."))
        elif not final_cat:
            st.error(t("Specify the category when 'Other' is selected."))
        else:
            run(
                "INSERT INTO expenses(edate, amount, place, category, note, mode) VALUES (?,?,?,?,?,?)",
                (edate.isoformat(), float(amount), place.strip(), final_cat, note.strip(), mode),
            )
            st.success(tf("Expense of {a} at {p} saved.", a=inr(amount), p=place.strip()))
            st.toast(t("Expense saved"))
            if final_cat == "Cash":
                st.info(t("Cash saved. Open it under 'Cash spending' below and record where it was spent."))
            show_cash_left()
    cash_spend_section()


def loan_entry_form():
    mode = st.radio(
        t("Action"), ["Add new loan", "Record payment"],
        horizontal=True, key="loan_mode", format_func=t,
    )
    if mode == "Add new loan":
        # form ke bahar, taaki bayaj ka label turant badle
        ptype = st.radio(
            t("How is penalty charged on late instalments?"), list(LOAN_PEN_TYPES.values()),
            horizontal=True, key="loan_pen_type", format_func=t,
        )
        pkey = next(k for k, v in LOAN_PEN_TYPES.items() if v == ptype)
        with st.form("loan_new", clear_on_submit=True):
            name = st.text_input(t("Loan name"), placeholder=t("e.g. Bank loan, Personal loan from Ramesh"))
            a, b, c = st.columns(3)
            loan_amount = a.number_input(t("Loan amount (₹, optional)"), min_value=0.0, step=1000.0, format="%.2f")
            kist = b.number_input(t("Instalment amount (₹)"), min_value=0.0, step=100.0, format="%.2f")
            n = c.number_input(t("Number of instalments"), min_value=1, value=12, step=1)
            d, e = st.columns(2)
            pen = d.number_input(
                t({"daily": "Penalty (₹ per day)",
                   "pct": "Interest (% per month)"}.get(pkey, "Penalty (₹ per late instalment)")),
                min_value=0.0, step=0.5 if pkey == "pct" else 10.0, format="%.2f",
            )
            first = e.date_input(t("First due date"), value=date.today())
            note = st.text_input(t("Note (optional)"), placeholder=t("e.g. vehicle loan, due on the 5th"))
            ok = st.form_submit_button(t("Save loan"), type="primary", use_container_width=True)
        if ok:
            name = name.strip()
            if not name:
                st.error(t("Enter a loan name."))
            elif kist <= 0:
                st.error(t("Instalment amount must be greater than 0."))
            elif not query_df("SELECT 1 FROM loans WHERE name = ? COLLATE NOCASE", (name,)).empty:
                st.error(t("A loan with this name already exists. Use a different name."))
            else:
                run(
                    "INSERT INTO loans(name, loan_amount, kist_amount, total_kists, first_due, "
                    "penalty_type, penalty_amount, note) VALUES (?,?,?,?,?,?,?,?)",
                    (name, float(loan_amount), float(kist), int(n), first.isoformat(),
                     pkey, float(pen), note.strip()),
                )
                st.success(
                    tf("Loan '{name}' saved: {n} instalments × {k} = {tot}.",
                       name=name, n=int(n), k=inr(kist), tot=inr(kist * n))
                )
                st.toast(t("Loan saved"))
        return

    loans = loans_df()
    if loans.empty:
        st.info(t("Add a loan first, using 'Add new loan'."))
        return
    pick = st.selectbox(t("Loan"), loans["name"].tolist(), key="loan_pick")
    l = loans[loans["name"] == pick].iloc[0].to_dict()
    pays = loan_pay_df()
    inf = loan_summary(l, pays[pays["loan_id"] == l["id"]], date.today())
    nxt = inf["next"]
    st.caption(
        tf("Instalments due: {a}, penalty due: {b}", a=inr(inf['pending']), b=inr(inf['pen_due']))
        + (tf(", next due {d}", d=fdate(nxt['due'])) if nxt else t(", all instalments paid"))
    )
    if inf["overdue"]:
        st.warning(tf("{n} instalment(s) overdue. Penalty accrued to date: {p}",
                      n=len(inf['overdue']), p=inr(inf['pen_total'])))

    with st.form("loan_pay", clear_on_submit=True):
        kind = st.radio(t("Payment type"), ["Instalment", "Penalty"], horizontal=True, format_func=t)
        a, b = st.columns(2)
        amount = a.number_input(
            t("Amount (₹)"), min_value=0.0, value=float(l["kist_amount"]), step=100.0,
            format="%.2f", key=f"lp_amt_{l['id']}",
        )
        pdate = b.date_input(t("Payment date"), value=date.today())
        mode = mode_pick(key="lp_mode")
        note = st.text_input(t("Note (optional)"), placeholder=t("e.g. receipt no., bank ref"))
        ok = st.form_submit_button(t("Save payment"), type="primary", use_container_width=True)
    if ok:
        if amount <= 0:
            st.error(t("Amount must be greater than 0."))
        else:
            run(
                "INSERT INTO loan_payments(loan_id, pdate, kind, amount, note, mode) VALUES (?,?,?,?,?,?)",
                (int(l["id"]), pdate.isoformat(), "kist" if kind == "Instalment" else "penalty", float(amount), note.strip(), mode),
            )
            st.success(tf("{loan}: {kind} of {a} saved.", loan=pick, kind=t(kind).lower(), a=inr(amount)))
            st.toast(t("Payment saved"))
            show_cash_left()


def month_figures(month):
    """Earned, spent (expenses + loan payments), net udhaar given and the spending split for one 'YYYY-MM' month."""
    inc, ex, pays, tx = income_df(), expenses_df(), loan_pay_df(), txns_df()
    earned = float(inc.loc[inc["month"] == month, "amount"].sum())
    exm = ex[ex["month"] == month]
    expenses = float(exm["amount"].sum())
    loan = float(pays.loc[pays["date"].str[:7] == month, "amount"].sum()) if not pays.empty else 0.0
    udhar = 0.0
    if not tx.empty:
        tm = tx[tx["date"].str[:7] == month]
        out = tm.loc[tm["kind"].isin(["Money lent", "Repayment made"]), "amount"].sum()
        back = tm.loc[tm["kind"].isin(["Repayment received", "Money borrowed"]), "amount"].sum()
        udhar = max(float(out - back), 0.0)
    return {"earned": earned, "expenses": expenses, "loan": loan, "udhar": udhar, "exm": exm}


def page_savings():
    hero("My Savings", "See where your money goes and save more")
    today = date.today()
    month = today.strftime("%Y-%m")
    if income_df().empty and expenses_df().empty:
        st.info(t("Add some income and expenses first to see your savings."))
        st.button(t("Add first entry"), on_click=go, args=(P_NEW,), type="primary")
        return

    # ---- savings goal
    goal = float(get_setting("save_goal", "0") or 0)
    with st.form("goal_form"):
        g1, g2 = st.columns([3, 1])
        new_goal = g1.number_input(t("Monthly savings goal (₹)"), min_value=0.0, value=goal, step=500.0, format="%.2f")
        g2.write("")
        saved_goal = g2.form_submit_button(t("Save goal"), type="primary", use_container_width=True)
    if saved_goal:
        set_setting("save_goal", str(new_goal))
        goal = float(new_goal)
        st.success(t("Goal saved."))

    f = month_figures(month)
    spent = f["expenses"] + f["loan"]
    saved = f["earned"] - spent - f["udhar"]

    # ---- four simple numbers
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(kpi("Earned", inr(f["earned"]), "income this month", "g"), unsafe_allow_html=True)
    c2.markdown(kpi("Spent", inr(spent), "expenses + instalments + penalties", "r"), unsafe_allow_html=True)
    c3.markdown(kpi("Given as udhaar", inr(f["udhar"]), "lent minus repayments received", "b"), unsafe_allow_html=True)
    c4.markdown(kpi("Saved", inr(saved), "earned − spent − udhaar given", "g" if saved >= 0 else "r"),
                unsafe_allow_html=True)
    st.write("")

    # ---- where did the income go (per Rs 100)
    st.subheader(t("Where did your income go?"))
    if f["earned"] > 0:
        e = f["earned"]
        parts = [
            ("Spent on expenses", f["expenses"] / e * 100, RED),
            ("Loan instalments / penalty", f["loan"] / e * 100, "#8a6d1f"),
            ("Lent to others", f["udhar"] / e * 100, BLUE),
        ]
        used = sum(p[1] for p in parts)
        parts.append(("Saved (kept)", max(100 - used, 0.0), GREEN))
        st.caption(t("Out of every ₹100 you earned this month:"))
        bar = "".join(
            f'<div style="width:{p[1] / max(used, 100) * 100:.2f}%;background:{p[2]}"></div>' for p in parts if p[1] > 0
        )
        st.markdown(
            f'<div style="display:flex;height:26px;border-radius:4px;overflow:hidden;background:#e7ebee">{bar}</div>',
            unsafe_allow_html=True,
        )
        legend = "".join(
            f'<div class="act"><div class="l"><span style="display:inline-block;width:12px;height:12px;'
            f'background:{col};border-radius:2px;margin-right:8px"></span>{t(name)}</div>'
            f'<div class="a">{tf("₹{v} out of every ₹100", v=f"{pct:.0f}")}</div></div>'
            for name, pct, col in parts
        )
        st.markdown(legend, unsafe_allow_html=True)
        if used > 100:
            st.error(t("You have spent more than you earned this month."))
    else:
        st.info(t("Income this month") + ": " + inr(0))
    st.write("")

    # ---- goal progress and daily allowance
    if goal > 0:
        st.subheader(t("Goal progress"))
        st.progress(min(max(saved / goal, 0.0), 1.0))
        st.caption(tf("{s} saved of {g} goal", s=inr(saved), g=inr(goal)))
        days_left = calendar.monthrange(today.year, today.month)[1] - today.day + 1
        if saved >= goal:
            st.success(t("Goal reached. Well done!"))
            if saved > goal and days_left > 0:
                # saved is already net of spending so far, so (saved - goal) is what is still free to spend
                st.info(tf("You can still spend {v} per day (for {n} more days) and reach your goal.",
                           v=inr((saved - goal) / days_left), n=days_left))
        else:
            st.warning(t("Your goal is out of reach this month. Try to keep spending low for the remaining days."))
    else:
        st.caption(t("Set a monthly savings goal to track it here."))
    st.write("")

    # ---- biggest spending categories
    st.subheader(t("Biggest spending categories this month"))
    exm = f["exm"]
    if exm.empty:
        st.info(t("No expenses recorded this month."))
    else:
        by_cat = exm.groupby("category")["amount"].sum().sort_values(ascending=False).reset_index()
        by_cat.columns = ["Category", "Total"]
        by_cat["Label"] = by_cat["Category"].map(t)
        chart = (
            alt.Chart(by_cat.head(6))
            .mark_bar(cornerRadiusEnd=2, size=18, color=RED)
            .encode(
                y=alt.Y("Label:N", sort="-x", title=None),
                x=alt.X("Total:Q", title=t("Amount (₹)")),
                tooltip=[alt.Tooltip("Label:N", title=t("Category")), alt.Tooltip("Total:Q", title=t("Total"), format=",.2f")],
            )
            .properties(height=max(120, 34 * min(len(by_cat), 6)))
        )
        st.altair_chart(chart, use_container_width=True)
        top = by_cat.iloc[0]
        st.caption(tf("Tip: cutting {c} by 10% would save you {v} every month.",
                      c=t(top["Category"]), v=inr(top["Total"] * 0.10)))

    # ---- category limits
    st.subheader(t("Category limits"))
    cats = [c for c in EXPENSE_CATS if c != "Cash"]
    limits = {c: float(get_setting(f"limit_{c}", "0") or 0) for c in cats}
    spent_by = exm.groupby("category")["amount"].sum().to_dict() if not exm.empty else {}
    for c in cats:
        lim, sp = limits[c], float(spent_by.get(c, 0.0))
        if lim > 0:
            if sp > lim:
                st.error(tf("Limit crossed: {c} spent {s} of {l}", c=t(c), s=inr(sp), l=inr(lim)))
            else:
                st.progress(min(sp / lim, 1.0), text=tf("{c}: {s} of {l}", c=t(c), s=inr(sp), l=inr(lim)))
    with st.expander(t("Monthly limit for a category")):
        st.caption(t("Set a monthly limit per category (0 = no limit). You will see a warning when you cross it."))
        with st.form("limit_form"):
            cols = st.columns(2)
            vals = {}
            for i, c in enumerate(cats):
                vals[c] = cols[i % 2].number_input(t(c), min_value=0.0, value=limits[c], step=500.0,
                                                   format="%.0f", key=f"lim_{c}")
            if st.form_submit_button(t("Save limits"), type="primary", use_container_width=True):
                for c, v in vals.items():
                    set_setting(f"limit_{c}", str(v))
                st.success(t("Limits saved."))
                st.rerun()
    st.write("")

    # ---- last 6 months
    st.subheader(t("Last 6 months: saved vs spent"))
    months = [str(x) for x in pd.period_range(end=pd.Period(today, freq="M"), periods=6, freq="M")]
    rows = []
    for m in months:
        fm = month_figures(m)
        rows.append({"Month": _month_label(m), "Saved": fm["earned"] - fm["expenses"] - fm["loan"] - fm["udhar"]})
    hist = pd.DataFrame(rows)
    hist["Sign"] = hist["Saved"].apply(lambda v: "pos" if v >= 0 else "neg")
    hchart = (
        alt.Chart(hist)
        .mark_bar(cornerRadiusEnd=2)
        .encode(
            x=alt.X("Month:N", sort=None, title=None),
            y=alt.Y("Saved:Q", title=t("Amount (₹)")),
            color=alt.Color("Sign:N", scale=alt.Scale(domain=["pos", "neg"], range=[GREEN, RED]), legend=None),
            tooltip=[alt.Tooltip("Month:N", title=t("Month")), alt.Tooltip("Saved:Q", title=t("Saved"), format=",.2f")],
        )
        .properties(height=220)
    )
    st.altair_chart(hchart, use_container_width=True)
    st.caption(tf("Total saved over all months: {v}", v=inr(float(hist["Saved"].sum()))))


def page_new_entry():
    hero("New entry", "Record a transaction, income or loan payment")
    typ = st.radio(
        t("Entry type"), ["Lending / borrowing", "Income", "Loan / instalment", "Expense"],
        horizontal=True, key="entry_type", format_func=t,
    )
    if typ == "Income":
        income_form()
        return
    if typ == "Loan / instalment":
        loan_entry_form()
        return
    if typ == "Expense":
        expense_form()
        return
    parties = parties_df()
    pre = st.session_state.pop("prefill_party", None)
    options = ["-- New party --"] + parties["name"].tolist()
    idx = options.index(pre) if pre in options else 0

    flash = st.session_state.pop("entry_flash", None)
    if flash:
        st.success(flash)
        st.toast(t("Entry saved"))
        show_cash_left()

    n = st.session_state.setdefault("entry_n", 0)

    # Party + phone form ke bahar hain, taaki party badalte hi saved number turant dikhe
    a, b = st.columns(2)
    existing = a.selectbox(t("Existing party"), options, index=idx, key=f"ent_party_{n}", format_func=t)
    new_name = b.text_input(t("Or new party name"), placeholder=t("e.g. Ramesh Sharma"), key=f"ent_new_{n}")
    name = new_name.strip() or ("" if existing.startswith("--") else existing)

    stored_phone = ""
    if name:
        m = parties[parties["name"].str.lower() == name.lower()]
        if not m.empty:
            name = m.iloc[0]["name"]
            stored_phone = (m.iloc[0]["phone"] or "").strip()

    if stored_phone:
        # Party ka number ek baar save ho gaya to hamesha wahi rahega
        st.text_input(t("Phone"), value=stored_phone, disabled=True,
                      key=f"ent_ph_locked_{n}_{name}",
                      help=t("This party's saved number. It is used for every entry."))
        phone = stored_phone
    else:
        phone = st.text_input(t("Phone (required)"), placeholder=t("98xxxxxx10"),
                              key=f"ent_ph_{n}_{name}")

    with st.form("entry_form", clear_on_submit=True):
        kind = st.radio(t("Transaction type"), list(KINDS.keys()), horizontal=True, format_func=t)
        c, d = st.columns(2)
        amount = c.number_input(t("Amount (₹)"), min_value=0.0, step=100.0, format="%.2f")
        tdate = d.date_input(t("Date"), value=date.today())
        rdate = st.date_input(
            t("Return date (lent: when they will return it, borrowed: when you will return it)"),
            value=date.today() + timedelta(days=30),
            help=t("Used only for 'Money lent' and 'Money borrowed'. You get an alert when this date arrives."),
        )
        mode = mode_pick(key="ent_mode")
        note = st.text_input(t("Note (optional)"), placeholder=t("e.g. shop supplies, wedding expenses"))
        submitted = st.form_submit_button(t("Save payment"), type="primary", use_container_width=True)

    if submitted:
        digits = "".join(ch for ch in phone if ch.isdigit())
        if not name:
            st.error(t("Select or enter a party name."))
        elif not stored_phone and len(digits) < 10:
            st.error(t("Phone number is required (at least 10 digits)."))
        elif amount <= 0:
            st.error(t("Amount must be greater than 0."))
        elif kind in DATED_KINDS and rdate < tdate:
            st.error(t("Return date cannot be before the entry date."))
        else:
            pid = get_or_create_party(name, phone)
            run(
                "INSERT INTO txns(party_id, tdate, kind, amount, note, due_date, mode) VALUES (?,?,?,?,?,?,?)",
                (pid, tdate.isoformat(), kind, float(amount), note.strip(),
                 rdate.isoformat() if kind in DATED_KINDS else "", mode),
            )
            st.session_state["entry_flash"] = tf("Entry saved: {a} with {n}.", a=inr(amount), n=name)
            st.session_state["entry_n"] = n + 1  # party/phone fields reset
            st.rerun()


SHEETS = ["Udhari", "Income", "Loan", "Kist_Penalty", "Kharcha", "Parties", "Cash_Kharch", "Followup"]
EXP_COLS = ["date", "amount", "place", "category", "note"]
LOAN_COLS = ["name", "loan_amount", "kist_amount", "total_kists", "first_due",
             "penalty_type", "penalty_amount", "note"]
PAY_COLS = ["loan", "date", "kind", "amount", "note"]
PARTY_COLS = ["name", "phone"]
CASH_COLS = ["cash_date", "cash_amount", "cash_place", "date", "amount", "place", "note"]
FOLLOW_COLS = ["party", "mode", "promise_date", "set_on"]

# ---------------------------------------------------------------- master sheet (ek hi sheet me sab kuch)
MASTER_SHEET = "Master"
MASTER_COLS = [
    "type", "date", "name", "kind", "amount", "category", "place", "note", "mode", "due_date", "phone",
    "loan_amount", "kist_amount", "total_kists", "first_due", "penalty_type", "penalty_amount",
    "cash_date", "cash_amount", "cash_place", "followup_mode", "promise_date", "set_on",
]
# type -> {master column: column of the normal sheet}
MASTER_MAP = {
    "Udhari": {"name": "party", "date": "date", "kind": "kind", "amount": "amount", "note": "note",
               "due_date": "due_date", "mode": "mode"},
    "Income": {"date": "date", "amount": "amount", "category": "source", "note": "note", "mode": "mode"},
    "Kharcha": {"date": "date", "amount": "amount", "place": "place", "category": "category",
                "note": "note", "mode": "mode"},
    "Loan": {"name": "name", "loan_amount": "loan_amount", "kist_amount": "kist_amount",
             "total_kists": "total_kists", "first_due": "first_due", "penalty_type": "penalty_type",
             "penalty_amount": "penalty_amount", "note": "note"},
    "Kist_Penalty": {"name": "loan", "date": "date", "kind": "kind", "amount": "amount", "note": "note",
                     "mode": "mode"},
    "Parties": {"name": "name", "phone": "phone"},
    "Cash_Kharch": {"cash_date": "cash_date", "cash_amount": "cash_amount", "cash_place": "cash_place",
                    "date": "date", "amount": "amount", "place": "place", "note": "note"},
    "Followup": {"name": "party", "followup_mode": "mode", "promise_date": "promise_date", "set_on": "set_on"},
}
MASTER_ALIASES = {
    "udhari": "Udhari", "income": "Income", "kharcha": "Kharcha", "expense": "Kharcha",
    "loan": "Loan", "kist_penalty": "Kist_Penalty", "party": "Parties", "parties": "Parties",
    "cash_kharch": "Cash_Kharch", "followup": "Followup", "follow_up": "Followup",
}


def to_master(sheets):
    """{sheet: DataFrame} ko ek hi 'Master' DataFrame me badalta hai (type column batata hai ki row kis cheez ki hai)."""
    parts = []
    for sh, mp in MASTER_MAP.items():
        df = sheets.get(sh)
        if df is None or len(df) == 0:
            continue
        df = df.reset_index(drop=True)
        out = pd.DataFrame({mc: (df[sc] if sc in df.columns else "") for mc, sc in mp.items()})
        out.insert(0, "type", sh)
        parts.append(out)
    if not parts:
        return pd.DataFrame(columns=MASTER_COLS)
    return pd.concat(parts, ignore_index=True).reindex(columns=MASTER_COLS).fillna("")


def from_master(m):
    """Master DataFrame ko wapas normal sheets me todta hai. Returns (sheets, unrecognised_rows)."""
    out = {k: None for k in SHEETS}
    m = m.copy()
    for c in MASTER_COLS:
        if c not in m.columns:
            m[c] = ""
    key = m["type"].astype(str).str.strip().str.lower().str.replace(r"[\s-]+", "_", regex=True)
    kind_of = key.map(MASTER_ALIASES)
    blank = m.drop(columns="type").astype(str).apply(lambda col: col.str.strip()).eq("").all(axis=1)
    unknown = int((kind_of.isna() & ~blank).sum())
    for sh, mp in MASTER_MAP.items():
        rows = m[kind_of == sh]
        if rows.empty:
            continue
        out[sh] = pd.DataFrame({sc: rows[mc] for mc, sc in mp.items()}).reset_index(drop=True)
    return out, unknown


def master_template_xlsx():
    """Ek hi sheet ('Master') wala khali restore format + Instructions + Examples (examples restore nahi hote)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = MASTER_SHEET
    head_fill = PatternFill("solid", fgColor="4F46E5")
    head_font = Font(bold=True, color="FFFFFF")
    text_cols = ("date", "due_date", "phone", "first_due", "cash_date", "promise_date", "set_on")
    widths = {"type": 14, "date": 14, "name": 24, "kind": 22, "amount": 14, "category": 22, "place": 24,
              "note": 30, "mode": 11, "due_date": 14, "phone": 16, "loan_amount": 13, "kist_amount": 13,
              "total_kists": 12, "first_due": 14, "penalty_type": 13, "penalty_amount": 15, "cash_date": 14,
              "cash_amount": 14, "cash_place": 22, "followup_mode": 14, "promise_date": 14, "set_on": 14}

    def setup(sheet, rows=0):
        sheet.append(MASTER_COLS)
        for i, col in enumerate(MASTER_COLS, start=1):
            c = sheet.cell(row=1, column=i)
            c.fill, c.font = head_fill, head_font
            sheet.column_dimensions[c.column_letter].width = widths[col]
        sheet.freeze_panes = "A2"

    setup(ws)
    for col in text_cols:  # tarikh/phone ko text rakho, taaki Excel format na badle
        i = MASTER_COLS.index(col) + 1
        for r in range(2, 3002):
            ws.cell(row=r, column=i).number_format = "@"

    def dropdown(options, col, strict=True):
        letter = ws.cell(row=1, column=MASTER_COLS.index(col) + 1).column_letter
        dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"',
                            allow_blank=True, showErrorMessage=strict)
        dv.error, dv.errorTitle = "Select a value from the dropdown", "Invalid value"
        ws.add_data_validation(dv)
        dv.add(f"{letter}2:{letter}3000")

    dropdown(list(MASTER_MAP), "type")
    dropdown(list(KINDS) + ["kist", "penalty"], "kind")
    dropdown(MODES, "mode")
    dropdown(list(LOAN_PEN_TYPES), "penalty_type")
    dropdown(["date", "never"], "followup_mode")

    ex = wb.create_sheet("Examples")
    setup(ex)
    samples = [
        dict(type="Parties", name="Ramesh Sharma", phone="9876543210"),
        dict(type="Udhari", date="2026-10-01", name="Ramesh Sharma", kind="Money lent", amount=5000,
             note="For shop", mode="Cash", due_date="2026-11-01"),
        dict(type="Udhari", date="2026-10-10", name="Ramesh Sharma", kind="Repayment received", amount=2000,
             mode="Online"),
        dict(type="Income", date="2026-10-01", category="Salary", amount=30000, mode="Online"),
        dict(type="Kharcha", date="2026-10-05", place="D-Mart", category="Ghar / Ration", amount=1200,
             mode="Online"),
        dict(type="Loan", name="Bike loan", loan_amount=60000, kist_amount=3000, total_kists=24,
             first_due="2026-11-05", penalty_type="fixed", penalty_amount=200),
        dict(type="Kist_Penalty", date="2026-11-05", name="Bike loan", kind="kist", amount=3000, mode="Online"),
        dict(type="Cash_Kharch", cash_date="2026-10-02", cash_amount=2000, cash_place="ATM",
             date="2026-10-03", amount=150, place="Chai"),
        dict(type="Followup", name="Ramesh Sharma", followup_mode="date", promise_date="2026-11-01",
             set_on="2026-10-20"),
    ]
    for smp in samples:
        ex.append([smp.get(c, "") for c in MASTER_COLS])

    ins = wb.create_sheet("Instructions")
    lines = [
        ("Master restore file: everything on ONE sheet", True),
        ("", False),
        ("1. Use only the 'Master' sheet. Each row is one record. Do not change the header row.", False),
        ("2. The 'type' column (dropdown) tells the app what the row is. Fill only the columns listed below for that type.", False),
        ("3. Dates: YYYY-MM-DD, for example 2026-10-27. Leave unused columns blank.", False),
        ("4. Rows can be in any order. Exact duplicates are skipped, so restoring the same file twice is safe.", False),
        ("5. The 'Examples' sheet shows one filled row per type. It is NOT restored.", False),
        ("6. 'Download master backup' in the app gives a file in this same format, ready to restore.", False),
        ("", False),
        ("Columns to fill for each type", True),
    ]
    for sh, mp in MASTER_MAP.items():
        lines.append((f"{sh:<13}-> " + ", ".join(mp), False))
    lines += [
        ("", False),
        ("Notes", True),
        ("Udhari: name = party name, kind = " + " / ".join(KINDS) + "; due_date only for Money lent / Money borrowed.", False),
        ("Income: category = source (Salary, Bonus, Rent ...).", False),
        ("Loan: name must be unique; penalty_type = fixed / daily / pct.", False),
        ("Kist_Penalty: name = loan name (must exist in a Loan row or in the app); kind = kist or penalty.", False),
        ("Cash_Kharch: cash_* = the original Cash expense; date/amount/place = where that cash was spent.", False),
        ("Followup: name = party name; followup_mode = date or never; promise_date only when mode is date.", False),
        ("mode (Udhari, Income, Kharcha, Kist_Penalty) = Cash or Online.", False),
    ]
    for text, bold in lines:
        ins.append([text])
        ins.cell(row=ins.max_row, column=1).font = Font(bold=bold, size=12 if bold else 11, name="Consolas" if "->" in text else "Calibri")
    ins.column_dimensions["A"].width = 120

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()



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
    for c in ("date", "first_due", "due_date", "cash_date", "promise_date", "set_on"):
        if c in d.columns:
            d[c] = d[c].astype(str).str[:10]
    return d


def read_backup_all(f):
    """Ek Excel file se saari sheets padhta hai (purani CSV ho to sirf Udhari)."""
    if f.name.lower().endswith(".csv"):
        out = {k: None for k in SHEETS}
        out["Udhari"] = _clean(pd.read_csv(f))
        return out
    sheets = pd.read_excel(f, sheet_name=None, dtype={"date": str, "first_due": str, "due_date": str, "phone": str,
                                                  "cash_date": str, "promise_date": str, "set_on": str,
                                                  "type": str})
    out = {k: _clean(sheets[k]) if k in sheets else None for k in SHEETS}
    out["_master_skipped"] = 0
    mk = next((n for n in sheets if str(n).strip().lower() == MASTER_SHEET.lower()), None)
    if mk is not None:  # Master sheet ho to uski rows ko normal sheets me baant do
        parts, out["_master_skipped"] = from_master(_clean(sheets[mk]))
        for k, df in parts.items():
            if df is not None:
                out[k] = df if out[k] is None else pd.concat([out[k], df], ignore_index=True)
    return out


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
    make(ws1, ["party", "date", "kind", "amount", "note", "due_date", "mode"], [24, 14, 28, 14, 36, 14, 12],
         date_cols=("date", "due_date"))
    dropdown(ws1, list(KINDS), "C2:C1000")
    dropdown(ws1, MODES, "G2:G1000")

    ws2 = wb.create_sheet("Income")
    make(ws2, ["date", "amount", "source", "note", "mode"], [14, 14, 24, 36, 12])
    dropdown(ws2, INCOME_SOURCES[:-1], "C2:C1000", strict=False)
    dropdown(ws2, MODES, "E2:E1000")

    ws3 = wb.create_sheet("Loan")
    make(ws3, LOAN_COLS, [24, 16, 14, 14, 14, 14, 16, 30], date_cols=("first_due",))
    dropdown(ws3, list(LOAN_PEN_TYPES), "F2:F1000")

    ws4 = wb.create_sheet("Kist_Penalty")
    make(ws4, PAY_COLS + ["mode"], [24, 14, 12, 14, 30, 12])
    dropdown(ws4, ["kist", "penalty"], "C2:C1000")
    dropdown(ws4, MODES, "F2:F1000")

    ws6 = wb.create_sheet("Kharcha")
    make(ws6, EXP_COLS + ["mode"], [14, 14, 28, 22, 36, 12])
    dropdown(ws6, EXPENSE_CATS[:-1], "D2:D1000", strict=False)
    dropdown(ws6, MODES, "F2:F1000")

    ws7 = wb.create_sheet("Parties")
    make(ws7, PARTY_COLS, [28, 18], date_cols=("phone",))

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
        ("due_date -> optional, return date for Money lent / Money borrowed (YYYY-MM-DD); the alert uses it", False),
        ("", False),
        ("Income sheet", True),
        ("date, amount, note -> as above", False),
        ("source -> where the income came from (for example Salary, Bonus, Rent, or your own label)", False),
        ("", False),
        ("Kharcha sheet (expenses)", True),
        ("date, amount, note -> as above", False),
        ("place    -> where the money was spent (required)", False),
        ("category -> for example Ghar / Ration, Petrol / Travel, or your own label", False),
        ("", False),
        ("Parties sheet (phone numbers)", True),
        ("name  -> party name, exactly as on the Udhari sheet", False),
        ("phone -> phone number (kept as text)", False),
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
        ("mode -> optional on the Udhari, Income, Kharcha and Kist_Penalty sheets: Cash or Online", False),
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
    with closing(sqlite3.connect(db_path())) as c:
        c.execute("PRAGMA foreign_keys = ON")
        for tbl in ("alert_acks", "cash_spends", "loan_payments", "loans", "followups", "txns", "parties", "income", "expenses"):
            c.execute(f"DELETE FROM {tbl}")
        c.execute("DELETE FROM sqlite_sequence")
        c.commit()


def wipe_callback():
    wipe_all_data()
    st.session_state["wipe_sure"] = False
    st.session_state["wipe_word"] = ""
    st.session_state["wiped"] = True


def wipe_section(counts):
    st.divider()
    st.markdown(t("#### Delete all data"))
    st.caption(counts)
    with st.expander(t("Danger zone")):
        st.error(
            t("This permanently deletes all lending records, parties, income, expenses, loans and instalments. It cannot be undone. Download an Excel backup first.")
        )
        sure = st.checkbox(t("I understand that all data will be deleted"), key="wipe_sure")
        word = st.text_input(t("Type DELETE to confirm"), key="wipe_word", placeholder=t("DELETE"))
        st.button(
            t("Delete all data"), type="primary",
            disabled=not (sure and word.strip().upper() == "DELETE"),
            on_click=wipe_callback,
        )


def backup_section():
    if st.session_state.pop("wiped", False):
        st.success(t("All data has been deleted."))
    st.warning(
        t("On Streamlit Cloud the database file can be lost when the app restarts. Download an Excel backup regularly.")
    )
    df = txns_df()
    export = df[["party", "date", "kind", "amount", "note", "due_date", "mode"]]
    inc = income_df()
    inc_export = inc[["date", "amount", "source", "note", "mode"]]
    loans = loans_df()
    loan_export = loans[LOAN_COLS]
    pays = loan_pay_df()
    pay_export = pays[PAY_COLS + ["mode"]]
    exp_export = expenses_df()[EXP_COLS + ["mode"]]
    phones = parties_df()
    party_export = phones[["name", "phone"]].fillna("")
    cash_export = query_df(
        "SELECT e.edate AS cash_date, e.amount AS cash_amount, e.place AS cash_place, "
        "c.sdate AS date, c.amount, c.place, c.note FROM cash_spends c "
        "JOIN expenses e ON e.id = c.expense_id ORDER BY c.sdate, c.id"
    ).fillna("")
    follow_export = query_df(
        "SELECT p.name AS party, f.mode, f.promise_date, f.set_on FROM followups f "
        "JOIN parties p ON p.id = f.party_id ORDER BY p.name"
    ).fillna("")
    empty = export.empty and inc_export.empty and loan_export.empty and exp_export.empty

    master_export = to_master({
        "Udhari": export, "Income": inc_export, "Kharcha": exp_export, "Loan": loan_export,
        "Kist_Penalty": pay_export, "Parties": party_export, "Cash_Kharch": cash_export,
        "Followup": follow_export,
    })

    c1, c2 = st.columns(2)
    # restore me error aane par bhi ye hissa dikhta rahe, isliye pehle hi bana liya
    wipe_box = st.container()
    with wipe_box:
        wipe_section(
            tf("Currently stored: {a} lending entries, {b} parties, {c} income entries, {d} expense entries, {e} loans, {f} instalment/penalty payments",
               a=len(export), b=len(phones), c=len(inc_export), d=len(exp_export),
               e=len(loan_export), f=len(pay_export))
        )
    with c1:
        st.markdown(t("#### Backup"))
        st.caption(
            tf("{a} lending entries, {b} parties, {c} income entries, {d} expense entries, {e} loans",
               a=len(export), b=len(phones), c=len(inc_export), d=len(exp_export), e=len(loan_export))
        )
        st.download_button(
            t("Download Excel backup"),
            to_xlsx_multi({MASTER_SHEET: master_export}),
            file_name=f"balance_sheet_master_backup_{date.today().isoformat()}.xlsx",
            mime=XLSX_MIME, disabled=master_export.empty, type="primary",
            help=t("All records on a single 'Master' sheet. It can be restored directly."),
        )
    with c2:
        st.markdown(t("#### Restore"))
        st.download_button(
            t("Download blank restore template"),
            master_template_xlsx(),
            file_name="balance_sheet_master_restore_format.xlsx",
            mime=XLSX_MIME,
            help=t("One sheet holds everything. The 'type' column says what each row is. See the Instructions sheet."),
        )
        up = st.file_uploader(t("Select a backup file"), type=["xlsx", "csv"], label_visibility="collapsed")
        if up is not None and st.button(t("Restore")):
            sheets = read_backup_all(up)
            ud, ic, lo, kp, ke, pa, cs, fu = (sheets[k] for k in SHEETS)
            if all(x is None for x in (ud, ic, lo, kp, ke, pa, cs, fu)):
                st.error(t("The file must contain at least one of these sheets: Master, Udhari, Income, Loan, Kist_Penalty, Kharcha, Parties, Cash_Kharch, Followup."))
                return

            msgs = []
            if sheets.get("_master_skipped"):
                msgs.append(tf("Master sheet: {n} rows skipped because the 'type' value was not recognised.",
                               n=sheets["_master_skipped"]))
            if pa is not None:
                # phone numbers pehle, taaki neeche banne wali parties me number pehle se jud jaye
                if not set(PARTY_COLS).issubset(pa.columns):
                    st.error(t("The Parties sheet must have these columns: ") + ", ".join(PARTY_COLS))
                    return
                done = 0
                for _, r in pa.iterrows():
                    nm = str(r["name"]).strip()
                    ph = str(r["phone"]).strip()
                    if ph.endswith(".0") and ph[:-2].isdigit():
                        ph = ph[:-2]
                    if not nm or nm.lower() == "nan":
                        continue
                    get_or_create_party(nm, "" if ph.lower() == "nan" else ph)
                    done += 1
                msgs.append(tf("Parties: {a} parties restored with their phone numbers.", a=done))

            if ud is not None:
                if "kind" in ud.columns:
                    ud["kind"] = ud["kind"].replace(LEGACY_KINDS)
                need = {"party", "date", "kind", "amount", "note"}
                if not need.issubset(ud.columns):
                    st.error(t("The Udhari sheet must have these columns: party, date, kind, amount, note"))
                    return
                bad = set(ud["kind"]) - set(KINDS)
                if bad:
                    st.error(tf("Unrecognised 'kind' values: {v}", v=", ".join(map(str, bad))))
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
                    due = str(r["due_date"])[:10] if "due_date" in ud.columns and r["kind"] in DATED_KINDS else ""
                    run(
                        "INSERT INTO txns(party_id, tdate, kind, amount, note, due_date, mode) VALUES (?,?,?,?,?,?,?)",
                        (pid, str(r["date"]), r["kind"], float(r["amount"]), str(r["note"]), due, _mode_of(r, ud)),
                    )
                    seen.add(key)
                    added += 1
                msgs.append(tf("Udhari: {a} entries added, {s} already present.", a=added, s=skipped))

            if ic is not None:
                if not {"date", "amount", "source", "note"}.issubset(ic.columns):
                    st.error(t("The Income sheet must have these columns: date, amount, source, note"))
                    return
                have = {(str(r.date), round(float(r.amount), 2), str(r.source), str(r.note)) for r in inc.itertuples()}
                added = skipped = 0
                for _, r in ic.iterrows():
                    key = (str(r["date"]), round(float(r["amount"]), 2), str(r["source"]), str(r["note"]))
                    if key in have:
                        skipped += 1
                        continue
                    run("INSERT INTO income(idate, amount, source, note, mode) VALUES (?,?,?,?,?)",
                        (key[0], float(r["amount"]), key[2], key[3], _mode_of(r, ic)))
                    have.add(key)
                    added += 1
                msgs.append(tf("Income: {a} entries added, {s} already present.", a=added, s=skipped))

            if ke is not None:
                if not set(EXP_COLS).issubset(ke.columns):
                    st.error(t("The Kharcha sheet must have these columns: ") + ", ".join(EXP_COLS))
                    return
                have = {
                    (str(r.date)[:10], round(float(r.amount), 2), str(r.place).strip(), str(r.note))
                    for r in expenses_df().itertuples()
                }
                added = skipped = bad = 0
                for _, r in ke.iterrows():
                    try:
                        amt = float(r["amount"])
                        date.fromisoformat(str(r["date"])[:10])
                        pl = str(r["place"]).strip()
                        if amt <= 0 or not pl:
                            raise ValueError
                    except (ValueError, TypeError):
                        bad += 1
                        continue
                    key = (str(r["date"])[:10], round(amt, 2), pl, str(r["note"]))
                    if key in have:
                        skipped += 1
                        continue
                    run(
                        "INSERT INTO expenses(edate, amount, place, category, note, mode) VALUES (?,?,?,?,?,?)",
                        (key[0], amt, pl, str(r["category"]).strip() or "Other", key[3], _mode_of(r, ke)),
                    )
                    have.add(key)
                    added += 1
                msgs.append(tf("Expenses: {a} added, {s} already present, {b} invalid rows skipped.", a=added, s=skipped, b=bad))

            if cs is not None:
                if not set(CASH_COLS).issubset(cs.columns):
                    st.error(t("The Cash_Kharch sheet must have these columns: ") + ", ".join(CASH_COLS))
                    return
                cash_ids = {}
                for r in expenses_df().itertuples():
                    if r.category == "Cash":
                        cash_ids[(str(r.date)[:10], round(float(r.amount), 2), str(r.place).strip())] = int(r.id)
                have = {
                    (r.cash_date, round(float(r.cash_amount), 2), r.cash_place, str(r.date), round(float(r.amount), 2), r.place, str(r.note))
                    for r in query_df(
                        "SELECT e.edate AS cash_date, e.amount AS cash_amount, e.place AS cash_place, "
                        "c.sdate AS date, c.amount, c.place, c.note FROM cash_spends c "
                        "JOIN expenses e ON e.id = c.expense_id"
                    ).itertuples()
                }
                added = skipped = bad = 0
                for _, r in cs.iterrows():
                    try:
                        ck = (str(r["cash_date"])[:10], round(float(r["cash_amount"]), 2), str(r["cash_place"]).strip())
                        amt = float(r["amount"])
                        sd = str(r["date"])[:10]
                        date.fromisoformat(sd)
                        pl = str(r["place"]).strip()
                        if ck not in cash_ids or amt <= 0 or not pl:
                            raise ValueError
                    except (ValueError, TypeError):
                        bad += 1
                        continue
                    key = (ck[0], ck[1], ck[2], sd, round(amt, 2), pl, str(r["note"]))
                    if key in have:
                        skipped += 1
                        continue
                    run(
                        "INSERT INTO cash_spends(expense_id, sdate, amount, place, note) VALUES (?,?,?,?,?)",
                        (cash_ids[ck], sd, amt, pl, str(r["note"])),
                    )
                    have.add(key)
                    added += 1
                msgs.append(tf("Cash spending: {a} added, {s} already present, {b} invalid rows skipped.", a=added, s=skipped, b=bad))

            if lo is not None:
                if not set(LOAN_COLS).issubset(lo.columns):
                    st.error(t("The Loan sheet must have these columns: ") + ", ".join(LOAN_COLS))
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
                    tf("Loan: {a} added, {s} already present, {b} invalid rows skipped.", a=added, s=skipped, b=bad)
                )

            if kp is not None:
                if not set(PAY_COLS).issubset(kp.columns):
                    st.error(t("The Kist_Penalty sheet must have these columns: ") + ", ".join(PAY_COLS))
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
                        "INSERT INTO loan_payments(loan_id, pdate, kind, amount, note, mode) VALUES (?,?,?,?,?,?)",
                        (ids[nm], key[1], kind, amt, key[4], _mode_of(r, kp)),
                    )
                    have.add(key)
                    added += 1
                msgs.append(
                    tf("Instalments/penalties: {a} added, {s} already present, {b} invalid rows skipped.", a=added, s=skipped, b=bad)
                )

            if fu is not None:
                if not set(FOLLOW_COLS).issubset(fu.columns):
                    st.error(t("The Followup sheet must have these columns: ") + ", ".join(FOLLOW_COLS))
                    return
                has = set(query_df("SELECT party_id FROM followups")["party_id"].astype(int))
                added = skipped = 0
                for _, r in fu.iterrows():
                    nm, mode = str(r["party"]).strip(), str(r["mode"]).strip()
                    if not nm or not mode or mode.lower() == "nan":
                        continue
                    pid = get_or_create_party(nm)
                    if pid in has:
                        skipped += 1
                        continue
                    pd_, so = str(r["promise_date"])[:10], str(r["set_on"])[:10]
                    run(
                        "INSERT INTO followups(party_id, mode, promise_date, set_on) VALUES (?,?,?,?)",
                        (pid, mode, "" if pd_.lower() == "nan" else pd_, so if so and so.lower() != "nan" else date.today().isoformat()),
                    )
                    has.add(pid)
                    added += 1
                msgs.append(tf("Follow-ups: {a} added, {s} already present.", a=added, s=skipped))

            st.success("  \n".join(msgs))


# ---------------------------------------------------------------- edit records
def cleanup_parties():
    """Remove parties that no longer have any entries."""
    run("DELETE FROM parties WHERE id NOT IN (SELECT DISTINCT party_id FROM txns)")


def delete_block(table, rid, key, warn=""):
    with st.expander(t("Delete this record")):
        if warn:
            st.warning(t(warn))
        sure = st.checkbox(t("Yes, delete this record permanently"), key=f"del_ok_{key}_{rid}")
        if st.button(t("Delete"), key=f"del_{key}_{rid}", disabled=not sure):
            run(f"DELETE FROM {table} WHERE id = ?", (int(rid),))
            cleanup_parties()
            st.session_state["flash"] = "Record deleted."
            st.rerun()


def _d(v):
    return date.fromisoformat(str(v)[:10])


def edit_txns():
    df = txns_df()
    if df.empty:
        st.info(t("No lending or borrowing entries yet."))
        return
    df = df.sort_values(["date", "id"], ascending=False)
    labels = {
        int(r["id"]): f"{r['date']} | {r['party']} | {t(r['kind'])} | {inr(r['amount'])}"
        for _, r in df.iterrows()
    }
    rid = st.selectbox(t("Select entry"), list(labels), format_func=labels.get, key="edit_txn_pick")
    r = df[df["id"] == rid].iloc[0]
    kinds = list(KINDS)
    cur_phone = ""
    prow = query_df("SELECT phone FROM parties WHERE id = ?", (int(r["party_id"]),))
    if not prow.empty:
        cur_phone = (prow.iloc[0]["phone"] or "").strip()
    with st.form(f"edit_txn_{rid}"):
        name = st.text_input(t("Party name (change it to move this entry to another party)"), value=r["party"])
        phone = st.text_input(
            t("Phone (required)"), value=cur_phone, placeholder=t("98xxxxxx10"),
            help=t("This party's phone number. Changing it here updates the party's number. If you move this entry to another saved party, that party's saved number is used."),
        )
        kind = st.selectbox(t("Transaction type"), kinds, index=kinds.index(r["kind"]) if r["kind"] in kinds else 0,
                            format_func=t)
        a, b = st.columns(2)
        amount = a.number_input(t("Amount (₹)"), min_value=0.0, value=float(r["amount"]), step=100.0, format="%.2f")
        tdate = b.date_input(t("Date"), value=_d(r["date"]))
        mode = mode_pick(r.get("mode", ""), key=f"edit_txn_mode_{rid}")
        rdate = st.date_input(
            t("Return date (lent: when they will return it, borrowed: when you will return it)"),
            value=_iso(r["due_date"]) or (date.today() + timedelta(days=30)),
            help=t("Used only for 'Money lent' and 'Money borrowed'. You get an alert when this date arrives."),
        )
        note = st.text_input(t("Note (optional)"), value=r["note"] or "")
        ok = st.form_submit_button(t("Save changes"), type="primary", use_container_width=True)
    if ok:
        digits = "".join(ch for ch in phone if ch.isdigit())
        target = query_df("SELECT id, phone FROM parties WHERE name = ?", (name.strip(),))
        target_phone = (target.iloc[0]["phone"] or "").strip() if not target.empty else ""
        moving_to_saved = (not target.empty) and int(target.iloc[0]["id"]) != int(r["party_id"]) and target_phone
        if not name.strip():
            st.error(t("Party name cannot be empty."))
        elif not moving_to_saved and len(digits) < 10:
            st.error(t("Phone number is required (at least 10 digits)."))
        elif amount <= 0:
            st.error(t("Amount must be greater than 0."))
        elif kind in DATED_KINDS and rdate < tdate:
            st.error(t("Return date cannot be before the entry date."))
        else:
            pid = get_or_create_party(name, phone.strip())
            if not moving_to_saved:
                run("UPDATE parties SET phone = ? WHERE id = ?", (phone.strip(), pid))
            run(
                "UPDATE txns SET party_id=?, tdate=?, kind=?, amount=?, note=?, due_date=?, mode=? WHERE id=?",
                (pid, tdate.isoformat(), kind, float(amount), note.strip(),
                 rdate.isoformat() if kind in DATED_KINDS else "", mode, int(rid)),
            )
            cleanup_parties()
            st.session_state["flash"] = "Entry updated."
            st.rerun()
    delete_block("txns", rid, "txn")


def edit_income():
    df = income_df()
    if df.empty:
        st.info(t("No income entries yet."))
        return
    df = df.sort_values(["date", "id"], ascending=False)
    labels = {
        int(r["id"]): f"{r['date']} | {r['source']} | {inr(r['amount'])}" for _, r in df.iterrows()
    }
    rid = st.selectbox(t("Select income entry"), list(labels), format_func=labels.get, key="edit_inc_pick")
    r = df[df["id"] == rid].iloc[0]
    cur = (r["source"] or "").strip()
    in_list = cur in INCOME_SOURCES and cur != "Other"
    # form ke bahar, taaki 'Other' chunte hi naam likhne ka box turant aa jaye
    src_pick = st.selectbox(
        t("Source"), INCOME_SOURCES, key=f"edit_inc_src_{rid}", format_func=t,
        index=INCOME_SOURCES.index(cur) if in_list else INCOME_SOURCES.index("Other"),
    )
    other = ""
    if src_pick == "Other":
        other = st.text_input(
            t("Specify source"), value="" if in_list else cur,
            placeholder=t("e.g. Tuition, Freelance"), key=f"edit_inc_other_{rid}",
        )
    with st.form(f"edit_inc_{rid}"):
        a, b = st.columns(2)
        amount = a.number_input(t("Amount (₹)"), min_value=0.0, value=float(r["amount"]), step=500.0, format="%.2f")
        idate = b.date_input(t("Date received"), value=_d(r["date"]))
        mode = mode_pick(r.get("mode", ""), key=f"edit_inc_mode_{rid}")
        note = st.text_input(t("Note (optional)"), value=r["note"] or "")
        ok = st.form_submit_button(t("Save changes"), type="primary", use_container_width=True)
    if ok:
        source = other.strip() if src_pick == "Other" else src_pick
        if amount <= 0:
            st.error(t("Amount must be greater than 0."))
        elif not source:
            st.error(t("Specify the source when 'Other' is selected."))
        else:
            run(
                "UPDATE income SET idate=?, amount=?, source=?, note=?, mode=? WHERE id=?",
                (idate.isoformat(), float(amount), source, note.strip(), mode, int(rid)),
            )
            st.session_state["flash"] = "Income entry updated."
            st.rerun()
    delete_block("income", rid, "inc")


def loan_total_note(loan):
    """Show instalments due + penalty = total outstanding for a loan (penalty is recalculated live)."""
    pays = loan_pay_df()
    inf = loan_summary(dict(loan), pays[pays["loan_id"] == int(loan["id"])], date.today())
    st.info(
        tf("Instalments due {a} + penalty due {b} = total outstanding {c}",
           a=inr(inf['pending']), b=inr(inf['pen_due']), c=inr(inf['pending'] + inf['pen_due']))
        + "  \n"
        + tf("Penalty accrued so far {d}, penalty paid {e}.", d=inr(inf['pen_total']), e=inr(inf['pen_paid']))
    )


def edit_expenses():
    df = expenses_df()
    if df.empty:
        st.info(t("No expense entries yet."))
        return
    df = df.sort_values(["date", "id"], ascending=False)
    labels = {
        int(r["id"]): f"{r['date']} | {r['place']} | {t(r['category'])} | {inr(r['amount'])}"
        for _, r in df.iterrows()
    }
    rid = st.selectbox(t("Select expense entry"), list(labels), format_func=labels.get, key="edit_exp_pick")
    r = df[df["id"] == rid].iloc[0]
    cats = EXPENSE_CATS if r["category"] in EXPENSE_CATS else EXPENSE_CATS + [r["category"]]
    with st.form(f"edit_exp_{rid}"):
        place = st.text_input(t("Where was it spent?"), value=r["place"])
        cat = st.selectbox(t("Category"), cats, index=cats.index(r["category"]), format_func=t)
        a, b = st.columns(2)
        amount = a.number_input(t("Amount (₹)"), min_value=0.0, value=float(r["amount"]), step=100.0, format="%.2f")
        edate = b.date_input(t("Date"), value=_d(r["date"]))
        mode = mode_pick(r.get("mode", ""), key=f"edit_exp_mode_{rid}")
        note = st.text_input(t("Note (optional)"), value=r["note"] or "")
        ok = st.form_submit_button(t("Save changes"), type="primary", use_container_width=True)
    if ok:
        if not place.strip():
            st.error(t("Place cannot be empty."))
        elif amount <= 0:
            st.error(t("Amount must be greater than 0."))
        else:
            run(
                "UPDATE expenses SET edate=?, amount=?, place=?, category=?, note=?, mode=? WHERE id=?",
                (edate.isoformat(), float(amount), place.strip(), cat, note.strip(), mode, int(rid)),
            )
            st.session_state["flash"] = "Expense updated."
            st.rerun()
    delete_block("expenses", rid, "exp")


def edit_loans():
    df = loans_df()
    if df.empty:
        st.info(t("No loans yet."))
        return
    labels = {int(r["id"]): f"{r['name']} | {inr(r['kist_amount'])} × {int(r['total_kists'])}" for _, r in df.iterrows()}
    rid = st.selectbox(t("Select loan"), list(labels), format_func=labels.get, key="edit_loan_pick")
    r = df[df["id"] == rid].iloc[0]
    loan_total_note(r)
    ptypes = list(LOAN_PEN_TYPES)
    with st.form(f"edit_loan_{rid}"):
        name = st.text_input(t("Loan name"), value=r["name"])
        a, b, c = st.columns(3)
        loan_amount = a.number_input(t("Loan amount (₹, optional)"), min_value=0.0, value=float(r["loan_amount"] or 0), step=1000.0, format="%.2f")
        kist = b.number_input(t("Instalment amount (₹)"), min_value=0.0, value=float(r["kist_amount"]), step=100.0, format="%.2f")
        n = c.number_input(t("Number of instalments"), min_value=1, value=int(r["total_kists"]), step=1)
        d, e, f = st.columns(3)
        ptype = d.selectbox(
            t("Penalty type"), ptypes, format_func=lambda k: t(LOAN_PEN_TYPES.get(k, k)),
            index=ptypes.index(r["penalty_type"]) if r["penalty_type"] in ptypes else 0,
        )
        pen = e.number_input(t("Penalty amount / %"), min_value=0.0, value=float(r["penalty_amount"]), step=10.0, format="%.2f")
        first = f.date_input(t("First due date"), value=_d(r["first_due"]))
        note = st.text_input(t("Note (optional)"), value=r["note"] or "")
        ok = st.form_submit_button(t("Save changes"), type="primary", use_container_width=True)
    if ok:
        name = name.strip()
        if not name:
            st.error(t("Enter a loan name."))
        elif kist <= 0:
            st.error(t("Instalment amount must be greater than 0."))
        elif not query_df(
            "SELECT 1 FROM loans WHERE name = ? COLLATE NOCASE AND id != ?", (name, int(rid))
        ).empty:
            st.error(t("Another loan already has this name."))
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
        st.info(t("No instalment or penalty payments yet."))
        return
    df = df.sort_values(["date", "id"], ascending=False)
    labels = {
        int(r["id"]): f"{r['date']} | {r['loan']} | {t('Instalment' if r['kind'] == 'kist' else 'Penalty')} | {inr(r['amount'])}"
        for _, r in df.iterrows()
    }
    rid = st.selectbox(t("Select payment"), list(labels), format_func=labels.get, key="edit_pay_pick")
    r = df[df["id"] == rid].iloc[0]
    loans = loans_df()
    loan_ids = {row["name"]: int(row["id"]) for row in loans.to_dict("records")}
    names = list(loan_ids)
    kinds = ["kist", "penalty"]
    if r["loan"] in names:
        loan_total_note(loans[loans["id"] == r["loan_id"]].iloc[0])
    with st.form(f"edit_pay_{rid}"):
        loan = st.selectbox(t("Loan"), names, index=names.index(r["loan"]) if r["loan"] in names else 0)
        kind = st.radio(
            t("Payment type"), kinds, horizontal=True,
            format_func=lambda k: t("Instalment" if k == "kist" else "Penalty"),
            index=kinds.index(r["kind"]) if r["kind"] in kinds else 0,
        )
        a, b = st.columns(2)
        amount = a.number_input(t("Amount (₹)"), min_value=0.0, value=float(r["amount"]), step=100.0, format="%.2f")
        pdate = b.date_input(t("Payment date"), value=_d(r["date"]))
        mode = mode_pick(r.get("mode", ""), key=f"edit_pay_mode_{rid}")
        note = st.text_input(t("Note (optional)"), value=r["note"] or "")
        ok = st.form_submit_button(t("Save changes"), type="primary", use_container_width=True)
    if ok:
        if amount <= 0:
            st.error(t("Amount must be greater than 0."))
        else:
            run(
                "UPDATE loan_payments SET loan_id=?, pdate=?, kind=?, amount=?, note=?, mode=? WHERE id=?",
                (loan_ids[loan], pdate.isoformat(), kind, float(amount), note.strip(), mode, int(rid)),
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
            "Mode": r.mode or "", "Direction": "In" if r.kind in IN_KINDS else "Out", "Amount": float(r.amount), "Note": r.note or "",
        })
    for r in income_df().itertuples():
        rows.append({
            "Date": r.date, "Group": "Income", "Type": "Income", "Party / loan": r.source,
            "Mode": r.mode or "", "Direction": "In", "Amount": float(r.amount), "Note": r.note or "",
        })
    for r in expenses_df().itertuples():
        rows.append({
            "Date": r.date, "Group": "Expenses", "Type": r.category, "Party / loan": r.place,
            "Mode": r.mode or "", "Direction": "Out", "Amount": float(r.amount), "Note": r.note or "",
        })
    for r in loan_pay_df().itertuples():
        rows.append({
            "Date": r.date, "Group": "Loan payments",
            "Type": "Instalment" if r.kind == "kist" else "Penalty", "Party / loan": r.loan,
            "Mode": r.mode or "", "Direction": "Out", "Amount": float(r.amount), "Note": r.note or "",
        })
    cols = ["Date", "Group", "Type", "Party / loan", "Mode", "Direction", "Amount", "Note"]
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values("Date", ascending=False, kind="stable").reset_index(drop=True)


def admin_transactions():
    df = all_transactions()
    if df.empty:
        st.info(t("No transactions yet."))
        return
    f1, f3, f2 = st.columns([1, 1, 2])
    group = f1.selectbox(t("Show"), ["All", "Lending / borrowing", "Income", "Expenses", "Loan payments"],
                         key="adm_group", format_func=t)
    mode_f = f3.selectbox(t("Payment mode"), ["All"] + MODES, key="adm_mode", format_func=t)
    q = f2.text_input(t("Search party, loan or note"), key="adm_q")
    if group != "All":
        df = df[df["Group"] == group]
    if mode_f != "All":
        df = df[df["Mode"] == mode_f]
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
    k1.markdown(kpi("Money in", inr(money_in), tf("{n} entries", n=int((df['Direction'] == 'In').sum())), "g"), unsafe_allow_html=True)
    k2.markdown(kpi("Money out", inr(money_out), tf("{n} entries", n=int((df['Direction'] == 'Out').sum())), "r"), unsafe_allow_html=True)
    k3.markdown(kpi("Net", inr(money_in - money_out), "in − out", "g" if money_in >= money_out else "r"), unsafe_allow_html=True)
    st.write("")
    show_df(
        df.drop(columns=["Group"]), hide_index=True, use_container_width=True,
        column_config={"Amount": st.column_config.NumberColumn(format="₹%.2f")},
    )
    st.caption(t("To correct or delete an entry, open 'Edit records' above."))


def profile_section():
    """Password turant badalta hai. Naam / pita ka naam / umar / photo admin ke verify karne par hi badlenge."""
    a = st.session_state.get("auth", {})
    if a.get("role") != "user":
        st.info(t("Profile settings are only for user accounts."))
        return
    uid = a["uid"]
    prof = user_profile(uid)
    if prof is None:
        return
    flash = st.session_state.pop("profile_flash", None)
    if flash:
        st.success(t(flash))

    # ---- current details
    st.markdown("#### 👤 " + t("Your current details"))
    fl = t("Father's name")
    c1, c2 = st.columns([1, 4])
    c1.markdown(photo_html(prof["photo"], 72, prof["name"]), unsafe_allow_html=True)
    c2.markdown(
        f"**{escape(prof['name'])}**  \n{fl}: {escape(prof['father_name'])}  \n"
        f"{t('Age')}: {prof['age']} · 📱 {escape(prof['phone'])}"
    )

    # ---- pending request (status) is always visible
    req = get_profile_request(uid)
    if req is not None:
        with st.container(border=True):
            st.markdown("🕒 **" + t("Waiting for admin approval") + "**")
            st.caption(t("Requested details"))
            r1, r2 = st.columns([1, 4])
            r1.markdown(photo_html(req["photo"] if req["photo"] is not None else prof["photo"], 56, req["name"]),
                        unsafe_allow_html=True)
            r2.markdown(f"**{escape(req['name'])}**  \n{fl}: {escape(req['father_name'])}  \n"
                        f"{t('Age')}: {req['age']}")
            if st.button(t("Cancel request"), key="pr_cancel"):
                delete_profile_request(uid)
                st.session_state["profile_flash"] = "Request cancelled."
                st.rerun()

    # ---- two buttons: the forms open only when clicked (click again to close)
    def _toggle(which):
        st.session_state["profile_open"] = None if st.session_state.get("profile_open") == which else which

    opened = st.session_state.get("profile_open")
    b1, b2 = st.columns(2)
    b1.button("🔒 " + t("Change password"), key="pf_pw_btn", on_click=_toggle, args=("pw",),
              use_container_width=True, type="primary" if opened == "pw" else "secondary")
    b2.button("👤 " + t("Update profile details"), key="pf_det_btn", on_click=_toggle, args=("details",),
              use_container_width=True, type="primary" if opened == "details" else "secondary")

    if opened == "pw":
        st.markdown(t("#### 🔒 Change password"))
        st.caption(t("Password changes take effect immediately."))
        with st.form("pw_change_form", clear_on_submit=True):
            cur = st.text_input(t("Current password"), type="password")
            n1 = st.text_input(t("New password"), type="password", help=t("At least 6 characters."))
            n2 = st.text_input(t("Confirm password"), type="password")
            ok = st.form_submit_button(t("Change password"), type="primary", use_container_width=True)
        if ok:
            if not verify_user_password(uid, cur):
                st.error(t("Current password is incorrect."))
            elif len(n1) < MIN_PASSWORD:
                st.error(t("Password must be at least 6 characters."))
            elif n1 != n2:
                st.error(t("Both passwords must be the same."))
            elif n1 == cur:
                st.error(t("New password must be different from the current one."))
            else:
                set_user_password(uid, n1)
                st.session_state["profile_flash"] = "Password updated."
                st.session_state["profile_open"] = None
                st.rerun()

    elif opened == "details":
        st.markdown(t("#### 👤 Update profile details"))
        st.info(t("Name, father's name, age and photo changes are applied only after the admin verifies them. Until then your old details stay."))
        base = req if req is not None else prof
        with st.form("profile_update_form"):
            name = st.text_input(t("Full name"), value=base["name"])
            father = st.text_input(t("Father's name"), value=base["father_name"])
            age = st.number_input(t("Age"), min_value=18, max_value=100, value=min(max(int(base["age"]), 18), 100), step=1)
            pic = st.file_uploader(t("Your photo (leave empty to keep the current one)"), type=["jpg", "jpeg", "png"])
            ok = st.form_submit_button(t("Send for verification"), type="primary", use_container_width=True)
        if ok:
            name, father = clean_name(name), clean_name(father)
            photo = None
            photo_bad = False
            if pic is not None:
                try:
                    photo = process_photo(pic.getvalue())
                except ValueError:
                    photo_bad = True
            if not valid_name(name) or not valid_name(father):
                st.error(t("Enter a valid name and father's name."))
            elif photo_bad:
                st.error(t("This photo could not be read. Please choose a JPG or PNG image."))
            elif (photo is None and name == prof["name"] and father == prof["father_name"]
                  and int(age) == int(prof["age"])):
                st.info(t("No change found. Edit a detail first."))
            else:
                if photo is None and req is not None:
                    photo = req["photo"]  # pehle bheji hui nayi photo na hat jaye
                save_profile_request(uid, name, father, int(age), photo)
                st.session_state["profile_flash"] = "Your update request has been sent to the admin. Until it is approved, your old details stay."
                st.session_state["profile_open"] = None
                st.rerun()


def page_admin():
    hero(P_EDIT, "Transactions, editing of older records, backup & restore, profile")
    language_picker()
    is_user = st.session_state.get("auth", {}).get("role") == "user"
    options = ["Transactions", "Edit records", "Backup & restore"] + (["Profile"] if is_user else [])
    icons = {"Transactions": "💸 ", "Edit records": "✏️ ", "Backup & restore": "💾 ", "Profile": "👤 "}
    section = st.radio(
        t("Section"), options, horizontal=True,
        key="admin_section", label_visibility="collapsed",
        format_func=lambda x: icons[x] + t(x if x != "Profile" else "Profile update"),
    )
    if section == "Profile":
        profile_section()  # password badalne ke liye alag se lock nahi
        return
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(t(flash))
    if section == "Transactions":
        admin_transactions()
        return
    if section == "Backup & restore":
        backup_section()
        return
    sections = {
        "Lending / borrowing": edit_txns,
        "Income": edit_income,
        "Expenses": edit_expenses,
        "Loans": edit_loans,
        "Instalment / penalty payments": edit_loan_payments,
    }
    _ic = {"Lending / borrowing": "🤝 ", "Income": "💰 ", "Expenses": "🧾 ", "Loans": "🏦 ", "Instalment / penalty payments": "📅 "}
    pick = st.radio(t("Record type"), list(sections), horizontal=True, key="edit_type",
                    format_func=lambda x: _ic.get(x, "") + t(x))
    sections[pick]()


# ---------------------------------------------------------------- main
def main():
    st.markdown(CSS, unsafe_allow_html=True)
    init_users_db()
    if not auth_gate():
        return
    auth = st.session_state["auth"]
    if auth["role"] == "admin" and not st.session_state.get("db_path"):
        admin_console()
        return
    init_db()
    load_language()
    if st.session_state.get("welcome"):
        st.toast("✅ " + st.session_state.pop("welcome"))
    if auth["role"] == "admin":
        c1, c2 = st.columns([4, 1])
        c1.warning("👁 " + tf("Viewing: {n}", n=st.session_state.get("viewing", "")))
        c2.button(t("Back to all users"), key="back_users", on_click=close_ledger, use_container_width=True)
    else:
        account_bar()
    if "page" not in st.session_state or st.session_state["page"] not in PAGES:
        st.session_state["page"] = P_DASH
    st.sidebar.markdown(f'<div class="brand">{t("Balance Sheet")}</div>', unsafe_allow_html=True)
    st.sidebar.caption(t("Personal ledger"))
    st.sidebar.radio(t("Menu"), PAGES, key="page", label_visibility="collapsed", format_func=t)

    top_nav()
    n_follow = len(followup_alerts()[0])
    if n_follow:
        st.sidebar.warning("⏰ " + tf("{n} follow-up(s) pending", n=n_follow))
        if st.session_state["page"] != P_DASH:
            st.warning("⏰ " + tf("{n} follow-up(s) pending", n=n_follow) + " — " + t("Open the Dashboard to see them."))
        if not st.session_state.get("alert_toast_done"):
            st.session_state["alert_toast_done"] = True
            st.toast("⏰ " + tf("{n} follow-up(s) pending", n=n_follow))

    s = summary_df()
    if not s.empty and s["entries"].sum() > 0:
        st.sidebar.divider()
        st.sidebar.metric(t("Net balance"), inr(s["balance"].sum()))
        st.sidebar.caption(tf("{p} parties, {n} entries", p=len(s), n=int(s['entries'].sum())))

    {
        P_DASH: page_dashboard,
        P_SAVE: page_savings,
        P_NEW: page_new_entry,
        P_EDIT: page_admin,
    }[st.session_state["page"]]()


main()
