


"""HOME DUO — app completa en un solo archivo (Streamlit + Supabase)."""
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="HOME DUO", page_icon="🏠", layout="centered")

# ───────────────────────── Utilidades ─────────────────────────
STATUS = {
    "pendiente_cotizacion": ("Pendiente de cotización", "#9A9A8E"),
    "en_cotizacion": ("En cotización", "#C79A3B"),
    "en_evaluacion": ("En evaluación", "#5B7DB1"),
    "pendiente_compra": ("Pendiente de compra", "#B5651D"),
    "comprado": ("Comprado", "#4F6B3A"),
    "descartado": ("Descartado", "#A04444"),
}
PRIORITY = ["baja", "media", "alta"]


def sb():
    """Cliente por sesión de navegador (nunca compartido entre usuarios)."""
    if "sb" not in st.session_state:
        st.session_state.sb = create_client(
            st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
    return st.session_state.sb


def hid() -> str:
    return st.session_state.hid


def clp(n) -> str:
    return "$" + f"{int(n or 0):,}".replace(",", ".")


def badge(status: str) -> str:
    label, color = STATUS[status]
    return (f"<span style='background:{color};color:#fff;padding:2px 10px;"
            f"border-radius:999px;font-size:0.78rem'>{label}</span>")


def log(entity, entity_id, action, detail=None):
    sb().table("activity_log").insert({
        "household_id": hid(), "entity": entity, "entity_id": entity_id,
        "action": action, "detail": detail or {}}).execute()


def names() -> dict:
    rows = sb().table("profiles").select("id,display_name").execute().data
    return {r["id"]: r["display_name"] for r in rows}


# ───────────────────────── Acceso ─────────────────────────
def login_view():
    st.title("🏠 HOME DUO")
    st.caption("Equipen su departamento juntos.")
    with st.form("login"):
        email = st.text_input("Correo")
        pw = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar", use_container_width=True):
            try:
                r = sb().auth.sign_in_with_password({"email": email, "password": pw})
                st.session_state.user = r.user
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo ingresar: {e}")


def household_setup_view():
    st.title("Tu hogar compartido")
    c1, c2 = st.columns(2)
    with c1:
        with st.form("crear"):
            st.subheader("Crear hogar")
            name = st.text_input("Nombre", value="Nuestro departamento")
            if st.form_submit_button("Crear", use_container_width=True):
                try:
                    sb().rpc("create_household", {"hname": name}).execute()
                    st.rerun()
                except Exception as e:
                    st.error(e)
    with c2:
        with st.form("unirse"):
            st.subheader("Tengo una invitación")
            code = st.text_input("Código")
            if st.form_submit_button("Unirme", use_container_width=True):
                try:
                    sb().rpc("accept_invite", {"invite_code": code.strip()}).execute()
                    st.rerun()
                except Exception as e:
                    st.error(e)


# ───────────────────────── Inicio ─────────────────────────
def page_inicio():
    st.title("🏠 Inicio")
    if st.button("🔄 Actualizar"):
        st.rerun()

    prods = sb().table("products").select("id,status,budget_max,quantity").eq("household_id", hid()).execute().data
    buys = sb().table("purchases").select("final_price").eq("household_id", hid()).execute().data
    total_budget = sb().table("households").select("total_budget").eq("id", hid()).execute().data[0]["total_budget"] or 0

    counts = {k: 0 for k in STATUS}
    for p in prods:
        counts[p["status"]] += 1
    bought = counts["comprado"]
    active = len(prods) - counts["descartado"]
    pct = bought / active if active else 0

    st.subheader("Progreso")
    st.progress(pct, text=f"{bought} de {active} productos comprados ({pct:.0%})")
    cols = st.columns(3)
    for i, (k, (label, _)) in enumerate(STATUS.items()):
        cols[i % 3].metric(label, counts[k])

    st.subheader("Presupuesto")
    spent = sum(b["final_price"] for b in buys)
    pending_est = sum((p["budget_max"] or 0) * p["quantity"] for p in prods
                      if p["status"] not in ("comprado", "descartado"))
    c1, c2 = st.columns(2)
    c1.metric("Presupuesto total", clp(total_budget))
    c2.metric("Gastado", clp(spent))
    c3, c4 = st.columns(2)
    c3.metric("Estimado pendiente", clp(pending_est))
    c4.metric("Restante", clp(total_budget - spent))
    if total_budget:
        used = spent / total_budget
        st.progress(min(used, 1.0), text=f"{used:.0%} del presupuesto utilizado")
        if used > 1:
            st.error("Se excedió el presupuesto total.")
        elif used > 0.85:
            st.warning("El gasto está cerca del presupuesto total.")
    else:
        st.caption("Define el presupuesto total en Configuración.")

    st.subheader("Actividad reciente")
    who = names()
    acts = (sb().table("activity_log").select("*").eq("household_id", hid())
            .order("created_at", desc=True).limit(8).execute().data)
    if not acts:
        st.caption("Aún no hay actividad.")
    for a in acts:
        st.write(f"**{who.get(a['user_id'], 'Alguien')}** · {a['action']} · "
                 f"{(a.get('detail') or {}).get('nombre', '')}  \n"
                 f"<small>{a['created_at'][:16].replace('T', ' ')}</small>",
                 unsafe_allow_html=True)

# ───────────────────────── Productos ─────────────────────────
def page_productos():
    st.title("🛋️ Productos")
    cats = sb().table("categories").select("id,name").eq("household_id", hid()).order("sort_order").execute().data
    cat_name = {c["id"]: c["name"] for c in cats}
    who = names()

    with st.expander("➕ Agregar producto", expanded=False):
        with st.form("nuevo", clear_on_submit=True):
            name = st.text_input("Nombre del producto *")
            cat = st.selectbox("Categoría", [c["id"] for c in cats], format_func=cat_name.get)
            c1, c2 = st.columns(2)    
            brand = c1.text_input("Marca preferida")
            color = c2.text_input("Color")
            b_min = c1.number_input("Presupuesto mínimo (CLP)", min_value=0, step=10000)
            b_max = c2.number_input("Presupuesto máximo (CLP)", min_value=0, step=10000)
            qty = c1.number_input("Cantidad", min_value=1, value=1)
            prio = c2.selectbox("Prioridad", PRIORITY, index=1)
            st.caption("Requisitos obligatorios de medidas (cm, máximo). Déjalos en 0 si no aplican.")
            d1, d2, d3 = st.columns(3)
            w = d1.number_input("Ancho", min_value=0.0)
            h = d2.number_input("Alto", min_value=0.0)
            d = d3.number_input("Profundidad", min_value=0.0)
            url = st.text_input("Link de referencia")
            notes = st.text_area("Observaciones")
            if st.form_submit_button("Guardar", use_container_width=True):
                if not name.strip():
                    st.error("El nombre es obligatorio.")
                else:
                    reqs = [{"key": k, "op": "<=", "value": v, "unit": "cm"}
                            for k, v in (("ancho", w), ("alto", h), ("profundidad", d)) if v]
                    row = sb().table("products").insert({
                        "household_id": hid(), "category_id": cat, "name": name.strip(),
                        "brand": brand or None, "color": color or None,
                        "budget_min": b_min or None, "budget_max": b_max or None,
                        "quantity": qty, "priority": prio, "requirements": reqs,
                        "reference_url": url or None, "notes": notes or None,
                    }).execute().data[0]
                    log("product", row["id"], "agregó producto", {"nombre": row["name"]})
                    st.rerun()

    f1, f2 = st.columns(2)
    f_status = f1.selectbox("Estado", ["Todos"] + list(STATUS),
                            format_func=lambda k: "Todos" if k == "Todos" else STATUS[k][0])
    f_cat = f2.selectbox("Categoría", ["Todas"] + [c["id"] for c in cats],
                         format_func=lambda k: "Todas" if k == "Todas" else cat_name[k])

    q = sb().table("products").select("*").eq("household_id", hid()).neq("status", "comprado")
    if f_status != "Todos":
        q = q.eq("status", f_status)
    if f_cat != "Todas":
        q = q.eq("category_id", f_cat)
    prods = q.order("created_at", desc=True).execute().data

    if not prods:
        st.info("No hay productos con estos filtros. Agrega el primero arriba.")

    for p in prods:
        with st.container(border=True):
            st.markdown(f"**{p['name']}** &nbsp; {badge(p['status'])}", unsafe_allow_html=True)
            budget = f"hasta {clp(p['budget_max'])}" if p["budget_max"] else "sin presupuesto"
            st.caption(f"{cat_name.get(p['category_id'], '—')} · {budget} · x{p['quantity']} · "
                       f"prioridad {p['priority']} · agregó {who.get(p['created_by'], '—')}")
            if p["requirements"]:
                st.caption("Obligatorio: " + ", ".join(
                    f"{r['key']} {r['op']} {r['value']:g} {r['unit']}" for r in p["requirements"]))
            if p["reference_url"]:
                st.link_button("Ver referencia", p["reference_url"])
            with st.expander("Gestionar"):
                opts = [k for k in STATUS if k != "comprado"]
                new = st.selectbox("Estado", opts,
                                   index=opts.index(p["status"]) if p["status"] in opts else 0,
                                   format_func=lambda k: STATUS[k][0], key=f"s{p['id']}")
                if new != p["status"]:
                    sb().table("products").update({"status": new}).eq("id", p["id"]).execute()
                    log("product", p["id"], f"cambió estado a {STATUS[new][0]}", {"nombre": p["name"]})
                    st.rerun()
                st.markdown("**Registrar compra**")
                with st.form(f"buy{p['id']}"):
                    store = st.text_input("Tienda")
                    price = st.number_input("Precio final (CLP)", min_value=0, step=1000)
                    order = st.text_input("N° de pedido (opcional)")
                    link = st.text_input("Link de compra (opcional)")
                    note = st.text_input("Comentarios")
                    if st.form_submit_button("Marcar como comprado"):
                        if not price:
                            st.error("Ingresa el precio final.")
                        else:
                            sb().table("purchases").insert({
                                "household_id": hid(), "product_id": p["id"], "store": store or None,
                                "final_price": price, "order_number": order or None,
                                "url": link or None, "notes": note or None}).execute()
                            sb().table("products").update({"status": "comprado"}).eq("id", p["id"]).execute()
                            log("product", p["id"], "registró compra", {"nombre": p["name"]})
                            st.rerun()


# ───────────────────────── Comprados ─────────────────────────
def page_comprados():
    st.title("✅ Comprados")
    who = names()
    rows = (sb().table("purchases").select("*, products(name)").eq("household_id", hid())
            .order("purchased_at", desc=True).execute().data)
    if not rows:
        st.info("Todavía no han registrado compras.")
    else:
        st.metric("Total gastado", clp(sum(r["final_price"] for r in rows)))
    for r in rows:
        with st.container(border=True):
            st.markdown(f"**{r['products']['name']}** — {clp(r['final_price'])}")
            st.caption(f"{r['store'] or 'Tienda no indicada'} · {r['purchased_at']} · "
                       f"registró {who.get(r['registered_by'], '—')}"
                       + (f" · pedido {r['order_number']}" if r["order_number"] else ""))
            if r["notes"]:
                st.write(r["notes"])
            if r["url"]:
                st.link_button("Link de compra", r["url"])


# ───────────────────────── Configuración ─────────────────────────
def page_config():
    st.title("⚙️ Configuración")
    st.subheader("Presupuesto total")
    cur = sb().table("households").select("total_budget").eq("id", hid()).execute().data[0]["total_budget"] or 0
    with st.form("budget"):
        val = st.number_input("Presupuesto total del departamento (CLP)",
                              min_value=0, step=100000, value=int(cur))
        if st.form_submit_button("Guardar"):
            sb().table("households").update({"total_budget": val}).eq("id", hid()).execute()
            st.success("Guardado.")

    st.subheader("Miembros")
    members = sb().table("household_members").select("user_id").eq("household_id", hid()).execute().data
    who = names()
    for m in members:
        st.write("• " + who.get(m["user_id"], "Miembro"))

    if len(members) < 2:
        st.subheader("Invitar a tu pareja")
        if st.button("Generar código de invitación"):
            inv = sb().table("invites").insert(
                {"household_id": hid(), "created_by": st.session_state.user.id}).execute().data[0]
            st.code(inv["code"])
            st.caption("Compártelo con tu pareja: lo ingresa en 'Tengo una invitación'. Vence en 7 días.")

    st.divider()
    if st.button("Cerrar sesión"):
        sb().auth.sign_out()
        st.session_state.clear()
        st.rerun()


# ───────────────────────── Arranque ─────────────────────────
if "user" not in st.session_state:
    login_view()
    st.stop()

if "hid" not in st.session_state:
    m = sb().table("household_members").select("household_id").limit(1).execute().data
    if not m:
        household_setup_view()
        st.stop()
    st.session_state.hid = m[0]["household_id"]

PAGES = {"🏠 Inicio": page_inicio, "🛋️ Productos": page_productos,
         "✅ Comprados": page_comprados, "⚙️ Config": page_config}
choice = st.radio("Menú", list(PAGES), horizontal=True, label_visibility="collapsed")
PAGES[choice]()










































































































































































































































































































































































