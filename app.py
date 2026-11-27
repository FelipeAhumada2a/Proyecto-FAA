"""HOME DUO · Fase 1 (MVP). App única en Streamlit + Supabase, sin cuentas de correo.

ARCHIVOS DEL REPO: solo app.py y requirements.txt.

PUESTA EN MARCHA
1. Supabase: crea un proyecto. En SQL Editor pega el esquema (está en Ajustes >
   Esquema SQL, o la app lo muestra si falta configuración) y ejecútalo una vez.
2. Supabase > Project Settings > API: copia "Project URL" y la clave "service_role".
3. Streamlit Cloud > tu app > Settings > Secrets:
       SUPABASE_URL = "https://xxxx.supabase.co"
       SUPABASE_KEY = "eyJ... (service_role)"
       APP_PASSWORD = "una-clave-larga-que-solo-saben-ustedes"
4. Cada uno entra con su nombre y la clave compartida.
5. Cotizar automático: crea una cuenta en serper.dev, copia tu API key y agrégala a los
   secrets como SERPER_API_KEY. Sin esa clave la app funciona igual, con alternativas manuales.
   Instalación existente: ejecuta el SQL de Ajustes > "SQL Fase 2" (no borra datos).
"""
import hashlib
import hmac
import re
from datetime import date, datetime
from urllib.parse import urlparse

import requests
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
-- HOME DUO · Esquema Fase 1 (sin cuentas de correo)
-- Ejecutar completo en Supabase > SQL Editor. Borra y recrea las tablas de HOME DUO.

drop table if exists alternatives, activity, comments, purchases, products, categories, household_members, households cascade;
drop function if exists is_member(uuid);
drop function if exists create_household(text, text);
drop function if exists join_household(text, text);

create extension if not exists pgcrypto;

create table households (
  id uuid primary key default gen_random_uuid(),
  name text not null default 'Nuestro departamento',
  total_budget numeric(14,0) not null default 0,
  created_at timestamptz not null default now()
);

create table categories (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  parent_id uuid references categories(id) on delete set null,
  name text not null,
  sort int not null default 0,
  created_at timestamptz not null default now(),
  unique (household_id, name)
);

create table products (
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
  requirements jsonb not null default '[]'::jsonb,
  status text not null default 'Pendiente de cotización' check (status in (
    'Pendiente de cotización','En cotización','En evaluación',
    'Pendiente de compra','Comprado','Descartado')),
  created_by text not null,
  updated_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index idx_products_hh on products(household_id, status);

create table purchases (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  product_id uuid not null references products(id) on delete cascade,
  store text not null,
  final_price numeric(14,0) not null check (final_price >= 0),
  purchase_date date not null default current_date,
  purchase_url text,
  order_number text,
  comments text,
  registered_by text not null,
  created_at timestamptz not null default now()
);
create index idx_purchases_hh on purchases(household_id);

create table comments (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  product_id uuid not null references products(id) on delete cascade,
  user_id text not null,
  body text not null check (length(body) between 1 and 2000),
  created_at timestamptz not null default now()
);
create index idx_comments_product on comments(product_id, created_at);

create table activity (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  user_id text not null,
  product_id uuid references products(id) on delete set null,
  action text not null,
  detail text,
  created_at timestamptz not null default now()
);
create index idx_activity_hh on activity(household_id, created_at desc);

create table alternatives (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  product_id uuid not null references products(id) on delete cascade,
  store text not null,
  title text not null,
  brand text,
  price numeric(14,0),
  old_price numeric(14,0),
  url text not null,
  image_url text,
  free_shipping boolean,
  source text not null default 'Manual',
  retrieved_at timestamptz not null default now(),
  added_by text,
  favorited_by text[] not null default '{}',
  created_at timestamptz not null default now(),
  unique (product_id, url)
);
create index idx_alt_product on alternatives(product_id);

-- RLS activo y SIN políticas: la clave pública (anon) no puede leer ni escribir nada.
-- La app accede con la clave service_role, guardada solo en los secrets del servidor.
alter table households enable row level security;
alter table categories enable row level security;
alter table products   enable row level security;
alter table purchases  enable row level security;
alter table comments   enable row level security;
alter table activity   enable row level security;
alter table alternatives enable row level security;

-- Permisos para la clave service_role (algunos proyectos nuevos no los dan por defecto).
grant usage on schema public to service_role;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
"""

MIGRATION_F2 = """
-- HOME DUO · Fase 2 (instalación existente; NO borra datos)
create table if not exists alternatives (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references households(id) on delete cascade,
  product_id uuid not null references products(id) on delete cascade,
  store text not null,
  title text not null,
  brand text,
  price numeric(14,0),
  old_price numeric(14,0),
  url text not null,
  image_url text,
  free_shipping boolean,
  source text not null default 'Manual',
  retrieved_at timestamptz not null default now(),
  added_by text,
  favorited_by text[] not null default '{}',
  created_at timestamptz not null default now(),
  unique (product_id, url)
);
create index if not exists idx_alt_product on alternatives(product_id);
alter table alternatives enable row level security;
grant all on all tables in schema public to service_role;
"""

DEFAULT_CATEGORIES = ["Living", "Comedor", "Cocina", "Electrodomésticos", "Dormitorio principal",
                      "Dormitorio secundario", "Baño", "Terraza", "Decoración", "Iluminación",
                      "Tecnología", "Organización", "Herramientas", "Otros"]

# ───────────────────────── Estilo ─────────────────────────
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@500;700&family=Figtree:wght@400;500;600&display=swap');
:root { --sand:#EFE8DB; --bone:#FBF9F4; --ink:#2B2A26; --moss:#44532A; --stone:#8A877D; }
html, body, [class*="css"], .stApp { font-family:'Figtree', sans-serif; color:var(--ink); }
.stApp { background: var(--bone); }
h1, h2, h3 { font-family:'Bricolage Grotesque', sans-serif !important; letter-spacing:-0.02em; }
header[data-testid="stHeader"] { background: var(--bone); }
.block-container { padding-top:4.5rem; padding-bottom:5rem; max-width:760px; }
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
            "detail": detail, "product_id": product_id,
            "user_id": st.session_state["uid"]}).execute()
    except Exception:
        pass  # el historial nunca debe bloquear la acción principal


def load_household():
    rows = db().table("households").select("*").order("created_at").limit(1).execute().data
    if rows:
        hh = rows[0]
    else:  # primera vez: crea el hogar y las categorías iniciales
        hh = db().table("households").insert({"name": "Nuestro departamento"}).execute().data[0]
        db().table("categories").insert(
            [{"household_id": hh["id"], "name": n, "sort": i} for i, n in enumerate(DEFAULT_CATEGORIES)]).execute()
    st.session_state["hid"] = hh["id"]
    st.session_state["hh"] = hh


def fetch(table: str, order: str = "created_at", desc: bool = True, limit: int | None = None):
    q = db().table(table).select("*").eq("household_id", st.session_state["hid"]).order(order, desc=desc)
    if limit:
        q = q.limit(limit)
    return q.execute().data


def who(uid: str) -> str:
    return uid or "Alguien"


# ───────────────────────── Autenticación ─────────────────────────
def _sig(name: str) -> str:
    key = str(st.secrets["APP_PASSWORD"]).encode()
    return hmac.new(key, name.encode(), hashlib.sha256).hexdigest()[:32]


def restore_session():
    """Recupera la sesión desde el token firmado del link (sobrevive a recargar la página)."""
    token = st.query_params.get("s", "")
    if "." in token:
        name, sig = token.rsplit(".", 1)
        if name and hmac.compare_digest(sig, _sig(name)):
            st.session_state["uid"] = name


def auth_screen():
    st.markdown("## HOME DUO")
    st.caption("Equipar el departamento, de a dos.")
    with st.form("login"):
        name = st.text_input("Tu nombre")
        pw = st.text_input("Clave de la casa", type="password")
        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            if not name.strip():
                st.warning("Escribe tu nombre.")
            elif not hmac.compare_digest(pw, str(st.secrets["APP_PASSWORD"])):
                st.error("Clave incorrecta.")
            else:
                st.session_state["uid"] = name.strip()
                st.query_params["s"] = f"{name.strip()}.{_sig(name.strip())}"
                st.rerun()


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
                data["created_by"] = st.session_state["uid"]
                res = db().table("products").insert(data).execute()
                log("Producto agregado", name.strip(), res.data[0]["id"])
                if search_ready():
                    with st.spinner("Buscando alternativas en tiendas de Chile…"):
                        auto_quote(res.data[0])
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
                "order_number": order.strip() or None, "comments": comm.strip() or None,
                "registered_by": st.session_state["uid"]}).execute()
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
                                               "body": body.strip(), "user_id": st.session_state["uid"]}).execute()
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
    st.markdown("### Sesión")
    st.write(f"Entraste como **{st.session_state['uid']}**.")
    with st.expander("Diagnóstico de tiendas (avanzado)"):
        diagnostics_ui()
    with st.expander("SQL Fase 2 (instalación existente)"):
        st.code(MIGRATION_F2, language="sql")
    with st.expander("Esquema SQL completo (instalación nueva; BORRA datos)"):
        st.code(SCHEMA_SQL, language="sql")
    if st.button("Cerrar sesión", use_container_width=True):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()


# ───────────────────────── Fase 2 · Cotizaciones ─────────────────────────
HEADERS = {"User-Agent": "HOME-DUO/1.0 (herramienta personal de cotización)", "Accept-Language": "es-CL,es;q=0.9"}
STORE_LIST = ["Falabella", "Paris", "Ripley", "Sodimac", "Easy", "Lider", "Hites", "ABC", "La Polar"]


@st.cache_data(ttl=3600, show_spinner=False)
def robots_allows(url: str):
    """True/False según el robots.txt del sitio; None si no se pudo leer."""
    from urllib.robotparser import RobotFileParser
    p = urlparse(url)
    try:
        r = requests.get(f"{p.scheme}://{p.netloc}/robots.txt", headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp.can_fetch(HEADERS["User-Agent"], url)
    except Exception:
        return None


def diagnose_url(url: str) -> dict:
    """Informa qué ve la app (desde Streamlit Cloud) al pedir una página. No guarda nada."""
    out = {"robots.txt permite esta URL": robots_allows(url)}
    if out["robots.txt permite esta URL"] is False:
        out["conclusión"] = "El sitio no permite acceso automatizado a esta ruta: no se consulta."
        return out
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
    except Exception as e:
        out["error"] = str(e)
        return out
    t = r.text
    m = re.search(r"<title[^>]*>(.*?)</title>", t, re.S | re.I)
    out.update({
        "HTTP": r.status_code,
        "tamaño (bytes)": len(r.content),
        "título": (m.group(1).strip()[:120] if m else None),
        "tiene JSON-LD (datos estructurados)": "application/ld+json" in t,
        "tiene __NEXT_DATA__": "__NEXT_DATA__" in t,
        "aparecen precios en el HTML": bool(re.search(r"\$\s?\d", t)),
        "señales de bloqueo": any(k in t.lower() for k in ("captcha", "access denied", "cloudflare", "akamai", "unusual traffic")),
    })
    return out


def _int(x):
    try:
        return int(round(float(x))) if x else None
    except (TypeError, ValueError):
        return None


def search_ready() -> bool:
    return bool(st.secrets.get("SERPER_API_KEY"))


def _price_clp(txt):
    m = re.search(r"\d[\d\.,]*", str(txt or ""))
    return _int(re.sub(r"\D", "", m.group(0))) if m else None


def build_queries(p: dict) -> list:
    """Consulta 1: producto exacto (nombre + marca + modelo). Consulta 2: equivalentes de cualquier
    marca con las características textuales obligatorias (las medidas numéricas no se pueden buscar)."""
    base = p["name"].strip()
    brand, model = (p.get("brand") or "").strip(), (p.get("model") or "").strip()
    q1 = " ".join(x for x in [base, brand if brand.lower() not in base.lower() else "", model] if x)
    extra = []
    for r in (p.get("requirements") or []):
        if r.get("kind") != "Obligatorio":
            continue
        val, label = (r.get("value") or "").strip(), re.sub(r"\(.*?\)", "", r.get("label") or "").strip()
        if val.lower() in ("sí", "si", "yes", "x") and label:
            extra.append(label)
        elif val and not re.search(r"\d", val) and len(val) <= 25:
            extra.append(val)
    q2 = " ".join([base] + extra[:3])
    return [q1] if q2.lower() == q1.lower() else [q1, q2]


def search_serper(p: dict, limit: int = 20):
    """Google Shopping (Chile) vía Serper. Excluye Mercado Libre. Devuelve (items, estado)."""
    key = st.secrets.get("SERPER_API_KEY")
    if not key:
        return [], "Sin configurar: falta SERPER_API_KEY en los secrets."
    queries = build_queries(p)
    items, errors = {}, []
    for q in queries:
        try:
            r = requests.post("https://google.serper.dev/shopping", timeout=20,
                              headers={"X-API-KEY": str(key), "Content-Type": "application/json"},
                              json={"q": q, "gl": "cl", "hl": "es", "num": limit})
            if r.status_code != 200:
                errors.append(f"HTTP {r.status_code}: {r.text[:150]}")
                continue
            for it in r.json().get("shopping", []):
                store, link = (it.get("source") or "").strip(), it.get("link")
                if not (store and link):
                    continue
                if re.search(r"mercado\s?libre|mercadolibre|mercadolivre", f"{store} {link}", re.I):
                    continue
                items.setdefault(link, {
                    "store": store, "title": it.get("title", ""), "brand": None,
                    "price": _price_clp(it.get("price")), "old_price": None, "url": link,
                    "image_url": it.get("imageUrl"),
                    "free_shipping": True if "gratis" in str(it.get("delivery") or "").lower() else None,
                    "source": "Google Shopping Chile (Serper)"})
        except Exception as e:
            errors.append(str(e))
    msg = f"{len(items)} resultados únicos con {len(queries)} búsqueda(s), sin Mercado Libre"
    return list(items.values()), msg + (" · errores: " + "; ".join(errors) if errors else "")


# Cada fuente es independiente: si una falla, las demás siguen funcionando.
ADAPTERS = {"Google Shopping Chile": search_serper}


def run_search(p: dict):
    found, statuses = [], {}
    for name, fn in ADAPTERS.items():
        items, msg = fn(p)
        statuses[name] = msg
        found += items
    return found, statuses


def auto_quote(p: dict):
    """Busca y guarda alternativas para un producto, y lo pasa a 'En cotización'."""
    try:
        items, statuses = run_search(p)
        st.session_state[f"qs_{p['id']}"] = statuses
        save_alternatives(p, items)
        if items:
            log("Cotización nueva", f"{p['name']}: {len(items)} alternativas", p["id"])
            if p["status"] == "Pendiente de cotización":
                db().table("products").update({"status": "En cotización", "updated_by": st.session_state["uid"],
                                               "updated_at": datetime.utcnow().isoformat() + "Z"}).eq("id", p["id"]).execute()
    except Exception as e:
        st.session_state[f"qs_{p['id']}"] = {"Error": str(e)}


def save_alternatives(p: dict, items: list):
    now = datetime.utcnow().isoformat() + "Z"
    rows = {}
    for it in items:
        rows[it["url"]] = {"household_id": st.session_state["hid"], "product_id": p["id"], "store": it["store"],
                           "title": it["title"], "brand": it.get("brand"), "price": it.get("price"),
                           "old_price": it.get("old_price"), "url": it["url"], "image_url": it.get("image_url"),
                           "free_shipping": it.get("free_shipping"), "source": it["source"],
                           "retrieved_at": now, "added_by": st.session_state["uid"]}
    if rows:
        db().table("alternatives").upsert(list(rows.values()), on_conflict="product_id,url").execute()


def budget_status(p: dict, price):
    mx = p.get("budget_max")
    if not price:
        return "Precio no verificado", None
    if not mx:
        return "Sin presupuesto definido", None
    if price <= float(mx):
        return "Dentro del presupuesto", True
    return f"Excede el máximo por {clp(price - float(mx))}", False


def toggle_fav(a: dict, p: dict):
    me = st.session_state["uid"]
    fav = list(a.get("favorited_by") or [])
    fav.remove(me) if me in fav else fav.append(me)
    db().table("alternatives").update({"favorited_by": fav}).eq("id", a["id"]).execute()
    if me in fav:
        log("Alternativa favorita", f"{p['name']}: {a['title'][:60]}", p["id"])
    st.rerun()


def alt_card(p: dict, a: dict, tag: str = ""):
    status, _ = budget_status(p, a.get("price"))
    with st.container(border=True):
        c1, c2 = st.columns([1, 3])
        if a.get("image_url"):
            c1.image(a["image_url"], width=90)
        c2.markdown((f"{tag}  \n" if tag else "") + f"**{a['title']}**")
        line = f"{a['store']} · **{clp(a.get('price'))}**"
        if a.get("old_price") and a.get("price") and float(a["old_price"]) > float(a["price"]):
            line += f" · antes {clp(a['old_price'])} (-{round((1 - float(a['price']) / float(a['old_price'])) * 100)}%)"
        c2.markdown(line)
        meta = [status]
        pb = (p.get("brand") or "").lower()
        if pb:
            hit = pb in (a.get("brand") or "").lower() or pb in a["title"].lower()
            meta.append("Marca preferida: " + ("sí" if hit else "no"))
        n_req = sum(1 for r in (p.get("requirements") or []) if r.get("kind") == "Obligatorio")
        if n_req:
            meta.append(f"{n_req} requisito(s) obligatorio(s) sin verificar (dimensiones y fichas técnicas aún no se leen)")
        if a.get("free_shipping"):
            meta.append("Despacho gratis")
        meta.append(f"Fuente: {a['source']} · consultado {fmt_dt(a['retrieved_at'])}")
        st.markdown("<span class='muted'>" + "<br>".join(meta) + "</span>", unsafe_allow_html=True)
        if a.get("favorited_by"):
            st.markdown("❤️ Favorito de " + ", ".join(a["favorited_by"]))
        b1, b2, b3 = st.columns(3)
        b1.link_button("Ver tienda", a["url"], use_container_width=True)
        me = st.session_state["uid"]
        if b2.button("Quitar ♥" if me in (a.get("favorited_by") or []) else "♡ Favorito", key=f"fv_{a['id']}", use_container_width=True):
            toggle_fav(a, p)
        if b3.button("Eliminar", key=f"rm_{a['id']}", use_container_width=True):
            db().table("alternatives").delete().eq("id", a["id"]).execute()
            st.rerun()


def page_quotes():
    st.markdown("## Cotizar")
    products = [p for p in fetch("products") if p["status"] not in ("Comprado", "Descartado")]
    if not products:
        st.info("Primero agrega un producto en Productos.")
        return
    by_id = {p["id"]: p for p in products}
    pid = st.selectbox("Producto", list(by_id), format_func=lambda i: by_id[i]["name"])
    p = by_id[pid]
    if p.get("budget_max"):
        st.caption(f"Presupuesto máximo: {clp(p['budget_max'])}")

    if not search_ready():
        st.info("Para buscar automáticamente en tiendas de Chile falta una API de búsqueda: crea una cuenta en "
                "serper.dev y agrega la clave como SERPER_API_KEY en los secrets de Streamlit. Mientras tanto "
                "puedes agregar alternativas manualmente más abajo.")
    elif st.button("Buscar y cotizar alternativas", type="primary", use_container_width=True):
        with st.spinner("Buscando en tiendas de Chile…"):
            auto_quote(p)
    statuses = st.session_state.get(f"qs_{pid}")
    if statuses:
        st.markdown("**Qué se consultó**")
        for store, msg in statuses.items():
            st.caption(f"• {store}: {msg}")

    try:
        alts = db().table("alternatives").select("*").eq("product_id", pid).execute().data
    except Exception as e:
        st.warning("Falta la tabla de alternativas. Ejecuta este SQL en Supabase (no borra datos):")
        st.code(MIGRATION_F2, language="sql")
        st.caption(f"Detalle: {e}")
        return

    if alts:
        found_stores = sorted({a["store"] for a in alts})
        missing = [s for s in STORE_LIST if not any(s.lower() in f.lower() for f in found_stores)]
        st.caption("Tiendas con resultados: " + ", ".join(found_stores))
        if missing:
            st.caption("Sin resultados de: " + ", ".join(missing) + ". La búsqueda no garantiza cubrir todas las "
                       "tiendas; que no aparezcan no significa que no lo vendan.")
    ok = sorted([a for a in alts if budget_status(p, a.get("price"))[1] is not False], key=lambda a: (a.get("price") is None, a.get("price") or 0))
    over = sorted([a for a in alts if budget_status(p, a.get("price"))[1] is False], key=lambda a: a["price"])
    priced = [a for a in ok if a.get("price")]
    cheapest = priced[0]["id"] if priced else None
    st.markdown(f"### Alternativas ({len(alts)})")
    if not alts:
        st.caption("Aún no hay alternativas. Busca en las tiendas o agrega una manualmente abajo.")
    for a in ok:
        alt_card(p, a, "💰 Mejor precio" if a["id"] == cheapest else "")
    if over:
        with st.expander(f"Fuera de presupuesto ({len(over)})"):
            for a in over:
                alt_card(p, a)

    with st.expander("Agregar alternativa manualmente"):
        with st.form(f"man_{pid}", clear_on_submit=True):
            store = st.text_input("Tienda *")
            title = st.text_input("Nombre del producto *")
            url = st.text_input("Link *")
            c1, c2 = st.columns(2)
            price = c1.number_input("Precio actual (CLP)", min_value=0, step=1000)
            old = c2.number_input("Precio anterior (CLP)", min_value=0, step=1000)
            if st.form_submit_button("Guardar alternativa", type="primary"):
                if not (store.strip() and title.strip() and url.strip().startswith("http")):
                    st.warning("Completa tienda, nombre y un link que empiece con http.")
                else:
                    try:
                        save_alternatives(p, [{"store": store.strip(), "title": title.strip(), "url": url.strip(),
                                               "price": int(price) or None, "old_price": int(old) or None,
                                               "source": "Manual"}])
                        log("Cotización nueva", f"{p['name']}: {store.strip()} (manual)", pid)
                        st.rerun()
                    except Exception as e:
                        show_error(e)


def page_favorites():
    st.markdown("## Favoritos")
    try:
        alts = [a for a in fetch("alternatives") if a.get("favorited_by")]
    except Exception as e:
        show_error(e)
        return
    prods = {p["id"]: p for p in fetch("products")}
    if not alts:
        st.info("Todavía no hay favoritos. Márcalos con ♡ desde Cotizar.")
        return
    people = sorted({n for a in alts for n in a["favorited_by"]})
    for person in people:
        st.markdown(f"### ❤️ {person}")
        for a in alts:
            if person in a["favorited_by"]:
                p = prods.get(a["product_id"], {"name": "Producto"})
                with st.container(border=True):
                    st.markdown(f"**{p['name']}** — {a['title']}  \n{a['store']} · **{clp(a.get('price'))}**")
                    st.link_button("Ver tienda", a["url"])


def diagnostics_ui():
    st.caption("Pega la URL de una búsqueda o de un producto de una tienda. Muestra qué ve la app y si el sitio "
               "permite el acceso automatizado (robots.txt). No guarda nada.")
    url = st.text_input("URL a probar", placeholder="https://www.tienda.cl/...")
    if st.button("Probar") and url.startswith("http"):
        with st.spinner("Consultando…"):
            st.json(diagnose_url(url.strip()))


def setup_guide(reason: str):
    st.markdown("## Falta configurar Supabase")
    st.warning(reason)
    if "Name or service not known" in reason or "getaddrinfo" in reason:
        st.error("La SUPABASE_URL no existe o está mal escrita. Debe verse así: https://abcdxyz.supabase.co "
                 "(sin /rest/v1, sin barra final y sin espacios).")
    st.markdown("1. En Supabase abre **SQL Editor**, pega este esquema y ejecútalo una vez.")
    st.code(SCHEMA_SQL, language="sql")
    st.markdown("2. En Streamlit Cloud abre **Settings > Secrets** y agrega:")
    st.code('SUPABASE_URL = "https://xxxx.supabase.co"\nSUPABASE_KEY = "eyJ... (service_role)"\n'
            'APP_PASSWORD = "una-clave-larga"', language="toml")
    st.caption("Guarda, reinicia la app (Manage app > Reboot) y recarga esta página.")


# ───────────────────────── Arranque ─────────────────────────
def main():
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_KEY", "APP_PASSWORD") if not st.secrets.get(k)]
    if missing:
        setup_guide("Faltan estos secrets: " + ", ".join(missing))
        st.stop()
    if "client" not in st.session_state:
        try:
            st.session_state["client"] = create_client(str(st.secrets["SUPABASE_URL"]).strip(),
                                                       str(st.secrets["SUPABASE_KEY"]).strip())
        except Exception as e:
            setup_guide(f"No se pudo crear la conexión con Supabase. Detalle: {e}")
            st.stop()

    if "uid" not in st.session_state:
        restore_session()
    if "uid" not in st.session_state:
        auth_screen()
        return

    if "hid" not in st.session_state:
        try:
            load_household()
        except Exception as e:
            setup_guide(f"No se pudo leer la base de datos. Detalle: {e}")
            st.stop()

    pages = {"Inicio": page_home, "Productos": page_products, "Cotizar": page_quotes,
             "Favoritos": page_favorites, "Comprados": page_bought,
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
