-- ============================================================
-- LexEC — Schema completo para Supabase
-- Pegar TODO esto en: Supabase → SQL Editor → New query → Run
-- ============================================================

-- Tabla principal de normas
create table if not exists normas (
  id           uuid primary key default gen_random_uuid(),
  titulo       text not null,
  numero_ro    text,
  numero_norma text,
  jerarquia    text not null default 'Otro',
  origen       text,
  tematica     text,
  vigencia     text not null default 'Vigente',
  fecha_pub    date,
  url_pdf      text,
  sumario      text,
  articulos    text[],
  metodo_ocr   text default 'automatico',
  created_at   timestamptz default now()
);

-- Tabla de logs del scraper (para ver qué hizo cada día)
create table if not exists scraper_logs (
  id         bigserial primary key,
  nivel      text not null,
  mensaje    text not null,
  detalle    jsonb,
  created_at timestamptz default now()
);

-- Índices para búsqueda rápida
create index if not exists idx_normas_jerarquia on normas(jerarquia);
create index if not exists idx_normas_vigencia  on normas(vigencia);
create index if not exists idx_normas_tematica  on normas(tematica);
create index if not exists idx_normas_fecha     on normas(fecha_pub desc);
create index if not exists idx_normas_fts on normas
  using gin(to_tsvector('spanish',
    coalesce(titulo,'') || ' ' ||
    coalesce(sumario,'') || ' ' ||
    coalesce(numero_norma,'')
  ));

-- ── Permisos (RLS) ────────────────────────────────────────
alter table normas       enable row level security;
alter table scraper_logs enable row level security;

-- Cualquiera puede leer normas (la app es pública)
create policy "lectura publica normas"
  on normas for select using (true);

-- Solo el service_role puede escribir (el scraper usa service_role)
create policy "escritura service role normas"
  on normas for all using (auth.role() = 'service_role');

create policy "escritura service role logs"
  on scraper_logs for all using (auth.role() = 'service_role');

-- ── Vista de estadísticas ─────────────────────────────────
create or replace view stats as
select
  count(*)                                            as total,
  count(*) filter (where vigencia = 'Vigente')        as vigentes,
  count(*) filter (where vigencia = 'Derogada')       as derogadas,
  count(*) filter (where vigencia = 'Reformada')      as reformadas,
  max(fecha_pub)                                      as ultima_pub,
  count(*) filter (where created_at > now() - interval '24h') as nuevas_hoy
from normas;
