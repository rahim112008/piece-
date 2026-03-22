"""
stock.py - Gestion avancée du stock
Mouvements, historique, ajustements manuels, alertes, inventaire
"""
import streamlit as st
import pandas as pd
from datetime import datetime
from database import get_connection
from utils import format_price
from config import STOCK_THRESHOLD


# ─────────────────────────────────────────────
#  TABLE MOUVEMENTS DE STOCK (extension)
# ─────────────────────────────────────────────

def ensure_stock_movements_table():
    """Crée la table des mouvements de stock si elle n'existe pas."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            part_id INTEGER NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            movement_type TEXT NOT NULL,  -- 'in', 'out', 'adjustment'
            quantity INTEGER NOT NULL,
            reason TEXT,
            reference TEXT,
            FOREIGN KEY (part_id) REFERENCES parts(id)
        )
    """)
    conn.commit()
    conn.close()


def record_movement(part_id: int, qty: int, movement_type: str,
                     reason: str = "", reference: str = "", conn=None):
    """Enregistre un mouvement de stock."""
    close = conn is None
    if close:
        conn = get_connection()
    conn.execute("""
        INSERT INTO stock_movements (part_id, date, movement_type, quantity, reason, reference)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (part_id, datetime.now().isoformat(), movement_type, qty, reason, reference))
    if close:
        conn.commit()
        conn.close()


def get_stock_movements(part_id: int = None, limit: int = 100) -> pd.DataFrame:
    """Retourne l'historique des mouvements."""
    conn = get_connection()
    query = """
        SELECT sm.id, sm.date, p.part_name, p.part_number,
               sm.movement_type, sm.quantity, sm.reason, sm.reference
        FROM stock_movements sm
        JOIN parts p ON sm.part_id = p.id
    """
    params = []
    if part_id:
        query += " WHERE sm.part_id = ?"
        params.append(part_id)
    query += f" ORDER BY sm.date DESC LIMIT {limit}"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def adjust_stock_manual(part_id: int, new_stock: int, reason: str) -> bool:
    """Ajustement manuel du stock (inventaire)."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT stock FROM parts WHERE id = ?", (part_id,))
        row = c.fetchone()
        if not row:
            return False
        old_stock = row["stock"]
        delta = new_stock - old_stock
        movement_type = "adjustment"

        conn.execute("UPDATE parts SET stock = ? WHERE id = ?", (new_stock, part_id))
        record_movement(part_id, abs(delta),
                        f"adjustment_{'in' if delta >= 0 else 'out'}",
                        reason=reason, reference="Inventaire", conn=conn)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        conn.close()
        st.error(f"Erreur ajustement : {e}")
        return False


def get_stock_stats() -> dict:
    """Statistiques globales du stock."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM parts")
    total_refs = c.fetchone()[0]

    c.execute("SELECT COALESCE(SUM(stock), 0) FROM parts")
    total_units = c.fetchone()[0]

    c.execute("SELECT COALESCE(SUM(stock * price), 0) FROM parts")
    total_value = c.fetchone()[0]

    c.execute(f"SELECT COUNT(*) FROM parts WHERE stock = 0")
    rupture = c.fetchone()[0]

    c.execute(f"SELECT COUNT(*) FROM parts WHERE stock > 0 AND stock <= {STOCK_THRESHOLD}")
    low = c.fetchone()[0]

    c.execute(f"SELECT COUNT(*) FROM parts WHERE stock > {STOCK_THRESHOLD}")
    ok = c.fetchone()[0]

    conn.close()
    return {
        "total_refs": total_refs,
        "total_units": total_units,
        "total_value": total_value,
        "rupture": rupture,
        "low": low,
        "ok": ok,
    }


# ─────────────────────────────────────────────
#  UI
# ─────────────────────────────────────────────

def show_stock():
    ensure_stock_movements_table()
    st.header("📦 Gestion du stock")

    stats = get_stock_stats()

    # ── KPIs ──
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📋 Références", stats["total_refs"])
    c2.metric("📦 Unités totales", f"{stats['total_units']:,}")
    c3.metric("💰 Valeur stock", format_price(stats["total_value"]))
    c4.metric("⚠️ Stock bas", stats["low"],
              delta=f"-{stats['low']} à surveiller" if stats["low"] > 0 else None,
              delta_color="inverse")
    c5.metric("🔴 Rupture", stats["rupture"],
              delta=f"-{stats['rupture']} en rupture" if stats["rupture"] > 0 else None,
              delta_color="inverse")

    st.markdown("---")

    tabs = st.tabs([
        "📊 État du stock",
        "✏️ Ajustement manuel",
        "📈 Mouvements de stock",
        "🖨️ Inventaire"
    ])

    with tabs[0]:
        _show_stock_state()
    with tabs[1]:
        _form_adjustment()
    with tabs[2]:
        _show_movements()
    with tabs[3]:
        _show_inventory()


def _show_stock_state():
    st.subheader("État du stock par pièce")

    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT id, make, model, part_name, part_number,
               category, stock, price,
               stock * price as valeur
        FROM parts
        ORDER BY stock ASC, make, model
    """, conn)
    conn.close()

    # Filtres
    col1, col2, col3 = st.columns(3)
    etat = col1.selectbox("Filtrer par état", ["Tous", "🔴 Rupture (stock=0)",
                                                "⚠️ Stock bas", "✅ Stock OK"])
    search = col2.text_input("Recherche pièce", key="stock_search")
    cat_filter = col3.selectbox("Catégorie", [""] + sorted(df["category"].dropna().unique().tolist()),
                                 key="stock_cat")

    if etat == "🔴 Rupture (stock=0)":
        df = df[df["stock"] == 0]
    elif etat == "⚠️ Stock bas":
        df = df[(df["stock"] > 0) & (df["stock"] <= STOCK_THRESHOLD)]
    elif etat == "✅ Stock OK":
        df = df[df["stock"] > STOCK_THRESHOLD]

    if search:
        df = df[df["part_name"].str.contains(search, case=False, na=False) |
                df["part_number"].str.contains(search, case=False, na=False)]
    if cat_filter:
        df = df[df["category"] == cat_filter]

    if df.empty:
        st.info("Aucune pièce trouvée.")
        return

    st.caption(f"{len(df)} pièce(s) | Valeur filtrée : {format_price(df['valeur'].sum())}")

    # Colorer selon état stock
    def color_stock(val):
        if val == 0:
            return "background-color:#ffcccc;color:#c00"
        elif val <= STOCK_THRESHOLD:
            return "background-color:#fff3cd;color:#856404"
        return "background-color:#d4edda;color:#155724"

    display = df[["part_name", "part_number", "make", "model",
                   "category", "stock", "price", "valeur"]].copy()
    display.columns = ["Pièce", "Référence", "Marque", "Modèle",
                        "Catégorie", "Stock", "Prix (DA)", "Valeur (DA)"]
    display["Prix (DA)"] = display["Prix (DA)"].apply(lambda x: f"{x:,.2f}")
    display["Valeur (DA)"] = display["Valeur (DA)"].apply(lambda x: f"{x:,.2f}")

    styled = display.style.applymap(color_stock, subset=["Stock"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _form_adjustment():
    st.subheader("Ajustement manuel du stock")
    st.info("Utilisez cet outil pour corriger le stock après un inventaire physique.")

    conn = get_connection()
    parts_df = pd.read_sql_query(
        "SELECT id, part_name, part_number, stock FROM parts ORDER BY part_name",
        conn
    )
    conn.close()

    if parts_df.empty:
        st.warning("Aucune pièce dans la base.")
        return

    part_options = {
        f"{r['part_name']} (Réf: {r['part_number']}) — Stock actuel: {r['stock']}": r
        for _, r in parts_df.iterrows()
    }
    sel = st.selectbox("Sélectionner la pièce", list(part_options.keys()),
                        key="adj_part_sel")
    part = part_options[sel]

    col1, col2 = st.columns(2)
    current = int(part["stock"])
    col1.metric("Stock actuel", current)
    new_stock = col2.number_input("Nouveau stock *", min_value=0, value=current,
                                   key="adj_new_stock")

    delta = new_stock - current
    if delta > 0:
        st.success(f"📈 Ajout de **+{delta}** unités")
    elif delta < 0:
        st.warning(f"📉 Réduction de **{delta}** unités")
    else:
        st.info("Aucun changement")

    reason = st.text_input("Raison de l'ajustement *",
                            placeholder="Ex: Inventaire mensuel, erreur de saisie, casse...",
                            key="adj_reason")

    if st.button("✅ Appliquer l'ajustement", type="primary", key="adj_apply",
                  disabled=(delta == 0)):
        if not reason:
            st.error("La raison est obligatoire.")
        else:
            if adjust_stock_manual(part["id"], new_stock, reason):
                st.success(f"✅ Stock de « {part['part_name']} » mis à jour : "
                           f"{current} → {new_stock}")
                st.rerun()


def _show_movements():
    st.subheader("Historique des mouvements de stock")

    ensure_stock_movements_table()
    df = get_stock_movements(limit=200)

    if df.empty:
        st.info("Aucun mouvement enregistré. Les entrées/sorties de stock apparaîtront ici.")
        return

    # Filtres
    col1, col2 = st.columns(2)
    type_filter = col1.selectbox(
        "Type",
        ["Tous", "in", "out", "adjustment_in", "adjustment_out"],
        format_func=lambda x: {
            "Tous": "Tous",
            "in": "📦 Entrées",
            "out": "📤 Sorties",
            "adjustment_in": "📈 Ajust. +",
            "adjustment_out": "📉 Ajust. −",
        }.get(x, x),
        key="mvt_type"
    )
    search = col2.text_input("Recherche pièce", key="mvt_search")

    if type_filter != "Tous":
        df = df[df["movement_type"] == type_filter]
    if search:
        df = df[df["part_name"].str.contains(search, case=False, na=False)]

    st.caption(f"{len(df)} mouvement(s)")

    def icon_type(t):
        return {"in": "📦", "out": "📤",
                "adjustment_in": "📈", "adjustment_out": "📉"}.get(t, "🔄")

    df_display = df.copy()
    df_display["movement_type"] = df_display["movement_type"].apply(
        lambda t: f"{icon_type(t)} {t}"
    )
    df_display["date"] = df_display["date"].astype(str).str[:16]

    st.dataframe(df_display, use_container_width=True, hide_index=True)


def _show_inventory():
    st.subheader("🖨️ Fiche d'inventaire")
    st.markdown("Exportez la liste complète du stock pour votre inventaire physique.")

    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT make as Marque, model as Modèle,
               part_name as Pièce, part_number as Référence,
               category as Catégorie, stock as "Stock système",
               '' as "Stock physique", '' as "Écart", '' as "Observations"
        FROM parts
        ORDER BY make, model, part_name
    """, conn)
    conn.close()

    st.dataframe(df, use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)

    # Export CSV
    col1.download_button(
        "⬇️ Exporter inventaire (CSV)",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=f"inventaire_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )

    # Export Excel
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Inventaire")
        ws = writer.sheets["Inventaire"]
        # Mise en forme basique
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col) + 4
            ws.column_dimensions[col[0].column_letter].width = min(max_len, 35)

    col2.download_button(
        "⬇️ Exporter inventaire (Excel)",
        data=buf.getvalue(),
        file_name=f"inventaire_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
