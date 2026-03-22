"""
expenses.py - Gestion des recettes et dépenses (transactions)
"""
import streamlit as st
import pandas as pd
from datetime import datetime, date
from database import get_connection
from utils import format_price, get_expense_categories


def get_all_transactions(filters: dict = None) -> pd.DataFrame:
    conn = get_connection()
    query = "SELECT * FROM transactions WHERE 1=1"
    params = []
    if filters:
        if filters.get("type"):
            query += " AND type = ?"
            params.append(filters["type"])
        if filters.get("category"):
            query += " AND category = ?"
            params.append(filters["category"])
        if filters.get("date_from"):
            query += " AND DATE(date) >= ?"
            params.append(str(filters["date_from"]))
        if filters.get("date_to"):
            query += " AND DATE(date) <= ?"
            params.append(str(filters["date_to"]))
    query += " ORDER BY date DESC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def add_transaction(data: dict) -> bool:
    try:
        conn = get_connection()
        conn.execute("""
            INSERT INTO transactions (date, type, category, amount, description, reference)
            VALUES (:date, :type, :category, :amount, :description, :reference)
        """, data)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erreur ajout transaction : {e}")
        return False


def delete_transaction(txn_id: int) -> bool:
    try:
        conn = get_connection()
        conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erreur suppression : {e}")
        return False


def get_summary() -> dict:
    """Retourne totaux recettes / dépenses / solde."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income'")
    total_income = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense'")
    total_expense = c.fetchone()[0]
    conn.close()
    return {
        "income": total_income,
        "expense": total_expense,
        "balance": total_income - total_expense,
    }


def get_monthly_summary() -> pd.DataFrame:
    """Résumé mensuel recettes vs dépenses."""
    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT strftime('%Y-%m', date) as month,
               type,
               SUM(amount) as total
        FROM transactions
        GROUP BY month, type
        ORDER BY month
    """, conn)
    conn.close()
    return df


# ─────────────────────────────────────────────
#  UI
# ─────────────────────────────────────────────

def show_expenses():
    st.header("💰 Recettes & Dépenses")

    # Résumé en haut
    summary = get_summary()
    c1, c2, c3 = st.columns(3)
    c1.metric("📈 Recettes totales", format_price(summary["income"]))
    c2.metric("📉 Dépenses totales", format_price(summary["expense"]))
    balance_delta = None
    c3.metric(
        "💼 Solde trésorerie",
        format_price(summary["balance"]),
        delta=f"{'▲' if summary['balance'] >= 0 else '▼'} {abs(summary['balance']):,.0f} DA"
    )

    tabs = st.tabs(["📋 Toutes les transactions",
                    "➕ Ajouter une dépense",
                    "📊 Visualisation mensuelle"])

    with tabs[0]:
        _show_transactions()
    with tabs[1]:
        _form_add_expense()
    with tabs[2]:
        _show_monthly_chart()


def _show_transactions():
    st.subheader("Transactions")
    col1, col2, col3 = st.columns(3)
    txn_type = col1.selectbox("Type", ["", "income", "expense"],
                               format_func=lambda x: {"": "Tous", "income": "Recettes",
                                                        "expense": "Dépenses"}.get(x, x),
                               key="txn_type")
    date_from = col2.date_input("Du", value=None, key="txn_from")
    date_to = col3.date_input("Au", value=None, key="txn_to")

    cats = [""] + get_expense_categories() + ["Vente"]
    cat_filter = st.selectbox("Catégorie", cats, key="txn_cat")

    filters = {
        "type": txn_type or None,
        "category": cat_filter or None,
        "date_from": date_from,
        "date_to": date_to,
    }
    df = get_all_transactions(filters)

    if df.empty:
        st.info("Aucune transaction.")
        return

    total_in = df[df["type"] == "income"]["amount"].sum()
    total_out = df[df["type"] == "expense"]["amount"].sum()
    st.caption(
        f"{len(df)} transaction(s) | Recettes : {format_price(total_in)} | "
        f"Dépenses : {format_price(total_out)}"
    )

    # Colorer les lignes
    def style_row(row):
        color = "#e8f5e9" if row["type"] == "income" else "#ffebee"
        return [f"background-color: {color}"] * len(row)

    display_df = df[["date", "type", "category", "amount", "description", "reference"]].copy()
    display_df["type"] = display_df["type"].map({"income": "📈 Recette", "expense": "📉 Dépense"})
    display_df["amount"] = display_df["amount"].apply(lambda x: f"{x:,.2f} DA")
    display_df["date"] = display_df["date"].astype(str).str[:10]

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Suppression
    with st.expander("🗑️ Supprimer une transaction"):
        if not df.empty:
            txn_options = {
                f"#{r['id']} — {str(r['date'])[:10]} — {r['category']} — {r['amount']:.2f} DA": r["id"]
                for _, r in df.iterrows()
            }
            sel = st.selectbox("Sélectionner", list(txn_options.keys()), key="del_txn_sel")
            if st.button("🗑️ Supprimer", key="del_txn_btn"):
                if delete_transaction(txn_options[sel]):
                    st.success("Transaction supprimée.")
                    st.rerun()


def _form_add_expense():
    st.subheader("Ajouter une dépense")
    with st.form("form_add_expense"):
        description = st.text_input("Description *")
        c1, c2 = st.columns(2)
        amount = c1.number_input("Montant (DA) *", min_value=0.01, value=0.01)
        category = c2.selectbox("Catégorie", get_expense_categories())
        expense_date = c1.date_input("Date", value=date.today())
        reference = c2.text_input("Référence (ex: numéro BC)")

        if st.form_submit_button("✅ Enregistrer la dépense"):
            if not description or amount <= 0:
                st.error("Description et montant obligatoires.")
            else:
                data = {
                    "date": datetime.combine(expense_date, datetime.min.time()).isoformat(),
                    "type": "expense",
                    "category": category,
                    "amount": amount,
                    "description": description,
                    "reference": reference,
                }
                if add_transaction(data):
                    st.success(f"✅ Dépense de {format_price(amount)} enregistrée.")
                    st.rerun()


def _show_monthly_chart():
    st.subheader("Évolution mensuelle")
    monthly = get_monthly_summary()
    if monthly.empty:
        st.info("Pas encore de données.")
        return

    # Pivot
    pivot = monthly.pivot(index="month", columns="type", values="total").fillna(0)
    pivot.columns = [{"income": "Recettes", "expense": "Dépenses"}.get(c, c)
                     for c in pivot.columns]
    pivot["Solde"] = pivot.get("Recettes", 0) - pivot.get("Dépenses", 0)

    st.line_chart(pivot)
    st.caption("Recettes et dépenses par mois")
    st.dataframe(pivot.style.format("{:,.2f}"), use_container_width=True)
