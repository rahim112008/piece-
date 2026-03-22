"""
sales.py - Gestion des ventes, panier et facturation
"""
import streamlit as st
import pandas as pd
from datetime import datetime
from database import get_connection, get_next_invoice_number
from catalogue import get_all_parts, update_stock
from clients import get_all_clients, add_client
from pdf_generator import generate_invoice_pdf
from utils import format_price, get_payment_methods
try:
    from stock import record_movement, ensure_stock_movements_table
except ImportError:
    def record_movement(*a, **k): pass
    def ensure_stock_movements_table(): pass
from config import INVOICE_PREFIX


# ─────────────────────────────────────────────
#  DONNÉES
# ─────────────────────────────────────────────

def get_all_sales(filters: dict = None) -> pd.DataFrame:
    conn = get_connection()
    query = """
        SELECT s.id, s.invoice_number, s.sale_date, s.total_amount,
               s.payment_method, s.status,
               COALESCE(c.name, 'Client divers') as client_name
        FROM sales s
        LEFT JOIN clients c ON s.client_id = c.id
        WHERE 1=1
    """
    params = []
    if filters:
        if filters.get("date_from"):
            query += " AND DATE(s.sale_date) >= ?"
            params.append(str(filters["date_from"]))
        if filters.get("date_to"):
            query += " AND DATE(s.sale_date) <= ?"
            params.append(str(filters["date_to"]))
        if filters.get("client_name"):
            query += " AND c.name LIKE ?"
            params.append(f"%{filters['client_name']}%")
        if filters.get("status"):
            query += " AND s.status = ?"
            params.append(filters["status"])
    query += " ORDER BY s.sale_date DESC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_sale_items(sale_id: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT si.*, p.part_name, p.part_number
        FROM sale_items si
        JOIN parts p ON si.part_id = p.id
        WHERE si.sale_id = ?
    """, conn, params=(sale_id,))
    conn.close()
    return df


def create_sale(client_id, items: list, payment_method: str) -> dict | None:
    """
    Valide une vente :
    - Crée la vente et les lignes
    - Déduit le stock
    - Crée une transaction de recette
    - Génère une facture PDF
    Retourne les infos de la vente créée.
    """
    conn = get_connection()
    try:
        total = sum(i["total"] for i in items)
        inv_num = get_next_invoice_number(conn)
        invoice_number = f"{INVOICE_PREFIX}{inv_num:04d}"

        c = conn.cursor()
        c.execute("""
            INSERT INTO sales (client_id, sale_date, total_amount,
                               payment_method, status, invoice_number)
            VALUES (?, ?, ?, ?, 'paid', ?)
        """, (client_id, datetime.now().isoformat(), total, payment_method, invoice_number))
        sale_id = c.lastrowid

        for item in items:
            c.execute("""
                INSERT INTO sale_items (sale_id, part_id, quantity, unit_price, total)
                VALUES (?, ?, ?, ?, ?)
            """, (sale_id, item["part_id"], item["quantity"],
                  item["unit_price"], item["total"]))
            # Déduire le stock et enregistrer le mouvement
            update_stock(item["part_id"], -item["quantity"], conn)
            record_movement(item["part_id"], item["quantity"], "out",
                            reason=f"Vente {invoice_number}", reference=invoice_number, conn=conn)

        # Enregistrer la recette
        c.execute("""
            INSERT INTO transactions (date, type, category, amount, description, reference)
            VALUES (?, 'income', 'Vente', ?, ?, ?)
        """, (datetime.now().isoformat(), total,
              f"Vente {invoice_number}", invoice_number))

        conn.commit()
        sale = {
            "id": sale_id,
            "invoice_number": invoice_number,
            "sale_date": datetime.now().isoformat(),
            "total_amount": total,
            "payment_method": payment_method,
            "client_id": client_id,
        }
        conn.close()
        return sale
    except Exception as e:
        conn.rollback()
        conn.close()
        st.error(f"Erreur lors de la validation : {e}")
        return None


def cancel_sale(sale_id: int) -> bool:
    """Annule une vente : remet le stock et supprime la transaction."""
    conn = get_connection()
    try:
        c = conn.cursor()
        # Récupérer les items
        c.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,))
        items = c.fetchall()
        for item in items:
            update_stock(item["part_id"], item["quantity"], conn)

        # Récupérer la facture
        c.execute("SELECT invoice_number FROM sales WHERE id = ?", (sale_id,))
        row = c.fetchone()
        inv = row["invoice_number"] if row else None

        # Supprimer transaction
        if inv:
            c.execute("DELETE FROM transactions WHERE reference = ? AND type='income'", (inv,))
        # Mettre à jour statut
        c.execute("UPDATE sales SET status='cancelled' WHERE id=?", (sale_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        conn.close()
        st.error(f"Erreur annulation : {e}")
        return False


# ─────────────────────────────────────────────
#  UI
# ─────────────────────────────────────────────

def show_sales():
    st.header("💳 Ventes & Facturation")
    tabs = st.tabs(["🛒 Nouvelle vente", "📋 Historique des ventes"])

    with tabs[0]:
        _show_new_sale()
    with tabs[1]:
        _show_sales_history()


def _show_new_sale():
    st.subheader("Nouvelle vente")

    # Initialiser le panier
    if "cart" not in st.session_state:
        st.session_state["cart"] = []

    # ── Ajout de pièces ──
    st.markdown("#### 1. Ajouter des pièces au panier")
    parts_df = get_all_parts()
    if not parts_df.empty:
        part_options = {
            f"{r['part_name']} — {r.get('part_number','?')} ({format_price(r['price'])})": r
            for _, r in parts_df.iterrows()
        }
        sel = st.selectbox("Sélectionner une pièce", [""] + list(part_options.keys()),
                            key="sale_part_sel")
        col1, col2 = st.columns([3, 1])
        qty = col1.number_input("Quantité", min_value=1, value=1, key="sale_qty")
        if col2.button("➕ Ajouter", key="btn_add_cart") and sel:
            part = part_options[sel]
            if qty > part["stock"]:
                st.warning(f"⚠️ Stock insuffisant (disponible : {part['stock']})")
            else:
                _add_to_cart_with_qty(part, qty)
                st.rerun()

    st.markdown("---")

    # ── Panier ──
    st.markdown("#### 2. Panier")
    cart = st.session_state["cart"]
    if not cart:
        st.info("Le panier est vide. Ajoutez des pièces ci-dessus ou depuis le catalogue.")
        return

    _show_cart_table()

    st.markdown("---")

    # ── Informations client et paiement ──
    st.markdown("#### 3. Client & Paiement")
    clients_df = get_all_clients()
    client_options = {"Client divers (sans compte)": None}
    client_options.update({
        f"{r['name']} — {r.get('phone', '')}": r["id"]
        for _, r in clients_df.iterrows()
    })
    sel_client_label = st.selectbox("Client", list(client_options.keys()), key="sale_client")
    client_id = client_options[sel_client_label]

    # Nouveau client rapide
    with st.expander("➕ Créer un nouveau client rapidement"):
        with st.form("quick_client"):
            nc_name = st.text_input("Nom *")
            nc_phone = st.text_input("Téléphone")
            nc_email = st.text_input("Email")
            if st.form_submit_button("Créer"):
                if nc_name:
                    from clients import add_client as ac
                    nc_id = ac({"name": nc_name, "phone": nc_phone,
                                 "email": nc_email, "address": ""})
                    if nc_id:
                        st.success(f"Client créé : {nc_name}")
                        st.rerun()

    payment = st.selectbox("Mode de paiement", get_payment_methods(), key="sale_payment")

    # Total
    total = sum(i["total"] for i in cart)
    st.markdown(f"### 💰 Total : **{format_price(total)}**")

    if st.button("✅ Valider la vente et générer la facture", type="primary"):
        sale = create_sale(client_id, cart, payment)
        if sale:
            # Récupérer infos client
            if client_id:
                from clients import get_client_by_id
                client_info = get_client_by_id(client_id) or {"name": "Client divers"}
            else:
                client_info = {"name": "Client divers", "phone": "", "address": ""}

            # Générer PDF
            try:
                pdf_path = generate_invoice_pdf(sale, cart, client_info)
                st.success(f"✅ Vente validée ! Facture : **{sale['invoice_number']}**")
                # Proposer le téléchargement
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        label="📄 Télécharger la facture PDF",
                        data=f.read(),
                        file_name=f"facture_{sale['invoice_number']}.pdf",
                        mime="application/pdf"
                    )
            except Exception as e:
                st.success(f"✅ Vente validée ! Facture : **{sale['invoice_number']}**")
                st.warning(f"PDF non généré : {e}")

            # Vider le panier
            st.session_state["cart"] = []
            st.rerun()


def _add_to_cart_with_qty(part, qty: int):
    cart = st.session_state.setdefault("cart", [])
    for item in cart:
        if item["part_id"] == part["id"]:
            item["quantity"] += qty
            item["total"] = item["quantity"] * item["unit_price"]
            return
    cart.append({
        "part_id": part["id"],
        "part_name": part["part_name"],
        "part_number": part.get("part_number", ""),
        "unit_price": part["price"],
        "quantity": qty,
        "total": qty * part["price"],
        "stock": part["stock"],
    })


def _show_cart_table():
    cart = st.session_state["cart"]
    if not cart:
        return

    # Affichage tableau
    cart_data = []
    for i, item in enumerate(cart):
        cart_data.append({
            "#": i + 1,
            "Pièce": item["part_name"],
            "Réf": item.get("part_number", ""),
            "Prix unit.": format_price(item["unit_price"]),
            "Qté": item["quantity"],
            "Total": format_price(item["total"]),
        })
    st.dataframe(pd.DataFrame(cart_data), use_container_width=True, hide_index=True)

    # Contrôles panier
    col1, col2 = st.columns([3, 1])
    part_names = [f"{i+1}. {item['part_name']}" for i, item in enumerate(cart)]
    sel_idx = col1.selectbox("Sélectionner une ligne à modifier/supprimer",
                              range(len(part_names)),
                              format_func=lambda x: part_names[x],
                              key="cart_sel_idx")
    if col2.button("🗑️ Retirer du panier"):
        st.session_state["cart"].pop(sel_idx)
        st.rerun()

    new_qty = col1.number_input("Modifier la quantité", min_value=1,
                                 value=cart[sel_idx]["quantity"],
                                 key="cart_edit_qty")
    if col2.button("🔄 Mettre à jour"):
        cart[sel_idx]["quantity"] = new_qty
        cart[sel_idx]["total"] = new_qty * cart[sel_idx]["unit_price"]
        st.rerun()

    if st.button("🧹 Vider le panier"):
        st.session_state["cart"] = []
        st.rerun()


def _show_sales_history():
    st.subheader("Historique des ventes")

    # Filtres
    col1, col2, col3 = st.columns(3)
    date_from = col1.date_input("Du", value=None, key="hist_from")
    date_to = col2.date_input("Au", value=None, key="hist_to")
    status_filter = col3.selectbox("Statut", ["", "paid", "cancelled", "pending"],
                                    key="hist_status")

    filters = {
        "date_from": date_from,
        "date_to": date_to,
        "status": status_filter or None,
    }
    df = get_all_sales(filters)

    if df.empty:
        st.info("Aucune vente trouvée.")
        return

    st.caption(f"{len(df)} vente(s) — Total : {format_price(df['total_amount'].sum())}")

    for _, sale in df.iterrows():
        status_icon = "✅" if sale["status"] == "paid" else ("❌" if sale["status"] == "cancelled" else "⏳")
        with st.expander(
            f"{status_icon} {sale['invoice_number']} | {sale['client_name']} | "
            f"{format_price(sale['total_amount'])} | {str(sale['sale_date'])[:10]}"
        ):
            items_df = get_sale_items(sale["id"])
            if not items_df.empty:
                st.dataframe(
                    items_df[["part_name", "quantity", "unit_price", "total"]],
                    use_container_width=True, hide_index=True
                )

            col1, col2 = st.columns(2)
            col1.write(f"**Paiement :** {sale.get('payment_method', '—')}")
            col1.write(f"**Statut :** {sale['status']}")

            # Regénérer PDF
            if col2.button("📄 Regénérer facture PDF", key=f"pdf_{sale['id']}"):
                sale_dict = dict(sale)
                from clients import get_client_by_id
                client_info = get_client_by_id(sale["id"]) or {"name": sale["client_name"]}
                items_list = items_df.to_dict("records") if not items_df.empty else []
                try:
                    pdf_path = generate_invoice_pdf(sale_dict, items_list, client_info)
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            "⬇️ Télécharger",
                            data=f.read(),
                            file_name=f"facture_{sale['invoice_number']}.pdf",
                            mime="application/pdf",
                            key=f"dl_pdf_{sale['id']}"
                        )
                except Exception as e:
                    st.error(f"Erreur PDF : {e}")

            # Annuler vente
            if sale["status"] == "paid":
                if col2.button("❌ Annuler cette vente", key=f"cancel_{sale['id']}"):
                    if cancel_sale(sale["id"]):
                        st.success("Vente annulée, stock restauré.")
                        st.rerun()
