CREATE TABLE IF NOT EXISTS companies (
    id BIGSERIAL PRIMARY KEY,
    cik TEXT UNIQUE,
    ticker TEXT,
    company_name TEXT NOT NULL,
    industry_name TEXT,
    country_code TEXT DEFAULT 'US',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS materials (
    id BIGSERIAL PRIMARY KEY,
    material_code TEXT NOT NULL UNIQUE,
    material_name TEXT NOT NULL,
    material_group TEXT NOT NULL,
    default_hs_code TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fred_series (
    id BIGSERIAL PRIMARY KEY,
    series_id TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'index',
    frequency TEXT NOT NULL DEFAULT 'monthly',
    source TEXT NOT NULL DEFAULT 'FRED',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS macro_observations (
    id BIGSERIAL PRIMARY KEY,
    series_id BIGINT NOT NULL REFERENCES fred_series(id) ON DELETE CASCADE,
    observation_date DATE NOT NULL,
    value NUMERIC(18, 6) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (series_id, observation_date)
);

CREATE INDEX IF NOT EXISTS idx_macro_observations_series_date
    ON macro_observations (series_id, observation_date DESC);

CREATE TABLE IF NOT EXISTS trade_flows (
    id BIGSERIAL PRIMARY KEY,
    material_id BIGINT NOT NULL REFERENCES materials(id),
    reporter_country TEXT NOT NULL,
    partner_country TEXT NOT NULL,
    flow_type TEXT NOT NULL CHECK (flow_type IN ('import', 'export')),
    period DATE NOT NULL,
    trade_value_usd NUMERIC(18, 2),
    net_weight_kg NUMERIC(18, 2),
    quantity NUMERIC(18, 2),
    hs_code TEXT,
    source TEXT NOT NULL DEFAULT 'UN_COMTRADE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (material_id, reporter_country, partner_country, flow_type, period, hs_code)
);

CREATE INDEX IF NOT EXISTS idx_trade_flows_period ON trade_flows (period DESC);

CREATE TABLE IF NOT EXISTS company_financials (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    fiscal_period_end DATE NOT NULL,
    fiscal_period_type TEXT NOT NULL,
    revenue NUMERIC(18, 2),
    cogs NUMERIC(18, 2),
    gross_margin NUMERIC(10, 4),
    inventory_value NUMERIC(18, 2),
    inventory_turnover NUMERIC(10, 4),
    operating_income NUMERIC(18, 2),
    source TEXT NOT NULL DEFAULT 'SEC_EDGAR',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, fiscal_period_end, fiscal_period_type)
);

CREATE TABLE IF NOT EXISTS company_filings (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    accession_number TEXT UNIQUE,
    filing_type TEXT NOT NULL,
    filing_date DATE NOT NULL,
    period_end_date DATE,
    cik TEXT,
    sec_url TEXT,
    risk_factors_text TEXT,
    management_discussion_text TEXT,
    inventory_commentary_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS supplier_mentions (
    id BIGSERIAL PRIMARY KEY,
    filing_id BIGINT NOT NULL REFERENCES company_filings(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    mention_count INTEGER NOT NULL DEFAULT 0,
    sample_snippet TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (filing_id, keyword)
);

CREATE TABLE IF NOT EXISTS buy_recommendations (
    id BIGSERIAL PRIMARY KEY,
    as_of_month DATE NOT NULL,
    recommendation_label TEXT NOT NULL CHECK (recommendation_label IN ('buy_less', 'buy_same', 'buy_more')),
    confidence NUMERIC(5, 4) NOT NULL,
    demand_index NUMERIC(10, 4),
    material_cost_pressure_score NUMERIC(10, 4),
    trade_supply_tightening_score NUMERIC(10, 4),
    overstock_risk_score NUMERIC(10, 4),
    rationale JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (as_of_month)
);

CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    material_id BIGINT REFERENCES materials(id),
    sku TEXT NOT NULL UNIQUE,
    product_name TEXT NOT NULL,
    product_category TEXT NOT NULL,
    hs_code TEXT,
    unit_of_measure TEXT NOT NULL DEFAULT 'units',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS warehouses (
    id BIGSERIAL PRIMARY KEY,
    warehouse_name TEXT NOT NULL UNIQUE,
    region TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'US',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inventory_snapshots (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    warehouse_id BIGINT NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    snapshot_month DATE NOT NULL,
    on_hand_units NUMERIC(18, 2) NOT NULL,
    reserved_units NUMERIC(18, 2) NOT NULL DEFAULT 0,
    available_units NUMERIC(18, 2) NOT NULL,
    inventory_value_usd NUMERIC(18, 2) NOT NULL,
    average_unit_cost_usd NUMERIC(18, 4) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, warehouse_id, snapshot_month)
);

CREATE TABLE IF NOT EXISTS sales_orders (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    warehouse_id BIGINT NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    order_month DATE NOT NULL,
    units_sold NUMERIC(18, 2) NOT NULL,
    revenue_usd NUMERIC(18, 2) NOT NULL,
    average_selling_price_usd NUMERIC(18, 4) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, warehouse_id, order_month)
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    warehouse_id BIGINT NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    supplier_name TEXT NOT NULL,
    order_month DATE NOT NULL,
    expected_receipt_month DATE NOT NULL,
    units_ordered NUMERIC(18, 2) NOT NULL,
    units_received NUMERIC(18, 2) NOT NULL DEFAULT 0,
    unit_cost_usd NUMERIC(18, 4) NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'partial', 'received', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, warehouse_id, supplier_name, order_month, expected_receipt_month)
);

CREATE TABLE IF NOT EXISTS supplier_lead_times (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    supplier_name TEXT NOT NULL,
    month DATE NOT NULL,
    average_lead_time_days NUMERIC(10, 2) NOT NULL,
    late_delivery_rate_percent NUMERIC(10, 2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, supplier_name, month)
);

ALTER TABLE buy_recommendations
    ADD COLUMN IF NOT EXISTS product_id BIGINT REFERENCES products(id),
    ADD COLUMN IF NOT EXISTS recommendation_month DATE,
    ADD COLUMN IF NOT EXISTS recommendation TEXT CHECK (recommendation IN ('buy_less', 'buy_same', 'buy_more')),
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5, 4),
    ADD COLUMN IF NOT EXISTS demand_signal TEXT,
    ADD COLUMN IF NOT EXISTS cost_pressure_signal TEXT,
    ADD COLUMN IF NOT EXISTS trade_supply_signal TEXT,
    ADD COLUMN IF NOT EXISTS inventory_signal TEXT,
    ADD COLUMN IF NOT EXISTS rationale_json JSONB,
    ADD COLUMN IF NOT EXISTS source_notes_json JSONB;

CREATE UNIQUE INDEX IF NOT EXISTS idx_buy_recommendations_product_month
    ON buy_recommendations (product_id, recommendation_month);
