import streamlit as st
import pandas as pd
import sqlite3
import os
import hashlib
from datetime import datetime, date
from PIL import Image
import io
import requests
import json
import matplotlib.pyplot as plt
from fpdf import FPDF
import base64

# ------------------------- CONFIGURATION -------------------------
DB_PATH = "database.db"
IMAGES_DIR = "data/images"
INVOICES_DIR = "data/invoices"
DEFAULT_IMAGE = "data/images/default.png"
STOCK_THRESHOLD = 5
VIN_MODE = "local"  # ou "api"
VIN_API_KEY = ""    # clé API si nécessaire
TAUX_TVA = 0.19     # 19% TVA, peut être modifié

# Création des dossiers nécessaires
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(INVOICES_DIR, exist_ok=True)
if not os.path.exists(DEFAULT_IMAGE):
    # Créer une image par défaut blanche
    img = Image.new('RGB', (200, 150), color='gray')
    img.save(DEFAULT_IMAGE)

# ------------------------- FONCTIONS BASE DE DONNÉES -------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Table parts
    c.execute('''CREATE TABLE IF NOT EXISTS parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        make TEXT,
        model TEXT,
        year_start INTEGER,
        year_end INTEGER,
        part_name TEXT NOT NULL,
        part_number TEXT UNIQUE,
        price REAL NOT NULL,
        stock INTEGER NOT NULL DEFAULT 0,
        image_path TEXT,
        category TEXT
    )''')
    # Table clients
    c.execute('''CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        email TEXT,
        address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    # Table sales
    c.execute('''CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        total_amount REAL NOT NULL,
        payment_method TEXT,
        status TEXT DEFAULT 'paid',
        invoice_number TEXT UNIQUE,
        FOREIGN KEY (client_id) REFERENCES clients(id)
    )''')
    # Table sale_items
    c.execute('''CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        part_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        total REAL NOT NULL,
        FOREIGN KEY (sale_id) REFERENCES sales(id),
        FOREIGN KEY (part_id) REFERENCES parts(id)
    )''')
    # Table transactions (recettes/dépenses)
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        type TEXT CHECK(type IN ('income', 'expense')),
        category TEXT,
        amount REAL NOT NULL,
        description TEXT,
        reference TEXT
    )''')
    # Table purchase_orders
    c.execute('''CREATE TABLE IF NOT EXISTS purchase_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_name TEXT NOT NULL,
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        delivery_date DATE,
        total_amount REAL NOT NULL,
        status TEXT DEFAULT 'pending'
    )''')
    # Table order_items
    c.execute('''CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        part_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        total REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES purchase_orders(id),
        FOREIGN KEY (part_id) REFERENCES parts(id)
    )''')
    conn.commit()
    conn.close()

def load_initial_data():
    # Vérifier si la table parts est vide
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM parts")
    if c.fetchone()[0] == 0:
        # Charger depuis CSV si existe, sinon données factices
        if os.path.exists("data/initial_parts.csv"):
            df = pd.read_csv("data/initial_parts.csv")
            df.to_sql("parts", conn, if_exists="append", index=False)
        else:
            # Données exemple
            sample_parts = [
                ("Renault", "Clio", 2012, 2018, "Filtre à huile", "8200123456", 450.0, 10, "data/images/filtre_huile.jpg", "Moteur"),
                ("Peugeot", "208", 2015, 2020, "Plaquettes de frein", "9807654321", 1200.0, 5, "data/images/plaquettes.jpg", "Freinage"),
                ("Toyota", "Corolla", 2010, 2015, "Amortisseur avant", "48510-09200", 3500.0, 2, "data/images/amortisseur.jpg", "Suspension"),
                ("Hyundai", "i10", 2014, 2019, "Courroie distribution", "24312-03000", 2100.0, 3, "data/images/courroie.jpg", "Moteur"),
                ("Kia", "Picanto", 2017, 2021, "Batterie", "99999-12345", 8500.0, 4, "data/images/batterie.jpg", "Électrique"),
                ("Chevrolet", "Spark", 2013, 2016, "Alternateur", "25187239", 14500.0, 1, "data/images/alternateur.jpg", "Électrique"),
                ("Citroën", "C3", 2009, 2016, "Filtre habitacle", "6479E7", 350.0, 8, "data/images/filtre_habitacle.jpg", "Moteur"),
                ("Renault", "Logan", 2008, 2014, "Pneu", "P185/65R15", 3200.0, 6, "data/images/pneu.jpg", "Pneumatique"),
                ("Peugeot", "Partner", 2010, 2018, "Kit embrayage", "2050A3", 8900.0, 0, "data/images/embrayage.jpg", "Transmission"),
                ("Toyota", "Hilux", 2015, 2020, "Filtre à gazole", "23390-0L030", 680.0, 7, "data/images/filtre_gazole.jpg", "Moteur"),
            ]
            for p in sample_parts:
                c.execute('''INSERT INTO parts (make, model, year_start, year_end, part_name, part_number, price, stock, image_path, category)
                             VALUES (?,?,?,?,?,?,?,?,?,?)''', p)
            conn.commit()
    # Clients factices
    c.execute("SELECT COUNT(*) FROM clients")
    if c.fetchone()[0] == 0:
        sample_clients = [
            ("Ahmed Benali", "0555123456", "ahmed@example.com", "Alger Centre"),
            ("Fatima Zohra", "0555987654", "fatima@example.com", "Oran"),
            ("Mohamed Lamine", "0555443322", "mohamed@example.com", "Constantine"),
        ]
        for cl in sample_clients:
            c.execute("INSERT INTO clients (name, phone, email, address) VALUES (?,?,?,?)", cl)
        conn.commit()
    conn.close()

# ------------------------- FONCTIONS VIN -------------------------
def decode_vin_local(vin):
    # Mapping simplifié : extraire les 3 premiers caractères (WMI)
    if not vin or len(vin) < 3:
        return None
    prefix = vin[:3].upper()
    mapping = {
        "VF1": ("Renault", "Clio", 2010, 2018),
        "VF3": ("Peugeot", "208", 2012, 2020),
        "VF7": ("Citroën", "C3", 2009, 2016),
        "KMH": ("Hyundai", "i10", 2011, 2019),
        "KNA": ("Kia", "Picanto", 2011, 2021),
        "8AP": ("Chevrolet", "Spark", 2010, 2016),
        "JTD": ("Toyota", "Corolla", 2007, 2018),
    }
    if prefix in mapping:
        return mapping[prefix]
    return None

def decode_vin_api(vin):
    # Utilise l'API NHTSA vPIC (gratuite sans clé)
    try:
        url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{vin}?format=json"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        results = data.get("Results", [])
        make = None
        model = None
        year = None
        for item in results:
            if item["Variable"] == "Make":
                make = item["Value"]
            elif item["Variable"] == "Model":
                model = item["Value"]
            elif item["Variable"] == "Model Year":
                year = item["Value"]
        if make and model and year:
            return (make, model, int(year), int(year))
        return None
    except:
        return None

def decode_vin(vin):
    if VIN_MODE == "local":
        return decode_vin_local(vin)
    else:
        return decode_vin_api(vin)

# ------------------------- FONCTIONS CRUD PIECES -------------------------
def get_parts(filters=None):
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT * FROM parts"
    params = []
    if filters:
        conditions = []
        if filters.get("make"):
            conditions.append("make=?")
            params.append(filters["make"])
        if filters.get("category"):
            conditions.append("category=?")
            params.append(filters["category"])
        if filters.get("search"):
            conditions.append("(part_name LIKE ? OR part_number LIKE ?)")
            params.append(f"%{filters['search']}%")
            params.append(f"%{filters['search']}%")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def add_part(make, model, year_start, year_end, part_name, part_number, price, stock, image_file, category):
    # Sauvegarde de l'image
    if image_file is not None:
        ext = image_file.name.split('.')[-1]
        filename = f"{part_number}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
        filepath = os.path.join(IMAGES_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(image_file.getbuffer())
        image_path = filepath
    else:
        image_path = DEFAULT_IMAGE
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('''INSERT INTO parts (make, model, year_start, year_end, part_name, part_number, price, stock, image_path, category)
                     VALUES (?,?,?,?,?,?,?,?,?,?)''',
                  (make, model, year_start, year_end, part_name, part_number, price, stock, image_path, category))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_part(part_id, make, model, year_start, year_end, part_name, part_number, price, stock, image_file, category):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Récupérer ancienne image pour la supprimer si nécessaire
    if image_file is not None:
        c.execute("SELECT image_path FROM parts WHERE id=?", (part_id,))
        old_image = c.fetchone()[0]
        if old_image and old_image != DEFAULT_IMAGE and os.path.exists(old_image):
            os.remove(old_image)
        ext = image_file.name.split('.')[-1]
        filename = f"{part_number}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
        filepath = os.path.join(IMAGES_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(image_file.getbuffer())
        image_path = filepath
    else:
        c.execute("SELECT image_path FROM parts WHERE id=?", (part_id,))
        image_path = c.fetchone()[0]
    c.execute('''UPDATE parts SET make=?, model=?, year_start=?, year_end=?, part_name=?, part_number=?, price=?, stock=?, image_path=?, category=?
                 WHERE id=?''',
              (make, model, year_start, year_end, part_name, part_number, price, stock, image_path, category, part_id))
    conn.commit()
    conn.close()

def delete_part(part_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT image_path FROM parts WHERE id=?", (part_id,))
    image_path = c.fetchone()[0]
    if image_path and image_path != DEFAULT_IMAGE and os.path.exists(image_path):
        os.remove(image_path)
    c.execute("DELETE FROM parts WHERE id=?", (part_id,))
    conn.commit()
    conn.close()

# ------------------------- FONCTIONS CLIENTS -------------------------
def get_clients():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM clients ORDER BY name", conn)
    conn.close()
    return df

def add_client(name, phone, email, address):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO clients (name, phone, email, address) VALUES (?,?,?,?)", (name, phone, email, address))
    conn.commit()
    conn.close()

def update_client(client_id, name, phone, email, address):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE clients SET name=?, phone=?, email=?, address=? WHERE id=?", (name, phone, email, address, client_id))
    conn.commit()
    conn.close()

def delete_client(client_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Vérifier si des ventes associées
    c.execute("SELECT COUNT(*) FROM sales WHERE client_id=?", (client_id,))
    if c.fetchone()[0] > 0:
        conn.close()
        return False
    c.execute("DELETE FROM clients WHERE id=?", (client_id,))
    conn.commit()
    conn.close()
    return True

# ------------------------- FONCTIONS VENTES -------------------------
def create_sale(client_id, cart_items, payment_method):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        total = sum(item["total"] for item in cart_items)
        # Générer numéro facture unique
        invoice_number = f"FAC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{client_id}"
        c.execute('''INSERT INTO sales (client_id, total_amount, payment_method, invoice_number)
                     VALUES (?,?,?,?)''', (client_id, total, payment_method, invoice_number))
        sale_id = c.lastrowid
        # Insérer lignes et mettre à jour stock
        for item in cart_items:
            c.execute('''INSERT INTO sale_items (sale_id, part_id, quantity, unit_price, total)
                         VALUES (?,?,?,?,?)''', (sale_id, item["part_id"], item["quantity"], item["unit_price"], item["total"]))
            c.execute("UPDATE parts SET stock = stock - ? WHERE id=?", (item["quantity"], item["part_id"]))
        # Enregistrer transaction de recette
        c.execute('''INSERT INTO transactions (type, category, amount, description, reference)
                     VALUES (?,?,?,?,?)''', ('income', 'vente', total, f'Vente facture {invoice_number}', invoice_number))
        conn.commit()
        return sale_id, invoice_number
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_sales():
    conn = sqlite3.connect(DB_PATH)
    query = '''SELECT s.id, s.invoice_number, c.name as client_name, s.sale_date, s.total_amount, s.payment_method
               FROM sales s LEFT JOIN clients c ON s.client_id = c.id ORDER BY s.sale_date DESC'''
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def get_sale_items(sale_id):
    conn = sqlite3.connect(DB_PATH)
    query = '''SELECT si.quantity, si.unit_price, si.total, p.part_name, p.part_number
               FROM sale_items si JOIN parts p ON si.part_id = p.id
               WHERE si.sale_id = ?'''
    df = pd.read_sql_query(query, conn, params=(sale_id,))
    conn.close()
    return df

def generate_invoice_pdf(sale_id, invoice_number):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Infos vente
    c.execute('''SELECT s.sale_date, s.total_amount, s.payment_method, c.name, c.address, c.phone
                 FROM sales s LEFT JOIN clients c ON s.client_id = c.id WHERE s.id = ?''', (sale_id,))
    sale = c.fetchone()
    if not sale:
        return None
    sale_date, total, payment, client_name, client_address, client_phone = sale
    # Lignes
    items = get_sale_items(sale_id)
    # Création PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "FACTURE", ln=1, align='C')
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 6, f"Numéro : {invoice_number}", ln=1)
    pdf.cell(0, 6, f"Date : {sale_date}", ln=1)
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Client", ln=1)
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 6, f"Nom : {client_name or 'Client divers'}", ln=1)
    if client_address:
        pdf.cell(0, 6, f"Adresse : {client_address}", ln=1)
    if client_phone:
        pdf.cell(0, 6, f"Tél : {client_phone}", ln=1)
    pdf.ln(5)
    # Tableau des articles
    pdf.set_font("Arial", "B", 10)
    pdf.cell(80, 8, "Désignation", 1)
    pdf.cell(30, 8, "Réf.", 1)
    pdf.cell(20, 8, "Qté", 1)
    pdf.cell(30, 8, "P.U. (DA)", 1)
    pdf.cell(30, 8, "Total (DA)", 1)
    pdf.ln()
    pdf.set_font("Arial", "", 10)
    for _, row in items.iterrows():
        pdf.cell(80, 8, row["part_name"], 1)
        pdf.cell(30, 8, row["part_number"], 1)
        pdf.cell(20, 8, str(row["quantity"]), 1)
        pdf.cell(30, 8, f"{row['unit_price']:.2f}", 1)
        pdf.cell(30, 8, f"{row['total']:.2f}", 1)
        pdf.ln()
    pdf.cell(160, 8, "TOTAL", 1)
    pdf.cell(30, 8, f"{total:.2f} DA", 1)
    pdf.ln(10)
    pdf.cell(0, 6, f"Mode de paiement : {payment}", ln=1)
    pdf.cell(0, 6, "Merci de votre achat !", ln=1)
    # Sauvegarde
    filepath = os.path.join(INVOICES_DIR, f"facture_{invoice_number}.pdf")
    pdf.output(filepath)
    return filepath

# ------------------------- FONCTIONS BONS DE COMMANDE -------------------------
def create_purchase_order(supplier_name, items, delivery_date):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total = sum(item["total"] for item in items)
    c.execute('''INSERT INTO purchase_orders (supplier_name, delivery_date, total_amount, status)
                 VALUES (?,?,?,?)''', (supplier_name, delivery_date, total, 'pending'))
    order_id = c.lastrowid
    for item in items:
        c.execute('''INSERT INTO order_items (order_id, part_id, quantity, unit_price, total)
                     VALUES (?,?,?,?,?)''', (order_id, item["part_id"], item["quantity"], item["unit_price"], item["total"]))
    conn.commit()
    conn.close()
    return order_id

def receive_purchase_order(order_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT status FROM purchase_orders WHERE id=?", (order_id,))
    status = c.fetchone()[0]
    if status != 'pending':
        conn.close()
        return False
    # Mettre à jour stock
    c.execute("SELECT part_id, quantity FROM order_items WHERE order_id=?", (order_id,))
    items = c.fetchall()
    for part_id, qty in items:
        c.execute("UPDATE parts SET stock = stock + ? WHERE id=?", (qty, part_id))
    c.execute("UPDATE purchase_orders SET status='received' WHERE id=?", (order_id,))
    # Enregistrer dépense (optionnel, mais recommandé)
    c.execute("SELECT supplier_name, total_amount FROM purchase_orders WHERE id=?", (order_id,))
    supp, total = c.fetchone()
    c.execute('''INSERT INTO transactions (type, category, amount, description, reference)
                 VALUES (?,?,?,?,?)''', ('expense', 'achat', total, f'Achat fournisseur {supp}', f'PO-{order_id}'))
    conn.commit()
    conn.close()
    return True

def get_purchase_orders():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM purchase_orders ORDER BY order_date DESC", conn)
    conn.close()
    return df

def get_order_items(order_id):
    conn = sqlite3.connect(DB_PATH)
    query = '''SELECT oi.quantity, oi.unit_price, oi.total, p.part_name, p.part_number
               FROM order_items oi JOIN parts p ON oi.part_id = p.id
               WHERE oi.order_id = ?'''
    df = pd.read_sql_query(query, conn, params=(order_id,))
    conn.close()
    return df

# ------------------------- FONCTIONS DÉPENSES -------------------------
def add_expense(category, amount, description):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO transactions (type, category, amount, description)
                 VALUES (?,?,?,?)''', ('expense', category, amount, description))
    conn.commit()
    conn.close()

def get_transactions():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM transactions ORDER BY date DESC", conn)
    conn.close()
    return df

# ------------------------- FONCTIONS TABLEAU DE BORD -------------------------
def get_financial_summary():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income'")
    total_income = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense'")
    total_expense = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(price*stock),0) FROM parts")
    stock_value = c.fetchone()[0]
    conn.close()
    return total_income, total_expense, total_income - total_expense, stock_value

def get_stock_alerts():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM parts WHERE stock <= ?", conn, params=(STOCK_THRESHOLD,))
    conn.close()
    return df

# ------------------------- FONCTIONS IMPORT/EXPORT -------------------------
def import_parts_csv(file):
    df = pd.read_csv(file)
    conn = sqlite3.connect(DB_PATH)
    df.to_sql("parts", conn, if_exists="append", index=False)
    conn.close()

def export_parts_csv():
    df = get_parts()
    return df.to_csv(index=False).encode('utf-8')

# ------------------------- INTERFACE STREAMLIT -------------------------
st.set_page_config(page_title="Gestion Magasin Pièces Auto", layout="wide")
st.title("🚗 Gestion Magasin Pièces Détachées Auto")

# Initialisation DB
init_db()
load_initial_data()

# Barre latérale
st.sidebar.image("https://via.placeholder.com/150x100?text=Logo", use_container_width=True)
st.sidebar.title("Navigation")
menu = st.sidebar.radio("Menu", ["Catalogue", "Ventes", "Bons de commande", "Dépenses", "Clients", "Tableau de bord", "Import/Export"])

# Recherche VIN dans la sidebar
st.sidebar.markdown("---")
vin_input = st.sidebar.text_input("🔍 Recherche par numéro VIN (châssis)", max_chars=17)
if vin_input:
    vin_info = decode_vin(vin_input.upper())
    if vin_info:
        make, model, year_start, year_end = vin_info
        st.sidebar.success(f"Véhicule identifié : {make} {model} ({year_start}-{year_end})")
        # Filtre catalogue pour ce véhicule
        st.session_state.vin_filter = {"make": make, "model": model, "year": year_start}
    else:
        st.sidebar.error("VIN non reconnu")

# ------------------------- CATALOGUE -------------------------
if menu == "Catalogue":
    st.header("📦 Catalogue des pièces")
    col1, col2 = st.columns([1, 3])
    with col1:
        # Filtres
        makes = ["Toutes"] + list(pd.read_sql_query("SELECT DISTINCT make FROM parts WHERE make IS NOT NULL", sqlite3.connect(DB_PATH))["make"])
        selected_make = st.selectbox("Marque", makes)
        categories = ["Toutes"] + list(pd.read_sql_query("SELECT DISTINCT category FROM parts WHERE category IS NOT NULL", sqlite3.connect(DB_PATH))["category"])
        selected_cat = st.selectbox("Catégorie", categories)
        search = st.text_input("Recherche (nom/réf)")
        # Appliquer filtres
        filters = {}
        if selected_make != "Toutes":
            filters["make"] = selected_make
        if selected_cat != "Toutes":
            filters["category"] = selected_cat
        if search:
            filters["search"] = search
        # Si filtre VIN actif
        if "vin_filter" in st.session_state:
            vin_make = st.session_state.vin_filter.get("make")
            if vin_make and (selected_make == "Toutes" or selected_make == vin_make):
                filters["make"] = vin_make
        parts_df = get_parts(filters)
    with col2:
        # Affichage en grille
        if parts_df.empty:
            st.info("Aucune pièce trouvée.")
        else:
            cols = st.columns(3)
            for idx, row in parts_df.iterrows():
                with cols[idx % 3]:
                    # Image
                    if os.path.exists(row["image_path"]):
                        img = Image.open(row["image_path"])
                        st.image(img, width=150)
                    else:
                        st.image(DEFAULT_IMAGE, width=150)
                    st.subheader(row["part_name"])
                    st.write(f"**Réf**: {row['part_number']}")
                    st.write(f"**Marque**: {row['make']} {row['model'] or ''}")
                    st.write(f"**Prix**: {row['price']:.2f} DA")
                    st.write(f"**Stock**: {row['stock']}")
                    if row["stock"] <= STOCK_THRESHOLD:
                        st.warning("⚠️ Stock bas")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button(f"➕ Panier", key=f"add_{row['id']}"):
                            if "cart" not in st.session_state:
                                st.session_state.cart = []
                            st.session_state.cart.append({
                                "part_id": row["id"],
                                "part_name": row["part_name"],
                                "part_number": row["part_number"],
                                "quantity": 1,
                                "unit_price": row["price"],
                                "total": row["price"]
                            })
                            st.success("Ajouté au panier")
                    with col_b:
                        if st.button(f"✏️ Modifier", key=f"edit_{row['id']}"):
                            st.session_state.edit_part = row.to_dict()
                    if st.button(f"🗑️ Supprimer", key=f"del_{row['id']}"):
                        delete_part(row["id"])
                        st.rerun()
    # Gestion des pièces (ajout/modif)
    with st.expander("➕ Ajouter une pièce"):
        with st.form("add_part_form"):
            make = st.text_input("Marque")
            model = st.text_input("Modèle")
            year_start = st.number_input("Année début", min_value=1900, max_value=2030, step=1)
            year_end = st.number_input("Année fin", min_value=1900, max_value=2030, step=1)
            part_name = st.text_input("Nom de la pièce")
            part_number = st.text_input("Référence")
            price = st.number_input("Prix (DA)", min_value=0.0, step=100.0)
            stock = st.number_input("Stock", min_value=0, step=1)
            category = st.text_input("Catégorie")
            image_file = st.file_uploader("Image", type=["jpg", "jpeg", "png"])
            submitted = st.form_submit_button("Ajouter")
            if submitted:
                if part_name and part_number:
                    ok = add_part(make, model, year_start, year_end, part_name, part_number, price, stock, image_file, category)
                    if ok:
                        st.success("Pièce ajoutée")
                        st.rerun()
                    else:
                        st.error("Référence déjà existante")
                else:
                    st.error("Nom et référence requis")
    # Modification
    if "edit_part" in st.session_state:
        part = st.session_state.edit_part
        with st.expander("✏️ Modifier la pièce", expanded=True):
            with st.form("edit_part_form"):
                make = st.text_input("Marque", value=part["make"] or "")
                model = st.text_input("Modèle", value=part["model"] or "")
                year_start = st.number_input("Année début", min_value=1900, max_value=2030, step=1, value=part["year_start"] or 2000)
                year_end = st.number_input("Année fin", min_value=1900, max_value=2030, step=1, value=part["year_end"] or 2000)
                part_name = st.text_input("Nom de la pièce", value=part["part_name"])
                part_number = st.text_input("Référence", value=part["part_number"])
                price = st.number_input("Prix (DA)", min_value=0.0, step=100.0, value=part["price"])
                stock = st.number_input("Stock", min_value=0, step=1, value=part["stock"])
                category = st.text_input("Catégorie", value=part["category"] or "")
                image_file = st.file_uploader("Nouvelle image (laisser vide pour garder actuelle)", type=["jpg", "jpeg", "png"])
                submitted = st.form_submit_button("Mettre à jour")
                if submitted:
                    update_part(part["id"], make, model, year_start, year_end, part_name, part_number, price, stock, image_file, category)
                    del st.session_state.edit_part
                    st.success("Pièce modifiée")
                    st.rerun()
            if st.button("Annuler"):
                del st.session_state.edit_part
                st.rerun()

# ------------------------- VENTES -------------------------
elif menu == "Ventes":
    st.header("🛒 Ventes et facturation")
    # Initialiser panier
    if "cart" not in st.session_state:
        st.session_state.cart = []
    # Afficher panier
    st.subheader("Panier")
    if st.session_state.cart:
        cart_df = pd.DataFrame(st.session_state.cart)
        st.table(cart_df[["part_name", "part_number", "quantity", "unit_price", "total"]])
        total_cart = cart_df["total"].sum()
        st.write(f"**Total panier : {total_cart:.2f} DA**")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Vider le panier"):
                st.session_state.cart = []
                st.rerun()
        with col2:
            # Sélection client
            clients = get_clients()
            client_options = {row["name"]: row["id"] for _, row in clients.iterrows()}
            client_names = ["Client divers"] + list(client_options.keys())
            selected_client_name = st.selectbox("Client", client_names)
            payment = st.selectbox("Mode de paiement", ["Espèces", "Carte bancaire", "Virement"])
            if st.button("Valider la vente"):
                client_id = client_options.get(selected_client_name) if selected_client_name != "Client divers" else None
                try:
                    sale_id, invoice_number = create_sale(client_id, st.session_state.cart, payment)
                    # Générer PDF
                    pdf_path = generate_invoice_pdf(sale_id, invoice_number)
                    st.success(f"Vente enregistrée. Facture : {invoice_number}")
                    with open(pdf_path, "rb") as f:
                        st.download_button("Télécharger la facture PDF", f, file_name=f"facture_{invoice_number}.pdf")
                    st.session_state.cart = []
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur : {e}")
    else:
        st.info("Panier vide. Ajoutez des pièces depuis le catalogue.")

    # Historique des ventes
    with st.expander("Historique des ventes"):
        sales_df = get_sales()
        st.dataframe(sales_df)
        sale_id_to_view = st.number_input("ID de vente pour voir détails", min_value=1, step=1)
        if sale_id_to_view:
            items = get_sale_items(sale_id_to_view)
            st.dataframe(items)

# ------------------------- BONS DE COMMANDE -------------------------
elif menu == "Bons de commande":
    st.header("📦 Bons de commande fournisseurs")
    tab1, tab2 = st.tabs(["Créer bon", "Liste des bons"])
    with tab1:
        with st.form("create_po"):
            supplier = st.text_input("Nom du fournisseur")
            delivery_date = st.date_input("Date de livraison prévue")
            st.write("Ajouter des articles")
            # Sélectionner pièces
            parts_df = get_parts()
            part_choices = {f"{row['part_name']} ({row['part_number']})": row["id"] for _, row in parts_df.iterrows()}
            selected_parts = st.multiselect("Pièces", list(part_choices.keys()))
            po_items = []
            if selected_parts:
                for sel in selected_parts:
                    part_id = part_choices[sel]
                    row = parts_df[parts_df["id"] == part_id].iloc[0]
                    qty = st.number_input(f"Quantité pour {sel}", min_value=1, step=1, key=f"qty_{part_id}")
                    unit_price = st.number_input(f"Prix unitaire (DA)", min_value=0.0, step=100.0, value=row["price"], key=f"price_{part_id}")
                    total = qty * unit_price
                    po_items.append({"part_id": part_id, "quantity": qty, "unit_price": unit_price, "total": total})
            submitted = st.form_submit_button("Créer bon")
            if submitted and supplier and po_items:
                order_id = create_purchase_order(supplier, po_items, delivery_date)
                st.success(f"Bon de commande n°{order_id} créé")
                st.rerun()
    with tab2:
        orders_df = get_purchase_orders()
        st.dataframe(orders_df)
        po_id = st.number_input("ID bon de commande", min_value=1, step=1)
        if st.button("Afficher détails"):
            items = get_order_items(po_id)
            st.dataframe(items)
        if st.button("Marquer comme reçu"):
            if receive_purchase_order(po_id):
                st.success("Bon reçu, stock mis à jour")
                st.rerun()
            else:
                st.error("Impossible de recevoir ce bon (déjà reçu ou annulé)")

# ------------------------- DÉPENSES -------------------------
elif menu == "Dépenses":
    st.header("💰 Gestion des dépenses")
    with st.form("add_expense"):
        cat = st.selectbox("Catégorie", ["Achat fournisseur", "Loyer", "Électricité", "Eau", "Salaires", "Autre"])
        amount = st.number_input("Montant (DA)", min_value=0.0, step=1000.0)
        desc = st.text_area("Description")
        if st.form_submit_button("Ajouter dépense"):
            add_expense(cat, amount, desc)
            st.success("Dépense ajoutée")
            st.rerun()
    st.subheader("Historique des transactions")
    trans_df = get_transactions()
    st.dataframe(trans_df)

# ------------------------- CLIENTS -------------------------
elif menu == "Clients":
    st.header("👥 Gestion des clients")
    clients_df = get_clients()
    st.dataframe(clients_df)
    with st.expander("➕ Ajouter client"):
        with st.form("add_client"):
            name = st.text_input("Nom")
            phone = st.text_input("Téléphone")
            email = st.text_input("Email")
            address = st.text_input("Adresse")
            if st.form_submit_button("Ajouter"):
                if name:
                    add_client(name, phone, email, address)
                    st.success("Client ajouté")
                    st.rerun()
                else:
                    st.error("Nom requis")
    # Modification / suppression à implémenter simplement
    client_id_edit = st.number_input("ID client à modifier/supprimer", min_value=1, step=1)
    if client_id_edit:
        client = clients_df[clients_df["id"] == client_id_edit]
        if not client.empty:
            client = client.iloc[0]
            with st.form("edit_client"):
                name = st.text_input("Nom", value=client["name"])
                phone = st.text_input("Téléphone", value=client["phone"] or "")
                email = st.text_input("Email", value=client["email"] or "")
                address = st.text_input("Adresse", value=client["address"] or "")
                if st.form_submit_button("Modifier"):
                    update_client(client_id_edit, name, phone, email, address)
                    st.success("Client modifié")
                    st.rerun()
            if st.button("Supprimer client"):
                if delete_client(client_id_edit):
                    st.success("Client supprimé")
                    st.rerun()
                else:
                    st.error("Impossible de supprimer : client a des ventes")

# ------------------------- TABLEAU DE BORD -------------------------
elif menu == "Tableau de bord":
    st.header("📊 Tableau de bord")
    total_income, total_expense, balance, stock_value = get_financial_summary()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Chiffre d'affaires", f"{total_income:,.0f} DA")
    col2.metric("Dépenses", f"{total_expense:,.0f} DA")
    col3.metric("Bénéfice net", f"{balance:,.0f} DA")
    col4.metric("Valeur du stock", f"{stock_value:,.0f} DA")
    st.subheader("Alertes stock bas")
    alerts = get_stock_alerts()
    if alerts.empty:
        st.success("Aucun stock bas")
    else:
        st.dataframe(alerts[["part_name", "part_number", "stock"]])
    # Graphique ventes mensuelles (simplifié)
    sales_df = get_sales()
    if not sales_df.empty:
        sales_df["sale_date"] = pd.to_datetime(sales_df["sale_date"])
        sales_df["month"] = sales_df["sale_date"].dt.to_period("M")
        monthly = sales_df.groupby("month")["total_amount"].sum().reset_index()
        monthly["month"] = monthly["month"].astype(str)
        fig, ax = plt.subplots()
        ax.bar(monthly["month"], monthly["total_amount"])
        ax.set_xlabel("Mois")
        ax.set_ylabel("CA (DA)")
        ax.set_title("Chiffre d'affaires mensuel")
        st.pyplot(fig)

# ------------------------- IMPORT/EXPORT -------------------------
elif menu == "Import/Export":
    st.header("📁 Import/Export de données")
    uploaded_file = st.file_uploader("Importer catalogue (CSV)", type=["csv"])
    if uploaded_file:
        import_parts_csv(uploaded_file)
        st.success("Catalogue importé")
        st.rerun()
    if st.button("Exporter catalogue (CSV)"):
        csv = export_parts_csv()
        st.download_button("Télécharger", csv, "catalogue_pieces.csv", "text/csv")
