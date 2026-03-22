"""
import_export.py - Import/Export CSV et Excel
"""
import streamlit as st
import pandas as pd
import io
from database import get_connection
from catalogue import get_all_parts


def show_import_export():
    st.header("📁 Import / Export")
    tabs = st.tabs(["📤 Import pièces", "📥 Export données"])

    with tabs[0]:
        _show_import()
    with tabs[1]:
        _show_export()


def _show_import():
    st.subheader("Importer des pièces depuis CSV/Excel")
    st.info("""
    **Format attendu des colonnes :**
    `make, model, year_start, year_end, part_name, part_number, price, stock, category`
    """)

    uploaded = st.file_uploader("Choisir un fichier CSV ou Excel",
                                 type=["csv", "xlsx", "xls"], key="import_file")

    if uploaded:
        try:
            if uploaded.name.endswith(".csv"):
                df = pd.read_csv(uploaded)
            else:
                df = pd.read_excel(uploaded)

            st.write(f"**Aperçu ({len(df)} lignes) :**")
            st.dataframe(df.head(10), use_container_width=True)

            required_cols = {"part_name", "part_number", "price"}
            missing = required_cols - set(df.columns)
            if missing:
                st.error(f"Colonnes manquantes : {missing}")
                return

            mode = st.radio("Mode d'import", ["Ajouter uniquement les nouvelles",
                                               "Mettre à jour si existe (par part_number)"])

            if st.button("✅ Lancer l'import", key="btn_import"):
                conn = get_connection()
                added = 0
                updated = 0
                errors = 0

                for _, row in df.iterrows():
                    try:
                        data = {
                            "make": row.get("make", ""),
                            "model": row.get("model", ""),
                            "year_start": int(row.get("year_start", 2000) or 2000),
                            "year_end": int(row.get("year_end", 2024) or 2024),
                            "part_name": str(row["part_name"]),
                            "part_number": str(row["part_number"]),
                            "price": float(row["price"]),
                            "stock": int(row.get("stock", 0) or 0),
                            "image_path": row.get("image_path", None),
                            "category": row.get("category", "Autre"),
                        }
                        c = conn.cursor()
                        # Vérifier si existe
                        c.execute("SELECT id FROM parts WHERE part_number = ?",
                                  (data["part_number"],))
                        existing = c.fetchone()

                        if existing and "Mettre à jour" in mode:
                            conn.execute("""
                                UPDATE parts SET make=:make, model=:model,
                                year_start=:year_start, year_end=:year_end,
                                part_name=:part_name, price=:price, stock=:stock,
                                category=:category WHERE part_number=:part_number
                            """, data)
                            updated += 1
                        elif not existing:
                            conn.execute("""
                                INSERT INTO parts (make, model, year_start, year_end,
                                part_name, part_number, price, stock, image_path, category)
                                VALUES (:make, :model, :year_start, :year_end,
                                :part_name, :part_number, :price, :stock,
                                :image_path, :category)
                            """, data)
                            added += 1
                    except Exception as e:
                        errors += 1

                conn.commit()
                conn.close()
                st.success(f"✅ Import terminé : {added} ajoutés, {updated} mis à jour, {errors} erreurs.")
                st.rerun()

        except Exception as e:
            st.error(f"Erreur lecture fichier : {e}")


def _show_export():
    st.subheader("Exporter les données")

    # Export catalogue
    st.markdown("#### 📦 Catalogue des pièces")
    parts_df = get_all_parts()
    if not parts_df.empty:
        col1, col2 = st.columns(2)
        col1.download_button(
            "⬇️ Exporter en CSV",
            data=parts_df.to_csv(index=False).encode("utf-8"),
            file_name="catalogue_pieces.csv",
            mime="text/csv"
        )
        buf = io.BytesIO()
        parts_df.to_excel(buf, index=False, engine="openpyxl")
        col2.download_button(
            "⬇️ Exporter en Excel",
            data=buf.getvalue(),
            file_name="catalogue_pieces.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Aucune pièce à exporter.")

    st.markdown("---")

    # Export ventes
    st.markdown("#### 💳 Historique des ventes")
    conn = get_connection()
    sales_df = pd.read_sql_query("""
        SELECT s.*, COALESCE(c.name, 'Client divers') as client_name
        FROM sales s LEFT JOIN clients c ON s.client_id = c.id
        ORDER BY s.sale_date DESC
    """, conn)
    if not sales_df.empty:
        col1, col2 = st.columns(2)
        col1.download_button(
            "⬇️ Ventes CSV",
            data=sales_df.to_csv(index=False).encode("utf-8"),
            file_name="ventes.csv", mime="text/csv"
        )
        buf2 = io.BytesIO()
        sales_df.to_excel(buf2, index=False, engine="openpyxl")
        col2.download_button(
            "⬇️ Ventes Excel",
            data=buf2.getvalue(),
            file_name="ventes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    st.markdown("---")

    # Export transactions
    st.markdown("#### 💰 Transactions (recettes/dépenses)")
    txn_df = pd.read_sql_query("SELECT * FROM transactions ORDER BY date DESC", conn)
    if not txn_df.empty:
        col1, col2 = st.columns(2)
        col1.download_button(
            "⬇️ Transactions CSV",
            data=txn_df.to_csv(index=False).encode("utf-8"),
            file_name="transactions.csv", mime="text/csv"
        )
        buf3 = io.BytesIO()
        txn_df.to_excel(buf3, index=False, engine="openpyxl")
        col2.download_button(
            "⬇️ Transactions Excel",
            data=buf3.getvalue(),
            file_name="transactions.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    st.markdown("---")

    # Export bons de commande
    st.markdown("#### 📋 Bons de commande")
    bc_df = pd.read_sql_query("SELECT * FROM purchase_orders ORDER BY order_date DESC", conn)
    if not bc_df.empty:
        col1, col2 = st.columns(2)
        col1.download_button(
            "⬇️ BC CSV",
            data=bc_df.to_csv(index=False).encode("utf-8"),
            file_name="bons_commande.csv", mime="text/csv"
        )
        buf4 = io.BytesIO()
        bc_df.to_excel(buf4, index=False, engine="openpyxl")
        col2.download_button(
            "⬇️ BC Excel",
            data=buf4.getvalue(),
            file_name="bons_commande.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    conn.close()

    st.markdown("---")
    st.markdown("#### 📋 Modèle d'import")
    template_df = pd.DataFrame([{
        "make": "Renault", "model": "Clio", "year_start": 2010, "year_end": 2020,
        "part_name": "Filtre à huile", "part_number": "RN-FH-001",
        "price": 850.0, "stock": 10, "category": "Filtration"
    }])
    st.download_button(
        "⬇️ Télécharger le modèle CSV",
        data=template_df.to_csv(index=False).encode("utf-8"),
        file_name="modele_import_pieces.csv",
        mime="text/csv"
    )
