"""Udhari Khata - personal ledger for lending, borrowing, income and loan instalments.

Three pages: Dashboard, New entry, Backup & restore.
"""

import calendar
import re
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
    "Salary", "Business", "Lottery", "Bonus", "Overtime", "Commission",
    "Rent", "Interest", "Gift", "Prize / Inaam", "Refund", "Other",
]

EXPENSE_CATS = [
    "Ghar / Ration", "Khana-Peena", "Petrol / Travel", "Bijli / Pani / Bill",
    "Dawai / Ilaaj", "Shopping", "Padhai / Fees", "Dukaan / Business",
    "Shaadi / Function", "Other",
]

GREEN = "#1e7a4f"
RED = "#b4372f"
BLUE = "#0f3d4c"

P_DASH = "Dashboard"
P_NEW = "New entry"
P_EDIT = "Admin panel"
P_BACKUP = "Backup & restore"
PAGES = [P_DASH, P_NEW, P_BACKUP, P_EDIT]  # Admin panel is always last

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
    "Udhari Khata": "उधारी खाता",
    "Personal ledger": "निजी लेन-देन खाता",
    "Dashboard": "डैशबोर्ड",
    "New entry": "नई एंट्री",
    "Admin panel": "एडमिन पैनल",
    "Backup & restore": "बैकअप और रिस्टोर",
    "Sign in to access your ledger.": "अपना खाता खोलने के लिए साइन इन करें।",
    "Password": "पासवर्ड",
    "Sign in": "साइन इन",
    "Incorrect password.": "गलत पासवर्ड।",
    "Language / भाषा": "Language / भाषा",
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
    "The file must contain at least one of these sheets: Udhari, Income, Loan, Kist_Penalty, Kharcha.":
        "फ़ाइल में इन शीट्स में से कम से कम एक होनी चाहिए: Udhari, Income, Loan, Kist_Penalty, Kharcha।",
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
}

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


def language_picker():
    """English / Hindi switch. The choice is saved, so it applies to the whole app."""
    codes = list(LANGS)
    cur = lang()
    pick = st.radio(
        "Language / भाषा", codes, index=codes.index(cur),
        format_func=LANGS.get, horizontal=True, key="lang_pick",
    )
    if pick != cur:
        st.session_state["lang"] = pick
        set_setting("lang", pick)
        st.rerun()


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


def expenses_df():
    df = query_df(
        "SELECT id, edate AS date, amount, place, category, note FROM expenses ORDER BY edate, id"
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
            entered = st.text_input(t("Password"), type="password")
            ok = st.form_submit_button(t("Sign in"), use_container_width=True, type="primary")
        if ok:
            if hmac.compare_digest(entered.encode(), str(pw).encode()):
                st.session_state["logged_in"] = True
                st.rerun()
            else:
                st.error(t("Incorrect password."))
    return False


# ---------------------------------------------------------------- navigation
def go(page, party=None):
    st.session_state["page"] = page
    if party is not None:
        st.session_state["prefill_party"] = party


# ---------------------------------------------------------------- pages
def party_card(r, key):
    cls, label = status_of(r["balance"])
    cls, label = cls, t(label)
    last = tf("last entry {d}", d=r["last"]) if r["last"] else t("no entries yet")
    meta = tf("{n} entries, {last}", n=r["entries"], last=last)
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
            v.sort_values(["date", "id"], ascending=False)[["date", "place", "category", "amount", "note"]]
            .rename(columns={"date": "Date", "place": "Place", "category": "Category",
                             "amount": "Amount", "note": "Note"}),
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
    for start in range(0, len(items), 3):
        cols = st.columns(3)
        for col, (l, i) in zip(cols, items[start:start + 3]):
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
                with st.expander(t("Instalment schedule")):
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

    s = summary_df()
    milna = s.loc[s["balance"] > 0, "balance"].sum()
    dena = -s.loc[s["balance"] < 0, "balance"].sum()
    n_mil = int((s["balance"] > 0).sum())
    n_den = int((s["balance"] < 0).sum())

    this_month = inc.loc[inc["month"] == date.today().strftime("%Y-%m"), "amount"].sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(kpi("Receivable", inr(milna), tf("from {n} parties", n=n_mil), "g"), unsafe_allow_html=True)
    c2.markdown(kpi("Payable", inr(dena), tf("to {n} parties", n=n_den), "r"), unsafe_allow_html=True)
    c3.markdown(
        kpi("Net balance", inr(milna - dena), "receivable − payable", "b"), unsafe_allow_html=True
    )
    c4.markdown(
        kpi("Income this month", inr(this_month), fdate(date.today(), "%B %Y"), "g"),
        unsafe_allow_html=True,
    )
    st.write("")

    cash_section()
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
                f'<div class="s">{escape(t(r["kind"]))}, {r["date"]}</div></div>'
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

    st.subheader(t("All parties"))
    f1, f2 = st.columns([2, 1])
    q = f1.text_input(t("Search by name"), placeholder=t("Search by name"), label_visibility="collapsed")
    flt = f2.selectbox(t("Filter"), ["All", "Receivable", "Payable", "Settled"],
                       format_func=t, label_visibility="collapsed")
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
        st.caption(t("No matching parties."))
    rows = list(v.iterrows())
    for i in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, (_, r) in zip(cols, rows[i:i + 3]):
            with col:
                party_card(r, key=f"open_{r['id']}")


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
                "INSERT INTO income(idate, amount, source, note) VALUES (?,?,?,?)",
                (idate.isoformat(), float(amount), final_source, note.strip()),
            )
            st.success(tf("Income of {a} saved.", a=inr(amount)))
            st.toast(t("Income saved"))
            show_cash_left()


def expense_form():
    # form ke bahar, taaki 'Other' chunte hi naam likhne ka box turant aa jaye
    cat = st.selectbox(t("Category"), EXPENSE_CATS, key="exp_cat", format_func=t)
    other = ""
    if cat == "Other":
        other = st.text_input(t("Specify category"), placeholder=t("e.g. Gift, Repair"), key="exp_other")
    known = expenses_df()["place"].str.strip()
    known = sorted({p for p in known if p}, key=str.lower)
    with st.form("expense_form", clear_on_submit=True):
        place = st.text_input(t("Where was it spent?"), placeholder=t("e.g. Big Bazaar, Petrol pump, Medical store"))
        a, b = st.columns(2)
        amount = a.number_input(t("Amount (₹)"), min_value=0.0, step=100.0, format="%.2f")
        edate = b.date_input(t("Date"), value=date.today())
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
                "INSERT INTO expenses(edate, amount, place, category, note) VALUES (?,?,?,?,?)",
                (edate.isoformat(), float(amount), place.strip(), final_cat, note.strip()),
            )
            st.success(tf("Expense of {a} at {p} saved.", a=inr(amount), p=place.strip()))
            st.toast(t("Expense saved"))
            show_cash_left()


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
        note = st.text_input(t("Note (optional)"), placeholder=t("e.g. online, cash"))
        ok = st.form_submit_button(t("Save payment"), type="primary", use_container_width=True)
    if ok:
        if amount <= 0:
            st.error(t("Amount must be greater than 0."))
        else:
            run(
                "INSERT INTO loan_payments(loan_id, pdate, kind, amount, note) VALUES (?,?,?,?,?)",
                (int(l["id"]), pdate.isoformat(), "kist" if kind == "Instalment" else "penalty", float(amount), note.strip()),
            )
            st.success(tf("{loan}: {kind} of {a} saved.", loan=pick, kind=t(kind).lower(), a=inr(amount)))
            st.toast(t("Payment saved"))
            show_cash_left()


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
        else:
            pid = get_or_create_party(name, phone)
            run(
                "INSERT INTO txns(party_id, tdate, kind, amount, note) VALUES (?,?,?,?,?)",
                (pid, tdate.isoformat(), kind, float(amount), note.strip()),
            )
            st.session_state["entry_flash"] = tf("Entry saved: {a} with {n}.", a=inr(amount), n=name)
            st.session_state["entry_n"] = n + 1  # party/phone fields reset
            st.rerun()


SHEETS = ["Udhari", "Income", "Loan", "Kist_Penalty", "Kharcha"]
EXP_COLS = ["date", "amount", "place", "category", "note"]
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

    ws6 = wb.create_sheet("Kharcha")
    make(ws6, EXP_COLS, [14, 14, 28, 22, 36])
    dropdown(ws6, EXPENSE_CATS[:-1], "D2:D1000", strict=False)

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
        ("Kharcha sheet (expenses)", True),
        ("date, amount, note -> as above", False),
        ("place    -> where the money was spent (required)", False),
        ("category -> for example Ghar / Ration, Petrol / Travel, or your own label", False),
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
        for tbl in ("loan_payments", "loans", "txns", "parties", "income", "expenses"):
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


def page_backup():
    hero("Backup & restore", "Keep a safe copy of your records")
    if st.session_state.pop("wiped", False):
        st.success(t("All data has been deleted."))
    st.warning(
        t("On Streamlit Cloud the database file can be lost when the app restarts. Download an Excel backup regularly.")
    )
    df = txns_df()
    export = df[["party", "date", "kind", "amount", "note"]]
    inc = income_df()
    inc_export = inc[["date", "amount", "source", "note"]]
    loans = loans_df()
    loan_export = loans[LOAN_COLS]
    pays = loan_pay_df()
    pay_export = pays[PAY_COLS[:1] + PAY_COLS[1:]]
    exp_export = expenses_df()[EXP_COLS]
    phones = parties_df()
    empty = export.empty and inc_export.empty and loan_export.empty and exp_export.empty

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
            to_xlsx_multi({
                "Udhari": export, "Income": inc_export,
                "Loan": loan_export, "Kist_Penalty": pay_export,
                "Kharcha": exp_export,
            }),
            file_name=f"udhari_backup_{date.today().isoformat()}.xlsx",
            mime=XLSX_MIME, disabled=empty, type="primary",
        )
    with c2:
        st.markdown(t("#### Restore"))
        st.download_button(
            t("Download blank restore template"),
            template_xlsx(),
            file_name="udhari_restore_format.xlsx",
            mime=XLSX_MIME,
            help=t("Fill in this template and upload it below. The Instructions sheet explains each column."),
        )
        up = st.file_uploader(t("Select a backup file"), type=["xlsx", "csv"], label_visibility="collapsed")
        if up is not None and st.button(t("Restore")):
            sheets = read_backup_all(up)
            ud, ic, lo, kp, ke = (sheets[k] for k in SHEETS)
            if all(x is None for x in (ud, ic, lo, kp, ke)):
                st.error(t("The file must contain at least one of these sheets: Udhari, Income, Loan, Kist_Penalty, Kharcha."))
                return

            msgs = []
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
                    run(
                        "INSERT INTO txns(party_id, tdate, kind, amount, note) VALUES (?,?,?,?,?)",
                        (pid, str(r["date"]), r["kind"], float(r["amount"]), str(r["note"])),
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
                    run("INSERT INTO income(idate, amount, source, note) VALUES (?,?,?,?)",
                        (key[0], float(r["amount"]), key[2], key[3]))
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
                        "INSERT INTO expenses(edate, amount, place, category, note) VALUES (?,?,?,?,?)",
                        (key[0], amt, pl, str(r["category"]).strip() or "Other", key[3]),
                    )
                    have.add(key)
                    added += 1
                msgs.append(tf("Expenses: {a} added, {s} already present, {b} invalid rows skipped.", a=added, s=skipped, b=bad))

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
                        "INSERT INTO loan_payments(loan_id, pdate, kind, amount, note) VALUES (?,?,?,?,?)",
                        (ids[nm], key[1], kind, amt, key[4]),
                    )
                    have.add(key)
                    added += 1
                msgs.append(
                    tf("Instalments/penalties: {a} added, {s} already present, {b} invalid rows skipped.", a=added, s=skipped, b=bad)
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
        st.info(t("Editing old records is protected. Enter the edit password to continue."))
        with st.form("edit_login"):
            entered = st.text_input(t("Edit password"), type="password")
            ok = st.form_submit_button(t("Unlock editing"), use_container_width=True, type="primary")
        if ok:
            if hmac.compare_digest(entered.encode(), edit_password().encode()):
                st.session_state["edit_ok"] = True
                st.rerun()
            else:
                st.error(t("Incorrect password."))
    return False


def lock_edit():
    """Lock the admin panel and go back to the dashboard."""
    st.session_state["edit_ok"] = False
    st.session_state["page"] = P_DASH


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
        else:
            pid = get_or_create_party(name, phone.strip())
            if not moving_to_saved:
                run("UPDATE parties SET phone = ? WHERE id = ?", (phone.strip(), pid))
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
                "UPDATE income SET idate=?, amount=?, source=?, note=? WHERE id=?",
                (idate.isoformat(), float(amount), source, note.strip(), int(rid)),
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
        note = st.text_input(t("Note (optional)"), value=r["note"] or "")
        ok = st.form_submit_button(t("Save changes"), type="primary", use_container_width=True)
    if ok:
        if not place.strip():
            st.error(t("Place cannot be empty."))
        elif amount <= 0:
            st.error(t("Amount must be greater than 0."))
        else:
            run(
                "UPDATE expenses SET edate=?, amount=?, place=?, category=?, note=? WHERE id=?",
                (edate.isoformat(), float(amount), place.strip(), cat, note.strip(), int(rid)),
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
        note = st.text_input(t("Note (optional)"), value=r["note"] or "")
        ok = st.form_submit_button(t("Save changes"), type="primary", use_container_width=True)
    if ok:
        if amount <= 0:
            st.error(t("Amount must be greater than 0."))
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
    for r in expenses_df().itertuples():
        rows.append({
            "Date": r.date, "Group": "Expenses", "Type": r.category, "Party / loan": r.place,
            "Direction": "Out", "Amount": float(r.amount), "Note": r.note or "",
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
        st.info(t("No transactions yet."))
        return
    f1, f2 = st.columns([1, 2])
    group = f1.selectbox(t("Show"), ["All", "Lending / borrowing", "Income", "Expenses", "Loan payments"],
                         key="adm_group", format_func=t)
    q = f2.text_input(t("Search party, loan or note"), key="adm_q")
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
    k1.markdown(kpi("Money in", inr(money_in), tf("{n} entries", n=int((df['Direction'] == 'In').sum())), "g"), unsafe_allow_html=True)
    k2.markdown(kpi("Money out", inr(money_out), tf("{n} entries", n=int((df['Direction'] == 'Out').sum())), "r"), unsafe_allow_html=True)
    k3.markdown(kpi("Net", inr(money_in - money_out), "in − out", "g" if money_in >= money_out else "r"), unsafe_allow_html=True)
    st.write("")
    show_df(
        df.drop(columns=["Group"]), hide_index=True, use_container_width=True,
        column_config={"Amount": st.column_config.NumberColumn(format="₹%.2f")},
    )
    st.caption(t("To correct or delete an entry, open 'Edit records' above."))


def page_admin():
    hero("Admin panel", "All transactions and editing of older records")
    language_picker()
    if not edit_gate():
        return
    c1, c2 = st.columns([5, 1])
    c1.caption(t("Admin panel is unlocked for this session."))
    c2.button(t("Lock"), on_click=lock_edit, use_container_width=True)
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(t(flash))
    section = st.radio(
        t("Section"), ["Transactions", "Edit records"], horizontal=True,
        key="admin_section", label_visibility="collapsed", format_func=t,
    )
    if section == "Transactions":
        admin_transactions()
        return
    sections = {
        "Lending / borrowing": edit_txns,
        "Income": edit_income,
        "Expenses": edit_expenses,
        "Loans": edit_loans,
        "Instalment / penalty payments": edit_loan_payments,
    }
    pick = st.radio(t("Record type"), list(sections), horizontal=True, key="edit_type", format_func=t)
    sections[pick]()


# ---------------------------------------------------------------- main
def main():
    init_db()
    load_language()
    st.markdown(CSS, unsafe_allow_html=True)
    if not check_password():
        return
    if "page" not in st.session_state or st.session_state["page"] not in PAGES:
        st.session_state["page"] = P_DASH
    st.sidebar.markdown(f'<div class="brand">{t("Udhari Khata")}</div>', unsafe_allow_html=True)
    st.sidebar.caption(t("Personal ledger"))
    st.sidebar.radio(t("Menu"), PAGES, key="page", label_visibility="collapsed", format_func=t)

    s = summary_df()
    if not s.empty and s["entries"].sum() > 0:
        st.sidebar.divider()
        st.sidebar.metric(t("Net balance"), inr(s["balance"].sum()))
        st.sidebar.caption(tf("{p} parties, {n} entries", p=len(s), n=int(s['entries'].sum())))

    {
        P_DASH: page_dashboard,
        P_NEW: page_new_entry,
        P_EDIT: page_admin,
        P_BACKUP: page_backup,
    }[st.session_state["page"]]()


main()
