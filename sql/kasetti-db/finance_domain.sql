-- =====================================================================
-- FINANCE / CORPORATE FINANCE & INVOICING DOMAIN
-- Combined schema + seed data (Postgres reference)
-- =====================================================================

-- ---------------------------------------------------------------------
-- Cleanup
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS fin.payments CASCADE;
DROP TABLE IF EXISTS fin.invoice_lines CASCADE;
DROP TABLE IF EXISTS fin.invoices CASCADE;
DROP TABLE IF EXISTS fin.fx_rates CASCADE;
DROP TABLE IF EXISTS fin.gl_accounts CASCADE;
DROP TABLE IF EXISTS fin.clients CASCADE;

DROP SCHEMA IF EXISTS fin CASCADE;

-- ---------------------------------------------------------------------
-- Schema
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS fin;

-- =====================================================================
-- TABLE DEFINITIONS
-- =====================================================================

-- ---------------------------------------------------------------------
-- CLIENTS: Customers / counterparties
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin.clients (
    client_id       SERIAL PRIMARY KEY,
    client_code     TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    country         TEXT NOT NULL,
    primary_language TEXT DEFAULT 'en',
    tax_id          TEXT,
    email           TEXT,
    phone           TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    risk_level      TEXT NOT NULL DEFAULT 'NORMAL', -- LOW, NORMAL, HIGH
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- GL_ACCOUNTS: Simplified chart of accounts
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin.gl_accounts (
    gl_account_id   SERIAL PRIMARY KEY,
    account_code    TEXT NOT NULL UNIQUE,
    account_name    TEXT NOT NULL,
    account_type    TEXT NOT NULL, -- ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

-- ---------------------------------------------------------------------
-- FX_RATES: Daily FX rates between currencies
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin.fx_rates (
    rate_date       DATE NOT NULL,
    from_currency   TEXT NOT NULL,
    to_currency     TEXT NOT NULL,
    rate            NUMERIC(18,8) NOT NULL,
    CONSTRAINT pk_fx_rates PRIMARY KEY (rate_date, from_currency, to_currency)
);

-- ---------------------------------------------------------------------
-- INVOICES: Header-level A/R invoices
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin.invoices (
    invoice_id          SERIAL PRIMARY KEY,
    invoice_number      TEXT NOT NULL UNIQUE,
    client_id           INTEGER NOT NULL REFERENCES fin.clients(client_id),
    invoice_date        DATE NOT NULL,
    due_date            DATE NOT NULL,
    currency            TEXT NOT NULL,                  -- invoice currency
    gross_amount        NUMERIC(18,2) NOT NULL,
    tax_amount          NUMERIC(18,2) NOT NULL,
    net_amount          NUMERIC(18,2) NOT NULL,
    balance_amount      NUMERIC(18,2) NOT NULL,         -- open balance
    status              TEXT NOT NULL,                  -- DRAFT, SENT, OVERDUE, PARTIALLY_PAID, PAID, WRITEOFF, DISPUTED, CANCELLED
    payment_terms       TEXT,                           -- e.g. "NET30"
    is_credit_note      BOOLEAN NOT NULL DEFAULT FALSE, -- for negative invoices
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- INVOICE_LINES: Line-level details
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin.invoice_lines (
    line_id         SERIAL PRIMARY KEY,
    invoice_id      INTEGER NOT NULL REFERENCES fin.invoices(invoice_id),
    line_no         INTEGER NOT NULL,
    description     TEXT NOT NULL,
    quantity        NUMERIC(18,3) NOT NULL,
    unit_price      NUMERIC(18,4) NOT NULL,
    tax_rate        NUMERIC(5,2) NOT NULL,             -- percent
    gl_account_id   INTEGER NOT NULL REFERENCES fin.gl_accounts(gl_account_id)
);

-- ---------------------------------------------------------------------
-- PAYMENTS: Payments applied to invoices (or on-account)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin.payments (
    payment_id      SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES fin.clients(client_id),
    invoice_id      INTEGER REFERENCES fin.invoices(invoice_id), -- nullable for on-account
    payment_date    DATE NOT NULL,
    amount          NUMERIC(18,2) NOT NULL,
    currency        TEXT NOT NULL,                              -- payment currency
    fx_rate_used    NUMERIC(18,8),                              -- to invoice currency or company currency
    method          TEXT NOT NULL,                              -- NEFT, RTGS, SWIFT, CARD, CASH
    status          TEXT NOT NULL,                              -- POSTED, FAILED, REFUNDED, PENDING
    reference       TEXT
);

-- =====================================================================
-- SEED DATA
-- =====================================================================

-- ---------------------------------------------------------------------
-- CLIENTS
-- Scenarios:
-- - Indian SaaS customer, key high-revenue account.
-- - European distributor.
-- - Chinese customer with multilingual name.
-- - US enterprise client.
-- - High-risk client with disputes.
-- - Inactive client (historic).
-- ---------------------------------------------------------------------
INSERT INTO fin.clients (client_code, name, country, primary_language, tax_id, email, phone, is_active, risk_level)
VALUES
    ('C-IND-001', 'Kasetti Digital Pvt Ltd', 'India', 'en', 'GSTIN-29ABCDE1234F1Z5', 'ap@kasetti-digital.in', '+91-80-40000001', TRUE, 'NORMAL'),
    ('C-EU-001', 'EuroDistrib GmbH', 'Germany', 'de', 'DE123456789', 'billing@eurodistrib.de', '+49-30-9000000', TRUE, 'LOW'),
    ('C-CN-001', '上海云科有限公司', 'China', 'zh', 'CN-TAX-0001', 'finance@yunke.cn', '+86-21-55550001', TRUE, 'NORMAL'),
    ('C-US-001', 'Acme Corp', 'USA', 'en', 'US-EIN-12-3456789', 'ap@acme.com', '+1-415-555-0001', TRUE, 'NORMAL'),
    ('C-IND-002', 'Ravi & Sons Exports', 'India', 'en', 'GSTIN-29XYZAB5678C1Z8', 'accounts@ravi-sons.in', '+91-80-40000002', TRUE, 'HIGH'),
    ('C-OLD-001', 'Legacy Client (Inactive 客户)', 'India', 'en', 'LEG-0001', 'legacy@oldclient.in', '+91-80-40000003', FALSE, 'HIGH');

-- ---------------------------------------------------------------------
-- GL_ACCOUNTS
-- Simplified chart: revenue, discount, FX gain/loss, etc.
-- ---------------------------------------------------------------------
INSERT INTO fin.gl_accounts (account_code, account_name, account_type, is_active)
VALUES
    ('400000', 'Software Subscription Revenue', 'REVENUE', TRUE),
    ('401000', 'Implementation Services Revenue', 'REVENUE', TRUE),
    ('402000', 'Support Services Revenue', 'REVENUE', TRUE),
    ('405000', 'Sales Discount', 'REVENUE', TRUE),
    ('430000', 'FX Gain/Loss', 'REVENUE', TRUE),
    ('100000', 'Accounts Receivable', 'ASSET', TRUE),
    ('101000', 'Bank - Operating', 'ASSET', TRUE),
    ('600000', 'Bad Debt Expense', 'EXPENSE', TRUE);

-- ---------------------------------------------------------------------
-- FX_RATES
-- Multi-currency environment: INR, USD, EUR, CNY
-- ---------------------------------------------------------------------
INSERT INTO fin.fx_rates (rate_date, from_currency, to_currency, rate)
VALUES
    ('2024-01-01', 'USD', 'INR', 83.25000000),
    ('2024-01-01', 'EUR', 'INR', 89.50000000),
    ('2024-01-01', 'CNY', 'INR', 11.80000000),
    ('2024-02-01', 'USD', 'INR', 82.75000000),
    ('2024-02-01', 'EUR', 'INR', 88.90000000),
    ('2024-02-01', 'CNY', 'INR', 11.60000000),
    ('2024-03-01', 'USD', 'INR', 84.10000000),
    ('2024-03-01', 'EUR', 'INR', 90.20000000),
    ('2024-03-01', 'CNY', 'INR', 11.90000000);

-- ---------------------------------------------------------------------
-- INVOICES
-- Scenarios:
-- - Fully paid, partially paid, overdue, disputed, written-off.
-- - Credit note (negative net_amount).
-- - Multi-currency invoices (INR, USD, EUR, CNY).
-- ---------------------------------------------------------------------
INSERT INTO fin.invoices (
    invoice_number, client_id, invoice_date, due_date,
    currency, gross_amount, tax_amount, net_amount, balance_amount,
    status, payment_terms, is_credit_note
)
VALUES
    -- Kasetti Digital: big INR subscription invoice, partially paid and overdue
    ('INV-IND-2024-0001', 1, '2024-01-05', '2024-02-04', 'INR',
     118000.00, 18000.00, 100000.00, 40000.00,
     'PARTIALLY_PAID', 'NET30', FALSE),

    -- EuroDistrib: EUR implementation project, fully paid
    ('INV-EU-2024-0001', 2, '2024-01-10', '2024-02-09', 'EUR',
     23800.00, 3800.00, 20000.00, 0.00,
     'PAID', 'NET30', FALSE),

    -- Shanghai Yunke: CNY invoice, still open and overdue
    ('INV-CN-2024-0001', 3, '2024-01-15', '2024-02-14', 'CNY',
     117000.00, 17000.00, 100000.00, 100000.00,
     'OVERDUE', 'NET30', FALSE),

    -- Acme Corp: USD subscription, fully paid
    ('INV-US-2024-0001', 4, '2024-02-01', '2024-03-02', 'USD',
     11800.00, 1800.00, 10000.00, 0.00,
     'PAID', 'NET30', FALSE),

    -- Ravi & Sons: INR invoice that is DISPUTED
    ('INV-IND-2024-0002', 5, '2024-01-20', '2024-02-19', 'INR',
     59000.00, 9000.00, 50000.00, 50000.00,
     'DISPUTED', 'NET30', FALSE),

    -- Ravi & Sons: credit note (negative net_amount)
    ('CN-IND-2024-0001', 5, '2024-02-15', '2024-02-15', 'INR',
     -1180.00, -180.00, -1000.00, -1000.00,
     'SENT', 'DUEONRECEIPT', TRUE),

    -- Kasetti Digital: small INR invoice fully written off
    ('INV-IND-2023-0099', 1, '2023-11-01', '2023-12-01', 'INR',
     5900.00, 900.00, 5000.00, 0.00,
     'WRITEOFF', 'NET30', FALSE),

    -- Legacy client: old invoice fully paid, historic
    ('INV-OLD-2020-0001', 6, '2020-01-10', '2020-02-09', 'INR',
     11800.00, 1800.00, 10000.00, 0.00,
     'PAID', 'NET30', FALSE);

-- ---------------------------------------------------------------------
-- INVOICE_LINES
-- Detail lines with mapping to GL accounts and tax
-- ---------------------------------------------------------------------
INSERT INTO fin.invoice_lines (invoice_id, line_no, description, quantity, unit_price, tax_rate, gl_account_id)
VALUES
    -- INV-IND-2024-0001 (Kasetti)
    (1, 1, 'Annual SaaS subscription - Enterprise plan', 1.000, 80000.0000, 18.00, 1),
    (1, 2, 'Onboarding & implementation services',       1.000, 20000.0000, 18.00, 2),

    -- INV-EU-2024-0001 (EuroDistrib)
    (2, 1, 'Integration project (Phase 1)',              1.000, 15000.0000, 19.00, 2),
    (2, 2, 'Travel & on-site support',                   1.000,  5000.0000, 19.00, 3),

    -- INV-CN-2024-0001 (Yunke, multilingual description)
    (3, 1, '云服务订阅 / Cloud subscription - Yearly',   1.000, 70000.0000, 13.00, 1),
    (3, 2, '实施服务 / Implementation services',         1.000, 30000.0000, 13.00, 2),

    -- INV-US-2024-0001 (Acme)
    (4, 1, 'Annual SaaS subscription - US region',       1.000,  8000.0000, 10.00, 1),
    (4, 2, 'Premium support',                            1.000,  2000.0000, 10.00, 3),

    -- INV-IND-2024-0002 (Ravi & Sons - disputed)
    (5, 1, 'Custom feature development',                 1.000, 40000.0000, 18.00, 2),
    (5, 2, 'Additional consulting days',                 5.000,  2000.0000, 18.00, 2),

    -- CN-IND-2024-0001 (Credit note)
    (6, 1, 'Credit note for overbilled consulting',      1.000, -1000.0000, 18.00, 5),

    -- INV-IND-2023-0099 (Kasetti, written off)
    (7, 1, 'Legacy support',                             1.000, 5000.0000, 18.00, 3),

    -- INV-OLD-2020-0001 (Legacy client)
    (8, 1, 'Historic subscription',                      1.000, 10000.0000, 18.00, 1);

-- ---------------------------------------------------------------------
-- PAYMENTS
-- Scenarios:
-- - Partial payment, full payment, failed, refunded, on-account.
-- - Payment in different currency than invoice, using FX.
-- ---------------------------------------------------------------------
INSERT INTO fin.payments (
    client_id, invoice_id, payment_date, amount, currency,
    fx_rate_used, method, status, reference
)
VALUES
    -- Kasetti Digital pays part of INV-IND-2024-0001
    (1, 1, '2024-02-01', 60000.00, 'INR', NULL, 'NEFT', 'POSTED', 'NEFT-2024-0001'),

    -- EuroDistrib fully pays in EUR
    (2, 2, '2024-01-30', 20000.00, 'EUR', NULL, 'SWIFT', 'POSTED', 'SWIFT-2024-1001'),

    -- Yunke attempts payment in USD for CNY invoice, then fails
    (3, 3, '2024-02-20', 12000.00, 'USD', 82.75000000, 'SWIFT', 'FAILED', 'SWIFT-FAIL-0001'),

    -- Acme fully pays USD invoice
    (4, 4, '2024-02-15', 10000.00, 'USD', NULL, 'SWIFT', 'POSTED', 'SWIFT-2024-ACME-01'),

    -- Ravi & Sons makes an on-account payment (no invoice_id), then payment applied later
    (5, NULL, '2024-02-10', 25000.00, 'INR', NULL, 'NEFT', 'POSTED', 'ONACC-2024-0001'),

    -- Payment for disputed invoice that was later REFUNDED
    (5, 5, '2024-02-18', 50000.00, 'INR', NULL, 'NEFT', 'REFUNDED', 'NEFT-2024-DISP-01'),

    -- Legacy client historic payment
    (6, 8, '2020-01-25', 10000.00, 'INR', NULL, 'CHEQUE', 'POSTED', 'CHQ-2020-001');

-- =====================================================================
-- END OF FINANCE / GL & INVOICING SEED
-- =====================================================================
