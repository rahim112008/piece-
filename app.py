#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║        AUTO PIÈCES RAHIM   — Application Streamlit Complète          ║
║        Gestion de magasin de pièces détachées automobiles            ║
╠══════════════════════════════════════════════════════════════════════╣
║  INSTALLATION :                                                      ║
║    pip install streamlit pandas Pillow requests openpyxl reportlab   ║
║                                                                      ║
║  LANCEMENT :                                                         ║
║    streamlit run app_complet.py                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  DOSSIERS À CRÉER :                                                  ║
║    data/images/   (images des pièces)                                ║
║    data/invoices/ (factures PDF)                                     ║
║  FICHIERS CSV à placer dans data/ :                                  ║
║    initial_parts.csv   (pièces initiales)                            ║
║    vin_mapping.csv     (préfixes VIN)                                ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ══════════════════════════════════════════════════════════════════════
# IMPORTS GLOBAUX
# ══════════════════════════════════════════════════════════════════════
import os
import sys
import sqlite3
import base64
import io
from datetime import datetime, date
from PIL import Image
import pandas as pd
import requests
import streamlit as st

# PDF : ReportLab recommandé, fpdf2 en fallback
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer, HRFlowable)
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    PDF_ENGINE = "reportlab"
except ImportError:
    PDF_ENGINE = "none"

try:
    from fpdf import FPDF
    if PDF_ENGINE == "none":
        PDF_ENGINE = "fpdf2"
except ImportError:
    pass


# ══════════════════════════════════════════════════════════════════════
# ██████  CONFIG
# ══════════════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(BASE_DIR, "database.db")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
INVOICES_DIR = os.path.join(DATA_DIR, "invoices")
INITIAL_PARTS_CSV = os.path.join(DATA_DIR, "initial_parts.csv")
VIN_MAPPING_CSV = os.path.join(DATA_DIR, "vin_mapping.csv")
LOGO_PATH = os.path.join(DATA_DIR, "logo.png")

STOCK_THRESHOLD = 5
VIN_MODE = "both"
NHTSA_API_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{vin}?format=json"

SHOP_NAME    = "Auto Pièces Maghreb"
SHOP_ADDRESS = "Rue des Zianides, Tlemcen 13000, Algérie"
SHOP_PHONE   = "+213 43 00 00 00"
SHOP_EMAIL   = "contact@autopiecesmaghreb.dz"

TVA_RATE     = 0.19
APPLY_TVA    = False
CURRENCY     = "DA"
INVOICE_PREFIX = "FAC"

os.makedirs(IMAGES_DIR,  exist_ok=True)
os.makedirs(INVOICES_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════
# ██████  DATABASE
# ══════════════════════════════════════════════════════════════════════

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        make TEXT, model TEXT, year_start INTEGER, year_end INTEGER,
        part_name TEXT NOT NULL, part_number TEXT UNIQUE,
        price REAL NOT NULL, stock INTEGER NOT NULL DEFAULT 0,
        image_path TEXT, category TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, phone TEXT, email TEXT, address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

    c.execute("""CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER, sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        total_amount REAL NOT NULL, payment_method TEXT DEFAULT 'cash',
        status TEXT DEFAULT 'paid', invoice_number TEXT,
        FOREIGN KEY (client_id) REFERENCES clients(id))""")

    c.execute("""CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL, part_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL, unit_price REAL NOT NULL, total REAL NOT NULL,
        FOREIGN KEY (sale_id) REFERENCES sales(id),
        FOREIGN KEY (part_id) REFERENCES parts(id))""")

    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        type TEXT CHECK(type IN ('income','expense')),
        category TEXT, amount REAL NOT NULL,
        description TEXT, reference TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS purchase_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_name TEXT NOT NULL,
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        delivery_date DATE, total_amount REAL NOT NULL DEFAULT 0,
        status TEXT DEFAULT 'pending')""")

    c.execute("""CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL, part_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL, unit_price REAL NOT NULL, total REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES purchase_orders(id),
        FOREIGN KEY (part_id) REFERENCES parts(id))""")

    c.execute("""CREATE TABLE IF NOT EXISTS invoice_counter (
        id INTEGER PRIMARY KEY, last_number INTEGER DEFAULT 0)""")
    c.execute("INSERT OR IGNORE INTO invoice_counter (id, last_number) VALUES (1, 0)")

    c.execute("""CREATE TABLE IF NOT EXISTS stock_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        part_id INTEGER NOT NULL,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        movement_type TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        reason TEXT, reference TEXT,
        FOREIGN KEY (part_id) REFERENCES parts(id))""")

    conn.commit()
    _load_initial_data(conn)
    conn.close()


def _load_initial_data(conn):
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM parts")
    if c.fetchone()[0] == 0 and os.path.exists(INITIAL_PARTS_CSV):
        df = pd.read_csv(INITIAL_PARTS_CSV)
        df.to_sql("parts", conn, if_exists="append", index=False)

    c.execute("SELECT COUNT(*) FROM clients")
    if c.fetchone()[0] == 0:
        clients = [
            ("Ahmed Benali",     "0555 12 34 56", "ahmed.benali@gmail.com",  "Rue Larbi Ben M'hidi, Tlemcen"),
            ("Fatima Bouderbala","0661 98 76 54", "fatima.b@outlook.com",    "Cité Kawkab, Oran"),
            ("Karim Mansouri",   "0770 45 67 89", "",                        "Boulevard Zighout Youcef, Alger"),
        ]
        c.executemany("INSERT INTO clients (name,phone,email,address) VALUES (?,?,?,?)", clients)
        conn.commit()


def get_next_invoice_number(conn):
    c = conn.cursor()
    c.execute("UPDATE invoice_counter SET last_number = last_number + 1 WHERE id = 1")
    conn.commit()
    c.execute("SELECT last_number FROM invoice_counter WHERE id = 1")
    return c.fetchone()[0]


# ══════════════════════════════════════════════════════════════════════
# ██████  UTILS
# ══════════════════════════════════════════════════════════════════════

def format_price(amount):
    return f"{amount:,.2f} {CURRENCY}"

def save_uploaded_image(uploaded_file, part_number):
    ext = uploaded_file.name.split(".")[-1].lower()
    filename = f"{part_number.replace('/', '_')}.{ext}"
    path = os.path.join(IMAGES_DIR, filename)
    img = Image.open(uploaded_file)
    img.thumbnail((400, 400))
    img.save(path)
    return path

def get_image_base64(image_path):
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        ext = image_path.split(".")[-1].lower()
        mime = {"jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png",
                "gif":"image/gif","webp":"image/webp"}.get(ext,"image/png")
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
    except Exception:
        return None

def placeholder_image_html(size=120):
    return f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" fill="#e0e0e0" rx="8"/><text x="50%" y="50%" font-size="12" fill="#888" text-anchor="middle" dominant-baseline="middle">📷</text></svg>'

def get_part_image_html(image_path, size=120):
    b64 = get_image_base64(image_path)
    if b64:
        return f'<img src="{b64}" width="{size}" height="{size}" style="object-fit:cover;border-radius:8px;">'
    return placeholder_image_html(size)

def validate_vin(vin):
    vin = vin.strip().upper()
    if len(vin) != 17:
        return False
    return all(c.isalnum() and c not in "IOQ" for c in vin)

def get_categories():
    return ["Moteur","Freinage","Suspension","Transmission","Électricité",
            "Carrosserie","Refroidissement","Échappement","Climatisation",
            "Filtration","Éclairage","Accessoires","Autre"]

def get_makes():
    return ["Renault","Peugeot","Citroën","Hyundai","Kia","Toyota",
            "Chevrolet","Volkswagen","Ford","Nissan","Dacia","Fiat",
            "Mercedes","BMW","Suzuki","Autre"]

def get_payment_methods():
    return ["Espèces","Carte bancaire","Virement","Chèque"]

def get_expense_categories():
    return ["Achat fournisseur","Loyer","Électricité","Eau","Transport",
            "Salaires","Publicité","Maintenance","Taxes et impôts","Autre"]


# ══════════════════════════════════════════════════════════════════════
# ██████  VIN DECODER
# ══════════════════════════════════════════════════════════════════════

_YEAR_CHAR_MAP = {
    'A':2010,'B':2011,'C':2012,'D':2013,'E':2014,'F':2015,'G':2016,
    'H':2017,'J':2018,'K':2019,'L':2020,'M':2021,'N':2022,'P':2023,'R':2024,
    'S':1995,'T':1996,'V':1997,'W':1998,'X':1999,'Y':2000,
    '1':2001,'2':2002,'3':2003,'4':2004,'5':2005,'6':2006,
    '7':2007,'8':2008,'9':2009,
}

def decode_vin(vin):
    vin = vin.strip().upper()
    if len(vin) != 17:
        return None
    if VIN_MODE == "local":
        return _decode_local(vin)
    elif VIN_MODE == "api":
        return _decode_api(vin)
    else:
        return _decode_local(vin) or _decode_api(vin)

def _decode_local(vin):
    if not os.path.exists(VIN_MAPPING_CSV):
        return None
    try:
        df = pd.read_csv(VIN_MAPPING_CSV)
        for length in [3, 2]:
            wmi = vin[:length]
            row = df[df["wmi"].str.upper() == wmi]
            if not row.empty:
                r = row.iloc[0]
                year = _YEAR_CHAR_MAP.get(vin[9].upper())
                return {"make": r.get("make","Inconnu"), "model": r.get("model","Inconnu"),
                        "year": year or int(r.get("year_default", 2010)), "source": "local"}
    except Exception:
        pass
    return None

def _decode_api(vin):
    try:
        url = NHTSA_API_URL.format(vin=vin)
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        results = resp.json().get("Results", [])
        info = {r["Variable"]: r["Value"] for r in results
                if r["Value"] not in (None, "", "0", "Not Applicable")}
        make  = info.get("Make", "")
        model = info.get("Model", "")
        year  = info.get("Model Year", "")
        if make and model:
            return {"make": make.title(), "model": model.title(),
                    "year": int(year) if str(year).isdigit() else None,
                    "source": "NHTSA API"}
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════
# ██████  PDF GENERATOR
# ══════════════════════════════════════════════════════════════════════

def _ps(name, size=10, color="#1e1e1e", align="LEFT", leading=None):
    al = {"LEFT":TA_LEFT,"CENTER":TA_CENTER,"RIGHT":TA_RIGHT}.get(align, TA_LEFT)
    c = colors.HexColor(color) if color.startswith("#") else colors.white
    return ParagraphStyle(name, fontSize=size, textColor=c,
                          alignment=al, leading=leading or size*1.5)

def _rl_invoice(sale, items, client):
    inv = sale.get("invoice_number","0000")
    date_str = str(sale.get("sale_date",""))[:10]
    filepath = os.path.join(INVOICES_DIR, f"facture_{inv}.pdf")
    os.makedirs(INVOICES_DIR, exist_ok=True)
    doc = SimpleDocTemplate(filepath, pagesize=A4,
                             rightMargin=1.5*cm, leftMargin=1.5*cm,
                             topMargin=1.5*cm, bottomMargin=1.5*cm)
    BLUE = colors.HexColor("#1a73e8")
    LBLUE = colors.HexColor("#e8f0fe")
    GRAY  = colors.HexColor("#666666")
    ALT   = colors.HexColor("#f8f9fc")
    story = []

    hdr = Table([[
        Paragraph(f'<font color="#1a73e8" size="17"><b>{SHOP_NAME}</b></font><br/>'
                  f'<font color="#666" size="8">{SHOP_ADDRESS}</font><br/>'
                  f'<font color="#666" size="8">Tél : {SHOP_PHONE} | {SHOP_EMAIL}</font>',
                  _ps("h_l", 9, leading=14)),
        Paragraph(f'<font color="#1a73e8" size="20"><b>FACTURE</b></font><br/>'
                  f'<font color="#1e1e1e" size="14"><b>#{inv}</b></font><br/>'
                  f'<font color="#666" size="9">Date : {date_str}</font>',
                  _ps("h_r", 9, align="RIGHT", leading=18))
    ]], colWidths=[10*cm, 8*cm])
    hdr.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.append(hdr)
    story.append(HRFlowable(width="100%", thickness=2, color=BLUE, spaceAfter=8))

    cn = client.get("name","Client divers")
    lines = f"<b>FACTURÉ À :</b><br/><b>{cn}</b>"
    if client.get("phone"): lines += f"<br/>Tél : {client['phone']}"
    if client.get("address"): lines += f"<br/>{client['address']}"
    ct = Table([[Paragraph(lines, _ps("cl", 10, leading=16))]], colWidths=[18*cm])
    ct.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LBLUE),
                             ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
                             ("LEFTPADDING",(0,0),(-1,-1),12)]))
    story.append(ct)
    story.append(Spacer(1, 10))

    W = [8.5*cm, 2*cm, 3.5*cm, 4*cm]
    heads = [("Désignation","LEFT"),("Qté","CENTER"),(f"P.U.({CURRENCY})","RIGHT"),(f"Total({CURRENCY})","RIGHT")]
    thead = [Paragraph(f"<b>{t}</b>", _ps(f"th{i}", 10, color="white", align=a)) for i,(t,a) in enumerate(heads)]
    rows = [thead]
    for i, item in enumerate(items):
        rows.append([
            Paragraph(str(item.get("part_name","")), _ps(f"td0{i}",9)),
            Paragraph(str(item.get("quantity","")), _ps(f"td1{i}",9,align="CENTER")),
            Paragraph(f"{item.get('unit_price',0):,.2f}", _ps(f"td2{i}",9,align="RIGHT")),
            Paragraph(f"{item.get('total',0):,.2f}", _ps(f"td3{i}",9,align="RIGHT")),
        ])
    ts = [("BACKGROUND",(0,0),(-1,0),BLUE),("TEXTCOLOR",(0,0),(-1,0),colors.white),
          ("LINEBELOW",(0,1),(-1,-1),0.3,colors.HexColor("#dddddd")),
          ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
          ("LEFTPADDING",(0,0),(0,-1),8),("RIGHTPADDING",(-1,0),(-1,-1),8)]
    for i in range(1, len(rows)):
        if i % 2 == 0: ts.append(("BACKGROUND",(0,i),(-1,i),ALT))
    at = Table(rows, colWidths=W, repeatRows=1)
    at.setStyle(TableStyle(ts))
    story.append(at)
    story.append(Spacer(1, 8))

    pay = sale.get("payment_method","Espèces")
    tot = sale.get("total_amount", 0)
    tt = Table([[
        Paragraph(f"Mode de paiement : <b>{pay}</b>", _ps("pm",10,color="white",leading=14)),
        Paragraph(f"<b>TOTAL : {tot:,.2f} {CURRENCY}</b>", _ps("tot",12,color="white",align="RIGHT",leading=14))
    ]], colWidths=[10*cm, 8*cm])
    tt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),BLUE),
                             ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
                             ("LEFTPADDING",(0,0),(0,-1),12),("RIGHTPADDING",(-1,0),(-1,-1),12)]))
    story.append(tt)
    story.append(Spacer(1,20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY))
    story.append(Paragraph(f"Merci pour votre confiance — {SHOP_NAME} | {SHOP_PHONE} | {SHOP_EMAIL}",
                            _ps("ft",8,color="#888888",align="CENTER")))
    doc.build(story)
    return filepath

def _rl_purchase_order(order, items):
    oid = order.get("id", 0)
    filepath = os.path.join(INVOICES_DIR, f"bc_{oid:04d}.pdf")
    os.makedirs(INVOICES_DIR, exist_ok=True)
    doc = SimpleDocTemplate(filepath, pagesize=A4,
                             rightMargin=1.5*cm, leftMargin=1.5*cm,
                             topMargin=1.5*cm, bottomMargin=1.5*cm)
    BLUE = colors.HexColor("#1a73e8")
    LBLUE = colors.HexColor("#e8f0fe")
    GRAY  = colors.HexColor("#666666")
    ALT   = colors.HexColor("#f8f9fc")
    story = []

    hdr = Table([[
        Paragraph(f'<font color="#1a73e8" size="17"><b>{SHOP_NAME}</b></font><br/>'
                  f'<font color="#666" size="8">{SHOP_ADDRESS} | {SHOP_PHONE}</font>',
                  _ps("bh",9,leading=14)),
        Paragraph(f'<font color="#1a73e8" size="20"><b>BON DE COMMANDE</b></font><br/>'
                  f'<font color="#1e1e1e" size="14"><b>#BC{oid:04d}</b></font><br/>'
                  f'<font color="#666" size="9">Date : {str(order.get("order_date",""))[:10]}</font>',
                  _ps("bhr",9,align="RIGHT",leading=18))
    ]], colWidths=[10*cm,8*cm])
    hdr.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.append(hdr)
    story.append(HRFlowable(width="100%",thickness=2,color=BLUE,spaceAfter=8))

    sup = Table([[Paragraph(f"<b>FOURNISSEUR :</b><br/><b>{order.get('supplier_name','')}</b>",
                            _ps("sup",11,leading=18))]], colWidths=[18*cm])
    sup.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LBLUE),
                              ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
                              ("LEFTPADDING",(0,0),(-1,-1),12)]))
    story.append(sup)
    story.append(Spacer(1,10))

    W = [8.5*cm,2*cm,3.5*cm,4*cm]
    heads = [("Désignation","LEFT"),("Qté","CENTER"),(f"P.U.({CURRENCY})","RIGHT"),(f"Total({CURRENCY})","RIGHT")]
    thead = [Paragraph(f"<b>{t}</b>",_ps(f"bth{i}",10,color="white",align=a)) for i,(t,a) in enumerate(heads)]
    rows = [thead]
    for i, item in enumerate(items):
        rows.append([
            Paragraph(str(item.get("part_name","")),_ps(f"btd0{i}",9)),
            Paragraph(str(item.get("quantity","")),_ps(f"btd1{i}",9,align="CENTER")),
            Paragraph(f"{item.get('unit_price',0):,.2f}",_ps(f"btd2{i}",9,align="RIGHT")),
            Paragraph(f"{item.get('total',0):,.2f}",_ps(f"btd3{i}",9,align="RIGHT")),
        ])
    ts = [("BACKGROUND",(0,0),(-1,0),BLUE),("TEXTCOLOR",(0,0),(-1,0),colors.white),
          ("LINEBELOW",(0,1),(-1,-1),0.3,colors.HexColor("#dddddd")),
          ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
          ("LEFTPADDING",(0,0),(0,-1),8),("RIGHTPADDING",(-1,0),(-1,-1),8)]
    for i in range(1, len(rows)):
        if i % 2 == 0: ts.append(("BACKGROUND",(0,i),(-1,i),ALT))
    at = Table(rows,colWidths=W,repeatRows=1)
    at.setStyle(TableStyle(ts))
    story.append(at)
    story.append(Spacer(1,8))

    tot = order.get("total_amount",0)
    tt = Table([[Paragraph("",_ps("e",9)),
                 Paragraph(f"<b>TOTAL : {tot:,.2f} {CURRENCY}</b>",
                            _ps("bct",13,color="white",align="RIGHT",leading=16))]],
               colWidths=[10*cm,8*cm])
    tt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),BLUE),
                             ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
                             ("RIGHTPADDING",(-1,0),(-1,-1),12)]))
    story.append(tt)
    story.append(Spacer(1,20))
    story.append(HRFlowable(width="100%",thickness=0.5,color=GRAY))
    story.append(Paragraph(f"{SHOP_NAME} — {SHOP_ADDRESS}",
                            _ps("bft",8,color="#888888",align="CENTER")))
    doc.build(story)
    return filepath

def generate_invoice_pdf(sale, items, client):
    os.makedirs(INVOICES_DIR, exist_ok=True)
    if PDF_ENGINE == "reportlab":
        return _rl_invoice(sale, items, client)
    raise RuntimeError("Installez reportlab : pip install reportlab")

def generate_purchase_order_pdf(order, items):
    os.makedirs(INVOICES_DIR, exist_ok=True)
    if PDF_ENGINE == "reportlab":
        return _rl_purchase_order(order, items)
    raise RuntimeError("Installez reportlab : pip install reportlab")


# ══════════════════════════════════════════════════════════════════════
# ██████  STOCK MOVEMENTS
# ══════════════════════════════════════════════════════════════════════

def record_movement(part_id, qty, movement_type, reason="", reference="", conn=None):
    close = conn is None
    if close:
        conn = get_connection()
    conn.execute("""INSERT INTO stock_movements
        (part_id, date, movement_type, quantity, reason, reference)
        VALUES (?,?,?,?,?,?)""",
        (part_id, datetime.now().isoformat(), movement_type, qty, reason, reference))
    if close:
        conn.commit()
        conn.close()

def update_stock(part_id, delta, conn=None):
    close = conn is None
    if close:
        conn = get_connection()
    conn.execute("UPDATE parts SET stock = stock + ? WHERE id = ?", (delta, part_id))
    if close:
        conn.commit()
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ██████  CATALOGUE
# ══════════════════════════════════════════════════════════════════════

def get_all_parts(filters=None):
    conn = get_connection()
    query = "SELECT * FROM parts WHERE 1=1"
    params = []
    if filters:
        if filters.get("make"):
            query += " AND make = ?"; params.append(filters["make"])
        if filters.get("model"):
            query += " AND model LIKE ?"; params.append(f"%{filters['model']}%")
        if filters.get("category"):
            query += " AND category = ?"; params.append(filters["category"])
        if filters.get("search"):
            query += " AND (part_name LIKE ? OR part_number LIKE ?)"
            params.extend([f"%{filters['search']}%", f"%{filters['search']}%"])
        if filters.get("min_price") is not None:
            query += " AND price >= ?"; params.append(filters["min_price"])
        if filters.get("max_price") is not None:
            query += " AND price <= ?"; params.append(filters["max_price"])
        if filters.get("low_stock"):
            query += f" AND stock <= {STOCK_THRESHOLD}"
        if filters.get("vin_make"):
            query += " AND make = ?"; params.append(filters["vin_make"])
        if filters.get("vin_year"):
            query += " AND (year_start <= ? AND year_end >= ?)"
            params.extend([filters["vin_year"], filters["vin_year"]])
    query += " ORDER BY make, model, part_name"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def get_part_by_id(part_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM parts WHERE id = ?", (part_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def add_part(data):
    try:
        conn = get_connection()
        conn.execute("""INSERT INTO parts (make,model,year_start,year_end,part_name,
            part_number,price,stock,image_path,category)
            VALUES (:make,:model,:year_start,:year_end,:part_name,
            :part_number,:price,:stock,:image_path,:category)""", data)
        conn.commit(); conn.close(); return True
    except Exception as e:
        st.error(f"Erreur ajout pièce : {e}"); return False

def update_part(part_id, data):
    try:
        conn = get_connection()
        conn.execute("""UPDATE parts SET make=:make,model=:model,year_start=:year_start,
            year_end=:year_end,part_name=:part_name,part_number=:part_number,
            price=:price,stock=:stock,image_path=:image_path,category=:category
            WHERE id=:id""", {**data, "id": part_id})
        conn.commit(); conn.close(); return True
    except Exception as e:
        st.error(f"Erreur modification : {e}"); return False

def delete_part(part_id):
    try:
        conn = get_connection()
        conn.execute("DELETE FROM parts WHERE id = ?", (part_id,))
        conn.commit(); conn.close(); return True
    except Exception as e:
        st.error(f"Erreur suppression : {e}"); return False

def _add_to_cart(part):
    cart = st.session_state.setdefault("cart", [])
    for item in cart:
        if item["part_id"] == part["id"]:
            item["quantity"] += 1
            item["total"] = item["quantity"] * item["unit_price"]
            st.toast(f"✅ {part['part_name']} (+1)"); return
    cart.append({"part_id":part["id"],"part_name":part["part_name"],
                 "part_number":part.get("part_number",""),"unit_price":part["price"],
                 "quantity":1,"total":part["price"],"stock":part["stock"]})
    st.toast(f"✅ {part['part_name']} ajouté au panier")

def show_catalogue():
    st.header("📦 Catalogue des pièces")
    with st.sidebar:
        st.markdown("### 🔍 Filtres")
        sel_make = st.selectbox("Marque", [""]+get_makes(), key="cat_make")
        sel_model = st.text_input("Modèle", key="cat_model")
        sel_cat = st.selectbox("Catégorie", [""]+get_categories(), key="cat_cat")
        sel_search = st.text_input("Recherche", key="cat_search")
        c1, c2 = st.columns(2)
        min_p = c1.number_input("Prix min", min_value=0.0, value=0.0, key="cat_pmin")
        max_p = c2.number_input("Prix max", min_value=0.0, value=0.0, key="cat_pmax")
        low_stock = st.checkbox("Stock bas", key="cat_lowstock")

    filters = {"make":sel_make or None,"model":sel_model or None,"category":sel_cat or None,
               "search":sel_search or None,"min_price":min_p if min_p > 0 else None,
               "max_price":max_p if max_p > 0 else None,"low_stock":low_stock}
    if st.session_state.get("vin_filter"):
        filters.update(st.session_state["vin_filter"])

    tab1, tab2 = st.tabs(["🗂️ Catalogue", "➕ Ajouter une pièce"])
    with tab1:
        df = get_all_parts(filters)
        if df.empty:
            st.info("Aucune pièce trouvée."); return
        st.caption(f"{len(df)} pièce(s)")
        for i in range(0, len(df), 3):
            cols = st.columns(3)
            for col, (_, part) in zip(cols, df.iloc[i:i+3].iterrows()):
                with col:
                    stk = "🔴" if part["stock"] <= STOCK_THRESHOLD else "🟢"
                    st.markdown(f"""
                    <div style="border:1px solid #ddd;border-radius:10px;padding:10px;
                                margin-bottom:8px;background:#fff;text-align:center;
                                box-shadow:0 1px 4px rgba(0,0,0,.08)">
                        {get_part_image_html(part.get("image_path"), 110)}
                        <div style="font-weight:600;font-size:.9em;margin-top:6px">{part['part_name']}</div>
                        <div style="color:#666;font-size:.78em">{part.get('make','')} {part.get('model','')}</div>
                        <div style="color:#555;font-size:.78em">Réf: {part.get('part_number','—')}</div>
                        <div style="color:#1a73e8;font-weight:700;margin:4px 0">{format_price(part['price'])}</div>
                        <div style="font-size:.78em">{stk} Stock: {part['stock']}</div>
                    </div>""", unsafe_allow_html=True)
                    ca, cb, cc = st.columns(3)
                    if ca.button("🛒", key=f"cart_{part['id']}", help="Panier"):
                        _add_to_cart(part)
                    if cb.button("✏️", key=f"edit_{part['id']}", help="Modifier"):
                        st.session_state[f"edit_part_{part['id']}"] = True
                    if cc.button("🗑️", key=f"del_{part['id']}", help="Supprimer"):
                        if delete_part(part["id"]):
                            st.success("Supprimé."); st.rerun()
                    if st.session_state.get(f"edit_part_{part['id']}"):
                        _form_edit_part(part)

    with tab2:
        st.subheader("Ajouter une pièce")
        with st.form("form_add_part"):
            c1, c2 = st.columns(2)
            part_name   = c1.text_input("Nom *")
            part_number = c2.text_input("Référence *")
            make  = c1.selectbox("Marque", get_makes())
            model = c2.text_input("Modèle")
            y1, y2 = st.columns(2)
            year_start = y1.number_input("Année début", min_value=1970, max_value=2030, value=2000)
            year_end   = y2.number_input("Année fin",   min_value=1970, max_value=2030, value=2024)
            p1, p2 = st.columns(2)
            price = p1.number_input("Prix (DA) *", min_value=0.0, value=0.0)
            stock = p2.number_input("Stock",       min_value=0,   value=0)
            category   = st.selectbox("Catégorie", get_categories())
            image_file = st.file_uploader("Image", type=["jpg","jpeg","png","webp"])
            if st.form_submit_button("✅ Ajouter"):
                if not part_name or not part_number or price <= 0:
                    st.error("Nom, référence et prix sont obligatoires.")
                else:
                    img_path = save_uploaded_image(image_file, part_number) if image_file else None
                    if add_part({"make":make,"model":model,"year_start":year_start,
                                 "year_end":year_end,"part_name":part_name,
                                 "part_number":part_number,"price":price,"stock":stock,
                                 "image_path":img_path,"category":category}):
                        st.success(f"✅ Pièce « {part_name} » ajoutée !"); st.rerun()

def _form_edit_part(part):
    with st.form(f"form_edit_{part['id']}"):
        st.markdown(f"**Modifier : {part['part_name']}**")
        c1, c2 = st.columns(2)
        part_name   = c1.text_input("Nom",      value=part["part_name"])
        part_number = c2.text_input("Référence", value=part.get("part_number",""))
        makes = get_makes()
        make_idx = makes.index(part["make"]) if part.get("make") in makes else 0
        make  = c1.selectbox("Marque", makes, index=make_idx)
        model = c2.text_input("Modèle", value=part.get("model",""))
        y1, y2 = st.columns(2)
        year_start = y1.number_input("Année début", min_value=1970, max_value=2030,
                                      value=int(part.get("year_start") or 2000))
        year_end   = y2.number_input("Année fin",   min_value=1970, max_value=2030,
                                      value=int(part.get("year_end") or 2024))
        p1, p2 = st.columns(2)
        price = p1.number_input("Prix (DA)", min_value=0.0, value=float(part["price"]))
        stock = p2.number_input("Stock",     min_value=0,   value=int(part["stock"]))
        cats = get_categories()
        cat_idx = cats.index(part["category"]) if part.get("category") in cats else 0
        category   = st.selectbox("Catégorie", cats, index=cat_idx)
        image_file = st.file_uploader("Nouvelle image", type=["jpg","jpeg","png","webp"],
                                       key=f"img_edit_{part['id']}")
        cs, cc = st.columns(2)
        saved     = cs.form_submit_button("💾 Sauvegarder")
        cancelled = cc.form_submit_button("❌ Annuler")
        if saved:
            img_path = save_uploaded_image(image_file, part_number) if image_file else part.get("image_path")
            if update_part(part["id"], {"make":make,"model":model,"year_start":year_start,
                                         "year_end":year_end,"part_name":part_name,
                                         "part_number":part_number,"price":price,"stock":stock,
                                         "image_path":img_path,"category":category}):
                st.success("✅ Modifié !")
                del st.session_state[f"edit_part_{part['id']}"]
                st.rerun()
        if cancelled:
            del st.session_state[f"edit_part_{part['id']}"]
            st.rerun()


# ══════════════════════════════════════════════════════════════════════
# ██████  CLIENTS
# ══════════════════════════════════════════════════════════════════════

def get_all_clients():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM clients ORDER BY name", conn)
    conn.close(); return df

def get_client_by_id(client_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
    row = c.fetchone(); conn.close()
    return dict(row) if row else None

def add_client(data):
    try:
        conn = get_connection(); c = conn.cursor()
        c.execute("INSERT INTO clients (name,phone,email,address) VALUES (:name,:phone,:email,:address)", data)
        conn.commit(); cid = c.lastrowid; conn.close(); return cid
    except Exception as e:
        st.error(f"Erreur : {e}"); return None

def update_client(client_id, data):
    try:
        conn = get_connection()
        conn.execute("UPDATE clients SET name=:name,phone=:phone,email=:email,address=:address WHERE id=:id",
                     {**data,"id":client_id})
        conn.commit(); conn.close(); return True
    except Exception as e:
        st.error(f"Erreur : {e}"); return False

def delete_client(client_id):
    try:
        conn = get_connection()
        conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        conn.commit(); conn.close(); return True
    except Exception as e:
        st.error(f"Erreur : {e}"); return False

def show_clients():
    st.header("👥 Gestion des clients")
    tab1, tab2 = st.tabs(["📋 Liste", "➕ Nouveau client"])
    with tab1:
        df = get_all_clients()
        search = st.text_input("🔍 Rechercher", key="client_search")
        if search:
            df = df[df["name"].str.contains(search, case=False, na=False) |
                    df["phone"].str.contains(search, case=False, na=False)]
        st.caption(f"{len(df)} client(s)")
        for _, cl in df.iterrows():
            with st.expander(f"👤 {cl['name']}  |  📞 {cl.get('phone','—')}"):
                c1, c2 = st.columns([3,1])
                with c1:
                    st.write(f"**Email :** {cl.get('email') or '—'}")
                    st.write(f"**Adresse :** {cl.get('address') or '—'}")
                    conn = get_connection()
                    hist = pd.read_sql_query(
                        "SELECT invoice_number,sale_date,total_amount,payment_method,status FROM sales WHERE client_id=? ORDER BY sale_date DESC",
                        conn, params=(cl["id"],))
                    conn.close()
                    if not hist.empty:
                        st.markdown("**Historique :**")
                        st.dataframe(hist, use_container_width=True, hide_index=True)
                with c2:
                    if st.button("✏️", key=f"edit_cl_{cl['id']}"):
                        st.session_state[f"edit_client_{cl['id']}"] = True
                    if st.button("🗑️", key=f"del_cl_{cl['id']}"):
                        if delete_client(cl["id"]): st.success("Supprimé."); st.rerun()
                if st.session_state.get(f"edit_client_{cl['id']}"):
                    with st.form(f"form_edit_cl_{cl['id']}"):
                        name    = st.text_input("Nom",       value=cl["name"])
                        c1b, c2b = st.columns(2)
                        phone   = c1b.text_input("Téléphone", value=cl.get("phone",""))
                        email   = c2b.text_input("Email",     value=cl.get("email",""))
                        address = st.text_area("Adresse",    value=cl.get("address",""))
                        cs, cc  = st.columns(2)
                        if cs.form_submit_button("💾 Sauvegarder"):
                            if update_client(cl["id"], {"name":name,"phone":phone,"email":email,"address":address}):
                                st.success("✅ Modifié !"); del st.session_state[f"edit_client_{cl['id']}"]; st.rerun()
                        if cc.form_submit_button("❌ Annuler"):
                            del st.session_state[f"edit_client_{cl['id']}"]; st.rerun()
    with tab2:
        st.subheader("Nouveau client")
        with st.form("form_add_client"):
            name = st.text_input("Nom complet *")
            c1, c2 = st.columns(2)
            phone = c1.text_input("Téléphone"); email = c2.text_input("Email")
            address = st.text_area("Adresse")
            if st.form_submit_button("✅ Enregistrer"):
                if not name: st.error("Le nom est obligatoire.")
                else:
                    cid = add_client({"name":name,"phone":phone,"email":email,"address":address})
                    if cid: st.success(f"✅ Client « {name} » créé (#{cid})"); st.rerun()


# ══════════════════════════════════════════════════════════════════════
# ██████  VENTES
# ══════════════════════════════════════════════════════════════════════

def get_all_sales(filters=None):
    conn = get_connection()
    q = """SELECT s.id,s.invoice_number,s.sale_date,s.total_amount,s.payment_method,s.status,
               COALESCE(c.name,'Client divers') as client_name
           FROM sales s LEFT JOIN clients c ON s.client_id=c.id WHERE 1=1"""
    params = []
    if filters:
        if filters.get("date_from"): q += " AND DATE(s.sale_date)>=?"; params.append(str(filters["date_from"]))
        if filters.get("date_to"):   q += " AND DATE(s.sale_date)<=?"; params.append(str(filters["date_to"]))
        if filters.get("status"):    q += " AND s.status=?";           params.append(filters["status"])
    q += " ORDER BY s.sale_date DESC"
    df = pd.read_sql_query(q, conn, params=params)
    conn.close(); return df

def get_sale_items(sale_id):
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT si.*,p.part_name,p.part_number FROM sale_items si JOIN parts p ON si.part_id=p.id WHERE si.sale_id=?",
        conn, params=(sale_id,))
    conn.close(); return df

def create_sale(client_id, items, payment_method):
    conn = get_connection()
    try:
        total = sum(i["total"] for i in items)
        inv_num = get_next_invoice_number(conn)
        invoice_number = f"{INVOICE_PREFIX}{inv_num:04d}"
        c = conn.cursor()
        c.execute("""INSERT INTO sales (client_id,sale_date,total_amount,payment_method,status,invoice_number)
                     VALUES (?,?,?,?,\'paid\',?)""",
                  (client_id, datetime.now().isoformat(), total, payment_method, invoice_number))
        sale_id = c.lastrowid
        for item in items:
            c.execute("INSERT INTO sale_items (sale_id,part_id,quantity,unit_price,total) VALUES (?,?,?,?,?)",
                      (sale_id, item["part_id"], item["quantity"], item["unit_price"], item["total"]))
            update_stock(item["part_id"], -item["quantity"], conn)
            record_movement(item["part_id"], item["quantity"], "out",
                            reason=f"Vente {invoice_number}", reference=invoice_number, conn=conn)
        c.execute("""INSERT INTO transactions (date,type,category,amount,description,reference)
                     VALUES (?,\'income\',\'Vente\',?,?,?)""",
                  (datetime.now().isoformat(), total, f"Vente {invoice_number}", invoice_number))
        conn.commit()
        sale = {"id":sale_id,"invoice_number":invoice_number,"sale_date":datetime.now().isoformat(),
                "total_amount":total,"payment_method":payment_method,"client_id":client_id}
        conn.close(); return sale
    except Exception as e:
        conn.rollback(); conn.close(); st.error(f"Erreur : {e}"); return None

def cancel_sale(sale_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,))
        for item in c.fetchall():
            update_stock(item["part_id"], item["quantity"], conn)
        c.execute("SELECT invoice_number FROM sales WHERE id=?", (sale_id,))
        row = c.fetchone()
        if row: c.execute("DELETE FROM transactions WHERE reference=? AND type='income'", (row["invoice_number"],))
        c.execute("UPDATE sales SET status='cancelled' WHERE id=?", (sale_id,))
        conn.commit(); conn.close(); return True
    except Exception as e:
        conn.rollback(); conn.close(); st.error(f"Erreur : {e}"); return False

def show_sales():
    st.header("💳 Ventes & Facturation")
    tab1, tab2 = st.tabs(["🛒 Nouvelle vente", "📋 Historique"])
    with tab1:
        st.subheader("Nouvelle vente")
        if "cart" not in st.session_state: st.session_state["cart"] = []
        st.markdown("#### 1. Ajouter des pièces")
        parts_df = get_all_parts()
        if not parts_df.empty:
            part_opts = {f"{r['part_name']} — {r.get('part_number','?')} ({format_price(r['price'])})": r
                         for _, r in parts_df.iterrows()}
            sel = st.selectbox("Pièce", [""]+list(part_opts.keys()), key="sale_part_sel")
            c1, c2 = st.columns([3,1])
            qty = c1.number_input("Quantité", min_value=1, value=1, key="sale_qty")
            if c2.button("➕ Ajouter", key="btn_add_cart") and sel:
                part = part_opts[sel]
                if qty > part["stock"]:
                    st.warning(f"⚠️ Stock insuffisant ({part['stock']} dispo)")
                else:
                    cart = st.session_state.setdefault("cart", [])
                    found = False
                    for item in cart:
                        if item["part_id"] == part["id"]:
                            item["quantity"] += qty; item["total"] = item["quantity"]*item["unit_price"]; found = True; break
                    if not found:
                        cart.append({"part_id":part["id"],"part_name":part["part_name"],
                                     "part_number":part.get("part_number",""),"unit_price":part["price"],
                                     "quantity":qty,"total":qty*part["price"],"stock":part["stock"]})
                    st.rerun()
        st.markdown("---")
        cart = st.session_state["cart"]
        if not cart:
            st.info("Panier vide. Ajoutez des pièces ci-dessus."); return
        st.markdown("#### 2. Panier")
        st.dataframe(pd.DataFrame([{"#":i+1,"Pièce":it["part_name"],"Qté":it["quantity"],
                                     "Prix unit.":format_price(it["unit_price"]),
                                     "Total":format_price(it["total"])} for i,it in enumerate(cart)]),
                     use_container_width=True, hide_index=True)
        c1, c2 = st.columns([3,1])
        sel_idx = c1.selectbox("Ligne", range(len(cart)),
                               format_func=lambda x: f"{x+1}. {cart[x]['part_name']}", key="cart_sel")
        if c2.button("🗑️ Retirer"): st.session_state["cart"].pop(sel_idx); st.rerun()
        new_qty = c1.number_input("Modifier qté", min_value=1, value=cart[sel_idx]["quantity"], key="cart_eq")
        if c2.button("🔄 Màj"):
            cart[sel_idx]["quantity"]=new_qty; cart[sel_idx]["total"]=new_qty*cart[sel_idx]["unit_price"]; st.rerun()
        if st.button("🧹 Vider le panier"): st.session_state["cart"]=[]; st.rerun()
        st.markdown("---")
        st.markdown("#### 3. Client & Paiement")
        clients_df = get_all_clients()
        client_opts = {"Client divers (sans compte)": None}
        client_opts.update({f"{r['name']} — {r.get('phone','')}": r["id"] for _,r in clients_df.iterrows()})
        sel_cl = st.selectbox("Client", list(client_opts.keys()), key="sale_client")
        client_id = client_opts[sel_cl]
        payment = st.selectbox("Mode de paiement", get_payment_methods(), key="sale_payment")
        total = sum(i["total"] for i in cart)
        st.markdown(f"### 💰 Total : **{format_price(total)}**")
        if st.button("✅ Valider la vente et générer la facture", type="primary"):
            sale = create_sale(client_id, cart, payment)
            if sale:
                client_info = get_client_by_id(client_id) or {"name":"Client divers","phone":"","address":""}
                try:
                    pdf_path = generate_invoice_pdf(sale, cart, client_info)
                    st.success(f"✅ Vente validée ! Facture : **{sale['invoice_number']}**")
                    with open(pdf_path,"rb") as f:
                        st.download_button("📄 Télécharger la facture PDF", data=f.read(),
                                           file_name=f"facture_{sale['invoice_number']}.pdf",
                                           mime="application/pdf")
                except Exception as e:
                    st.success(f"✅ Vente validée ! ({sale['invoice_number']})"); st.warning(f"PDF: {e}")
                st.session_state["cart"]=[]; st.rerun()

    with tab2:
        st.subheader("Historique des ventes")
        c1,c2,c3 = st.columns(3)
        df_from = c1.date_input("Du",  value=None, key="hist_from")
        df_to   = c2.date_input("Au",  value=None, key="hist_to")
        stat_f  = c3.selectbox("Statut",["","paid","cancelled"],
                               format_func=lambda x:{"":"Tous","paid":"✅ Payé","cancelled":"❌ Annulé"}.get(x,x))
        df = get_all_sales({"date_from":df_from,"date_to":df_to,"status":stat_f or None})
        if df.empty: st.info("Aucune vente."); return
        st.caption(f"{len(df)} vente(s) — Total : {format_price(df['total_amount'].sum())}")
        for _, sale in df.iterrows():
            icon = "✅" if sale["status"]=="paid" else "❌"
            with st.expander(f"{icon} {sale['invoice_number']} | {sale['client_name']} | {format_price(sale['total_amount'])} | {str(sale['sale_date'])[:10]}"):
                items_df = get_sale_items(sale["id"])
                if not items_df.empty:
                    st.dataframe(items_df[["part_name","quantity","unit_price","total"]],
                                 use_container_width=True, hide_index=True)
                c1b, c2b = st.columns(2)
                c1b.write(f"**Paiement :** {sale.get('payment_method','—')}")
                if sale["status"]=="paid":
                    if c2b.button("❌ Annuler", key=f"cancel_{sale['id']}"):
                        if cancel_sale(sale["id"]): st.success("Vente annulée."); st.rerun()


# ══════════════════════════════════════════════════════════════════════
# ██████  BONS DE COMMANDE
# ══════════════════════════════════════════════════════════════════════

def get_all_orders(status=None):
    conn = get_connection()
    q = "SELECT * FROM purchase_orders" + (" WHERE status=?" if status else "") + " ORDER BY order_date DESC"
    df = pd.read_sql_query(q, conn, params=([status] if status else []))
    conn.close(); return df

def get_order_items(order_id):
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT oi.*,p.part_name,p.part_number FROM order_items oi JOIN parts p ON oi.part_id=p.id WHERE oi.order_id=?",
        conn, params=(order_id,))
    conn.close(); return df

def create_order(supplier_name, items, delivery_date=None):
    if not items: return None
    total = sum(i["total"] for i in items)
    try:
        conn = get_connection(); c = conn.cursor()
        c.execute("INSERT INTO purchase_orders (supplier_name,order_date,delivery_date,total_amount,status) VALUES (?,?,?,?,'pending')",
                  (supplier_name, datetime.now().isoformat(), str(delivery_date) if delivery_date else None, total))
        order_id = c.lastrowid
        for item in items:
            c.execute("INSERT INTO order_items (order_id,part_id,quantity,unit_price,total) VALUES (?,?,?,?,?)",
                      (order_id, item["part_id"], item["quantity"], item["unit_price"], item["total"]))
        conn.commit(); conn.close(); return order_id
    except Exception as e:
        st.error(f"Erreur : {e}"); return None

def receive_order(order_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,))
        for item in c.fetchall():
            update_stock(item["part_id"], item["quantity"], conn)
            record_movement(item["part_id"], item["quantity"], "in",
                            reason=f"Réception BC #{order_id:04d}", reference=f"BC{order_id:04d}", conn=conn)
        c.execute("SELECT * FROM purchase_orders WHERE id=?", (order_id,))
        order = c.fetchone()
        c.execute("UPDATE purchase_orders SET status='received' WHERE id=?", (order_id,))
        conn.commit()
        if order:
            conn2 = get_connection()
            conn2.execute("""INSERT INTO transactions (date,type,category,amount,description,reference)
                             VALUES (?,\'expense\',\'Achat fournisseur\',?,?,?)""",
                          (datetime.now().isoformat(), order["total_amount"],
                           f"Réception BC #{order_id:04d} — {order['supplier_name']}", f"BC{order_id:04d}"))
            conn2.commit(); conn2.close()
        conn.close(); return True
    except Exception as e:
        conn.rollback(); conn.close(); st.error(f"Erreur : {e}"); return False

def show_purchase_orders():
    st.header("📋 Bons de commande fournisseurs")
    tab1, tab2 = st.tabs(["➕ Nouveau bon", "📂 Historique"])
    with tab1:
        st.subheader("Créer un bon de commande")
        if "bc_cart" not in st.session_state: st.session_state["bc_cart"] = []
        supplier = st.text_input("Fournisseur *", key="bc_supplier")
        delivery = st.date_input("Livraison prévue", value=None, key="bc_delivery")
        parts_df = get_all_parts()
        if not parts_df.empty:
            part_opts = {f"{r['part_name']} — {r.get('part_number','?')} (stock:{r['stock']})": r
                         for _,r in parts_df.iterrows()}
            sel = st.selectbox("Pièce", [""]+list(part_opts.keys()), key="bc_part_sel")
            c1,c2,c3 = st.columns(3)
            qty   = c1.number_input("Quantité", min_value=1, value=1, key="bc_qty")
            price = c2.number_input("Prix unitaire (DA)", min_value=0.0, value=0.0, key="bc_unit_price")
            if c3.button("➕ Ajouter", key="bc_add") and sel:
                part = part_opts[sel]
                p = price if price > 0 else part["price"]
                bc = st.session_state.setdefault("bc_cart",[])
                found = False
                for item in bc:
                    if item["part_id"]==part["id"]:
                        item["quantity"]+=qty; item["total"]=item["quantity"]*item["unit_price"]; found=True; break
                if not found:
                    bc.append({"part_id":part["id"],"part_name":part["part_name"],
                               "part_number":part.get("part_number",""),"unit_price":p,"quantity":qty,"total":qty*p})
                st.rerun()
        bc = st.session_state["bc_cart"]
        if bc:
            st.dataframe(pd.DataFrame([{"#":i+1,"Pièce":it["part_name"],"Qté":it["quantity"],
                                         "P.U.":format_price(it["unit_price"]),"Total":format_price(it["total"])}
                                        for i,it in enumerate(bc)]),
                         use_container_width=True, hide_index=True)
            st.markdown(f"**Total : {format_price(sum(i['total'] for i in bc))}**")
            c1b, c2b = st.columns(2)
            if c1b.button("🧹 Vider"): st.session_state["bc_cart"]=[]; st.rerun()
            if c2b.button("✅ Créer le BC", type="primary"):
                if not supplier: st.error("Fournisseur obligatoire.")
                else:
                    oid = create_order(supplier, bc, delivery)
                    if oid:
                        st.success(f"✅ BC#{oid:04d} créé !")
                        try:
                            p = generate_purchase_order_pdf({"id":oid,"supplier_name":supplier,
                                                              "order_date":datetime.now().isoformat(),
                                                              "total_amount":sum(i["total"] for i in bc)}, bc)
                            with open(p,"rb") as f:
                                st.download_button("📄 Télécharger BC PDF",data=f.read(),
                                                   file_name=f"bc_{oid:04d}.pdf",mime="application/pdf")
                        except Exception as e: st.warning(f"PDF: {e}")
                        st.session_state["bc_cart"]=[]; st.rerun()
    with tab2:
        st.subheader("Historique")
        stat_f = st.selectbox("Statut",["","pending","received","cancelled"],
                               format_func=lambda x:{"":"Tous","pending":"⏳ En attente",
                                                       "received":"✅ Reçu","cancelled":"❌ Annulé"}.get(x,x))
        df = get_all_orders(stat_f or None)
        if df.empty: st.info("Aucun bon."); return
        icons = {"pending":"⏳","received":"✅","cancelled":"❌"}
        for _, order in df.iterrows():
            with st.expander(f"{icons.get(order['status'],'?')} BC{order['id']:04d} | {order['supplier_name']} | {format_price(order['total_amount'])} | {str(order['order_date'])[:10]}"):
                items_df = get_order_items(order["id"])
                if not items_df.empty:
                    st.dataframe(items_df[["part_name","quantity","unit_price","total"]],
                                 use_container_width=True, hide_index=True)
                c1b,c2b,c3b = st.columns(3)
                if order["status"]=="pending":
                    if c2b.button("✅ Marquer reçu", key=f"recv_{order['id']}"):
                        if receive_order(order["id"]): st.success("✅ Reçu ! Stock mis à jour."); st.rerun()
                    if c3b.button("❌ Annuler", key=f"canc_{order['id']}"):
                        conn=get_connection(); conn.execute("UPDATE purchase_orders SET status='cancelled' WHERE id=?",(order["id"],)); conn.commit(); conn.close(); st.rerun()
                if c1b.button("📄 PDF", key=f"pdf_bc_{order['id']}"):
                    try:
                        il = items_df.to_dict("records") if not items_df.empty else []
                        p = generate_purchase_order_pdf(dict(order), il)
                        with open(p,"rb") as f:
                            st.download_button("⬇️",data=f.read(),file_name=f"bc_{order['id']:04d}.pdf",
                                               mime="application/pdf",key=f"dl_bc_{order['id']}")
                    except Exception as e: st.error(f"PDF: {e}")


# ══════════════════════════════════════════════════════════════════════
# ██████  RECETTES & DÉPENSES
# ══════════════════════════════════════════════════════════════════════

def get_all_transactions(filters=None):
    conn = get_connection()
    q = "SELECT * FROM transactions WHERE 1=1"; params=[]
    if filters:
        if filters.get("type"):     q+=" AND type=?";              params.append(filters["type"])
        if filters.get("category"): q+=" AND category=?";          params.append(filters["category"])
        if filters.get("date_from"):q+=" AND DATE(date)>=?";        params.append(str(filters["date_from"]))
        if filters.get("date_to"):  q+=" AND DATE(date)<=?";        params.append(str(filters["date_to"]))
    q += " ORDER BY date DESC"
    df = pd.read_sql_query(q, conn, params=params)
    conn.close(); return df

def add_transaction(data):
    try:
        conn = get_connection()
        conn.execute("INSERT INTO transactions (date,type,category,amount,description,reference) VALUES (:date,:type,:category,:amount,:description,:reference)", data)
        conn.commit(); conn.close(); return True
    except Exception as e:
        st.error(f"Erreur : {e}"); return False

def get_financial_summary():
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income'")
    inc = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense'")
    exp = c.fetchone()[0]
    conn.close()
    return {"income":inc,"expense":exp,"balance":inc-exp}

def show_expenses():
    st.header("💰 Recettes & Dépenses")
    summary = get_financial_summary()
    c1,c2,c3 = st.columns(3)
    c1.metric("📈 Recettes totales",    format_price(summary["income"]))
    c2.metric("📉 Dépenses totales",    format_price(summary["expense"]))
    c3.metric("💼 Solde trésorerie",    format_price(summary["balance"]))

    tab1, tab2, tab3 = st.tabs(["📋 Transactions","➕ Ajouter dépense","📊 Graphique mensuel"])
    with tab1:
        c1b,c2b,c3b = st.columns(3)
        txn_type = c1b.selectbox("Type",["","income","expense"],
                                  format_func=lambda x:{"":"Tous","income":"📈 Recettes","expense":"📉 Dépenses"}.get(x,x))
        df_from = c2b.date_input("Du",  value=None, key="txn_from")
        df_to   = c3b.date_input("Au",  value=None, key="txn_to")
        cats = [""]+get_expense_categories()+["Vente"]
        cat_f = st.selectbox("Catégorie", cats, key="txn_cat")
        df = get_all_transactions({"type":txn_type or None,"category":cat_f or None,"date_from":df_from,"date_to":df_to})
        if df.empty: st.info("Aucune transaction.")
        else:
            st.caption(f"{len(df)} transaction(s) | In: {format_price(df[df['type']=='income']['amount'].sum())} | Out: {format_price(df[df['type']=='expense']['amount'].sum())}")
            disp = df[["date","type","category","amount","description","reference"]].copy()
            disp["type"] = disp["type"].map({"income":"📈 Recette","expense":"📉 Dépense"})
            disp["amount"] = disp["amount"].apply(lambda x: f"{x:,.2f} DA")
            disp["date"] = disp["date"].astype(str).str[:10]
            st.dataframe(disp, use_container_width=True, hide_index=True)
    with tab2:
        st.subheader("Ajouter une dépense")
        with st.form("form_add_expense"):
            description = st.text_input("Description *")
            c1b,c2b = st.columns(2)
            amount   = c1b.number_input("Montant (DA) *", min_value=0.01, value=0.01)
            category = c2b.selectbox("Catégorie", get_expense_categories())
            exp_date = c1b.date_input("Date", value=date.today())
            reference = c2b.text_input("Référence")
            if st.form_submit_button("✅ Enregistrer"):
                if not description or amount <= 0: st.error("Description et montant obligatoires.")
                else:
                    if add_transaction({"date":datetime.combine(exp_date, datetime.min.time()).isoformat(),
                                        "type":"expense","category":category,"amount":amount,
                                        "description":description,"reference":reference}):
                        st.success(f"✅ Dépense de {format_price(amount)} enregistrée."); st.rerun()
    with tab3:
        conn = get_connection()
        monthly = pd.read_sql_query("""
            SELECT strftime('%Y-%m', date) as month, type, SUM(amount) as total
            FROM transactions GROUP BY month, type ORDER BY month""", conn)
        conn.close()
        if monthly.empty: st.info("Pas encore de données.")
        else:
            pivot = monthly.pivot(index="month", columns="type", values="total").fillna(0)
            pivot.columns = [{"income":"Recettes","expense":"Dépenses"}.get(c,c) for c in pivot.columns]
            pivot["Solde"] = pivot.get("Recettes",0) - pivot.get("Dépenses",0)
            st.line_chart(pivot)


# ══════════════════════════════════════════════════════════════════════
# ██████  STOCK
# ══════════════════════════════════════════════════════════════════════

def get_stock_stats():
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM parts");                                             total_refs  = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(stock),0) FROM parts");                               total_units = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(stock*price),0) FROM parts");                         total_value = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM parts WHERE stock=0");                               rupture     = c.fetchone()[0]
    c.execute(f"SELECT COUNT(*) FROM parts WHERE stock>0 AND stock<={STOCK_THRESHOLD}"); low         = c.fetchone()[0]
    c.execute(f"SELECT COUNT(*) FROM parts WHERE stock>{STOCK_THRESHOLD}");              ok          = c.fetchone()[0]
    conn.close()
    return {"total_refs":total_refs,"total_units":total_units,"total_value":total_value,
            "rupture":rupture,"low":low,"ok":ok}

def show_stock():
    st.header("🗄️ Gestion du stock")
    stats = get_stock_stats()
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("📋 Références", stats["total_refs"])
    c2.metric("📦 Unités",     f"{stats['total_units']:,}")
    c3.metric("💰 Valeur",     format_price(stats["total_value"]))
    c4.metric("⚠️ Stock bas",  stats["low"])
    c5.metric("🔴 Rupture",    stats["rupture"])
    st.markdown("---")
    tab1,tab2,tab3,tab4 = st.tabs(["📊 État","✏️ Ajustement","📈 Mouvements","🖨️ Inventaire"])
    with tab1:
        conn = get_connection()
        df = pd.read_sql_query("""SELECT id,make,model,part_name,part_number,category,stock,price,
                                         stock*price as valeur FROM parts ORDER BY stock ASC,make,model""", conn)
        conn.close()
        c1b,c2b,c3b = st.columns(3)
        etat = c1b.selectbox("État",["Tous","🔴 Rupture","⚠️ Stock bas","✅ OK"])
        search = c2b.text_input("Recherche", key="stock_search")
        if etat == "🔴 Rupture": df = df[df["stock"]==0]
        elif etat == "⚠️ Stock bas": df = df[(df["stock"]>0)&(df["stock"]<=STOCK_THRESHOLD)]
        elif etat == "✅ OK": df = df[df["stock"]>STOCK_THRESHOLD]
        if search:
            df = df[df["part_name"].str.contains(search,case=False,na=False)|
                    df["part_number"].str.contains(search,case=False,na=False)]
        st.caption(f"{len(df)} pièce(s) | Valeur : {format_price(df['valeur'].sum())}")
        disp = df[["part_name","part_number","make","model","category","stock","price","valeur"]].copy()
        disp.columns = ["Pièce","Réf","Marque","Modèle","Catégorie","Stock","Prix (DA)","Valeur (DA)"]
        disp["Prix (DA)"]  = disp["Prix (DA)"].apply(lambda x:f"{x:,.2f}")
        disp["Valeur (DA)"]= disp["Valeur (DA)"].apply(lambda x:f"{x:,.2f}")
        st.dataframe(disp, use_container_width=True, hide_index=True)
    with tab2:
        st.subheader("Ajustement manuel")
        conn = get_connection()
        parts_df = pd.read_sql_query("SELECT id,part_name,part_number,stock FROM parts ORDER BY part_name", conn)
        conn.close()
        if not parts_df.empty:
            opts = {f"{r['part_name']} (Réf:{r['part_number']}) — Stock:{r['stock']}": r
                    for _,r in parts_df.iterrows()}
            sel = st.selectbox("Pièce", list(opts.keys()), key="adj_sel")
            part = opts[sel]
            c1b,c2b = st.columns(2)
            c1b.metric("Stock actuel", int(part["stock"]))
            new_stock = c2b.number_input("Nouveau stock", min_value=0, value=int(part["stock"]), key="adj_new")
            delta = new_stock - int(part["stock"])
            if delta > 0: st.success(f"📈 +{delta} unités")
            elif delta < 0: st.warning(f"📉 {delta} unités")
            else: st.info("Aucun changement")
            reason = st.text_input("Raison *", placeholder="Ex: Inventaire mensuel", key="adj_reason")
            if st.button("✅ Appliquer", type="primary", disabled=(delta==0)):
                if not reason: st.error("Raison obligatoire.")
                else:
                    conn2 = get_connection()
                    conn2.execute("UPDATE parts SET stock=? WHERE id=?", (new_stock, part["id"]))
                    record_movement(part["id"], abs(delta),
                                    f"adjustment_{'in' if delta>=0 else 'out'}",
                                    reason=reason, reference="Inventaire", conn=conn2)
                    conn2.commit(); conn2.close()
                    st.success(f"✅ Stock mis à jour : {int(part['stock'])} → {new_stock}"); st.rerun()
    with tab3:
        st.subheader("Mouvements de stock")
        conn = get_connection()
        df_mv = pd.read_sql_query("""SELECT sm.date,p.part_name,p.part_number,sm.movement_type,
                                            sm.quantity,sm.reason,sm.reference
                                     FROM stock_movements sm JOIN parts p ON sm.part_id=p.id
                                     ORDER BY sm.date DESC LIMIT 200""", conn)
        conn.close()
        if df_mv.empty: st.info("Aucun mouvement enregistré.")
        else:
            icons = {"in":"📦","out":"📤","adjustment_in":"📈","adjustment_out":"📉"}
            df_mv["movement_type"] = df_mv["movement_type"].apply(lambda t: f"{icons.get(t,'🔄')} {t}")
            df_mv["date"] = df_mv["date"].astype(str).str[:16]
            st.dataframe(df_mv, use_container_width=True, hide_index=True)
    with tab4:
        st.subheader("Fiche d'inventaire")
        conn = get_connection()
        df_inv = pd.read_sql_query("""SELECT make Marque,model Modèle,part_name Pièce,
                                             part_number Référence,category Catégorie,
                                             stock "Stock système",'' "Stock physique",'' Écart
                                      FROM parts ORDER BY make,model,part_name""", conn)
        conn.close()
        st.dataframe(df_inv, use_container_width=True, hide_index=True)
        buf = io.BytesIO()
        df_inv.to_excel(buf, index=False, engine="openpyxl")
        c1b,c2b = st.columns(2)
        c1b.download_button("⬇️ CSV", data=df_inv.to_csv(index=False).encode("utf-8"),
                             file_name=f"inventaire_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")
        c2b.download_button("⬇️ Excel", data=buf.getvalue(),
                             file_name=f"inventaire_{datetime.now().strftime('%Y%m%d')}.xlsx",
                             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ══════════════════════════════════════════════════════════════════════
# ██████  TABLEAU DE BORD
# ══════════════════════════════════════════════════════════════════════

def show_dashboard():
    st.header("📊 Tableau de bord")
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(total_amount),0) FROM sales WHERE strftime('%Y-%m',sale_date)=strftime('%Y-%m','now') AND status='paid'")
    ca_month = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(total_amount),0) FROM sales WHERE status='paid'")
    ca_total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sales WHERE strftime('%Y-%m',sale_date)=strftime('%Y-%m','now') AND status='paid'")
    nb_sales = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense'")
    total_exp = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income'")
    total_inc = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(stock*price),0) FROM parts")
    stock_val = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM parts")
    nb_parts = c.fetchone()[0]
    c.execute(f"SELECT * FROM parts WHERE stock<={STOCK_THRESHOLD} ORDER BY stock ASC")
    low_parts = [dict(r) for r in c.fetchall()]
    conn.close()

    col1,col2,col3,col4 = st.columns(4)
    col1.metric("💵 CA ce mois",     format_price(ca_month))
    col2.metric("💰 CA total",       format_price(ca_total))
    col3.metric("🛍️ Ventes ce mois", nb_sales)
    col4.metric("📦 Stock valorisé", format_price(stock_val))
    col1b,col2b,col3b,col4b = st.columns(4)
    col1b.metric("📈 Recettes",   format_price(total_inc))
    col2b.metric("📉 Dépenses",   format_price(total_exp))
    col3b.metric("💼 Trésorerie", format_price(total_inc - total_exp))
    col4b.metric("🔧 Références", nb_parts)
    st.markdown("---")

    left, right = st.columns(2)
    with left:
        st.subheader("📅 Ventes par mois")
        conn2 = get_connection()
        sm = pd.read_sql_query("""SELECT strftime('%Y-%m',sale_date) as mois,SUM(total_amount) as ca
                                   FROM sales WHERE status='paid' GROUP BY mois ORDER BY mois""", conn2)
        conn2.close()
        if not sm.empty: st.bar_chart(sm.set_index("mois")[["ca"]])
        else: st.info("Pas encore de ventes.")
    with right:
        st.subheader("💸 Dépenses par catégorie")
        conn3 = get_connection()
        ec = pd.read_sql_query("""SELECT category,SUM(amount) as total FROM transactions
                                   WHERE type='expense' GROUP BY category ORDER BY total DESC""", conn3)
        conn3.close()
        if not ec.empty: st.bar_chart(ec.set_index("category")["total"])
        else: st.info("Pas encore de dépenses.")
    st.markdown("---")
    st.subheader("🏆 Top 5 pièces vendues")
    conn4 = get_connection()
    top = pd.read_sql_query("""SELECT p.part_name,p.make,SUM(si.quantity) as qty,SUM(si.total) as ca
                                FROM sale_items si JOIN parts p ON si.part_id=p.id
                                JOIN sales s ON si.sale_id=s.id WHERE s.status='paid'
                                GROUP BY si.part_id ORDER BY qty DESC LIMIT 5""", conn4)
    conn4.close()
    if not top.empty:
        top["ca"] = top["ca"].apply(lambda x:f"{x:,.2f} DA")
        st.dataframe(top, use_container_width=True, hide_index=True)
    else: st.info("Aucune vente.")
    st.markdown("---")
    st.subheader(f"⚠️ Alertes stock bas ({len(low_parts)} pièce(s))")
    if low_parts:
        df_low = pd.DataFrame(low_parts)[["part_name","part_number","make","model","stock","category"]]
        df_low.columns = ["Pièce","Réf","Marque","Modèle","Stock","Catégorie"]
        st.dataframe(df_low, use_container_width=True, hide_index=True)
        c1b, c2b = st.columns(2)
        if c1b.button("🔍 Filtrer catalogue"): st.session_state["vin_filter"]={"low_stock":True}; st.session_state["nav"]="📦 Catalogue"; st.rerun()
        if c2b.button("🗄️ Gérer le stock"):   st.session_state["nav"]="🗄️ Stock"; st.rerun()
    else: st.success(f"✅ Tous les stocks sont au-dessus du seuil ({STOCK_THRESHOLD}).")
    st.markdown("---")
    st.subheader("📉 Évolution trésorerie")
    conn5 = get_connection()
    txn = pd.read_sql_query("""SELECT DATE(date) as jour,
                                       SUM(CASE WHEN type='income' THEN amount ELSE -amount END) as flux
                                FROM transactions GROUP BY jour ORDER BY jour""", conn5)
    conn5.close()
    if not txn.empty:
        txn["cumul"] = txn["flux"].cumsum()
        st.line_chart(txn.set_index("jour")[["cumul"]])
    else: st.info("Aucune transaction.")


# ══════════════════════════════════════════════════════════════════════
# ██████  IMPORT / EXPORT
# ══════════════════════════════════════════════════════════════════════

def show_import_export():
    st.header("📁 Import / Export")
    tab1, tab2 = st.tabs(["📤 Import pièces", "📥 Export données"])
    with tab1:
        st.subheader("Importer des pièces (CSV / Excel)")
        st.info("Colonnes : `make, model, year_start, year_end, part_name, part_number, price, stock, category`")
        uploaded = st.file_uploader("Fichier CSV ou Excel", type=["csv","xlsx","xls"], key="import_file")
        if uploaded:
            try:
                df = pd.read_csv(uploaded) if uploaded.name.endswith(".csv") else pd.read_excel(uploaded)
                st.write(f"**Aperçu ({len(df)} lignes) :**"); st.dataframe(df.head(10), use_container_width=True)
                missing = {"part_name","part_number","price"} - set(df.columns)
                if missing: st.error(f"Colonnes manquantes : {missing}")
                else:
                    mode = st.radio("Mode", ["Ajouter uniquement les nouvelles","Mettre à jour si existe"])
                    if st.button("✅ Lancer l'import"):
                        conn = get_connection(); added=updated=errors=0
                        for _,row in df.iterrows():
                            try:
                                data = {"make":row.get("make",""),"model":row.get("model",""),
                                        "year_start":int(row.get("year_start",2000) or 2000),
                                        "year_end":int(row.get("year_end",2024) or 2024),
                                        "part_name":str(row["part_name"]),"part_number":str(row["part_number"]),
                                        "price":float(row["price"]),"stock":int(row.get("stock",0) or 0),
                                        "image_path":None,"category":row.get("category","Autre")}
                                c = conn.cursor()
                                c.execute("SELECT id FROM parts WHERE part_number=?",(data["part_number"],))
                                existing = c.fetchone()
                                if existing and "Mettre à jour" in mode:
                                    conn.execute("UPDATE parts SET make=:make,model=:model,year_start=:year_start,year_end=:year_end,part_name=:part_name,price=:price,stock=:stock,category=:category WHERE part_number=:part_number", data); updated+=1
                                elif not existing:
                                    conn.execute("INSERT INTO parts (make,model,year_start,year_end,part_name,part_number,price,stock,image_path,category) VALUES (:make,:model,:year_start,:year_end,:part_name,:part_number,:price,:stock,:image_path,:category)", data); added+=1
                            except: errors+=1
                        conn.commit(); conn.close()
                        st.success(f"✅ Import : {added} ajoutés, {updated} mis à jour, {errors} erreurs."); st.rerun()
            except Exception as e: st.error(f"Erreur lecture : {e}")
    with tab2:
        st.subheader("Exporter les données")
        sections = [
            ("📦 Catalogue", get_all_parts(), "catalogue_pieces"),
        ]
        conn = get_connection()
        sales_df = pd.read_sql_query("SELECT s.*,COALESCE(c.name,'Client divers') client_name FROM sales s LEFT JOIN clients c ON s.client_id=c.id ORDER BY s.sale_date DESC", conn)
        txn_df   = pd.read_sql_query("SELECT * FROM transactions ORDER BY date DESC", conn)
        bc_df    = pd.read_sql_query("SELECT * FROM purchase_orders ORDER BY order_date DESC", conn)
        conn.close()
        sections += [("💳 Ventes", sales_df, "ventes"),("💰 Transactions", txn_df, "transactions"),("📋 Bons de commande", bc_df, "bons_commande")]
        for label, df_exp, fname in sections:
            st.markdown(f"#### {label}")
            if df_exp is not None and not df_exp.empty:
                c1b,c2b = st.columns(2)
                c1b.download_button(f"⬇️ CSV", data=df_exp.to_csv(index=False).encode("utf-8"),
                                    file_name=f"{fname}.csv", mime="text/csv", key=f"csv_{fname}")
                buf = io.BytesIO(); df_exp.to_excel(buf, index=False, engine="openpyxl")
                c2b.download_button(f"⬇️ Excel", data=buf.getvalue(),
                                    file_name=f"{fname}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key=f"xlsx_{fname}")
            st.markdown("---")
        st.markdown("#### 📋 Modèle d'import")
        tmpl = pd.DataFrame([{"make":"Renault","model":"Clio","year_start":2010,"year_end":2020,
                               "part_name":"Filtre à huile","part_number":"RN-FH-XXX","price":850.0,"stock":10,"category":"Filtration"}])
        st.download_button("⬇️ Télécharger modèle CSV", data=tmpl.to_csv(index=False).encode("utf-8"),
                           file_name="modele_import.csv", mime="text/csv")


# ══════════════════════════════════════════════════════════════════════
# ██████  PARAMÈTRES
# ══════════════════════════════════════════════════════════════════════

def show_settings():
    st.header("⚙️ Paramètres")
    tab1, tab2, tab3 = st.tabs(["🏪 Magasin","🗄️ Base de données","ℹ️ À propos"])
    with tab1:
        st.subheader("Informations du magasin")
        st.info("Pour changer ces valeurs définitivement, modifiez les constantes en haut de ce fichier (section CONFIG).")
        c1,c2 = st.columns(2)
        c1.text_input("Nom",      value=SHOP_NAME,    disabled=True)
        c2.text_input("Adresse",  value=SHOP_ADDRESS, disabled=True)
        c1.text_input("Téléphone",value=SHOP_PHONE,   disabled=True)
        c2.text_input("Email",    value=SHOP_EMAIL,   disabled=True)
        c1.text_input("Devise",   value=CURRENCY,     disabled=True)
        c2.text_input("Mode VIN", value=VIN_MODE,     disabled=True)
        st.markdown("#### Logo")
        if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, width=200)
        else: st.warning("Aucun logo (placez logo.png dans data/)")
        new_logo = st.file_uploader("Changer le logo", type=["png","jpg","jpeg"])
        if new_logo:
            img = Image.open(new_logo); img.save(LOGO_PATH)
            st.success("✅ Logo mis à jour !"); st.rerun()
    with tab2:
        st.subheader("Base de données")
        conn = get_connection(); c = conn.cursor()
        stats = {}
        for t in ["parts","clients","sales","sale_items","transactions","purchase_orders","order_items"]:
            c.execute(f"SELECT COUNT(*) FROM {t}"); stats[t] = c.fetchone()[0]
        conn.close()
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Pièces",       stats["parts"])
        c2.metric("Clients",      stats["clients"])
        c3.metric("Ventes",       stats["sales"])
        c4.metric("Transactions", stats["transactions"])
        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        st.caption(f"DB : {DB_PATH} — {db_size/1024:.1f} Ko")
        if os.path.exists(DB_PATH):
            with open(DB_PATH,"rb") as f:
                st.download_button("⬇️ Sauvegarder database.db", data=f.read(),
                                   file_name="database_backup.db", mime="application/octet-stream")
    with tab3:
        st.markdown(f"""
        ## 🔧 {SHOP_NAME}
        Application de gestion de magasin de pièces détachées automobiles.
        **Version :** 1.0.0  |  **Moteur PDF :** {PDF_ENGINE}

        **Modules :** Catalogue · VIN · Stock · Ventes · Bons de commande · Dépenses · Dashboard · Import/Export

        **Technologies :** Python · Streamlit · SQLite · ReportLab · pandas · Pillow · openpyxl
        """)


# ══════════════════════════════════════════════════════════════════════
# ██████  APP PRINCIPALE
# ══════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Auto Pièces Maghreb",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stSidebar"] { background-color: #1a1a2e; }
[data-testid="stSidebar"] * { color: #e0e0e0 !important; }
.stButton > button[kind="primary"] { background-color:#1a73e8;color:white;border-radius:8px; }
</style>
""", unsafe_allow_html=True)

# Initialisation DB au démarrage
init_db()

PAGES = [
    "📊 Tableau de bord",
    "📦 Catalogue",
    "🗄️ Stock",
    "💳 Ventes",
    "📋 Bons de commande",
    "💰 Dépenses",
    "👥 Clients",
    "📁 Import / Export",
    "⚙️ Paramètres",
]

def render_sidebar():
    with st.sidebar:
        st.markdown(f"""
        <div style="text-align:center;padding:16px 0 8px">
            <div style="font-size:2.5rem">🔧</div>
            <div style="font-size:1.1rem;font-weight:700;color:#fff">{SHOP_NAME}</div>
            <div style="font-size:.75rem;color:#aaa">Gestion de magasin</div>
        </div>""", unsafe_allow_html=True)
        st.markdown("---")

        # Recherche VIN
        st.markdown("### 🔑 Recherche VIN")
        vin_input = st.text_input("Numéro de châssis (17 car.)", max_chars=17,
                                   placeholder="Ex: VF1BB1B0H45123456", key="vin_input")
        if vin_input:
            if not validate_vin(vin_input):
                st.warning("⚠️ VIN invalide")
            else:
                with st.spinner("Décodage..."):
                    result = decode_vin(vin_input)
                if result:
                    st.success(f"✅ **{result['make']} {result['model']}** ({result['year']})")
                    st.caption(f"Source : {result.get('source','?')}")
                    if st.button("🔍 Filtrer le catalogue"):
                        st.session_state["vin_filter"] = {"vin_make":result["make"],"vin_year":result.get("year")}
                        st.session_state["nav"] = "📦 Catalogue"; st.rerun()
                else:
                    st.error("Véhicule non reconnu.")
        if st.session_state.get("vin_filter"):
            if st.button("❌ Effacer filtre VIN"):
                st.session_state.pop("vin_filter", None); st.rerun()
        st.markdown("---")

        # Panier rapide
        cart = st.session_state.get("cart", [])
        nb_cart = sum(i["quantity"] for i in cart)
        if nb_cart > 0:
            total_cart = sum(i["total"] for i in cart)
            st.markdown(f'🛒 **Panier : {nb_cart} article(s)**<br><small>Total : {format_price(total_cart)}</small>',
                        unsafe_allow_html=True)
            if st.button("➡️ Aller aux ventes"):
                st.session_state["nav"] = "💳 Ventes"; st.rerun()
            st.markdown("---")

        # Navigation
        st.markdown("### 🗂️ Navigation")
        if "nav" not in st.session_state:
            st.session_state["nav"] = "📊 Tableau de bord"
        for page in PAGES:
            active = st.session_state["nav"] == page
            if st.button(page, key=f"nav_{page}", use_container_width=True,
                          type="primary" if active else "secondary"):
                st.session_state["nav"] = page; st.rerun()


def main():
    render_sidebar()
    page = st.session_state.get("nav", "📊 Tableau de bord")
    dispatch = {
        "📊 Tableau de bord":    show_dashboard,
        "📦 Catalogue":          show_catalogue,
        "🗄️ Stock":              show_stock,
        "💳 Ventes":             show_sales,
        "📋 Bons de commande":   show_purchase_orders,
        "💰 Dépenses":           show_expenses,
        "👥 Clients":            show_clients,
        "📁 Import / Export":    show_import_export,
        "⚙️ Paramètres":         show_settings,
    }
    fn = dispatch.get(page)
    if fn:
        fn()
    else:
        st.error("Page introuvable.")


if __name__ == "__main__":
    main()
