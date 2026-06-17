-- =====================================================================
-- Banking / Loan Core Domain
-- Combined schema + seed for Postgres (kasetti_bank) as reference.
-- Based on your existing crm + loan_core example.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Safety cleanup (idempotent-ish for Postgres)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS loan_core.loan_payments CASCADE;
DROP TABLE IF EXISTS loan_core.loan_collateral CASCADE;
DROP TABLE IF EXISTS loan_core.loan_products CASCADE;
DROP TABLE IF EXISTS loan_core.loans CASCADE;
DROP TABLE IF EXISTS crm.customer_addresses CASCADE;
DROP TABLE IF EXISTS crm.customers CASCADE;

DROP SCHEMA IF EXISTS loan_core CASCADE;
DROP SCHEMA IF EXISTS crm CASCADE;

-- ---------------------------------------------------------------------
-- Schemas
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS crm;
CREATE SCHEMA IF NOT EXISTS loan_core;

-- =====================================================================
-- TABLE DEFINITIONS
-- =====================================================================

-- ---------------------------------------------------------------------
-- CRM: customers
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.customers (
    customer_id          SERIAL PRIMARY KEY,
    full_name            TEXT        NOT NULL,
    email                TEXT        NOT NULL UNIQUE,
    phone                TEXT,
    preferred_language   TEXT        DEFAULT 'en',
    -- e.g. INDIVIDUAL, SME, CORPORATE
    customer_type        TEXT        DEFAULT 'INDIVIDUAL',
    -- link to loan_core.loans.loan_account_number (logical FK)
    primary_loan_account TEXT,
    created_at           TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- CRM: customer_addresses
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.customer_addresses (
    address_id    SERIAL PRIMARY KEY,
    customer_id   INTEGER    NOT NULL REFERENCES crm.customers(customer_id),
    address_line1 TEXT       NOT NULL,
    address_line2 TEXT,
    city          TEXT       NOT NULL,
    state         TEXT,
    postal_code   TEXT,
    country       TEXT       NOT NULL,
    is_primary    BOOLEAN    NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- LOAN_CORE: loan_products
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loan_core.loan_products (
    product_id        SERIAL PRIMARY KEY,
    product_code      TEXT       NOT NULL UNIQUE,  -- e.g. HOME_LOAN, AUTO_LOAN
    product_name      TEXT       NOT NULL,
    interest_rate_apr NUMERIC(5,2) NOT NULL,
    min_term_months   INTEGER    NOT NULL,
    max_term_months   INTEGER    NOT NULL
);

-- ---------------------------------------------------------------------
-- LOAN_CORE: loans
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loan_core.loans (
    loan_id            SERIAL PRIMARY KEY,
    loan_account_number TEXT      NOT NULL UNIQUE,
    customer_id        INTEGER    NOT NULL REFERENCES crm.customers(customer_id),
    product_id         INTEGER    REFERENCES loan_core.loan_products(product_id),
    principal_amount   NUMERIC(18,2) NOT NULL DEFAULT 0,
    currency           TEXT       NOT NULL DEFAULT 'INR',
    status             TEXT       NOT NULL,   -- e.g. OPEN, CLOSED, WRITEOFF
    opened_at          TIMESTAMPTZ DEFAULT NOW(),
    closed_at          TIMESTAMPTZ,
    -- simple risk bucket just for testing filters
    risk_bucket        TEXT       DEFAULT 'LOW'
);

-- ---------------------------------------------------------------------
-- LOAN_CORE: loan_collateral
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loan_core.loan_collateral (
    collateral_id  SERIAL PRIMARY KEY,
    loan_id        INTEGER    NOT NULL REFERENCES loan_core.loans(loan_id),
    collateral_type TEXT      NOT NULL,       -- e.g. PROPERTY, VEHICLE, GUARANTOR
    description    TEXT,
    value_amount   NUMERIC(18,2),
    value_currency TEXT       DEFAULT 'INR',
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- LOAN_CORE: loan_payments
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loan_core.loan_payments (
    payment_id     SERIAL PRIMARY KEY,
    loan_id        INTEGER    NOT NULL REFERENCES loan_core.loans(loan_id),
    payment_date   TIMESTAMPTZ NOT NULL,
    amount         NUMERIC(18,2) NOT NULL,
    currency       TEXT       NOT NULL DEFAULT 'INR',
    payment_method TEXT,                 -- e.g. NEFT, UPI, CARD
    status         TEXT       NOT NULL,  -- e.g. SUCCESS, FAILED, PENDING
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================================
-- SEED DATA
-- =====================================================================

-- ---------------------------------------------------------------------
-- Seed loan products
-- ---------------------------------------------------------------------
INSERT INTO loan_core.loan_products
    (product_code,   product_name,                interest_rate_apr, min_term_months, max_term_months)
VALUES
    ('HOME_LOAN',    'Home Loan',                 8.25,              60,              360),
    ('AUTO_LOAN',    'Auto Loan',                 9.50,              24,              84),
    ('PERSONAL_LOAN','Personal Loan',            14.75,              12,              60),
    ('EDU_LOAN',     'Education Loan',           11.25,              12,              120),
    ('SME_LOAN',     'Small Business Loan',      12.00,              12,              180)
;

-- ---------------------------------------------------------------------
-- Seed customers
-- Include:
--  - Valid closed-loan customer for LN12345 (happy path)
--  - Customers with OPEN loans
--  - Mismatched / wrong-email / no-loan cases
--  - Case-sensitive names and multilingual (including Chinese)
-- ---------------------------------------------------------------------
INSERT INTO crm.customers
    (full_name,              email,                        phone,                preferred_language, customer_type, primary_loan_account)
VALUES
    -- 1: Valid closed loan customer for LN12345 (used by live tests)
    ('John Valid',           'customer@example.com',       '+91-9000000001',     'en', 'INDIVIDUAL', 'LN12345'),

    -- 2: Customer with OPEN loan (LN99999)
    ('Jane Open',            'openloan@example.com',       '+91-9000000002',     'en', 'INDIVIDUAL', 'LN99999'),

    -- 3: Customer with wrong email for a loan account (LN77777)
    ('Wrong Email Customer', 'different@example.com',      '+91-9000000003',     'en', 'INDIVIDUAL', 'LN77777'),

    -- 4: Customer for numeric loan 10001 (CLOSED)
    ('TestGood Customer',    'good.customer@example.com',  '+91-9000000004',     'en', 'INDIVIDUAL', '10001'),

    -- 5: Customer for numeric loan 10002 (ACTIVE)
    ('Unknown Customer',     'unknown.customer@example.com','+91-9000000005',    'en', 'INDIVIDUAL', '10002'),

    -- 6: Case-sensitivity / unicode name
    ('loanClosed User',      'LoanClosed.User@example.com','+91-9000000006',     'en', 'INDIVIDUAL', 'LC123'),

    -- 7: Multilingual name – Chinese
    ('张伟',                 'zhang.wei@example.cn',       '+86-13800000001',    'zh', 'INDIVIDUAL', 'CN001'),

    -- 8: Multilingual / mixed script name
    ('Arun कुमार',           'arun.kumar@example.in',      '+91-9000000007',     'hi', 'INDIVIDUAL', 'INMIX001'),

    -- 9: SME customer with multiple loans
    ('Bright Traders LLP',   'finance@brighttraders.com',  '+91-9000000008',     'en', 'SME',        NULL),

    -- 10: Corporate customer (no loans yet)
    ('Global Corp Ltd',      'treasury@globalcorp.com',    '+1-212-555-0000',    'en', 'CORPORATE',  NULL)
;

-- ---------------------------------------------------------------------
-- Seed customer addresses
-- ---------------------------------------------------------------------
INSERT INTO crm.customer_addresses
    (customer_id, address_line1,                address_line2,         city,        state,         postal_code, country, is_primary)
VALUES
    (1, '12 MG Road',           'Apt 4B',                     'Bengaluru', 'Karnataka',   '560001',  'India', TRUE),
    (2, '45 Residency Road',    NULL,                         'Bengaluru', 'Karnataka',   '560025',  'India', TRUE),
    (3, '77 Brigade Road',      'Floor 3',                    'Bengaluru', 'Karnataka',   '560030',  'India', TRUE),
    (4, '100 Market Street',    NULL,                         'Mumbai',    'Maharashtra', '400001',  'India', TRUE),
    (5, '200 Lake View',        'Phase 2',                    'Hyderabad', 'Telangana',   '500081',  'India', TRUE),
    (6, '1 CaseSensitive Lane', NULL,                         'Chennai',   'Tamil Nadu',  '600001',  'India', TRUE),
    (7, '中关村东路66号',          '海淀区',                     '北京',         '北京',          '100190',  'China', TRUE),
    (8, '11 MG Road',           'Near Metro',                 'Delhi',     'Delhi',       '110001',  'India', TRUE),
    (9, 'Industrial Estate',    'Plot 23',                    'Pune',      'Maharashtra', '411001',  'India', TRUE),
    (10,'Corporate Tower 9',    '14th Floor',                 'New York',  'NY',          '10001',   'USA',    TRUE)
;

-- ---------------------------------------------------------------------
-- Seed loans
-- Key scenarios:
--  - LN12345 -> CLOSED (happy path)
--  - LN99999 -> OPEN
--  - LN77777 not present in loans (to test missing loan)
--  - 10001 CLOSED, 10002 ACTIVE
--  - Case-sensitive statuses + multilingual, different products and risk buckets
-- ---------------------------------------------------------------------

-- LN12345: CLOSED (happy path, must exist for live integration tests)
INSERT INTO loan_core.loans
    (loan_account_number, customer_id, product_id, principal_amount, currency, status, opened_at, closed_at, risk_bucket)
VALUES
    ('LN12345', 1, 1, 5000000.00, 'INR', 'CLOSED', NOW() - INTERVAL '365 days', NOW() - INTERVAL '10 days', 'LOW');

-- LN99999: OPEN (exists but not closed; should fail "closed-loan" validations)
INSERT INTO loan_core.loans
    (loan_account_number, customer_id, product_id, principal_amount, currency, status, opened_at, closed_at, risk_bucket)
VALUES
    ('LN99999', 2, 2, 800000.00,  'INR', 'OPEN',  NOW() - INTERVAL '180 days', NULL,                       'MEDIUM');

-- Important: LN77777 is intentionally NOT created in loan_core.loans
-- to support "loan does not exist" scenarios.

-- 10001: CLOSED (happy path for numeric account)
INSERT INTO loan_core.loans
    (loan_account_number, customer_id, product_id, principal_amount, currency, status, opened_at, closed_at, risk_bucket)
VALUES
    ('10001', 4, 3, 300000.00, 'INR', 'CLOSED', NOW() - INTERVAL '720 days', NOW() - INTERVAL '30 days', 'LOW');

-- 10002: ACTIVE (exists but not closed)
INSERT INTO loan_core.loans
    (loan_account_number, customer_id, product_id, principal_amount, currency, status, opened_at, closed_at, risk_bucket)
VALUES
    ('10002', 5, 3, 150000.00, 'INR', 'ACTIVE', NOW() - INTERVAL '90 days',  NULL,                      'MEDIUM');

-- Case-sensitive / unicode loan
INSERT INTO loan_core.loans
    (loan_account_number, customer_id, product_id, principal_amount, currency, status, opened_at, closed_at, risk_bucket)
VALUES
    ('LC123',  6, 4, 100000.00, 'INR', 'closed', NOW() - INTERVAL '400 days', NOW() - INTERVAL '5 days', 'HIGH'),
    ('CN001',  7, 1, 200000.00, 'CNY', 'CLOSED', NOW() - INTERVAL '365 days', NOW() - INTERVAL '1 day',  'LOW'),
    ('INMIX001',8, 5, 750000.00, 'INR', 'Closed', NOW() - INTERVAL '300 days', NOW() - INTERVAL '2 days','MEDIUM');

-- SME loans for Bright Traders LLP (multiple loans, different statuses)
INSERT INTO loan_core.loans
    (loan_account_number, customer_id, product_id, principal_amount, currency, status, opened_at, closed_at, risk_bucket)
VALUES
    ('SME001', 9, 5, 2000000.00, 'INR', 'OPEN',   NOW() - INTERVAL '365 days', NULL,                      'HIGH'),
    ('SME002', 9, 5, 1200000.00, 'INR', 'CLOSED', NOW() - INTERVAL '730 days', NOW() - INTERVAL '365 days','MEDIUM');

-- ---------------------------------------------------------------------
-- Seed loan_collateral
-- ---------------------------------------------------------------------
INSERT INTO loan_core.loan_collateral
    (loan_id, collateral_type, description, value_amount, value_currency)
SELECT
    l.loan_id,
    c.collateral_type,
    c.description,
    c.value_amount,
    c.value_currency
FROM (
    VALUES
        ('LN12345', 'PROPERTY', 'Apartment in Bengaluru', 6500000.00, 'INR'),
        ('LN99999', 'VEHICLE',  'SUV registered in Karnataka', 900000.00,  'INR'),
        ('10001',   'GUARANTOR','Personal guarantee by director', 500000.00,'INR'),
        ('CN001',   'PROPERTY', '公寓 - 北京市海淀区', 2200000.00, 'CNY'),
        ('SME001',  'PROPERTY', 'Factory building in Pune', 10000000.00, 'INR')
) AS c(loan_acc, collateral_type, description, value_amount, value_currency)
JOIN loan_core.loans l ON l.loan_account_number = c.loan_acc;

-- ---------------------------------------------------------------------
-- Seed loan_payments
-- Mix of SUCCESS, FAILED, PENDING, across different loans.
-- ---------------------------------------------------------------------
INSERT INTO loan_core.loan_payments
    (loan_id, payment_date, amount, currency, payment_method, status)
SELECT
    l.loan_id,
    p.payment_date,
    p.amount,
    p.currency,
    p.payment_method,
    p.status
FROM (
    VALUES
        -- LN12345 closed with successful payments
        ('LN12345', NOW() - INTERVAL '60 days', 50000.00, 'INR', 'NEFT', 'SUCCESS'),
        ('LN12345', NOW() - INTERVAL '30 days', 50000.00, 'INR', 'UPI',  'SUCCESS'),

        -- LN99999 open with a failed payment
        ('LN99999', NOW() - INTERVAL '15 days', 25000.00, 'INR', 'CARD', 'FAILED'),

        -- 10001 closed with pending payment (for edge case)
        ('10001',   NOW() - INTERVAL '10 days', 15000.00, 'INR', 'NEFT', 'PENDING'),

        -- 10002 active with mixed status
        ('10002',   NOW() - INTERVAL '7 days',  10000.00, 'INR', 'UPI',  'SUCCESS'),
        ('10002',   NOW() - INTERVAL '3 days',  10000.00, 'INR', 'UPI',  'FAILED'),

        -- CN001 Chinese customer with SUCCESS payment
        ('CN001',   NOW() - INTERVAL '5 days',  5000.00,  'CNY', 'CARD', 'SUCCESS'),

        -- SME loans: multiple payments
        ('SME001',  NOW() - INTERVAL '20 days', 100000.00,'INR', 'NEFT', 'SUCCESS'),
        ('SME001',  NOW() - INTERVAL '5 days',  50000.00, 'INR', 'NEFT', 'PENDING'),
        ('SME002',  NOW() - INTERVAL '400 days',80000.00, 'INR', 'NEFT', 'SUCCESS')
) AS p(loan_acc, payment_date, amount, currency, payment_method, status)
JOIN loan_core.loans l ON l.loan_account_number = p.loan_acc;

-- =====================================================================
-- END OF BANKING / LOAN CORE SEED
-- =====================================================================
