"""
purchase_orders.py - Gestion des bons de commande fournisseurs
"""
import streamlit as st
import pandas as pd
from datetime import datetime, date
from database import get_connection
from catalogue import get_all_parts, update_stock
from pdf_generator import generate_purchase_order_pdf
from utils import format_price
try:
    from stock import record_movement, ensure_stock_movements_table
except ImportError:
    def record_movement(*a, **k): pass
    def ensure_stock_movements_table(): pass
from expenses import add_transaction


def get_all_orders(status: str = None) -> pd.DataFrame:
    conn = get_connection()
    query = "SELECT * FROM purchase_orders"
    params = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY order_date DESC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_order_items(order_id: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT oi.*, p.part_name, p.part_number, p.make, p.model
        FROM order_items oi
        JOIN parts p ON oi.part_id = p.id
        WHERE oi.order_id = ?
    """, conn, params=(order_id,))
    conn.close()
    return df


def create_order(supplier_name: str, items: list, delivery_date=None) -> int | None:
    """Crée un bon de commande. Retourne l'ID créé."""
    if not items:
        return None
    total = sum(i["total"] for i in items)
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO purchase_orders (supplier_name, order_date, delivery_date, total_amount, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (supplier_name, datetime.now().isoformat(),
              str(delivery_date) if delivery_date else None, total))
        order_id = c.lastrowid

        for item in items:
            c.execute("""
                INSERT INTO order_items (order_id, part_id, quantity, unit_price, total)
                VALUES (?, ?, ?, ?, ?)
            """, (order_id, item["part_id"], item["quantity"],
                  item["unit_price"], item["total"]))
        conn.commit()
        conn.close()
        return order_id
    except Exception as e:
        st.error(f"Erreur création BC : {e}")
        return None


def receive_order(order_id: int, record_expense: bool = True) -> bool:
    """Marque un BC comme reçu, incrémente le stock."""
    conn = get_connection()
    try:
        c = conn.cursor()
        # Récupérer les lignes
        c.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,))
        items = c.fetchall()
        for item in items:
            update_stock(item["part_id"], item["quantity"], conn)
            record_movement(item["part_id"], item["quantity"], "in",
                            reason=f"Réception BC #{order_id:04d}",
                            reference=f"BC{order_id:04d}", conn=conn)

        c.execute("UPDATE purchase_orders SET status='received' WHERE id=?", (order_id,))

        # Récupérer total
        c.execute("SELECT * FROM purchase_orders WHERE id=?", (order_id,))
        order = c.fetchone()
        conn.commit()
        conn.close()

        # Enregistrer dépense automatiquement
        if record_expense and order:
            add_transaction({
                "date": datetime.now().isoformat(),
                "type": "expense",
                "category": "Achat fournisseur",
                "amount": order["total_amount"],
                "description": f"Réception BC #{order_id:04d} — {order['supplier_name']}",
                "reference": f"BC{order_id:04d}",
            })
        return True
    except Exception as e:
        conn.rollback()
        conn.close()
        st.error(f"Erreur réception BC : {e}")
        return False


def cancel_order(order_id: int) -> bool:
    try:
        conn = get_connection()
        conn.execute("UPDATE purchase_orders SET status='cancelled' WHERE id=?", (order_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erreur annulation BC : {e}")
        return False


# ─────────────────────────────────────────────
#  UI
# ─────────────────────────────────────────────

def show_purchase_orders():
    st.header("📋 Bons de commande fournisseurs")
    tabs = st.tabs(["➕ Nouveau bon de commande", "📂 Historique des bons"])

    with tabs[0]:
        _form_new_order()
    with tabs[1]:
        _show_orders_history()


def _form_new_order():
    st.subheader("Créer un bon de commande")

    # Initialiser panier BC
    if "bc_cart" not in st.session_state:
        st.session_state["bc_cart"] = []

    supplier = st.text_input("Nom du fournisseur *", key="bc_supplier")
    delivery_date = st.date_input("Date de livraison prévue", value=None, key="bc_delivery")

    st.markdown("#### Articles à commander")
    parts_df = get_all_parts()
    if not parts_df.empty:
        part_options = {
            f"{r['part_name']} — {r.get('part_number','?')} (stock: {r['stock']})": r
            for _, r in parts_df.iterrows()
        }
        sel = st.selectbox("Sélectionner une pièce", [""] + list(part_options.keys()),
                            key="bc_part_sel")
        c1, c2, c3 = st.columns(3)
        qty = c1.number_input("Quantité", min_value=1, value=1, key="bc_qty")
        unit_price = c2.number_input("Prix unitaire (DA)", min_value=0.0, value=0.0,
                                      key="bc_unit_price")
        if c3.button("➕ Ajouter", key="bc_add_btn") and sel:
            part = part_options[sel]
            _add_to_bc_cart(part, qty, unit_price)
            st.rerun()

    # Afficher le panier BC
    bc_cart = st.session_state["bc_cart"]
    if bc_cart:
        st.markdown("**Articles sélectionnés :**")
        bc_data = []
        for i, item in enumerate(bc_cart):
            bc_data.append({
                "#": i + 1,
                "Pièce": item["part_name"],
                "Qté": item["quantity"],
                "P.U. (DA)": f"{item['unit_price']:,.2f}",
                "Total (DA)": f"{item['total']:,.2f}",
            })
        st.dataframe(pd.DataFrame(bc_data), use_container_width=True, hide_index=True)

        total_bc = sum(i["total"] for i in bc_cart)
        st.markdown(f"**Total commande : {format_price(total_bc)}**")

        c1, c2 = st.columns(2)
        if c1.button("🧹 Vider la liste", key="bc_clear"):
            st.session_state["bc_cart"] = []
            st.rerun()

        if c2.button("✅ Créer le bon de commande", type="primary", key="bc_create"):
            if not supplier:
                st.error("Veuillez indiquer le nom du fournisseur.")
            else:
                order_id = create_order(supplier, bc_cart, delivery_date)
                if order_id:
                    st.success(f"✅ Bon de commande **BC{order_id:04d}** créé !")
                    # Générer PDF
                    try:
                        order_dict = {
                            "id": order_id,
                            "supplier_name": supplier,
                            "order_date": datetime.now().isoformat(),
                            "total_amount": sum(i["total"] for i in bc_cart),
                        }
                        pdf_path = generate_purchase_order_pdf(order_dict, bc_cart)
                        with open(pdf_path, "rb") as f:
                            st.download_button(
                                "📄 Télécharger le BC (PDF)",
                                data=f.read(),
                                file_name=f"bc_{order_id:04d}.pdf",
                                mime="application/pdf"
                            )
                    except Exception as e:
                        st.warning(f"PDF non généré : {e}")
                    st.session_state["bc_cart"] = []
                    st.rerun()


def _add_to_bc_cart(part, qty: int, unit_price: float):
    cart = st.session_state.setdefault("bc_cart", [])
    for item in cart:
        if item["part_id"] == part["id"]:
            item["quantity"] += qty
            item["total"] = item["quantity"] * item["unit_price"]
            return
    price = unit_price if unit_price > 0 else part["price"]
    cart.append({
        "part_id": part["id"],
        "part_name": part["part_name"],
        "part_number": part.get("part_number", ""),
        "unit_price": price,
        "quantity": qty,
        "total": qty * price,
    })


def _show_orders_history():
    st.subheader("Historique des bons de commande")

    status_filter = st.selectbox(
        "Filtrer par statut",
        ["", "pending", "received", "cancelled"],
        format_func=lambda x: {
            "": "Tous", "pending": "⏳ En attente",
            "received": "✅ Reçu", "cancelled": "❌ Annulé"
        }.get(x, x),
        key="bc_status_filter"
    )

    df = get_all_orders(status_filter or None)
    if df.empty:
        st.info("Aucun bon de commande.")
        return

    st.caption(f"{len(df)} bon(s) de commande")

    status_icons = {"pending": "⏳", "received": "✅", "cancelled": "❌"}

    for _, order in df.iterrows():
        icon = status_icons.get(order["status"], "❓")
        with st.expander(
            f"{icon} BC{order['id']:04d} | {order['supplier_name']} | "
            f"{format_price(order['total_amount'])} | {str(order['order_date'])[:10]}"
        ):
            items_df = get_order_items(order["id"])
            if not items_df.empty:
                st.dataframe(
                    items_df[["part_name", "quantity", "unit_price", "total"]],
                    use_container_width=True, hide_index=True
                )

            col1, col2, col3 = st.columns(3)
            col1.write(f"**Statut :** {order['status']}")
            if order.get("delivery_date"):
                col1.write(f"**Livraison prévue :** {order['delivery_date']}")

            # Actions selon statut
            if order["status"] == "pending":
                if col2.button("✅ Marquer comme reçu", key=f"recv_{order['id']}"):
                    if receive_order(order["id"]):
                        st.success("✅ BC reçu ! Stock mis à jour, dépense enregistrée.")
                        st.rerun()
                if col3.button("❌ Annuler", key=f"canc_{order['id']}"):
                    if cancel_order(order["id"]):
                        st.success("BC annulé.")
                        st.rerun()

            # PDF
            if col2.button("📄 Télécharger PDF", key=f"pdf_bc_{order['id']}"):
                try:
                    items_list = items_df.to_dict("records") if not items_df.empty else []
                    pdf_path = generate_purchase_order_pdf(dict(order), items_list)
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            "⬇️ PDF",
                            data=f.read(),
                            file_name=f"bc_{order['id']:04d}.pdf",
                            mime="application/pdf",
                            key=f"dl_bc_{order['id']}"
                        )
                except Exception as e:
                    st.error(f"Erreur PDF : {e}")
