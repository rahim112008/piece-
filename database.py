"""
database.py - Connexion SQLite et création des tables
"""
import sqlite3
import pandas as pd
import os
from config import DB_PATH, INITIAL_PARTS_CSV, VIN_MAPPING_CSV


def get_connection():
    """Retourne une connexion SQLite avec row_factory."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Crée toutes les tables et charge les données initiales."""
    conn = get_connection()
    c = conn.cursor()

    # --- Table pièces ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS parts (
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
        )
    """)

    # --- Table clients ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- Table ventes ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_amount REAL NOT NULL,
            payment_method TEXT DEFAULT 'cash',
            status TEXT DEFAULT 'paid',
            invoice_number TEXT,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )
    """)

    # --- Table lignes de vente ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            part_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            total REAL NOT NULL,
            FOREIGN KEY (sale_id) REFERENCES sales(id),
            FOREIGN KEY (part_id) REFERENCES parts(id)
        )
    """)

    # --- Table transactions (recettes/dépenses) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            type TEXT CHECK(type IN ('income', 'expense')),
            category TEXT,
            amount REAL NOT NULL,
            description TEXT,
            reference TEXT
        )
    """)

    # --- Table bons de commande ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_name TEXT NOT NULL,
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            delivery_date DATE,
            total_amount REAL NOT NULL DEFAULT 0,
            status TEXT DEFAULT 'pending'
        )
    """)

    # --- Table lignes de bon de commande ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            part_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            total REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES purchase_orders(id),
            FOREIGN KEY (part_id) REFERENCES parts(id)
        )
    """)

    # --- Table compteur factures ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS invoice_counter (
            id INTEGER PRIMARY KEY,
            last_number INTEGER DEFAULT 0
        )
    """)
    c.execute("INSERT OR IGNORE INTO invoice_counter (id, last_number) VALUES (1, 0)")

    conn.commit()

    # Charger données initiales si les tables sont vides
    _load_initial_data(conn)
    conn.close()


def _load_initial_data(conn):
    """Charge les données initiales depuis CSV si les tables sont vides."""
    c = conn.cursor()

    # Pièces
    c.execute("SELECT COUNT(*) FROM parts")
    if c.fetchone()[0] == 0 and os.path.exists(INITIAL_PARTS_CSV):
        df = pd.read_csv(INITIAL_PARTS_CSV)
        df.to_sql("parts", conn, if_exists="append", index=False)
        print(f"[DB] {len(df)} pièces chargées depuis {INITIAL_PARTS_CSV}")

    # Clients factices
    c.execute("SELECT COUNT(*) FROM clients")
    if c.fetchone()[0] == 0:
        clients = [
            ("Ahmed Benali", "0555 12 34 56", "ahmed.benali@gmail.com", "Rue Larbi Ben M'hidi, Tlemcen"),
            ("Fatima Bouderbala", "0661 98 76 54", "fatima.b@outlook.com", "Cité Kawkab, Oran"),
            ("Karim Mansouri", "0770 45 67 89", "", "Boulevard Zighout Youcef, Alger"),
        ]
        c.executemany(
            "INSERT INTO clients (name, phone, email, address) VALUES (?,?,?,?)",
            clients
        )
        conn.commit()
        print("[DB] 3 clients factices créés.")


def get_next_invoice_number(conn):
    """Génère et retourne le prochain numéro de facture."""
    c = conn.cursor()
    c.execute("UPDATE invoice_counter SET last_number = last_number + 1 WHERE id = 1")
    conn.commit()
    c.execute("SELECT last_number FROM invoice_counter WHERE id = 1")
    return c.fetchone()[0]
