"""
catalogue.py - Affichage et gestion du catalogue de pièces
"""
import streamlit as st
import pandas as pd
from database import get_connection
from utils import (format_price, save_uploaded_image, get_part_image_html,
                   get_categories, get_makes, validate_vin)
from config import STOCK_THRESHOLD


# ─────────────────────────────────────────────
#  LECTURE
# ─────────────────────────────────────────────

def get_all_parts(filters: dict = None) -> pd.DataFrame:
    """Retourne les pièces avec filtres optionnels."""
    conn = get_connection()
    query = "SELECT * FROM parts WHERE 1=1"
    params = []

    if filters:
        if filters.get("make"):
            query += " AND make = ?"
            params.append(filters["make"])
        if filters.get("model"):
            query += " AND model LIKE ?"
            params.append(f"%{filters['model']}%")
        if filters.get("category"):
            query += " AND category = ?"
            params.append(filters["category"])
        if filters.get("search"):
            query += " AND (part_name LIKE ? OR part_number LIKE ?)"
            params.extend([f"%{filters['search']}%", f"%{filters['search']}%"])
        if filters.get("year"):
            query += " AND (year_start <= ? AND year_end >= ?)"
            params.extend([filters["year"], filters["year"]])
        if filters.get("min_price") is not None:
            query += " AND price >= ?"
            params.append(filters["min_price"])
        if filters.get("max_price") is not None:
            query += " AND price <= ?"
            params.append(filters["max_price"])
        if filters.get("low_stock"):
            query += f" AND stock <= {STOCK_THRESHOLD}"
        if filters.get("vin_make"):
            query += " AND make = ?"
            params.append(filters["vin_make"])
        if filters.get("vin_model"):
            query += " AND model LIKE ?"
            params.append(f"%{filters['vin_model']}%")
        if filters.get("vin_year"):
            query += " AND (year_start <= ? AND year_end >= ?)"
            params.extend([filters["vin_year"], filters["vin_year"]])

    query += " ORDER BY make, model, part_name"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_part_by_id(part_id: int) -> dict | None:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM parts WHERE id = ?", (part_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


# ─────────────────────────────────────────────
#  CRUD
# ─────────────────────────────────────────────

def add_part(data: dict) -> bool:
    try:
        conn = get_connection()
        conn.execute("""
            INSERT INTO parts (make, model, year_start, year_end, part_name,
                               part_number, price, stock, image_path, category)
            VALUES (:make, :model, :year_start, :year_end, :part_name,
                    :part_number, :price, :stock, :image_path, :category)
        """, data)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erreur ajout pièce : {e}")
        return False


def update_part(part_id: int, data: dict) -> bool:
    try:
        conn = get_connection()
        conn.execute("""
            UPDATE parts SET make=:make, model=:model, year_start=:year_start,
            year_end=:year_end, part_name=:part_name, part_number=:part_number,
            price=:price, stock=:stock, image_path=:image_path, category=:category
            WHERE id=:id
        """, {**data, "id": part_id})
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erreur modification pièce : {e}")
        return False


def delete_part(part_id: int) -> bool:
    try:
        conn = get_connection()
        conn.execute("DELETE FROM parts WHERE id = ?", (part_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erreur suppression pièce : {e}")
        return False


def update_stock(part_id: int, delta: int, conn=None):
    """Incrémente (delta>0) ou décrémente (delta<0) le stock."""
    close = conn is None
    if close:
        conn = get_connection()
    conn.execute("UPDATE parts SET stock = stock + ? WHERE id = ?", (delta, part_id))
    if close:
        conn.commit()
        conn.close()


# ─────────────────────────────────────────────
#  UI
# ─────────────────────────────────────────────

def show_catalogue():
    st.header("📦 Catalogue des pièces")

    # --- Filtres sidebar ---
    with st.sidebar:
        st.markdown("### 🔍 Filtres catalogue")
        makes = [""] + get_makes()
        sel_make = st.selectbox("Marque", makes, key="cat_make")
        sel_model = st.text_input("Modèle", key="cat_model")
        categories = [""] + get_categories()
        sel_cat = st.selectbox("Catégorie", categories, key="cat_cat")
        sel_search = st.text_input("Recherche (nom / référence)", key="cat_search")
        col1, col2 = st.columns(2)
        min_p = col1.number_input("Prix min", min_value=0.0, value=0.0, key="cat_pmin")
        max_p = col2.number_input("Prix max", min_value=0.0, value=0.0, key="cat_pmax")
        low_stock = st.checkbox("Stock bas uniquement", key="cat_lowstock")

    filters = {
        "make": sel_make or None,
        "model": sel_model or None,
        "category": sel_cat or None,
        "search": sel_search or None,
        "min_price": min_p if min_p > 0 else None,
        "max_price": max_p if max_p > 0 else None,
        "low_stock": low_stock,
    }
    # Filtre VIN depuis session_state
    if st.session_state.get("vin_filter"):
        filters.update(st.session_state["vin_filter"])

    tabs = st.tabs(["🗂️ Catalogue", "➕ Ajouter une pièce"])

    with tabs[0]:
        _show_parts_grid(filters)

    with tabs[1]:
        _form_add_part()


def _show_parts_grid(filters):
    df = get_all_parts(filters)
    if df.empty:
        st.info("Aucune pièce trouvée avec ces critères.")
        return

    st.caption(f"{len(df)} pièce(s) trouvée(s)")

    # Grille 3 colonnes
    cols_per_row = 3
    rows = [df.iloc[i:i+cols_per_row] for i in range(0, len(df), cols_per_row)]

    for row_df in rows:
        cols = st.columns(cols_per_row)
        for col, (_, part) in zip(cols, row_df.iterrows()):
            with col:
                _render_part_card(part)


def _render_part_card(part):
    stock_color = "🔴" if part["stock"] <= STOCK_THRESHOLD else "🟢"
    img_html = get_part_image_html(part.get("image_path"), size=110)

    card_html = f"""
    <div style="border:1px solid #ddd;border-radius:10px;padding:10px;
                margin-bottom:8px;background:#fff;text-align:center;
                box-shadow:0 1px 4px rgba(0,0,0,.08)">
        {img_html}
        <div style="font-weight:600;font-size:.9em;margin-top:6px;
                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis"
             title="{part['part_name']}">{part['part_name']}</div>
        <div style="color:#666;font-size:.78em">{part.get('make','')} {part.get('model','')}</div>
        <div style="color:#555;font-size:.78em">Réf: {part.get('part_number','—')}</div>
        <div style="color:#1a73e8;font-weight:700;margin:4px 0">{format_price(part['price'])}</div>
        <div style="font-size:.78em">{stock_color} Stock: {part['stock']}</div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    if c1.button("🛒", key=f"cart_{part['id']}", help="Ajouter au panier"):
        _add_to_cart(part)
    if c2.button("✏️", key=f"edit_{part['id']}", help="Modifier"):
        st.session_state[f"edit_part_{part['id']}"] = True
    if c3.button("🗑️", key=f"del_{part['id']}", help="Supprimer"):
        if delete_part(part["id"]):
            st.success("Pièce supprimée.")
            st.rerun()

    # Formulaire édition inline
    if st.session_state.get(f"edit_part_{part['id']}"):
        _form_edit_part(part)


def _add_to_cart(part):
    if "cart" not in st.session_state:
        st.session_state["cart"] = []
    cart = st.session_state["cart"]
    # Chercher si déjà dans le panier
    for item in cart:
        if item["part_id"] == part["id"]:
            item["quantity"] += 1
            item["total"] = item["quantity"] * item["unit_price"]
            st.toast(f"✅ {part['part_name']} (+1 au panier)")
            return
    cart.append({
        "part_id": part["id"],
        "part_name": part["part_name"],
        "part_number": part.get("part_number", ""),
        "unit_price": part["price"],
        "quantity": 1,
        "total": part["price"],
        "stock": part["stock"],
    })
    st.toast(f"✅ {part['part_name']} ajouté au panier")


def _form_add_part():
    st.subheader("Ajouter une nouvelle pièce")
    with st.form("form_add_part"):
        c1, c2 = st.columns(2)
        part_name = c1.text_input("Nom de la pièce *")
        part_number = c2.text_input("Référence *")
        make = c1.selectbox("Marque", get_makes())
        model = c2.text_input("Modèle")
        y1, y2 = st.columns(2)
        year_start = y1.number_input("Année début", min_value=1970, max_value=2030, value=2000)
        year_end = y2.number_input("Année fin", min_value=1970, max_value=2030, value=2024)
        p1, p2 = st.columns(2)
        price = p1.number_input("Prix (DA) *", min_value=0.0, value=0.0)
        stock = p2.number_input("Stock initial", min_value=0, value=0)
        category = st.selectbox("Catégorie", get_categories())
        image_file = st.file_uploader("Image", type=["jpg", "jpeg", "png", "webp"])
        submitted = st.form_submit_button("✅ Ajouter")

        if submitted:
            if not part_name or not part_number or price <= 0:
                st.error("Champs obligatoires : nom, référence, prix.")
            else:
                image_path = None
                if image_file:
                    image_path = save_uploaded_image(image_file, part_number)
                data = {
                    "make": make, "model": model, "year_start": year_start,
                    "year_end": year_end, "part_name": part_name,
                    "part_number": part_number, "price": price, "stock": stock,
                    "image_path": image_path, "category": category
                }
                if add_part(data):
                    st.success(f"✅ Pièce « {part_name} » ajoutée avec succès !")
                    st.rerun()


def _form_edit_part(part):
    with st.form(f"form_edit_{part['id']}"):
        st.markdown(f"**Modifier : {part['part_name']}**")
        c1, c2 = st.columns(2)
        part_name = c1.text_input("Nom", value=part["part_name"])
        part_number = c2.text_input("Référence", value=part.get("part_number", ""))
        makes = get_makes()
        make_idx = makes.index(part["make"]) if part.get("make") in makes else 0
        make = c1.selectbox("Marque", makes, index=make_idx)
        model = c2.text_input("Modèle", value=part.get("model", ""))
        y1, y2 = st.columns(2)
        year_start = y1.number_input("Année début", min_value=1970, max_value=2030,
                                      value=int(part.get("year_start") or 2000))
        year_end = y2.number_input("Année fin", min_value=1970, max_value=2030,
                                    value=int(part.get("year_end") or 2024))
        p1, p2 = st.columns(2)
        price = p1.number_input("Prix (DA)", min_value=0.0, value=float(part["price"]))
        stock = p2.number_input("Stock", min_value=0, value=int(part["stock"]))
        cats = get_categories()
        cat_idx = cats.index(part["category"]) if part.get("category") in cats else 0
        category = st.selectbox("Catégorie", cats, index=cat_idx)
        image_file = st.file_uploader("Nouvelle image (optionnel)", type=["jpg", "jpeg", "png", "webp"],
                                       key=f"img_edit_{part['id']}")
        c_save, c_cancel = st.columns(2)
        saved = c_save.form_submit_button("💾 Sauvegarder")
        cancelled = c_cancel.form_submit_button("❌ Annuler")

        if saved:
            image_path = part.get("image_path")
            if image_file:
                image_path = save_uploaded_image(image_file, part_number)
            data = {
                "make": make, "model": model, "year_start": year_start,
                "year_end": year_end, "part_name": part_name,
                "part_number": part_number, "price": price, "stock": stock,
                "image_path": image_path, "category": category
            }
            if update_part(part["id"], data):
                st.success("✅ Pièce modifiée !")
                del st.session_state[f"edit_part_{part['id']}"]
                st.rerun()
        if cancelled:
            del st.session_state[f"edit_part_{part['id']}"]
            st.rerun()
