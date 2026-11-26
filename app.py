"""HOME DUO · Fase 1 (MVP). App única en Streamlit + Supabase.

ARCHIVOS DEL REPO: solo app.py y requirements.txt.

PUESTA EN MARCHA
1. Supabase: crea un proyecto. En SQL Editor pega el esquema (la app lo muestra
   completo cuando falta configuración, o en Ajustes > Esquema SQL) y ejecútalo una vez.
2. Supabase > Project Settings > API: copia Project URL y la clave "anon public".
   No uses la clave service_role.
3. Streamlit Cloud > tu app > Settings > Secrets:
       SUPABASE_URL = "https://xxxx.supabase.co"
       SUPABASE_ANON_KEY = "eyJ..."
4. Uno crea cuenta y hogar; en Ajustes está el código para que la pareja se una.

LIMITACIONES: sincronización manual (botón Actualizar), la sesión se pierde al
recargar, sin fotos todavía. Fases 2 a 5 pendientes.
"""
from datetime import date, datetime

import streamlit as st
from supabase import create_client

st.set_page_config(page_title="HOME DUO", page_icon="🏠", layout="centered")

# ───────────────────────── Constantes ─────────────────────────
STATUSES = ["Pendiente de cotización", "En cotización", "En evaluación",
            "Pendiente de compra", "Comprado", "Descartado"]
STATUS_COLORS = {  # (fondo, texto)
    "Pendiente de cotización": ("#E9E4D8", "#5C584C"),
    "En cotización": ("#F3E3BE", "#7A5A12"),
    "En evaluación": ("#DCE6F0", "#2F4C6B"),
    "Pendiente de compra": ("#EAD9CF", "#7A4326"),
    "Comprado": ("#D8E3C6", "#3B4D1F"),
    "Descartado": ("#E6E2E0", "#7A7471"),
}
PRIORITIES = ["Alta", "Media", "Baja"]
SPACES = ["", "Living", "Comedor", "Cocina", "Dormitorio principal",
          "Dormitorio secundario", "Baño", "Terraza", "Otro"]
# Plantillas: sugieren características, nunca las exigen.
TEMPLATES = {
    "Sin plantilla": [],
    "Refrigerador": ["Ancho máximo (cm)", "Alto máximo (cm)", "Profundidad máxima (cm)",
                     "Capacidad mínima (litros)", "No Frost", "Tipo de refrigerador",
                     "Eficiencia energética"],
    "Sofá": ["Largo máximo (cm)", "Profundidad máxima (cm)", "Número de cuerpos",
             "Tipo de sofá"],
    "Televisor": ["Tamaño (pulgadas)", "Resolución", "Tecnología"],
    "Cama": ["Tamaño", "Tipo", "Largo (cm)", "Ancho (cm)"],
}
KINDS = ["Obligatorio", "Preferencia"]

SCHEMA_SQL = """
-- HOME DUO · Esquema Fase 1
-- Ejecutar completo en Supabase > SQL Editor (una sola vez).

create extension if not exists pgcrypto;

-- ───────── Tablas ─────────
create table if not exists households (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  invite_code text not null unique,
  total_budget numeric(14,0) not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists household_members (
  household_id uuid not null references households(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  display_name text not null,
  joined_at timestamptz not null default now(),
  primary key (household_id, user_id)
);
create index if not exists idx_members_user on household_members(user_id);

create table if not exists categories (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  parent_id uuid references categories(id) on delete set null,
  name text not null,
  sort int not null default 0,
  created_at timestamptz not null default now(),
  unique (household_id, name)
);

create table if not exists products (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  category_id uuid references categories(id) on delete set null,
  name text not null,
  space text,
  brand text,
  model text,
  budget_min numeric(14,0),
  budget_max numeric(14,0),
  dimensions text,
  color text,
  material text,
  features text,
  quantity int not null default 1 check (quantity > 0),
  priority text not null default 'Media' check (priority in ('Alta','Media','Baja')),
  notes text,
  reference_url text,
  -- Requisitos y preferencias: [{"label": "...", "value": "...", "kind": "Obligatorio"|"Preferencia"}]
  requirements jsonb not null default '[]'::jsonb,
  status text not null default 'Pendiente de cotización' check (status in (
    'Pendiente de cotización','En cotización','En evaluación',
    'Pendiente de compra','Comprado','Descartado')),
  created_by uuid not null default auth.uid() references auth.users(id),
  updated_by uuid references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_products_hh on products(household_id, status);

create table if not exists purchases (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  product_id uuid not null references products(id) on delete cascade,
  store text not null,
  final_price numeric(14,0) not null check (final_price >= 0),
  purchase_date date not null default current_date,
  purchase_url text,
  order_number text,
  comments text,
  registered_by uuid not null default auth.uid() references auth.users(id),
  created_at timestamptz not null default now()
);
create index if not exists idx_purchases_hh on purchases(household_id);

create table if not exists comments (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  product_id uuid not null references products(id) on delete cascade,
  user_id uuid not null default auth.uid() references auth.users(id),
  body text not null check (length(body) between 1 and 2000),
  created_at timestamptz not null default now()
);
create index if not exists idx_comments_product on comments(product_id, created_at);

create table if not exists activity (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  user_id uuid not null default auth.uid() references auth.users(id),
  product_id uuid references products(id) on delete set null,
  action text not null,
  detail text,
  created_at timestamptz not null default now()
);
create index if not exists idx_activity_hh on activity(household_id, created_at desc);

-- ───────── Función de pertenencia ─────────
create or replace function is_member(hid uuid)
returns boolean
language sql stable security definer
set search_path = public
as $$
  select exists (
    select 1 from household_members
    where household_id = hid and user_id = auth.uid()
  );
$$;

-- ───────── Row Level Security ─────────
alter table households        enable row level security;
alter table household_members enable row level security;
alter table categories        enable row level security;
alter table products          enable row level security;
alter table purchases         enable row level security;
alter table comments          enable row level security;
alter table activity          enable row level security;

-- households: solo lectura/edición para miembros. La creación va por RPC.
create policy hh_select on households for select using (is_member(id));
create policy hh_update on households for update using (is_member(id)) with check (is_member(id));

create policy mem_select on household_members for select using (is_member(household_id));
create policy mem_update_own on household_members for update
  using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy cat_all on categories for all
  using (is_member(household_id)) with check (is_member(household_id));
create policy prod_all on products for all
  using (is_member(household_id)) with check (is_member(household_id));
create policy pur_all on purchases for all
  using (is_member(household_id)) with check (is_member(household_id));

create policy com_select on comments for select using (is_member(household_id));
create policy com_insert on comments for insert
  with check (is_member(household_id) and user_id = auth.uid());
create policy com_delete on comments for delete using (user_id = auth.uid());

create policy act_select on activity for select using (is_member(household_id));
create policy act_insert on activity for insert
  with check (is_member(household_id) and user_id = auth.uid());

-- ───────── RPC: crear hogar y unirse con código ─────────
create or replace function create_household(p_name text, p_display text)
returns uuid
language plpgsql security definer
set search_path = public
as $$
declare
  hid uuid;
  cat text;
  i int := 0;
begin
  if auth.uid() is null then raise exception 'No autenticado'; end if;
  if exists (select 1 from household_members where user_id = auth.uid()) then
    raise exception 'Ya perteneces a un hogar';
  end if;

  insert into households (name, invite_code)
  values (p_name, upper(substr(encode(gen_random_bytes(6), 'hex'), 1, 8)))
  returning id into hid;

  insert into household_members (household_id, user_id, display_name)
  values (hid, auth.uid(), p_display);

  foreach cat in array array[
    'Living','Comedor','Cocina','Electrodomésticos','Dormitorio principal',
    'Dormitorio secundario','Baño','Terraza','Decoración','Iluminación',
    'Tecnología','Organización','Herramientas','Otros']
  loop
    insert into categories (household_id, name, sort) values (hid, cat, i);
    i := i + 1;
  end loop;

  return hid;
end;
$$;

create or replace function join_household(p_code text, p_display text)
returns uuid
language plpgsql security definer
set search_path = public
as $$
declare
  hid uuid;
begin
  if auth.uid() is null then raise exception 'No autenticado'; end if;
  if exists (select 1 from household_members where user_id = auth.uid()) then
    raise exception 'Ya perteneces a un hogar';
  end if;

  select id into hid from households where invite_code = upper(trim(p_code));
  if hid is null then raise exception 'Código de invitación inválido'; end if;

  if (select count(*) from household_members where household_id = hid) >= 2 then
    raise exception 'Este hogar ya tiene dos integrantes';
  end if;

  insert into household_members (household_id, user_id, display_name)
  values (hid, auth.uid(), p_display);
  return hid;
end;
$$;

revoke all on function create_household(text, text) from public, anon;
revoke all on function join_household(text, text) from public, anon;
grant execute on function create_household(text, text) to authenticated;
grant execute on function join_household(text, text) to authenticated;

-- Sincronización en tiempo real (se usará en una fase posterior)
alter publication supabase_realtime add table products, comments, activity;
"""

# ───────────────────────── Estilo ─────────────────────────
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@500;700&family=Figtree:wght@400;500;600&display=swap');
:root { --sand:#EFE8DB; --bone:#FBF9F4; --ink:#2B2A26; --moss:#44532A; --stone:#8A877D; }
html, body, [class*="css"], .stApp { font-family:'Figtree', sans-serif; color:var(--ink); }
.stApp { background: var(--bone); }
h1, h2, h3 { font-family:'Bricolage Grotesque', sans-serif !important; letter-spacing:-0.02em; }
.block-container { padding-top:1.6rem; padding-bottom:5rem; max-width:760px; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius:16px; border-color:#E3DBCB; background:#fff; }
.stButton > button, .stFormSubmitButton > button { border-radius:12px; border:1px solid #D9D0BD; min-height:2.6rem; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] { background:var(--moss); border-color:var(--moss); color:#fff; }
.badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:.78rem; font-weight:600; }
.muted { color:var(--stone); font-size:.85rem; }
.big { font-family:'Bricolage Grotesque'; font-size:2rem; font-weight:700; line-height:1.1; }
.stProgress > div > div > div > div { background-color: var(--moss); }
@media (max-width: 640px) { .block-container { padding-left:1rem; padding-right:1rem; } }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ───────────────────────── Utilidades ─────────────────────────
def clp(n) -> str:
    return "—" if n in (None, "") else "$" + f"{int(n):,}".replace(",", ".")


def badge(status: str) -> str:
    bg, fg = STATUS_COLORS[status]
    return f'<span class="badge" style="background:{bg};color:{fg}">{status}</span>'


def fmt_dt(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d-%m-%Y %H:%M")
    except Exception:
        return iso or ""


def db():
    return st.session_state["client"]


def show_error(e: Exception):
    msg = getattr(e, "message", None) or str(e)
    st.error(f"No se pudo completar la acción: {msg}")


# ───────────────────────── Acceso a datos ─────────────────────────
def log(action: str, detail: str = "", product_id: str | None = None):
    try:
        db().table("activity").insert({
            "household_id": st.session_state["hid"], "action": action,
            "detail": detail, "product_id": product_id}).execute()
    except Exception:
        pass  # el historial nunca debe bloquear la acción principal


def load_household():
    uid = st.session_state["uid"]
    rows = db().table("household_members").select("*").eq("user_id", uid).execute().data
    if not rows:
        st.session_state["hid"] = None
        return
    st.session_state["hid"] = rows[0]["household_id"]
    hid = st.session_state["hid"]
    st.session_state["hh"] = db().table("households").select("*").eq("id", hid).single().execute().data
    members = db().table("household_members").select("*").eq("household_id", hid).execute().data
    st.session_state["members"] = {m["user_id"]: m["display_name"] for m in members}


def fetch(table: str, order: str = "created_at", desc: bool = True, limit: int | None = None):
    q = db().table(table).select("*").eq("household_id", st.session_state["hid"]).order(order, desc=desc)
    if limit:
        q = q.limit(limit)
    return q.execute().data


def who(uid: str) -> str:
    return st.session_state["members"].get(uid, "Alguien")


# ───────────────────────── Autenticación ─────────────────────────
def auth_screen():
    st.markdown("## HOME DUO")
    st.caption("Equipar el departamento, de a dos.")
    tab_in, tab_up = st.tabs(["Iniciar sesión", "Crear cuenta"])
    with tab_in:
        with st.form("login"):
            email = st.text_input("Correo")
            pw = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Entrar", type="primary", use_container_width=True):
                try:
                    res = st.session_state["client"].auth.sign_in_with_password({"email": email, "password": pw})
                    st.session_state["uid"] = res.user.id
                    st.rerun()
                except Exception as e:
                    show_error(e)
    with tab_up:
        with st.form("signup"):
            email = st.text_input("Correo", key="su_mail")
            pw = st.text_input("Contraseña (mínimo 8 caracteres)", type="password", key="su_pw")
            if st.form_submit_button("Crear cuenta", type="primary", use_container_width=True):
                try:
                    res = st.session_state["client"].auth.sign_up({"email": email, "password": pw})
                    if res.session:
                        st.session_state["uid"] = res.user.id
                        st.rerun()
                    else:
                        st.success("Cuenta creada. Confirma tu correo y luego inicia sesión.")
                except Exception as e:
                    show_error(e)


def onboarding():
    st.markdown("## Tu hogar compartido")
    st.caption("Uno de los dos crea el hogar y comparte el código con el otro.")
    t1, t2 = st.tabs(["Crear hogar", "Unirme con código"])
    with t1:
        with st.form("create_hh"):
            name = st.text_input("Nombre del hogar", value="Nuestro departamento")
            me = st.text_input("Tu nombre")
            if st.form_submit_button("Crear hogar", type="primary", use_container_width=True):
                if not name.strip() or not me.strip():
                    st.warning("Completa ambos campos.")
                else:
                    try:
                        db().rpc("create_household", {"p_name": name.strip(), "p_display": me.strip()}).execute()
                        load_household()
                        log("Hogar creado", name.strip())
                        st.rerun()
                    except Exception as e:
                        show_error(e)
    with t2:
        with st.form("join_hh"):
            code = st.text_input("Código de invitación")
            me = st.text_input("Tu nombre", key="join_name")
            if st.form_submit_button("Unirme", type="primary", use_container_width=True):
                try:
                    db().rpc("join_household", {"p_code": code, "p_display": me.strip()}).execute()
                    load_household()
                    log("Se unió al hogar", me.strip())
                    st.rerun()
                except Exception as e:
                    show_error(e)


# ───────────────────────── Productos ─────────────────────────
def cat_maps():
    cats = fetch("categories", order="sort", desc=False)
    return cats, {c["id"]: c["name"] for c in cats}


@st.dialog("Producto")
def product_dialog(p: dict | None = None):
    cats, cat_names = cat_maps()
    p = p or {}
    editing = bool(p.get("id"))

    tpl = "Sin plantilla"
    if not editing:
        tpl = st.selectbox("Plantilla de características", list(TEMPLATES), help="Solo sugiere filas; puedes borrar las que no apliquen.")

    name = st.text_input("Nombre del producto *", value=p.get("name", ""))
    c1, c2 = st.columns(2)
    cat_ids = [None] + [c["id"] for c in cats]
    cur_cat = p.get("category_id")
    cat_id = c1.selectbox("Categoría", cat_ids, index=cat_ids.index(cur_cat) if cur_cat in cat_ids else 0,
                          format_func=lambda i: "Sin categoría" if i is None else cat_names[i])
    space = c2.selectbox("Espacio", SPACES, index=SPACES.index(p["space"]) if p.get("space") in SPACES else 0)
    c1, c2 = st.columns(2)
    brand = c1.text_input("Marca preferida", value=p.get("brand") or "")
    model = c2.text_input("Modelo (opcional)", value=p.get("model") or "")
    c1, c2 = st.columns(2)
    bmin = c1.number_input("Presupuesto mínimo (CLP)", min_value=0, step=10000, value=int(p.get("budget_min") or 0))
    bmax = c2.number_input("Presupuesto máximo (CLP)", min_value=0, step=10000, value=int(p.get("budget_max") or 0))
    c1, c2 = st.columns(2)
    qty = c1.number_input("Cantidad", min_value=1, step=1, value=int(p.get("quantity") or 1))
    prio = c2.selectbox("Prioridad", PRIORITIES, index=PRIORITIES.index(p.get("priority", "Media")))
    c1, c2 = st.columns(2)
    color = c1.text_input("Color", value=p.get("color") or "")
    material = c2.text_input("Material", value=p.get("material") or "")
    dims = st.text_input("Dimensiones", value=p.get("dimensions") or "", placeholder="Ej: máx. 60 × 180 × 65 cm")

    st.markdown("**Requisitos y preferencias**")
    st.caption("Obligatorio = el producto debe cumplirlo. Preferencia = deseable, puede ser flexible.")
    rows = p.get("requirements") or [{"label": l, "value": "", "kind": "Obligatorio"} for l in TEMPLATES.get(tpl, [])]
    edited = st.data_editor(
        rows if rows else [{"label": "", "value": "", "kind": "Preferencia"}],
        key=f"req_{p.get('id', 'new')}_{tpl}", num_rows="dynamic", use_container_width=True,
        column_config={
            "label": st.column_config.TextColumn("Característica"),
            "value": st.column_config.TextColumn("Valor"),
            "kind": st.column_config.SelectboxColumn("Tipo", options=KINDS, default="Preferencia"),
        })
    features = st.text_area("Características deseadas (texto libre)", value=p.get("features") or "")
    url = st.text_input("Link de referencia", value=p.get("reference_url") or "")
    notes = st.text_area("Observaciones", value=p.get("notes") or "")

    if editing:
        status = st.selectbox("Estado", [s for s in STATUSES if s != "Comprado" or p.get("status") == "Comprado"],
                              index=[s for s in STATUSES if s != "Comprado" or p.get("status") == "Comprado"].index(p["status"]))
    else:
        status = STATUSES[0]

    if st.button("Guardar cambios" if editing else "Agregar producto", type="primary", use_container_width=True):
        if not name.strip():
            st.warning("El nombre es obligatorio.")
            return
        if bmax and bmin and bmin > bmax:
            st.warning("El presupuesto mínimo no puede superar al máximo.")
            return
        reqs = [{"label": (r.get("label") or "").strip(), "value": (r.get("value") or "").strip(),
                 "kind": r.get("kind") or "Preferencia"}
                for r in (edited if isinstance(edited, list) else edited.to_dict("records"))
                if (r.get("label") or "").strip()]
        data = {
            "name": name.strip(), "category_id": cat_id, "space": space or None,
            "brand": brand.strip() or None, "model": model.strip() or None,
            "budget_min": bmin or None, "budget_max": bmax or None,
            "quantity": int(qty), "priority": prio, "color": color.strip() or None,
            "material": material.strip() or None, "dimensions": dims.strip() or None,
            "features": features.strip() or None, "reference_url": url.strip() or None,
            "notes": notes.strip() or None, "requirements": reqs, "status": status,
            "updated_by": st.session_state["uid"], "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        try:
            if editing:
                db().table("products").update(data).eq("id", p["id"]).execute()
                log("Producto editado", name.strip(), p["id"])
            else:
                data["household_id"] = st.session_state["hid"]
                res = db().table("products").insert(data).execute()
                log("Producto agregado", name.strip(), res.data[0]["id"])
            st.rerun()
        except Exception as e:
            show_error(e)


@st.dialog("Registrar compra")
def purchase_dialog(p: dict):
    st.markdown(f"**{p['name']}**")
    store = st.text_input("Tienda *")
    price = st.number_input("Precio final (CLP) *", min_value=0, step=1000, value=int(p.get("budget_max") or 0))
    d = st.date_input("Fecha de compra", value=date.today())
    url = st.text_input("Link de compra")
    order = st.text_input("Número de pedido (opcional)")
    comm = st.text_area("Comentarios")
    c1, c2 = st.columns(2)
    if c1.button("Cancelar", use_container_width=True):
        st.session_state[f"st_{p['id']}"] = p["status"]
        st.rerun()
    if c2.button("Guardar compra", type="primary", use_container_width=True):
        if not store.strip() or price <= 0:
            st.warning("Indica la tienda y el precio final.")
            return
        try:
            db().table("purchases").insert({
                "household_id": st.session_state["hid"], "product_id": p["id"], "store": store.strip(),
                "final_price": int(price), "purchase_date": d.isoformat(), "purchase_url": url.strip() or None,
                "order_number": order.strip() or None, "comments": comm.strip() or None}).execute()
            db().table("products").update({"status": "Comprado", "updated_by": st.session_state["uid"],
                                           "updated_at": datetime.utcnow().isoformat() + "Z"}).eq("id", p["id"]).execute()
            log("Producto comprado", f"{p['name']} · {store.strip()} · {clp(price)}", p["id"])
            st.rerun()
        except Exception as e:
            show_error(e)


def comments_block(p: dict):
    try:
        cms = (db().table("comments").select("*").eq("product_id", p["id"]).order("created_at").execute().data)
    except Exception as e:
        show_error(e)
        return
    for c in cms:
        st.markdown(f"**{who(c['user_id'])}** · <span class='muted'>{fmt_dt(c['created_at'])}</span><br>{c['body']}",
                    unsafe_allow_html=True)
    with st.form(f"cf_{p['id']}", clear_on_submit=True):
        body = st.text_input("Escribe un comentario", label_visibility="collapsed", placeholder="Escribe un comentario")
        if st.form_submit_button("Comentar") and body.strip():
            try:
                db().table("comments").insert({"household_id": st.session_state["hid"], "product_id": p["id"],
                                               "body": body.strip()}).execute()
                log("Comentario agregado", f"{p['name']}: {body.strip()[:80]}", p["id"])
                st.rerun()
            except Exception as e:
                show_error(e)


def product_card(p: dict, cat_names: dict):
    with st.container(border=True):
        st.markdown(f"**{p['name']}**  \n{badge(p['status'])}", unsafe_allow_html=True)
        bits = [cat_names.get(p.get("category_id")), p.get("space"), p.get("brand"),
                f"x{p['quantity']}" if p["quantity"] > 1 else None, f"Prioridad {p['priority'].lower()}"]
        st.markdown(f"<span class='muted'>{' · '.join(b for b in bits if b)}</span>", unsafe_allow_html=True)
        if p.get("budget_max"):
            rng = f"{clp(p['budget_min'])} – {clp(p['budget_max'])}" if p.get("budget_min") else f"hasta {clp(p['budget_max'])}"
            st.markdown(f"Presupuesto: **{rng}**")
        reqs = p.get("requirements") or []
        if reqs:
            st.markdown("<span class='muted'>" + " · ".join(
                f"{'● ' if r['kind'] == 'Obligatorio' else '○ '}{r['label']}{': ' + r['value'] if r['value'] else ''}"
                for r in reqs) + "</span>", unsafe_allow_html=True)
        st.markdown(f"<span class='muted'>Agregado por {who(p['created_by'])} · {fmt_dt(p['created_at'])}"
                    + (f" · editado por {who(p['updated_by'])}" if p.get("updated_by") else "") + "</span>",
                    unsafe_allow_html=True)
        if p.get("reference_url"):
            st.markdown(f"[Link de referencia]({p['reference_url']})")

        if p["status"] == "Comprado":
            st.caption("Ya comprado: el detalle está en la pestaña Comprados.")
        else:
            cur = p["status"]
            new = st.selectbox("Estado", STATUSES, index=STATUSES.index(cur), key=f"st_{p['id']}",
                               label_visibility="collapsed")
            if new != cur:
                if new == "Comprado":
                    purchase_dialog(p)
                else:
                    try:
                        db().table("products").update({"status": new, "updated_by": st.session_state["uid"],
                                                       "updated_at": datetime.utcnow().isoformat() + "Z"}).eq("id", p["id"]).execute()
                        log("Estado actualizado", f"{p['name']}: {cur} → {new}", p["id"])
                        st.rerun()
                    except Exception as e:
                        show_error(e)
        c1, c2 = st.columns(2)
        if c1.button("Editar", key=f"ed_{p['id']}", use_container_width=True):
            product_dialog(p)
        with c2.popover("Comentarios", use_container_width=True):
            comments_block(p)


# ───────────────────────── Páginas ─────────────────────────
def page_home():
    hh = st.session_state["hh"]
    products = fetch("products")
    purchases = fetch("purchases")
    st.markdown(f"## {hh['name']}")

    planned = [p for p in products if p["status"] != "Descartado"]
    bought = [p for p in products if p["status"] == "Comprado"]
    pct = len(bought) / len(planned) if planned else 0
    st.markdown(f"<div class='big'>{int(pct * 100)}%</div><div class='muted'>equipado · {len(bought)} de {len(planned)} productos comprados</div>",
                unsafe_allow_html=True)
    st.progress(pct)

    counts = {s: sum(1 for p in products if p["status"] == s) for s in STATUSES}
    cols = st.columns(3)
    for i, s in enumerate(STATUSES):
        cols[i % 3].markdown(f"{badge(s)}<div class='big'>{counts[s]}</div>", unsafe_allow_html=True)

    st.markdown("### Presupuesto")
    total = float(hh.get("total_budget") or 0)
    spent = sum(float(x["final_price"]) for x in purchases)
    pending = sum(float(p.get("budget_max") or 0) * p["quantity"]
                  for p in products if p["status"] not in ("Comprado", "Descartado"))
    c1, c2 = st.columns(2)
    c1.metric("Presupuesto total", clp(total) if total else "Sin definir")
    c2.metric("Gastado", clp(spent))
    c1, c2 = st.columns(2)
    c1.metric("Estimado pendiente", clp(pending))
    c2.metric("Restante", clp(total - spent) if total else "—")
    if total:
        used = spent / total
        st.progress(min(used, 1.0), text=f"{int(used * 100)}% del presupuesto utilizado")
        if spent > total:
            st.error("Ya superaron el presupuesto total.")
        elif spent + pending > total:
            st.warning("Lo gastado más lo estimado pendiente supera el presupuesto total.")
        elif used >= 0.85:
            st.warning("Están cerca del presupuesto total.")
    else:
        st.caption("Define el presupuesto total en Configuración.")

    st.markdown("### Actividad reciente")
    acts = fetch("activity", limit=12)
    if not acts:
        st.caption("Aún no hay actividad. Agrega el primer producto desde Productos.")
    for a in acts:
        st.markdown(f"**{who(a['user_id'])}** · {a['action']}" + (f" — {a['detail']}" if a.get("detail") else "")
                    + f"  \n<span class='muted'>{fmt_dt(a['created_at'])}</span>", unsafe_allow_html=True)


def page_products():
    cats, cat_names = cat_maps()
    st.markdown("## Productos")
    if st.button("+ Agregar producto", type="primary", use_container_width=True):
        product_dialog()
    products = [p for p in fetch("products") if p["status"] != "Comprado"]
    c1, c2 = st.columns(2)
    f_status = c1.multiselect("Estado", [s for s in STATUSES if s != "Comprado"], placeholder="Todos")
    f_cat = c2.multiselect("Categoría", [c["id"] for c in cats], format_func=lambda i: cat_names[i], placeholder="Todas")
    q = st.text_input("Buscar", placeholder="Buscar por nombre o marca", label_visibility="collapsed")
    shown = [p for p in products
             if (not f_status or p["status"] in f_status)
             and (not f_cat or p.get("category_id") in f_cat)
             and (not q or q.lower() in f"{p['name']} {p.get('brand') or ''}".lower())]
    if not products:
        st.info("Todavía no hay productos. Presiona “+ Agregar producto” para empezar.")
    elif not shown:
        st.caption("Ningún producto coincide con los filtros.")
    for p in shown:
        product_card(p, cat_names)


def page_bought():
    st.markdown("## Comprados")
    purchases = fetch("purchases", order="purchase_date")
    prod = {p["id"]: p for p in fetch("products")}
    if not purchases:
        st.info("Aún no han comprado nada. Cuando marquen un producto como Comprado, aparecerá aquí.")
        return
    total = sum(float(x["final_price"]) for x in purchases)
    st.metric("Total gastado", clp(total))
    for x in purchases:
        p = prod.get(x["product_id"], {})
        with st.container(border=True):
            st.markdown(f"**{p.get('name', 'Producto eliminado')}**  \n{badge('Comprado')}", unsafe_allow_html=True)
            st.markdown(f"{x['store']} · **{clp(x['final_price'])}** · {x['purchase_date']}")
            if p.get("budget_max"):
                diff = float(p["budget_max"]) * p.get("quantity", 1) - float(x["final_price"])
                st.caption(f"Ahorro frente al máximo presupuestado: {clp(diff)}" if diff >= 0
                           else f"Excedió el máximo presupuestado por {clp(-diff)}")
            st.markdown(f"<span class='muted'>Registrado por {who(x['registered_by'])}"
                        + (f" · pedido {x['order_number']}" if x.get("order_number") else "") + "</span>",
                        unsafe_allow_html=True)
            if x.get("purchase_url"):
                st.markdown(f"[Link de compra]({x['purchase_url']})")
            if x.get("comments"):
                st.write(x["comments"])


def page_categories():
    cats, cat_names = cat_maps()
    products = fetch("products")
    purchases = fetch("purchases")
    paid = {}
    for x in purchases:
        pr = next((p for p in products if p["id"] == x["product_id"]), None)
        if pr:
            paid[pr.get("category_id")] = paid.get(pr.get("category_id"), 0) + float(x["final_price"])
    st.markdown("## Categorías")
    for c in cats:
        ps = [p for p in products if p.get("category_id") == c["id"]]
        if c.get("parent_id"):
            continue
        subs = [s for s in cats if s.get("parent_id") == c["id"]]
        ids = {c["id"], *[s["id"] for s in subs]}
        ps = [p for p in products if p.get("category_id") in ids]
        n_b = sum(1 for p in ps if p["status"] == "Comprado")
        n_p = sum(1 for p in ps if p["status"] not in ("Comprado", "Descartado"))
        est = sum(float(p.get("budget_max") or 0) * p["quantity"] for p in ps if p["status"] not in ("Descartado",))
        real = sum(paid.get(i, 0) for i in ids)
        with st.container(border=True):
            st.markdown(f"**{c['name']}**" + (f"  <span class='muted'>({', '.join(s['name'] for s in subs)})</span>" if subs else ""),
                        unsafe_allow_html=True)
            st.markdown(f"<span class='muted'>{len(ps)} productos · {n_b} comprados · {n_p} pendientes<br>"
                        f"Estimado {clp(est)} · Gastado {clp(real)}</span>", unsafe_allow_html=True)
    with st.expander("Crear categoría o subcategoría"):
        with st.form("newcat", clear_on_submit=True):
            nm = st.text_input("Nombre")
            tops = [c["id"] for c in cats if not c.get("parent_id")]
            parent = st.selectbox("Pertenece a", [None] + tops, format_func=lambda i: "Categoría principal" if i is None else cat_names[i])
            if st.form_submit_button("Crear", type="primary") and nm.strip():
                try:
                    db().table("categories").insert({"household_id": st.session_state["hid"], "name": nm.strip(),
                                                     "parent_id": parent, "sort": len(cats)}).execute()
                    log("Categoría creada", nm.strip())
                    st.rerun()
                except Exception as e:
                    show_error(e)


def page_settings():
    hh = st.session_state["hh"]
    st.markdown("## Configuración")
    st.markdown("### Hogar")
    with st.form("hh_form"):
        name = st.text_input("Nombre del hogar", value=hh["name"])
        budget = st.number_input("Presupuesto total (CLP)", min_value=0, step=100000, value=int(hh.get("total_budget") or 0))
        if st.form_submit_button("Guardar", type="primary"):
            try:
                db().table("households").update({"name": name.strip(), "total_budget": budget}).eq("id", hh["id"]).execute()
                log("Configuración actualizada", f"Presupuesto total {clp(budget)}")
                load_household()
                st.rerun()
            except Exception as e:
                show_error(e)
    st.markdown("### Integrantes")
    for uid, nm in st.session_state["members"].items():
        st.write(f"• {nm}" + (" (tú)" if uid == st.session_state["uid"] else ""))
    if len(st.session_state["members"]) < 2:
        st.markdown("Comparte este código con tu pareja para que se una:")
        st.code(hh["invite_code"])
    else:
        st.caption("El hogar ya tiene sus dos integrantes; el código de invitación quedó inactivo.")
    with st.expander("Esquema SQL (referencia)"):
        st.code(SCHEMA_SQL, language="sql")
    st.markdown("### Sesión")
    if st.button("Cerrar sesión", use_container_width=True):
        try:
            db().auth.sign_out()
        except Exception:
            pass
        st.session_state.clear()
        st.rerun()


def setup_guide(reason: str):
    st.markdown("## Falta configurar Supabase")
    st.warning(reason)
    st.markdown("1. En Supabase abre **SQL Editor**, pega este esquema y ejecútalo una vez.")
    st.code(SCHEMA_SQL, language="sql")
    st.markdown("2. En Streamlit Cloud abre **Settings > Secrets** y agrega:")
    st.code('SUPABASE_URL = "https://xxxx.supabase.co"\nSUPABASE_ANON_KEY = "eyJ..."', language="toml")
    st.caption("Luego recarga esta página.")


# ───────────────────────── Arranque ─────────────────────────
def main():
    if "client" not in st.session_state:
        try:
            st.session_state["client"] = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
        except Exception:
            setup_guide("Faltan SUPABASE_URL y SUPABASE_ANON_KEY en los secrets de la app.")
            st.stop()

    if "uid" not in st.session_state:
        auth_screen()
        return

    if "hid" not in st.session_state:
        try:
            load_household()
        except Exception as e:
            setup_guide(f"No se pudo leer la base de datos (¿ya ejecutaste el esquema?). Detalle: {e}")
            st.stop()
    if not st.session_state.get("hid"):
        onboarding()
        return

    pages = {"Inicio": page_home, "Productos": page_products, "Comprados": page_bought,
             "Categorías": page_categories, "Ajustes": page_settings}
    choice = st.segmented_control("Navegación", list(pages), default="Inicio", label_visibility="collapsed")
    c1, _ = st.columns([1, 3])
    if c1.button("↻ Actualizar", help="Trae los cambios de tu pareja"):
        load_household()
        st.rerun()
    try:
        pages[choice or "Inicio"]()
    except Exception as e:
        show_error(e)


main()
