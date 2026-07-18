-- =============================================================================
-- LogiStat — PostgreSQL Schema
-- =============================================================================
-- Uruchomienie:
--   psql -h <HOST> -U <USER> -d <DATABASE> -f postgres_schema.sql
--
-- Skrypt jest idempotentny (IF NOT EXISTS wszędzie) —
-- bezpieczny do ponownego uruchomienia na istniejącej bazie.
-- =============================================================================

-- Rozszerzenia
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- opcjonalnie: dla gen_random_uuid()

-- =============================================================================
-- user
-- =============================================================================
CREATE TABLE IF NOT EXISTS "user" (
    id            SERIAL       PRIMARY KEY,
    username      VARCHAR(100) NOT NULL,
    display_name  VARCHAR(150) NOT NULL,
    barcode_id    VARCHAR(100),
    password_hash VARCHAR(200),
    role          VARCHAR(20)  NOT NULL DEFAULT 'operator',
    is_active_user BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP    NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_user_username   UNIQUE (username),
    CONSTRAINT uq_user_barcode_id UNIQUE (barcode_id),
    CONSTRAINT chk_user_role CHECK (role IN ('operator', 'leader', 'admin'))
);

-- =============================================================================
-- activity
-- =============================================================================
CREATE TABLE IF NOT EXISTS activity (
    id         SERIAL       PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    sort_order INTEGER      NOT NULL DEFAULT 0,
    is_active  BOOLEAN      NOT NULL DEFAULT TRUE,

    CONSTRAINT uq_activity_name UNIQUE (name)
);

-- =============================================================================
-- shift
-- =============================================================================
CREATE TABLE IF NOT EXISTS shift (
    id           SERIAL   PRIMARY KEY,
    date         DATE     NOT NULL,
    shift_number SMALLINT NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_shift_date_number UNIQUE (date, shift_number),
    CONSTRAINT chk_shift_number CHECK (shift_number IN (1, 2))
);

-- =============================================================================
-- shift_attendance
-- =============================================================================
CREATE TABLE IF NOT EXISTS shift_attendance (
    id         SERIAL    PRIMARY KEY,
    shift_id   INTEGER   NOT NULL REFERENCES shift(id) ON DELETE CASCADE,
    user_id    INTEGER   NOT NULL REFERENCES "user"(id),
    scanned_at TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_attendance_shift_user UNIQUE (shift_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_attendance_shift_id ON shift_attendance (shift_id);
CREATE INDEX IF NOT EXISTS ix_attendance_user_id  ON shift_attendance (user_id);

-- =============================================================================
-- activity_assignment
-- =============================================================================
CREATE TABLE IF NOT EXISTS activity_assignment (
    id            SERIAL    PRIMARY KEY,
    shift_id      INTEGER   NOT NULL REFERENCES shift(id) ON DELETE CASCADE,
    user_id       INTEGER   NOT NULL REFERENCES "user"(id),
    activity_id   INTEGER   NOT NULL REFERENCES activity(id),
    is_suggestion BOOLEAN   NOT NULL DEFAULT FALSE,
    assigned_by   INTEGER   REFERENCES "user"(id),
    assigned_at   TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_assignment_shift_user_activity UNIQUE (shift_id, user_id, activity_id)
);

CREATE INDEX IF NOT EXISTS ix_assignment_shift_id ON activity_assignment (shift_id);
CREATE INDEX IF NOT EXISTS ix_assignment_user_id  ON activity_assignment (user_id);

-- =============================================================================
-- daily_stat
-- =============================================================================
CREATE TABLE IF NOT EXISTS daily_stat (
    id          SERIAL       PRIMARY KEY,
    shift_id    INTEGER      NOT NULL REFERENCES shift(id) ON DELETE CASCADE,
    user_id     INTEGER      NOT NULL REFERENCES "user"(id),
    activity_id INTEGER      NOT NULL REFERENCES activity(id),
    quantity    INTEGER      NOT NULL DEFAULT 0,
    note        VARCHAR(300),
    entered_by  INTEGER      REFERENCES "user"(id),
    entered_at  TIMESTAMP    DEFAULT NOW(),
    modified_by INTEGER      REFERENCES "user"(id),
    modified_at TIMESTAMP,

    CONSTRAINT uq_stat_shift_user_activity UNIQUE (shift_id, user_id, activity_id)
);

CREATE INDEX IF NOT EXISTS ix_daily_stat_shift_id   ON daily_stat (shift_id);
CREATE INDEX IF NOT EXISTS ix_daily_stat_user_id    ON daily_stat (user_id);

-- =============================================================================
-- country_mapping
-- =============================================================================
CREATE TABLE IF NOT EXISTS country_mapping (
    id           SERIAL       PRIMARY KEY,
    country      VARCHAR(150) NOT NULL,
    innenauftrag VARCHAR(100) NOT NULL
);

-- =============================================================================
-- imported_carton
-- Największa tabela (~2.75M wierszy/5 lat) — BIGSERIAL dla id
-- =============================================================================
CREATE TABLE IF NOT EXISTS imported_carton (
    id                 BIGSERIAL    PRIMARY KEY,
    barcode            VARCHAR(100) NOT NULL,
    land               VARCHAR(150),
    stueckzahl         INTEGER      DEFAULT 0,
    kategorie          VARCHAR(100),
    ziel_datum         DATE,
    uebergabe_nr       VARCHAR(100),
    country_mapping_id INTEGER      REFERENCES country_mapping(id),
    imported_at        TIMESTAMP    DEFAULT NOW(),
    imported_by        INTEGER      REFERENCES "user"(id),
    processed_by       INTEGER      REFERENCES "user"(id),
    processed_at       TIMESTAMP,
    scan_start_at      TIMESTAMP,
    scan_start_by      INTEGER      REFERENCES "user"(id),
    scan_end_at        TIMESTAMP,
    scan_end_by        INTEGER      REFERENCES "user"(id),
    double_rate        BOOLEAN      NOT NULL DEFAULT FALSE,
    added_manually     BOOLEAN      NOT NULL DEFAULT FALSE,
    modified_at        TIMESTAMP,
    modified_by        INTEGER      REFERENCES "user"(id),

    CONSTRAINT uq_carton_barcode UNIQUE (barcode)
);

CREATE INDEX IF NOT EXISTS ix_carton_ziel_datum   ON imported_carton (ziel_datum);
CREATE INDEX IF NOT EXISTS ix_carton_uebergabe_nr ON imported_carton (uebergabe_nr);
CREATE INDEX IF NOT EXISTS ix_carton_processed_by ON imported_carton (processed_by);
CREATE INDEX IF NOT EXISTS ix_carton_land         ON imported_carton (land);
CREATE INDEX IF NOT EXISTS ix_carton_imported_at  ON imported_carton (imported_at);

-- =============================================================================
-- general_stat
-- category_data jako JSONB (lepsza wydajność niż TEXT w PostgreSQL)
-- =============================================================================
CREATE TABLE IF NOT EXISTS general_stat (
    id                     SERIAL       PRIMARY KEY,
    loading_date           DATE         NOT NULL,
    week_number            SMALLINT     NOT NULL,
    list_id                VARCHAR(100) NOT NULL,
    country_of_destination VARCHAR(150),
    country_ledger         VARCHAR(150) NOT NULL,
    amounts                INTEGER      DEFAULT 0,
    category_data          JSONB        NOT NULL DEFAULT '{}',
    double_rate            BOOLEAN      NOT NULL DEFAULT FALSE,  -- legacy, nieużywane
    double_rate_category_data JSONB     NOT NULL DEFAULT '{}',   -- żółta linia double rate
    created_at             TIMESTAMP    DEFAULT NOW(),
    updated_at             TIMESTAMP,
    updated_by             INTEGER      REFERENCES "user"(id),

    CONSTRAINT uq_general_stat UNIQUE (list_id, country_ledger, loading_date)
);

CREATE INDEX IF NOT EXISTS ix_gstat_loading_date ON general_stat (loading_date);
CREATE INDEX IF NOT EXISTS ix_gstat_list_id      ON general_stat (list_id);

-- =============================================================================
-- cost_mapping
-- rates_data jako JSONB
-- =============================================================================
CREATE TABLE IF NOT EXISTS cost_mapping (
    id         SERIAL    PRIMARY KEY,
    year       SMALLINT  NOT NULL,
    month      SMALLINT  NOT NULL,
    rates_data JSONB     NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    updated_by INTEGER   REFERENCES "user"(id),

    CONSTRAINT uq_cost_mapping_ym UNIQUE (year, month),
    CONSTRAINT chk_cost_mapping_month CHECK (month BETWEEN 1 AND 12)
);

-- =============================================================================
-- forecast
-- =============================================================================
CREATE TABLE IF NOT EXISTS forecast (
    id         SERIAL       PRIMARY KEY,
    date       DATE         NOT NULL,
    quantity   INTEGER      DEFAULT 0,
    notes      VARCHAR(500),
    created_by INTEGER      REFERENCES "user"(id),
    created_at TIMESTAMP    DEFAULT NOW(),
    updated_at TIMESTAMP,
    updated_by INTEGER      REFERENCES "user"(id),

    CONSTRAINT uq_forecast_date UNIQUE (date)
);

-- =============================================================================
-- worker_time_event
-- =============================================================================
CREATE TABLE IF NOT EXISTS worker_time_event (
    id          SERIAL      PRIMARY KEY,
    user_id     INTEGER     NOT NULL REFERENCES "user"(id),
    shift_id    INTEGER     NOT NULL REFERENCES shift(id) ON DELETE CASCADE,
    event_type  VARCHAR(20) NOT NULL,
    timestamp   TIMESTAMP   NOT NULL DEFAULT NOW(),
    recorded_by INTEGER     REFERENCES "user"(id),
    is_manual   BOOLEAN     DEFAULT FALSE,
    note        VARCHAR(300),

    CONSTRAINT chk_wte_event_type CHECK (event_type IN ('break_start', 'break_end', 'work_end'))
);

CREATE INDEX IF NOT EXISTS ix_wte_user_shift ON worker_time_event (user_id, shift_id);
CREATE INDEX IF NOT EXISTS ix_wte_shift_id   ON worker_time_event (shift_id);
CREATE INDEX IF NOT EXISTS ix_wte_timestamp  ON worker_time_event (timestamp);

-- =============================================================================
-- Seed: domyślne czynności
-- =============================================================================
INSERT INTO activity (name, sort_order, is_active) VALUES
    ('Post Processing',       0, TRUE),
    ('Zwroty',                1, TRUE),
    ('Organic Decoration',    2, TRUE),
    ('Rollout Decoration',    3, TRUE),
    ('Expansion',             4, TRUE),
    ('Textile-Picking',       5, TRUE),
    ('Order-VAS',             6, TRUE),
    ('Carton Labeling',       7, TRUE),
    ('Orders',                8, TRUE)
ON CONFLICT (name) DO NOTHING;

-- =============================================================================
-- Seed: mapowania krajów
-- =============================================================================
INSERT INTO country_mapping (country, innenauftrag) VALUES
    ('Schweiz',                '91000741810'),
    ('Italien',                '91000741812'),
    ('Rumänien',               '91000741814'),
    ('Vereinigtes Königreich', '91000741816'),
    ('Frankreich',             '91000741817'),
    ('Croatia',                '91000741820'),
    ('Spanien Kanaren',        'ES01'),
    ('Spanien',                'ES01'),
    ('Portugal',               '91000741824'),
    ('Elfenbeinküste',         '91000741828'),
    ('Deutschland',            'Orsay DE'),
    ('Kongo',                  'IAM RCB'),
    ('Senegal',                'IAM SN'),
    ('Deutschland AMAZON',     'DE AMAZON'),
    ('EDEKA',                  'EDK1'),
    ('Netherlands',            'NL01'),
    ('Northern Ireland',       'IRL'),
    ('ES',                     'ES01'),
    ('IT',                     '91000741812'),
    ('CH',                     '91000741810'),
    ('Slowakei',               'SLO'),
    ('Tschechien',             'TSC'),
    ('PL',                     'PL'),
    ('HU',                     'HU'),
    ('BE',                     'BE'),
    ('PT',                     'PT'),
    ('AT',                     'AT'),
    ('Deutschland C&A',        'DE'),
    ('SI',                     'SI')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Seed: konto admina
-- Hasło należy zmienić po pierwszym logowaniu!
-- Wygeneruj hash: python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('TWOJE_HASLO'))"
-- =============================================================================
INSERT INTO "user" (username, display_name, role, password_hash, is_active_user)
VALUES (
    'admin',
    'Administrator',
    'admin',
    'ZASTAP_HASH_HASLEM',   -- wygeneruj jak wyżej
    TRUE
)
ON CONFLICT (username) DO NOTHING;

-- =============================================================================
-- Weryfikacja po uruchomieniu
-- =============================================================================
-- SELECT tablename, pg_size_pretty(pg_total_relation_size(tablename::regclass))
--   FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;
