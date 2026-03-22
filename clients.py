"""
clients.py - Gestion des clients (CRUD)
"""
import streamlit as st
import pandas as pd
from database import get_connection


def get_all_clients() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM clients ORDER BY name", conn)
    conn.close()
    return df


def get_client_by_id(client_id: int) -> dict | None:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def add_client(data: dict) -> int | None:
    """Ajoute un client, retourne son id."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO clients (name, phone, email, address)
            VALUES (:name, :phone, :email, :address)
        """, data)
        conn.commit()
        cid = c.lastrowid
        conn.close()
        return cid
    except Exception as e:
        st.error(f"Erreur ajout client : {e}")
        return None


def update_client(client_id: int, data: dict) -> bool:
    try:
        conn = get_connection()
        conn.execute("""
            UPDATE clients SET name=:name, phone=:phone, email=:email, address=:address
            WHERE id=:id
        """, {**data, "id": client_id})
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erreur modification client : {e}")
        return False


def delete_client(client_id: int) -> bool:
    try:
        conn = get_connection()
        conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erreur suppression client : {e}")
        return False


def get_client_sales_history(client_id: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT s.id, s.invoice_number, s.sale_date, s.total_amount,
               s.payment_method, s.status
        FROM sales s
        WHERE s.client_id = ?
        ORDER BY s.sale_date DESC
    """, conn, params=(client_id,))
    conn.close()
    return df


# ─────────────────────────────────────────────
#  UI
# ─────────────────────────────────────────────

def show_clients():
    st.header("👥 Gestion des clients")
    tabs = st.tabs(["📋 Liste des clients", "➕ Nouveau client"])

    with tabs[0]:
        _show_clients_list()

    with tabs[1]:
        _form_add_client()


def _show_clients_list():
    df = get_all_clients()
    if df.empty:
        st.info("Aucun client enregistré.")
        return

    search = st.text_input("🔍 Rechercher un client", key="client_search")
    if search:
        mask = df["name"].str.contains(search, case=False, na=False) | \
               df["phone"].str.contains(search, case=False, na=False)
        df = df[mask]

    st.caption(f"{len(df)} client(s)")

    for _, client in df.iterrows():
        with st.expander(f"👤 {client['name']}  |  📞 {client.get('phone', '—')}"):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.write(f"**Email :** {client.get('email') or '—'}")
                st.write(f"**Adresse :** {client.get('address') or '—'}")
                st.write(f"**Client depuis :** {client.get('created_at', '—')[:10]}")

                # Historique achats
                history = get_client_sales_history(client["id"])
                if not history.empty:
                    st.markdown("**Historique des achats :**")
                    st.dataframe(history[["invoice_number", "sale_date", "total_amount",
                                          "payment_method", "status"]],
                                 use_container_width=True, hide_index=True)
                else:
                    st.caption("Aucun achat enregistré.")

            with c2:
                if st.button("✏️ Modifier", key=f"edit_cl_{client['id']}"):
                    st.session_state[f"edit_client_{client['id']}"] = True
                if st.button("🗑️ Supprimer", key=f"del_cl_{client['id']}"):
                    if delete_client(client["id"]):
                        st.success("Client supprimé.")
                        st.rerun()

            # Formulaire édition inline
            if st.session_state.get(f"edit_client_{client['id']}"):
                _form_edit_client(client)


def _form_add_client():
    st.subheader("Nouveau client")
    with st.form("form_add_client"):
        name = st.text_input("Nom complet *")
        c1, c2 = st.columns(2)
        phone = c1.text_input("Téléphone")
        email = c2.text_input("Email")
        address = st.text_area("Adresse")
        if st.form_submit_button("✅ Enregistrer"):
            if not name:
                st.error("Le nom est obligatoire.")
            else:
                cid = add_client({"name": name, "phone": phone,
                                   "email": email, "address": address})
                if cid:
                    st.success(f"✅ Client « {name} » ajouté (ID #{cid})")
                    st.rerun()


def _form_edit_client(client):
    with st.form(f"form_edit_client_{client['id']}"):
        st.markdown("**Modifier le client**")
        name = st.text_input("Nom", value=client["name"])
        c1, c2 = st.columns(2)
        phone = c1.text_input("Téléphone", value=client.get("phone", ""))
        email = c2.text_input("Email", value=client.get("email", ""))
        address = st.text_area("Adresse", value=client.get("address", ""))
        cs, cc = st.columns(2)
        saved = cs.form_submit_button("💾 Sauvegarder")
        cancelled = cc.form_submit_button("❌ Annuler")
        if saved:
            if update_client(client["id"], {"name": name, "phone": phone,
                                             "email": email, "address": address}):
                st.success("✅ Client modifié !")
                del st.session_state[f"edit_client_{client['id']}"]
                st.rerun()
        if cancelled:
            del st.session_state[f"edit_client_{client['id']}"]
            st.rerun()
