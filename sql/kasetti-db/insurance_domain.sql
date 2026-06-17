-- =====================================================================
-- INSURANCE DOMAIN – POLICIES, COVERAGES & CLAIMS
-- Combined schema + seed data (Postgres reference)
-- =====================================================================

-- ---------------------------------------------------------------------
-- Cleanup
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS ins.claim_payments CASCADE;
DROP TABLE IF EXISTS ins.claim_events CASCADE;
DROP TABLE IF EXISTS ins.claims CASCADE;
DROP TABLE IF EXISTS ins.policy_insured_items CASCADE;
DROP TABLE IF EXISTS ins.policy_coverages CASCADE;
DROP TABLE IF EXISTS ins.policies CASCADE;
DROP TABLE IF EXISTS ins.customers CASCADE;

DROP SCHEMA IF EXISTS ins CASCADE;

-- ---------------------------------------------------------------------
-- Schema
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS ins;

-- =====================================================================
-- TABLE DEFINITIONS
-- =====================================================================

-- ---------------------------------------------------------------------
-- CUSTOMERS: Policyholders / insured parties
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ins.customers (
    customer_id        SERIAL PRIMARY KEY,
    customer_number    TEXT NOT NULL UNIQUE,
    full_name          TEXT NOT NULL,
    date_of_birth      DATE,
    email              TEXT,
    phone              TEXT,
    country            TEXT NOT NULL,
    primary_language   TEXT DEFAULT 'en',
    kyc_status         TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING, VERIFIED, REJECTED
    risk_segment       TEXT NOT NULL DEFAULT 'NORMAL',   -- LOW, NORMAL, HIGH
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- POLICIES: Policy headers
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ins.policies (
    policy_id          SERIAL PRIMARY KEY,
    policy_number      TEXT NOT NULL UNIQUE,
    customer_id        INTEGER NOT NULL REFERENCES ins.customers(customer_id),
    product_type       TEXT NOT NULL,                    -- MOTOR, PROPERTY, HEALTH, TRAVEL
    policy_status      TEXT NOT NULL,                    -- QUOTED, ACTIVE, LAPSED, CANCELLED, EXPIRED
    inception_date     DATE NOT NULL,
    expiry_date        DATE NOT NULL,
    currency           TEXT NOT NULL,
    gross_premium      NUMERIC(18,2) NOT NULL,
    net_premium        NUMERIC(18,2) NOT NULL,
    payment_frequency  TEXT NOT NULL,                    -- ANNUAL, SEMI_ANNUAL, MONTHLY
    channel            TEXT NOT NULL,                    -- AGENT, DIRECT, ONLINE, BROKER
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- POLICY_COVERAGES: Coverage sections per policy
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ins.policy_coverages (
    coverage_id        SERIAL PRIMARY KEY,
    policy_id          INTEGER NOT NULL REFERENCES ins.policies(policy_id),
    coverage_code      TEXT NOT NULL,                    -- BASIC_TP, OD, FIRE, THEFT, FLOOD, PA, LIABILITY
    coverage_name      TEXT NOT NULL,
    sum_insured        NUMERIC(18,2) NOT NULL,
    deductible_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,
    is_active          BOOLEAN NOT NULL DEFAULT TRUE
);

-- ---------------------------------------------------------------------
-- POLICY_INSURED_ITEMS: Vehicles, properties, etc.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ins.policy_insured_items (
    insured_item_id    SERIAL PRIMARY KEY,
    policy_id          INTEGER NOT NULL REFERENCES ins.policies(policy_id),
    item_type          TEXT NOT NULL,                    -- VEHICLE, PROPERTY
    item_reference     TEXT NOT NULL,                    -- registration number, asset code
    make_model         TEXT,
    location_address   TEXT,
    city               TEXT,
    state              TEXT,
    country            TEXT,
    year_of_manufacture INTEGER,
    sum_insured        NUMERIC(18,2),
    risk_zone          TEXT,                             -- LOW, MEDIUM, HIGH, FLOOD_PRONE, etc.
    UNIQUE (policy_id, item_reference)
);

-- ---------------------------------------------------------------------
-- CLAIMS: Claim headers
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ins.claims (
    claim_id           SERIAL PRIMARY KEY,
    claim_number       TEXT NOT NULL UNIQUE,
    policy_id          INTEGER NOT NULL REFERENCES ins.policies(policy_id),
    insured_item_id    INTEGER REFERENCES ins.policy_insured_items(insured_item_id),
    reported_date      DATE NOT NULL,
    loss_date          DATE NOT NULL,
    claim_status       TEXT NOT NULL,                    -- REPORTED, OPEN, UNDER_INVESTIGATION, APPROVED, DENIED, CLOSED
    claim_type         TEXT NOT NULL,                    -- MOTOR_ACCIDENT, FIRE, FLOOD, THEFT, THIRD_PARTY
    cause_description  TEXT,
    loss_estimate      NUMERIC(18,2) NOT NULL,
    reserve_amount     NUMERIC(18,2) NOT NULL,
    total_paid_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,
    currency           TEXT NOT NULL,
    fraud_flag         TEXT NOT NULL DEFAULT 'NO',       -- NO, SUSPECTED, CONFIRMED
    severity           TEXT NOT NULL,                    -- LOW, MEDIUM, HIGH, TOTAL_LOSS
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- CLAIM_EVENTS: Adjuster notes, status changes, documents, etc.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ins.claim_events (
    event_id           SERIAL PRIMARY KEY,
    claim_id           INTEGER NOT NULL REFERENCES ins.claims(claim_id),
    event_timestamp    TIMESTAMPTZ NOT NULL,
    event_type         TEXT NOT NULL,                    -- FNOL, SURVEY, ASSESSMENT, APPROVAL, DENIAL, PAYMENT, RECOVERY
    actor_role         TEXT NOT NULL,                    -- CUSTOMER, AGENT, ADJUSTER, SYSTEM
    actor_name         TEXT NOT NULL,
    notes              TEXT
);

-- ---------------------------------------------------------------------
-- CLAIM_PAYMENTS: Payments for claims
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ins.claim_payments (
    payment_id         SERIAL PRIMARY KEY,
    claim_id           INTEGER NOT NULL REFERENCES ins.claims(claim_id),
    payment_date       DATE NOT NULL,
    amount             NUMERIC(18,2) NOT NULL,
    currency           TEXT NOT NULL,
    payee_type         TEXT NOT NULL,                    -- INSURED, GARAGE, HOSPITAL, THIRD_PARTY
    payee_name         TEXT NOT NULL,
    payment_status     TEXT NOT NULL,                    -- INITIATED, SUCCESS, FAILED, REVERSED
    reference_number   TEXT
);

-- =====================================================================
-- SEED DATA
-- =====================================================================

-- ---------------------------------------------------------------------
-- CUSTOMERS
-- Scenarios:
-- - Mix of countries, languages, KYC statuses, and risk segments
-- - Multilingual names (English + Chinese + mixed script)
-- ---------------------------------------------------------------------
INSERT INTO ins.customers
    (customer_number, full_name, date_of_birth, email, phone, country, primary_language, kyc_status, risk_segment)
VALUES
    ('CUST-IN-001', 'Arjun Mehta',       '1985-03-10', 'arjun.mehta@example.in', '+91-9000000001', 'India',  'en', 'VERIFIED', 'NORMAL'),
    ('CUST-IN-002', 'Saraswati Devi',   '1955-11-22', 's.devi@example.in',      '+91-9000000002', 'India',  'hi', 'VERIFIED', 'HIGH'),
    ('CUST-IN-003', 'Ravi & Sons Exports', NULL,      'owner@ravi-sons.in',     '+91-80-40000001','India',  'en', 'PENDING',  'HIGH'),
    ('CUST-CN-001', '张伟',             '1990-06-15', 'zhang.wei@example.cn',   '+86-13800000001','China',  'zh', 'VERIFIED', 'NORMAL'),
    ('CUST-US-001', 'Jane Doe',         '1978-09-05', 'j.doe@example.com',      '+1-415-555-1000','USA',    'en', 'VERIFIED', 'LOW'),
    ('CUST-MIX-001','Arun कुमार',       '1982-01-01', 'arun.kumar@example.in',  '+91-9000000003', 'India',  'hi', 'REJECTED', 'HIGH');

-- ---------------------------------------------------------------------
-- POLICIES
-- Scenarios:
-- - Active motor policy with multiple coverages and open claim
-- - Lapsed property policy with old large claim
-- - Active property policy with denied claim
-- - Active motor policy (China) with flood claim
-- - US motor policy with small closed claim
-- - Cancelled policy (high-risk, no claim)
-- ---------------------------------------------------------------------
INSERT INTO ins.policies
    (policy_number, customer_id, product_type, policy_status,
     inception_date, expiry_date, currency, gross_premium, net_premium,
     payment_frequency, channel)
VALUES
    -- 1: Active motor policy India, annual
    ('POL-MOTOR-IN-0001', 1, 'MOTOR',    'ACTIVE',
     '2024-01-01', '2025-01-01', 'INR', 25000.00, 22000.00, 'ANNUAL', 'AGENT'),

    -- 2: Lapsed property policy with big historic claim
    ('POL-PROP-IN-0001', 2, 'PROPERTY', 'LAPSED',
     '2022-01-01', '2023-01-01', 'INR', 80000.00, 75000.00, 'ANNUAL', 'AGENT'),

    -- 3: Active property policy for SME with high risk
    ('POL-PROP-IN-0002', 3, 'PROPERTY', 'ACTIVE',
     '2024-03-01', '2025-03-01', 'INR', 120000.00, 110000.00, 'ANNUAL', 'BROKER'),

    -- 4: Active motor policy in China
    ('POL-MOTOR-CN-0001', 4, 'MOTOR',   'ACTIVE',
     '2024-01-15', '2025-01-15', 'CNY', 6000.00, 5500.00, 'ANNUAL', 'ONLINE'),

    -- 5: Active motor policy US
    ('POL-MOTOR-US-0001', 5, 'MOTOR',   'ACTIVE',
     '2023-10-01', '2024-10-01', 'USD', 1200.00, 1000.00, 'ANNUAL', 'DIRECT'),

    -- 6: Cancelled policy for high-risk customer
    ('POL-MOTOR-IN-0002', 6, 'MOTOR',   'CANCELLED',
     '2023-01-01', '2024-01-01', 'INR', 30000.00, 25000.00, 'ANNUAL', 'AGENT');

-- ---------------------------------------------------------------------
-- POLICY_COVERAGES
-- ---------------------------------------------------------------------
INSERT INTO ins.policy_coverages
    (policy_id, coverage_code, coverage_name, sum_insured, deductible_amount, is_active)
VALUES
    -- Policy 1: Motor India – third party + own damage + PA
    (1, 'BASIC_TP', 'Third Party Liability',  500000.00,  0.00,  TRUE),
    (1, 'OD',       'Own Damage',            800000.00, 5000.00, TRUE),
    (1, 'PA',       'Personal Accident',     200000.00,  0.00,   TRUE),

    -- Policy 2: Property India – Fire + Flood (lapsed)
    (2, 'FIRE',     'Fire & Allied Perils',  5000000.00, 25000.00, TRUE),
    (2, 'FLOOD',    'Flood Coverage',        3000000.00, 50000.00, TRUE),

    -- Policy 3: SME Property – Fire + Theft, high sum insured
    (3, 'FIRE',     'Fire & Allied Perils',  10000000.00, 100000.00, TRUE),
    (3, 'THEFT',    'Burglary & Theft',      2000000.00,  50000.00, TRUE),

    -- Policy 4: Motor China – Motor + Flood
    (4, 'BASIC_TP', '交强险 / Compulsory third party',  300000.00,    0.00, TRUE),
    (4, 'OD',       '车辆损失险 / Own Damage',        500000.00,  2000.00, TRUE),
    (4, 'FLOOD',    '水淹险 / Flood coverage',        200000.00,  3000.00, TRUE),

    -- Policy 5: Motor US – TP + collision
    (5, 'BASIC_TP', 'Liability Coverage',    100000.00,  500.00, TRUE),
    (5, 'OD',       'Collision & Comprehensive', 50000.00, 1000.00, TRUE),

    -- Policy 6: Cancelled motor – some coverages (inactive by policy status)
    (6, 'BASIC_TP', 'Third Party Liability',  500000.00,  0.00, TRUE),
    (6, 'OD',       'Own Damage',            600000.00, 5000.00, TRUE);

-- ---------------------------------------------------------------------
-- POLICY_INSURED_ITEMS
-- Vehicles & properties
-- ---------------------------------------------------------------------
INSERT INTO ins.policy_insured_items
    (policy_id, item_type, item_reference, make_model, location_address,
     city, state, country, year_of_manufacture, sum_insured, risk_zone)
VALUES
    -- Policy 1: Motor – car
    (1, 'VEHICLE', 'KA01AB1234', 'Hyundai Creta', '12 MG Road, Indiranagar',
     'Bengaluru', 'Karnataka', 'India', 2019, 800000.00, 'MEDIUM'),

    -- Policy 2: Property – house
    (2, 'PROPERTY', 'PROP-IN-0001', 'Independent House', '45 Residency Road',
     'Bengaluru', 'Karnataka', 'India', 2005, 5000000.00, 'FLOOD_PRONE'),

    -- Policy 3: Property – warehouse
    (3, 'PROPERTY', 'WH-IN-BLR-01', 'Export Warehouse', 'Industrial Area, Plot 23',
     'Bengaluru', 'Karnataka', 'India', 2010, 10000000.00, 'HIGH'),

    -- Policy 4: Motor – Chinese car
    (4, 'VEHICLE', '沪A12345', '比亚迪 SUV / BYD SUV', '中山路123号',
     '上海', '上海', 'China', 2021, 500000.00, 'FLOOD_PRONE'),

    -- Policy 5: Motor – US car
    (5, 'VEHICLE', 'CA-8XYZ123', 'Toyota Camry', '100 Market Street',
     'San Francisco', 'CA', 'USA', 2018, 30000.00, 'LOW'),

    -- Policy 6: Motor – high risk bike
    (6, 'VEHICLE', 'KA05MN9999', 'KTM Duke 390', '1 High Street',
     'Bengaluru', 'Karnataka', 'India', 2020, 350000.00, 'HIGH');

-- ---------------------------------------------------------------------
-- CLAIMS
-- Scenarios:
-- - Open motor claim with partial payments
-- - Historic large property claim (closed)
-- - Active property claim under investigation (potential fraud)
-- - Flood claim China – in process
-- - Small US claim – closed & fully paid
-- - Denied claim for cancelled policy
-- ---------------------------------------------------------------------
INSERT INTO ins.claims
    (claim_number, policy_id, insured_item_id,
     reported_date, loss_date, claim_status, claim_type,
     cause_description, loss_estimate, reserve_amount,
     total_paid_amount, currency, fraud_flag, severity)
VALUES
    -- Claim 1: Motor India – major accident, open
    ('CLM-MOTOR-IN-0001', 1, 1,
     '2024-03-10', '2024-03-09', 'OPEN', 'MOTOR_ACCIDENT',
     'Front-end collision on highway; 2 panels, bumper, radiator damaged.',
     300000.00, 250000.00, 100000.00, 'INR', 'NO', 'HIGH'),

    -- Claim 2: Property India – house fire, closed & fully paid (historic)
    ('CLM-PROP-IN-0001', 2, 2,
     '2022-08-05', '2022-08-03', 'CLOSED', 'FIRE',
     'Kitchen fire spread to living room; structural and contents damage.',
     1500000.00, 1500000.00, 1500000.00, 'INR', 'NO', 'HIGH'),

    -- Claim 3: SME warehouse theft – under investigation, suspected fraud
    ('CLM-PROP-IN-0002', 3, 3,
     '2024-05-01', '2024-04-29', 'UNDER_INVESTIGATION', 'THEFT',
     'Reported theft of high-value electronics; CCTV footage inconclusive.',
     2000000.00, 1800000.00, 0.00, 'INR', 'SUSPECTED', 'HIGH'),

    -- Claim 4: Motor China – flood damage, open
    ('CLM-MOTOR-CN-0001', 4, 4,
     '2024-06-20', '2024-06-18', 'OPEN', 'FLOOD',
     '车辆在暴雨中被淹 / vehicle submerged in heavy rain.',
     180000.00, 150000.00, 50000.00, 'CNY', 'NO', 'HIGH'),

    -- Claim 5: Motor US – small fender-bender, closed & fully paid
    ('CLM-MOTOR-US-0001', 5, 5,
     '2024-01-15', '2024-01-14', 'CLOSED', 'MOTOR_ACCIDENT',
     'Rear bumper scratch in parking lot.',
     1200.00, 1200.00, 1200.00, 'USD', 'NO', 'LOW'),

    -- Claim 6: Denied claim for cancelled high-risk policy
    ('CLM-MOTOR-IN-0002', 6, 6,
     '2023-06-10', '2023-06-08', 'DENIED', 'MOTOR_ACCIDENT',
     'Single-vehicle crash; policy cancelled for non-payment before loss.',
     80000.00, 0.00, 0.00, 'INR', 'CONFIRMED', 'MEDIUM');

-- ---------------------------------------------------------------------
-- CLAIM_EVENTS
-- ---------------------------------------------------------------------
INSERT INTO ins.claim_events
    (claim_id, event_timestamp, event_type, actor_role, actor_name, notes)
VALUES
    -- Claim 1: Motor India – open, multiple events
    (1, '2024-03-10 09:00', 'FNOL',       'CUSTOMER', 'Arjun Mehta',
     'Reported accident via call center.'),
    (1, '2024-03-10 15:00', 'SURVEY',     'ADJUSTER', 'Surveyor Ramesh',
     'On-site inspection; heavy front damage.'),
    (1, '2024-03-12 11:00', 'ASSESSMENT', 'ADJUSTER', 'Surveyor Ramesh',
     'Estimate 3 lakhs, recommend repair at network garage.'),
    (1, '2024-03-15 10:30', 'PAYMENT',    'SYSTEM',   'ClaimsCore',
     'First interim payment processed to garage.'),

    -- Claim 2: Property fire – closed
    (2, '2022-08-05 10:00', 'FNOL',       'CUSTOMER', 'Saraswati Devi',
     'Reported house fire.'),
    (2, '2022-08-06 14:00', 'SURVEY',     'ADJUSTER', 'Inspector Singh',
     'Extensive damage to ground floor.'),
    (2, '2022-08-10 16:30', 'APPROVAL',   'ADJUSTER', 'Claims Manager',
     'Full settlement approved.'),
    (2, '2022-08-15 09:45', 'PAYMENT',    'SYSTEM',   'ClaimsCore',
     'Final settlement payment made.'),

    -- Claim 3: SME theft – under investigation, suspected fraud
    (3, '2024-05-01 08:30', 'FNOL',       'AGENT',    'Broker XYZ',
     'Reported large theft from warehouse.'),
    (3, '2024-05-02 11:00', 'SURVEY',     'ADJUSTER', 'Investigator Mehta',
     'CCTV footage does not clearly show break-in.'),
    (3, '2024-05-10 16:00', 'ASSESSMENT', 'ADJUSTER', 'Fraud Desk',
     'Multiple red flags; mark as suspected fraud.'),

    -- Claim 4: Motor CN flood – open
    (4, '2024-06-20 10:00', 'FNOL',       'CUSTOMER', '张伟',
     '通过手机应用报案 / claim reported via mobile app.'),
    (4, '2024-06-21 09:30', 'SURVEY',     'ADJUSTER', 'Inspector Li',
     'Engine and interior water damage.'),

    -- Claim 5: Motor US – closed
    (5, '2024-01-15 09:00', 'FNOL',       'CUSTOMER', 'Jane Doe',
     'Reported minor collision.'),
    (5, '2024-01-16 11:15', 'ASSESSMENT', 'ADJUSTER', 'John Smith',
     'Minor damage, approve repair.'),
    (5, '2024-01-20 14:00', 'PAYMENT',    'SYSTEM',   'ClaimsCore',
     'Payment to body shop.'),

    -- Claim 6: Denied claim for cancelled policy
    (6, '2023-06-10 10:00', 'FNOL',       'CUSTOMER', 'Arun कुमार',
     'Reported accident; admitted late premium payment.'),
    (6, '2023-06-12 15:30', 'DENIAL',     'ADJUSTER', 'Claims Manager',
     'Claim denied due to policy cancellation before loss date.');

-- ---------------------------------------------------------------------
-- CLAIM_PAYMENTS
-- ---------------------------------------------------------------------
INSERT INTO ins.claim_payments
    (claim_id, payment_date, amount, currency,
     payee_type, payee_name, payment_status, reference_number)
VALUES
    -- Claim 1: Motor India – partial payments to garage and insured
    (1, '2024-03-15', 60000.00, 'INR', 'GARAGE',  'ABC Motors', 'SUCCESS', 'PAY-IN-0001'),
    (1, '2024-03-25', 40000.00, 'INR', 'INSURED', 'Arjun Mehta', 'SUCCESS', 'PAY-IN-0002'),

    -- Claim 2: Property fire – full settlement to insured
    (2, '2022-08-15', 1500000.00, 'INR', 'INSURED', 'Saraswati Devi', 'SUCCESS', 'PAY-IN-0003'),

    -- Claim 3: SME theft – no payments yet (zero rows intentionally)

    -- Claim 4: Motor CN flood – one interim payment to garage, one failed
    (4, '2024-06-25', 30000.00, 'CNY', 'GARAGE', '上汽维修中心', 'SUCCESS', 'PAY-CN-0001'),
    (4, '2024-06-28', 20000.00, 'CNY', 'INSURED','张伟',       'FAILED',  'PAY-CN-0002'),

    -- Claim 5: Motor US – full payment to body shop
    (5, '2024-01-20', 1200.00, 'USD', 'GARAGE', 'Downtown Body Shop', 'SUCCESS', 'PAY-US-0001'),

    -- Claim 6: Denied claim – attempted payment reversed
    (6, '2023-06-15', 10000.00, 'INR', 'INSURED', 'Arun कुमार', 'REVERSED', 'PAY-IN-0004');

-- =====================================================================
-- END OF INSURANCE DOMAIN SEED
-- =====================================================================
