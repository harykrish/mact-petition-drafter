-- Cambrian — shared case knowledge base (Supabase / Postgres)
-- ============================================================================
-- The self-evolving source of truth, consumed by NyayaSetu (legal), Appa Speaks,
-- rehab, medical-care, and coordination apps. Mirrors knowledge/case_record.json
-- (facts[] / contradictions[] / changelog[]) but multi-case and persistent.
--
-- Run this in the SAME Supabase project as the existing NyayaSetu tables
-- (documents, case_law_cache, case_library). All tables are backend-only
-- (service_role) — PII is never exposed to the browser; the app gates access
-- behind login.  Run in: Supabase Dashboard → SQL Editor → New Query → Run.

-- ── Cases ────────────────────────────────────────────────────────────────────
create table if not exists cases (
  case_id     text primary key,              -- e.g. 'MACT-CGP-2026-0215'
  title       text,                          -- e.g. 'R. Narayanan Santhanam'
  status      text default 'active',
  created_at  timestamptz default now(),
  updated_at  timestamptz default now()
);

-- ── Facts (the knowledge base) ───────────────────────────────────────────────
create table if not exists facts (
  id                    uuid primary key default gen_random_uuid(),
  case_id               text not null references cases(case_id) on delete cascade,
  fact_ref              text not null,         -- human id 'F001', unique per case
  field                 text not null,         -- 'victim_name','annual_income','disability_pct'
  value                 text,
  stream                text not null
    check (stream in ('medical','police','financial','rehab','personal','other')),
  domain                text default 'general',-- which agent cares: 'legal','medical','rehab','aac','general'
  source_doc            text,                  -- storage path / document id
  source_type           text,                  -- 'FIR','ITR','DisabilityCert','MRI',...
  extracted_on          timestamptz default now(),
  confidence            float default 0.5 check (confidence >= 0 and confidence <= 1),
  extraction_confidence float,
  needs_human_review    boolean default false,
  superseded            boolean default false,
  history               jsonb default '[]'::jsonb,  -- prior values on correction (invariant I5)
  created_at            timestamptz default now(),
  unique (case_id, fact_ref)
);
create index if not exists idx_facts_case   on facts(case_id);
create index if not exists idx_facts_field  on facts(case_id, field);
create index if not exists idx_facts_stream on facts(case_id, stream);
create index if not exists idx_facts_active on facts(case_id) where superseded = false;

-- ── Contradictions (first-class; conflicts park here, never silently resolved) ─
create table if not exists contradictions (
  id                uuid primary key default gen_random_uuid(),
  case_id           text not null references cases(case_id) on delete cascade,
  contra_ref        text not null,             -- 'C001'
  field             text not null,
  status            text default 'unresolved'
    check (status in ('unresolved','resolved')),
  values            jsonb not null,            -- [{fact_ref,value,source,stream}, ...]
  resolution_note   text,
  created_at        timestamptz default now(),
  unique (case_id, contra_ref)
);
create index if not exists idx_contra_case on contradictions(case_id);

-- ── Changelog (append-only, monotonic seq per case) ──────────────────────────
create table if not exists changelog (
  id                 uuid primary key default gen_random_uuid(),
  case_id            text not null references cases(case_id) on delete cascade,
  seq                integer not null,
  ts                 timestamptz default now(),
  action             text not null,            -- ingest_new | correction | contradiction | duplicate
  field              text,
  fact_ref           text,
  contradiction_ref  text,
  summary            text,
  unique (case_id, seq)
);
create index if not exists idx_changelog_case on changelog(case_id, seq);

-- ── Extend existing documents table: stream + PII flag + case FK ─────────────
alter table documents add column if not exists stream text
  check (stream in ('medical','police','financial','rehab','personal','other'));
alter table documents add column if not exists is_pii boolean default true;

-- ── Row Level Security: backend (service_role) only — PII never client-exposed ─
alter table cases          enable row level security;
alter table facts          enable row level security;
alter table contradictions enable row level security;
alter table changelog      enable row level security;

create policy "svc_cases"   on cases          for all using (auth.role() = 'service_role');
create policy "svc_facts"   on facts          for all using (auth.role() = 'service_role');
create policy "svc_contra"  on contradictions for all using (auth.role() = 'service_role');
create policy "svc_change"  on changelog      for all using (auth.role() = 'service_role');
