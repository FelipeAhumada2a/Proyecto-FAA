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
