"""
settings.py - Page de paramètres et configuration de l'application
"""
import streamlit as st
import os
import sqlite3
from database import get_connection, init_db
from utils import save_uploaded_image, format_price
from config import (DB_PATH, IMAGES_DIR, INVOICES_DIR,
                    SHOP_NAME, STOCK_THRESHOLD, CURRENCY)


def show_settings():
    st.header("⚙️ Paramètres")

    tabs = st.tabs([
        "🏪 Informations du magasin",
        "🗄️ Base de données",
        "🔔 Seuils et alertes",
        "ℹ️ À propos",
    ])

    with tabs[0]:
        _show_shop_settings()
    with tabs[1]:
        _show_db_settings()
    with tabs[2]:
        _show_thresholds()
    with tabs[3]:
        _show_about()


def _show_shop_settings():
    st.subheader("Informations du magasin")
    st.info(
        "Ces informations apparaissent sur vos factures PDF. "
        "Modifiez le fichier `src/config.py` pour les changer définitivement."
    )

    # Afficher la config actuelle
    import config as cfg
    col1, col2 = st.columns(2)
    col1.text_input("Nom du magasin", value=cfg.SHOP_NAME, disabled=True)
    col2.text_input("Adresse", value=cfg.SHOP_ADDRESS, disabled=True)
    col1.text_input("Téléphone", value=cfg.SHOP_PHONE, disabled=True)
    col2.text_input("Email", value=cfg.SHOP_EMAIL, disabled=True)
    col1.text_input("Devise", value=cfg.CURRENCY, disabled=True)
    col2.text_input("Mode VIN", value=cfg.VIN_MODE, disabled=True)

    # Upload logo
    st.markdown("#### Logo du magasin")
    logo_path = cfg.LOGO_PATH
    if os.path.exists(logo_path):
        st.image(logo_path, width=200, caption="Logo actuel")
    else:
        st.warning("⚠️ Aucun logo défini. Uploadez un fichier `logo.png` ci-dessous.")

    new_logo = st.file_uploader("Changer le logo (PNG/JPG, 300×100 recommandé)",
                                 type=["png", "jpg", "jpeg"], key="logo_upload")
    if new_logo:
        from PIL import Image
        img = Image.open(new_logo)
        img.save(logo_path)
        st.success("✅ Logo mis à jour !")
        st.rerun()


def _show_db_settings():
    st.subheader("Base de données")

    # Statistiques DB
    conn = get_connection()
    c = conn.cursor()
    stats = {}
    for table in ["parts", "clients", "sales", "sale_items",
                   "transactions", "purchase_orders", "order_items"]:
        c.execute(f"SELECT COUNT(*) FROM {table}")
        stats[table] = c.fetchone()[0]
    conn.close()

    st.markdown("**Contenu de la base :**")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📦 Pièces", stats["parts"])
    col2.metric("👥 Clients", stats["clients"])
    col3.metric("💳 Ventes", stats["sales"])
    col4.metric("💰 Transactions", stats["transactions"])

    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    st.caption(f"Fichier DB : `{DB_PATH}` — Taille : {db_size / 1024:.1f} Ko")

    st.markdown("---")

    # Sauvegarde
    st.markdown("**Sauvegarde de la base :**")
    if os.path.exists(DB_PATH):
        with open(DB_PATH, "rb") as f:
            st.download_button(
                "⬇️ Télécharger database.db",
                data=f.read(),
                file_name="database_backup.db",
                mime="application/octet-stream"
            )

    # Reinitialisation
    st.markdown("---")
    st.markdown("**⚠️ Zone dangereuse**")
    with st.expander("🔴 Réinitialiser / vider des tables"):
        st.warning("Ces actions sont irréversibles ! Sauvegardez d'abord.")
        table_to_clear = st.selectbox(
            "Table à vider",
            ["sales + sale_items + transactions liées",
             "purchase_orders + order_items",
             "transactions",
             "stock_movements"]
        )
        confirm = st.text_input("Tapez CONFIRMER pour valider", key="confirm_reset")
        if st.button("🗑️ Vider la table", key="reset_table"):
            if confirm != "CONFIRMER":
                st.error("Vous devez taper CONFIRMER.")
            else:
                conn = get_connection()
                try:
                    if "sales" in table_to_clear:
                        conn.execute("DELETE FROM sale_items")
                        conn.execute("DELETE FROM sales")
                        conn.execute("DELETE FROM transactions WHERE type='income' AND category='Vente'")
                    elif "purchase_orders" in table_to_clear:
                        conn.execute("DELETE FROM order_items")
                        conn.execute("DELETE FROM purchase_orders")
                    elif table_to_clear == "transactions":
                        conn.execute("DELETE FROM transactions")
                    elif table_to_clear == "stock_movements":
                        conn.execute("DELETE FROM stock_movements")
                    conn.commit()
                    conn.close()
                    st.success(f"✅ Table(s) vidée(s).")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur : {e}")


def _show_thresholds():
    st.subheader("Seuils et alertes")
    st.info("Modifiez `src/config.py` pour changer ces valeurs de façon permanente.")

    import config as cfg
    st.markdown(f"""
    | Paramètre | Valeur actuelle |
    |---|---|
    | Seuil stock bas | **{cfg.STOCK_THRESHOLD} unités** |
    | TVA | **{'Activée (' + str(int(cfg.TVA_RATE*100)) + '%)' if cfg.APPLY_TVA else 'Désactivée'}** |
    | Mode VIN | **{cfg.VIN_MODE}** |
    | Préfixe facture | **{cfg.INVOICE_PREFIX}** |
    """)

    st.markdown("---")
    st.markdown("**Dossiers de travail :**")
    st.code(f"""
Base de données : {DB_PATH}
Images pièces   : {IMAGES_DIR}
Factures PDF    : {INVOICES_DIR}
    """)

    # Compter les fichiers
    n_images = len([f for f in os.listdir(IMAGES_DIR)
                    if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))])
    n_invoices = len([f for f in os.listdir(INVOICES_DIR) if f.endswith(".pdf")])
    st.caption(f"Images : {n_images} | Factures PDF : {n_invoices}")


def _show_about():
    st.subheader("À propos de l'application")
    st.markdown("""
    ## 🔧 Auto Pièces Maghreb

    Application de gestion de magasin de pièces détachées automobiles,
    conçue pour le marché algérien.

    **Version :** 1.0.0

    **Fonctionnalités :**
    - 📦 Catalogue avec images et références
    - 🔑 Recherche par numéro de châssis (VIN)
    - 🗄️ Gestion de stock avec historique des mouvements
    - 💳 Ventes et facturation PDF
    - 📋 Bons de commande fournisseurs
    - 💰 Suivi des recettes et dépenses
    - 📊 Tableau de bord financier
    - 📁 Import/Export CSV et Excel

    **Marques supportées :** Renault, Peugeot, Citroën, Hyundai, Kia,
    Toyota, Chevrolet, Dacia, Volkswagen, Fiat, Nissan, BMW, Mercedes...

    **Technologies :**
    - Python 3.9+
    - Streamlit
    - SQLite
    - fpdf2 (PDF)
    - pandas, Pillow, openpyxl

    ---
    *Développé avec ❤️ pour la gestion automobile algérienne*
    """)
