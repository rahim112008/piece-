"""
app.py - Point d'entrée principal de l'application Auto Pièces
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

# ── Configuration page Streamlit ──
st.set_page_config(
    page_title="Auto Pièces Maghreb",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS personnalisé ──
st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #1a1a2e; }
    [data-testid="stSidebar"] * { color: #e0e0e0 !important; }
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stTextInput label { color: #aaa !important; }
    .main-header { color: #1a73e8; font-size: 1.5rem; font-weight: bold; }
    .metric-card { background: white; padding: 16px; border-radius: 10px;
                   box-shadow: 0 2px 8px rgba(0,0,0,.08); text-align: center; }
    div[data-testid="stMetricValue"] { font-size: 1.4rem !important; }
    .stButton > button[kind="primary"] {
        background-color: #1a73e8; color: white; border-radius: 8px;
    }
    .cart-badge { background: #e8f5e9; border-radius: 20px;
                  padding: 2px 10px; font-weight: bold; color: #2e7d32; }
</style>
""", unsafe_allow_html=True)

# ── Initialisation DB ──
from database import init_db
init_db()

# ── Modules ──
from catalogue import show_catalogue
from sales import show_sales
from purchase_orders import show_purchase_orders
from expenses import show_expenses
from clients import show_clients
from dashboard import show_dashboard
from import_export import show_import_export
from stock import show_stock
from settings import show_settings
from vin_decoder import decode_vin
from utils import validate_vin, format_price
from config import SHOP_NAME, STOCK_THRESHOLD


# ─────────────────────────────────────────────
#  BARRE LATÉRALE
# ─────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        # Logo / titre
        st.markdown(f"""
        <div style="text-align:center;padding:16px 0 8px">
            <div style="font-size:2.5rem">🔧</div>
            <div style="font-size:1.1rem;font-weight:700;color:#fff">{SHOP_NAME}</div>
            <div style="font-size:.75rem;color:#aaa">Gestion de magasin</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        # ── Recherche VIN ──
        st.markdown("### 🔑 Recherche par VIN")
        vin_input = st.text_input(
            "Numéro de châssis (17 car.)",
            max_chars=17,
            placeholder="Ex: VF1BB1B0H45123456",
            key="vin_input"
        )

        if vin_input:
            if not validate_vin(vin_input):
                st.warning("⚠️ VIN invalide (17 caractères, pas I/O/Q)")
            else:
                with st.spinner("Décodage..."):
                    result = decode_vin(vin_input)
                if result:
                    st.success(f"✅ **{result['make']} {result['model']}** ({result['year']})")
                    st.caption(f"Source : {result.get('source', '?')}")
                    if st.button("🔍 Filtrer le catalogue", key="vin_filter_btn"):
                        st.session_state["vin_filter"] = {
                            "vin_make": result["make"],
                            "vin_year": result.get("year"),
                        }
                        st.session_state["nav"] = "📦 Catalogue"
                        st.rerun()
                else:
                    st.error("Véhicule non reconnu.")
                    if st.button("🔍 Afficher tout le catalogue", key="vin_all"):
                        st.session_state.pop("vin_filter", None)
                        st.session_state["nav"] = "📦 Catalogue"
                        st.rerun()

        # Effacer filtre VIN
        if st.session_state.get("vin_filter"):
            if st.button("❌ Effacer le filtre VIN", key="clear_vin"):
                st.session_state.pop("vin_filter", None)
                st.rerun()

        st.markdown("---")

        # ── Panier rapide ──
        cart = st.session_state.get("cart", [])
        nb_cart = sum(i["quantity"] for i in cart)
        total_cart = sum(i["total"] for i in cart)
        if nb_cart > 0:
            st.markdown(
                f'🛒 **Panier** : <span class="cart-badge">{nb_cart} article(s)</span><br>'
                f'<small>Total : {format_price(total_cart)}</small>',
                unsafe_allow_html=True
            )
            if st.button("➡️ Aller aux ventes", key="goto_sales_btn"):
                st.session_state["nav"] = "💳 Ventes"
                st.rerun()
            st.markdown("---")

        # ── Navigation ──
        st.markdown("### 🗂️ Navigation")
        pages = [
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
        if "nav" not in st.session_state:
            st.session_state["nav"] = "📊 Tableau de bord"

        for page in pages:
            active = st.session_state["nav"] == page
            style = "font-weight:bold;color:#1a73e8;" if active else ""
            if st.button(
                page,
                key=f"nav_{page}",
                use_container_width=True,
                type="primary" if active else "secondary"
            ):
                st.session_state["nav"] = page
                st.rerun()


# ─────────────────────────────────────────────
#  CONTENU PRINCIPAL
# ─────────────────────────────────────────────

def main():
    render_sidebar()

    page = st.session_state.get("nav", "📊 Tableau de bord")

    if page == "📊 Tableau de bord":
        show_dashboard()
    elif page == "📦 Catalogue":
        show_catalogue()
    elif page == "🗄️ Stock":
        show_stock()
    elif page == "💳 Ventes":
        show_sales()
    elif page == "📋 Bons de commande":
        show_purchase_orders()
    elif page == "💰 Dépenses":
        show_expenses()
    elif page == "👥 Clients":
        show_clients()
    elif page == "📁 Import / Export":
        show_import_export()
    elif page == "⚙️ Paramètres":
        show_settings()
    else:
        st.error("Page introuvable.")


if __name__ == "__main__":
    main()
