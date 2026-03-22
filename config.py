"""
config.py - Configuration globale de l'application
"""
import os

# --- Chemins ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(BASE_DIR, "database.db")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
INVOICES_DIR = os.path.join(DATA_DIR, "invoices")
INITIAL_PARTS_CSV = os.path.join(DATA_DIR, "initial_parts.csv")
VIN_MAPPING_CSV = os.path.join(DATA_DIR, "vin_mapping.csv")
LOGO_PATH = os.path.join(DATA_DIR, "logo.png")

# --- Stock ---
STOCK_THRESHOLD = 5  # Seuil d'alerte stock bas

# --- VIN ---
# "local" : décodage depuis vin_mapping.csv
# "api"   : décodage via API NHTSA
# "both"  : essaie local, puis API si pas trouvé
VIN_MODE = "both"
NHTSA_API_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{vin}?format=json"

# --- Magasin ---
SHOP_NAME = "Auto Pièces Maghreb"
SHOP_ADDRESS = "Rue des Zianides, Tlemcen 13000, Algérie"
SHOP_PHONE = "+213 43 00 00 00"
SHOP_EMAIL = "contact@autopiecesmaghreb.dz"

# --- TVA ---
TVA_RATE = 0.19  # 19% en Algérie (optionnel)
APPLY_TVA = False  # Mettre True pour activer la TVA

# --- Devise ---
CURRENCY = "DA"  # Dinar Algérien

# --- PDF ---
INVOICE_PREFIX = "FAC"

# Créer les dossiers si nécessaires
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(INVOICES_DIR, exist_ok=True)
