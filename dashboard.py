"""
dashboard.py - Tableau de bord : indicateurs financiers, graphiques, alertes
"""
import streamlit as st
import pandas as pd
from database import get_connection
from utils import format_price
from config import STOCK_THRESHOLD


def get_dashboard_data() -> dict:
    conn = get_connection()
    c = conn.cursor()

    # CA mois en cours
    c.execute("""
        SELECT COALESCE(SUM(total_amount), 0) FROM sales
        WHERE strftime('%Y-%m', sale_date) = strftime('%Y-%m', 'now')
        AND status = 'paid'
    """)
    ca_month = c.fetchone()[0]

    # CA total
    c.execute("SELECT COALESCE(SUM(total_amount), 0) FROM sales WHERE status='paid'")
    ca_total = c.fetchone()[0]

    # Nombre de ventes mois
    c.execute("""
        SELECT COUNT(*) FROM sales
        WHERE strftime('%Y-%m', sale_date) = strftime('%Y-%m', 'now')
        AND status = 'paid'
    """)
    nb_sales_month = c.fetchone()[0]

    # Total dépenses
    c.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type='expense'")
    total_expenses = c.fetchone()[0]

    # Total recettes
    c.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type='income'")
    total_income = c.fetchone()[0]

    # Stock valorisé
    c.execute("SELECT COALESCE(SUM(stock * price), 0) FROM parts")
    stock_value = c.fetchone()[0]

    # Nombre total de pièces
    c.execute("SELECT COUNT(*) FROM parts")
    nb_parts = c.fetchone()[0]

    # Alertes stock bas
    c.execute("SELECT * FROM parts WHERE stock <= ? ORDER BY stock ASC", (STOCK_THRESHOLD,))
    low_stock_parts = [dict(r) for r in c.fetchall()]

    conn.close()
    return {
        "ca_month": ca_month,
        "ca_total": ca_total,
        "nb_sales_month": nb_sales_month,
        "total_expenses": total_expenses,
        "total_income": total_income,
        "balance": total_income - total_expenses,
        "stock_value": stock_value,
        "nb_parts": nb_parts,
        "low_stock_parts": low_stock_parts,
        "profit_estimate": ca_total - total_expenses,
    }


def get_sales_by_month() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT strftime('%Y-%m', sale_date) as mois,
               COUNT(*) as nb_ventes,
               SUM(total_amount) as ca
        FROM sales
        WHERE status = 'paid'
        GROUP BY mois
        ORDER BY mois
    """, conn)
    conn.close()
    return df


def get_top_parts(limit: int = 5) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query(f"""
        SELECT p.part_name, p.make, p.model,
               SUM(si.quantity) as qty_vendue,
               SUM(si.total) as ca_genere
        FROM sale_items si
        JOIN parts p ON si.part_id = p.id
        JOIN sales s ON si.sale_id = s.id
        WHERE s.status = 'paid'
        GROUP BY si.part_id
        ORDER BY qty_vendue DESC
        LIMIT {limit}
    """, conn)
    conn.close()
    return df


def get_expenses_by_category() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT category, SUM(amount) as total
        FROM transactions
        WHERE type = 'expense'
        GROUP BY category
        ORDER BY total DESC
    """, conn)
    conn.close()
    return df


# ─────────────────────────────────────────────
#  UI
# ─────────────────────────────────────────────

def show_dashboard():
    st.header("📊 Tableau de bord")

    data = get_dashboard_data()

    # ── KPIs principaux ──
    st.subheader("📈 Indicateurs clés")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💵 CA ce mois", format_price(data["ca_month"]))
    c2.metric("💰 CA total", format_price(data["ca_total"]))
    c3.metric("🛍️ Ventes ce mois", data["nb_sales_month"])
    c4.metric("📦 Stock valorisé", format_price(data["stock_value"]))

    c1b, c2b, c3b, c4b = st.columns(4)
    c1b.metric("📈 Recettes totales", format_price(data["total_income"]))
    c2b.metric("📉 Dépenses totales", format_price(data["total_expenses"]))
    balance_color = "normal" if data["balance"] >= 0 else "inverse"
    c3b.metric("💼 Trésorerie nette", format_price(data["balance"]))
    c4b.metric("🔧 Pièces catalogue", data["nb_parts"])

    st.markdown("---")

    # ── Graphiques ──
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("📅 Ventes par mois")
        sales_monthly = get_sales_by_month()
        if not sales_monthly.empty:
            chart_data = sales_monthly.set_index("mois")[["ca"]]
            chart_data.columns = ["Chiffre d'affaires (DA)"]
            st.bar_chart(chart_data)
        else:
            st.info("Pas encore de données de ventes.")

    with col_right:
        st.subheader("💸 Dépenses par catégorie")
        exp_cat = get_expenses_by_category()
        if not exp_cat.empty:
            st.bar_chart(exp_cat.set_index("category")["total"])
        else:
            st.info("Pas encore de dépenses enregistrées.")

    st.markdown("---")

    # ── Top pièces ──
    st.subheader("🏆 Top 5 pièces les plus vendues")
    top = get_top_parts(5)
    if not top.empty:
        top["ca_genere"] = top["ca_genere"].apply(lambda x: f"{x:,.2f} DA")
        st.dataframe(top, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune vente enregistrée.")

    st.markdown("---")

    # ── Alertes stock bas ──
    low = data["low_stock_parts"]
    st.subheader(f"⚠️ Alertes stock bas ({len(low)} pièce(s))")
    if low:
        df_low = pd.DataFrame(low)[["part_name", "part_number", "make", "model",
                                     "stock", "price", "category"]]
        df_low = df_low.rename(columns={
            "part_name": "Pièce", "part_number": "Réf",
            "make": "Marque", "model": "Modèle",
            "stock": "Stock", "price": "Prix (DA)",
            "category": "Catégorie"
        })
        st.dataframe(
            df_low.style.applymap(
                lambda v: "background-color: #ffcccc" if isinstance(v, int) and v == 0
                else ("background-color: #fff3cd" if isinstance(v, int) and 0 < v <= STOCK_THRESHOLD
                      else ""),
                subset=["Stock"]
            ),
            use_container_width=True,
            hide_index=True
        )
        col_btn1, col_btn2 = st.columns(2)
        if col_btn1.button("🔍 Filtrer dans le catalogue", key="dash_low_cat"):
            st.session_state["vin_filter"] = {"low_stock": True}
            st.session_state["nav"] = "📦 Catalogue"
            st.rerun()
        if col_btn2.button("🗄️ Gérer le stock", key="dash_low_stock"):
            st.session_state["nav"] = "🗄️ Stock"
            st.rerun()
    else:
        st.success(f"✅ Tous les stocks sont au-dessus du seuil ({STOCK_THRESHOLD} unités).")

    st.markdown("---")

    # ── Évolution trésorerie ──
    st.subheader("📉 Évolution de la trésorerie")
    conn = get_connection()
    txn_df = pd.read_sql_query("""
        SELECT DATE(date) as jour,
               SUM(CASE WHEN type='income' THEN amount ELSE -amount END) as flux
        FROM transactions
        GROUP BY jour
        ORDER BY jour
    """, conn)
    conn.close()

    if not txn_df.empty:
        txn_df["cumul"] = txn_df["flux"].cumsum()
        txn_df = txn_df.set_index("jour")
        st.line_chart(txn_df[["cumul"]])
        st.caption("Solde cumulé (recettes − dépenses)")
    else:
        st.info("Aucune transaction enregistrée.")
