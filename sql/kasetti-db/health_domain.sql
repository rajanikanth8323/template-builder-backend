-- =====================================================================
-- HEALTH / EMR DOMAIN
-- Combined schema + seed data (Postgres reference)
-- =====================================================================

-- ---------------------------------------------------------------------
-- Cleanup
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS emr.billing CASCADE;
DROP TABLE IF EXISTS emr.lab_results CASCADE;
DROP TABLE IF EXISTS emr.medications CASCADE;
DROP TABLE IF EXISTS emr.diagnoses CASCADE;
DROP TABLE IF EXISTS emr.encounters CASCADE;
DROP TABLE IF EXISTS emr.patients CASCADE;

DROP SCHEMA IF EXISTS emr CASCADE;

-- ---------------------------------------------------------------------
-- Schema
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS emr;

-- =====================================================================
-- TABLE DEFINITIONS
-- =====================================================================

-- ---------------------------------------------------------------------
-- PATIENTS: Master patient index
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS emr.patients (
    patient_id         SERIAL PRIMARY KEY,
    mrn                TEXT NOT NULL UNIQUE,           -- Medical Record Number
    full_name          TEXT NOT NULL,
    date_of_birth      DATE NOT NULL,
    gender             TEXT NOT NULL,                  -- e.g. "M", "F", "O"
    primary_language   TEXT DEFAULT 'en',
    national_id        TEXT,                           -- e.g. Aadhar, SSN
    phone              TEXT,
    email              TEXT,
    country            TEXT NOT NULL,
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- ENCOUNTERS: Outpatient visits, ED visits, admissions
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS emr.encounters (
    encounter_id       SERIAL PRIMARY KEY,
    patient_id         INTEGER NOT NULL REFERENCES emr.patients(patient_id),
    encounter_date     TIMESTAMPTZ NOT NULL,
    encounter_type     TEXT NOT NULL,                  -- "OPD", "IPD", "ED"
    department         TEXT NOT NULL,                  -- "Cardiology", "Endocrinology", etc.
    provider_name      TEXT NOT NULL,
    chief_complaint    TEXT,
    notes              TEXT,
    status             TEXT NOT NULL,                  -- "OPEN", "CLOSED", "CANCELLED"
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- DIAGNOSES: ICD-10-coded diagnoses per encounter
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS emr.diagnoses (
    diagnosis_id       SERIAL PRIMARY KEY,
    encounter_id       INTEGER NOT NULL REFERENCES emr.encounters(encounter_id),
    icd10_code         TEXT NOT NULL,                  -- e.g. "E11.9"
    diagnosis_text     TEXT NOT NULL,
    is_primary         BOOLEAN NOT NULL DEFAULT FALSE,
    diagnosis_status   TEXT NOT NULL,                  -- "CONFIRMED", "RULED_OUT", "PRESUMED"
    recorded_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- MEDICATIONS: Orders / prescriptions per encounter
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS emr.medications (
    medication_id      SERIAL PRIMARY KEY,
    encounter_id       INTEGER NOT NULL REFERENCES emr.encounters(encounter_id),
    drug_name          TEXT NOT NULL,
    dose               TEXT NOT NULL,                  -- "500 mg"
    route              TEXT NOT NULL,                  -- "PO", "IV", etc.
    frequency          TEXT NOT NULL,                  -- "OD", "BID", "TID"
    start_date         DATE NOT NULL,
    end_date           DATE,
    is_chronic         BOOLEAN NOT NULL DEFAULT FALSE,
    instructions       TEXT
);

-- ---------------------------------------------------------------------
-- LAB_RESULTS: Lab tests and results per encounter
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS emr.lab_results (
    lab_result_id      SERIAL PRIMARY KEY,
    encounter_id       INTEGER NOT NULL REFERENCES emr.encounters(encounter_id),
    test_code          TEXT NOT NULL,                  -- e.g. "HbA1c"
    test_name          TEXT NOT NULL,
    result_value       NUMERIC(10,3),
    unit               TEXT,
    reference_low      NUMERIC(10,3),
    reference_high     NUMERIC(10,3),
    abnormal_flag      TEXT,                           -- "H", "L", "N"
    collected_at       TIMESTAMPTZ,
    reported_at        TIMESTAMPTZ
);

-- ---------------------------------------------------------------------
-- BILLING: Charges & payment status per encounter
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS emr.billing (
    bill_id            SERIAL PRIMARY KEY,
    encounter_id       INTEGER NOT NULL REFERENCES emr.encounters(encounter_id),
    patient_id         INTEGER NOT NULL REFERENCES emr.patients(patient_id),
    gross_amount       NUMERIC(12,2) NOT NULL,
    discount_amount    NUMERIC(12,2) NOT NULL DEFAULT 0,
    net_amount         NUMERIC(12,2) NOT NULL,
    currency           TEXT NOT NULL DEFAULT 'INR',
    payer_type         TEXT NOT NULL,                  -- "SELF", "INSURANCE"
    insurance_payer    TEXT,
    claim_number       TEXT,
    bill_status        TEXT NOT NULL,                  -- "PENDING", "PARTIALLY_PAID", "PAID", "DENIED", "WRITEOFF"
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at            TIMESTAMPTZ
);

-- =====================================================================
-- SEED DATA
-- =====================================================================

-- ---------------------------------------------------------------------
-- PATIENTS
-- Scenarios:
-- 1  - Indian patient with type 2 diabetes, chronic follow-ups.
-- 2  - Indian patient with hypertension + cardiac issues.
-- 3  - Chinese patient with mixed-language notes.
-- 4  - Pediatric asthma patient.
-- 5  - Elderly patient with multiple comorbidities and unpaid bills.
-- 6  - Patient with RULED_OUT diagnoses.
-- 7  - Multilingual name ("mixed script").
-- 8  - Inactive patient for historical queries.
-- ---------------------------------------------------------------------
INSERT INTO emr.patients
    (mrn,   full_name,              date_of_birth, gender, primary_language, national_id,      phone,              email,                        country,  is_active)
VALUES
    ('MRN0001', 'Ravi Kumar',         '1975-04-10', 'M',   'en',            'AADHAR-1234',   '+91-9000000001', 'ravi.kumar@example.in',       'India',   TRUE),
    ('MRN0002', 'Anita Sharma',       '1982-09-22', 'F',   'en',            'AADHAR-5678',   '+91-9000000002', 'anita.sharma@example.in',     'India',   TRUE),
    ('MRN0003', '张伟',               '1990-01-15', 'M',   'zh',            'CN-ID-0001',    '+86-13800000001','zhang.wei@example.cn',        'China',   TRUE),
    ('MRN0004', 'Rahul Verma',        '2012-06-05', 'M',   'en',            'IND-CHILD-01',  '+91-9000000003', 'rahul.verma.parent@example.com', 'India', TRUE),
    ('MRN0005', 'Saraswati Devi',     '1948-11-30', 'F',   'hi',            'AADHAR-9999',   '+91-9000000004', 's.devi@example.in',           'India',   TRUE),
    ('MRN0006', 'John Doe',           '1985-03-18', 'M',   'en',            'US-SSN-1111',   '+1-212-555-1111','john.doe@example.com',        'USA',     TRUE),
    ('MRN0007', 'Arun कुमार',         '1979-12-02', 'M',   'hi',            'AADHAR-2222',   '+91-9000000005', 'arun.kumar@example.in',       'India',   TRUE),
    ('MRN0008', 'Retired Patient',    '1950-07-19', 'M',   'en',            'HIST-0001',     '+91-9000000006', 'retired.patient@example.in',  'India',   FALSE);

-- ---------------------------------------------------------------------
-- ENCOUNTERS
-- Key scenarios:
-- - Multiple OPD follow-ups for diabetes (MRN0001).
-- - ED visit followed by admission for chest pain (MRN0002).
-- - Visits with mixed-language notes (MRN0003, MRN0007).
-- - Pediatric asthma exacerbation (MRN0004).
-- - Elderly patient with multiple unpaid/denied claims (MRN0005).
-- - Encounter with CANCELLED status (MRN0006).
-- - Historical encounters for inactive patient (MRN0008).
-- ---------------------------------------------------------------------
INSERT INTO emr.encounters
    (patient_id, encounter_date,           encounter_type, department,        provider_name,              chief_complaint,                             notes,                                     status)
VALUES
    -- MRN0001: Diabetes OPD visits
    (1,        NOW() - INTERVAL '180 days', 'OPD',        'Endocrinology',   'Dr. Meera Rao',             'Follow-up for diabetes',                  'Type 2 DM, fair control.',               'CLOSED'),
    (1,        NOW() - INTERVAL '90 days',  'OPD',        'Endocrinology',   'Dr. Meera Rao',             'Follow-up for diabetes',                  'HbA1c trending up.',                      'CLOSED'),
    (1,        NOW() - INTERVAL '30 days',  'OPD',        'Endocrinology',   'Dr. Meera Rao',             'Follow-up for diabetes',                  'Discussed insulin initiation.',           'OPEN'),

    -- MRN0002: Chest pain ED + IPD admission
    (2,        NOW() - INTERVAL '10 days',  'ED',         'Emergency',       'Dr. Sanjay Kulkarni',       'Acute chest pain',                        'Possible ACS, admit to Cardiology.',      'CLOSED'),
    (2,        NOW() - INTERVAL '9 days',   'IPD',        'Cardiology',      'Dr. Priya Menon',           'Inpatient monitoring post-angioplasty',   'PCI done, monitor troponins.',            'OPEN'),

    -- MRN0003: Chinese patient with mixed notes
    (3,        NOW() - INTERVAL '60 days',  'OPD',        'General Medicine','Dr. Li Wei',                '体检 / routine check-up',                 '患者主诉疲劳, 建议做HbA1c检查。',           'CLOSED'),
    (3,        NOW() - INTERVAL '5 days',   'OPD',        'Endocrinology',   'Dr. Li Wei',                '糖尿病随访 / diabetes follow-up',          '血糖控制欠佳, 建议调整用药。',               'OPEN'),

    -- MRN0004: Pediatric asthma
    (4,        NOW() - INTERVAL '20 days',  'ED',         'Pediatrics',      'Dr. Kavita Nair',           'Shortness of breath, wheeze',             'Acute asthma exacerbation.',              'CLOSED'),
    (4,        NOW() - INTERVAL '7 days',   'OPD',        'Pediatrics',      'Dr. Kavita Nair',           'Follow-up asthma',                        'Stable on inhaled steroids.',             'OPEN'),

    -- MRN0005: Elderly with comorbidities
    (5,        NOW() - INTERVAL '120 days', 'OPD',        'Geriatrics',      'Dr. Alok Gupta',            'Gait instability, hypertension',          'Fall risk, needs PT and BP control.',     'CLOSED'),
    (5,        NOW() - INTERVAL '15 days',  'OPD',        'Cardiology',      'Dr. Alok Gupta',            'Dizziness, possible arrhythmia',          'Ordered Holter monitoring.',              'OPEN'),

    -- MRN0006: Cancelled encounter
    (6,        NOW() - INTERVAL '2 days',   'OPD',        'General Medicine','Dr. Jane Smith',            'Annual physical',                         'Appointment cancelled by patient.',       'CANCELLED'),

    -- MRN0007: Mixed-script patient, multiple complaints
    (7,        NOW() - INTERVAL '40 days',  'OPD',        'Neurology',       'Dr. Rahul Iyer',            'Headaches and neck pain',                 'Possible tension headache.',              'CLOSED'),
    (7,        NOW() - INTERVAL '3 days',   'OPD',        'Orthopedics',     'Dr. Rahul Iyer',            'Low back pain',                           'Chronic low back pain, needs MRI.',       'OPEN'),

    -- MRN0008: Historical inactive patient
    (8,        NOW() - INTERVAL '365 days', 'OPD',        'General Medicine','Dr. Old Provider',          'Hypertension follow-up',                  'Lost to follow up.',                       'CLOSED');

-- ---------------------------------------------------------------------
-- DIAGNOSES
-- Scenarios:
-- - Confirmed type 2 diabetes, hypertension, ACS, asthma, etc.
-- - RULED_OUT myocardial infarction, infection, etc.
-- - PRESUMED diagnoses.
-- - Case-sensitive ICD-10 codes and varied diagnosis_status.
-- ---------------------------------------------------------------------
INSERT INTO emr.diagnoses
    (encounter_id, icd10_code, diagnosis_text,                     is_primary, diagnosis_status)
VALUES
    -- MRN0001: Diabetes encounters
    (1, 'E11.9',      'Type 2 diabetes mellitus without complications', TRUE,  'CONFIRMED'),
    (1, 'I10',        'Essential (primary) hypertension',               FALSE, 'CONFIRMED'),
    (2, 'E11.65',     'Type 2 diabetes mellitus with hyperglycemia',    TRUE,  'CONFIRMED'),
    (2, 'E78.5',      'Hyperlipidemia, unspecified',                    FALSE, 'CONFIRMED'),
    (3, 'E11.65',     'Type 2 diabetes mellitus with hyperglycemia',    TRUE,  'CONFIRMED'),

    -- MRN0002: Chest pain ED + IPD
    (4, 'I20.0',      'Unstable angina',                               TRUE,  'PRESUMED'),
    (4, 'R07.9',      'Chest pain, unspecified',                       FALSE, 'CONFIRMED'),
    (4, 'I21.9',      'Acute myocardial infarction, unspecified',      FALSE, 'RULED_OUT'),
    (5, 'I25.10',     'Atherosclerotic heart disease of native artery', TRUE, 'CONFIRMED'),

    -- MRN0003: Chinese patient
    (6, 'E11.9',      '2型糖尿病 / Type 2 diabetes mellitus',          TRUE,  'CONFIRMED'),
    (7, 'E11.65',     '2型糖尿病伴高血糖 / T2DM with hyperglycemia',   TRUE,  'CONFIRMED'),

    -- MRN0004: Pediatric asthma
    (8, 'J45.901',    'Unspecified asthma with (acute) exacerbation',  TRUE,  'CONFIRMED'),
    (9, 'J45.909',    'Unspecified asthma, uncomplicated',             TRUE,  'CONFIRMED'),

    -- MRN0005: Elderly comorbidities
    (10, 'I10',       'Essential (primary) hypertension',              TRUE,  'CONFIRMED'),
    (10, 'R26.81',    'Unsteadiness on feet',                          FALSE, 'CONFIRMED'),
    (11, 'I49.9',     'Cardiac arrhythmia, unspecified',               TRUE,  'PRESUMED'),

    -- MRN0006: Cancelled encounter, RULED_OUT
    (12, 'Z00.00',    'Encounter for general adult medical exam',      TRUE,  'RULED_OUT'),

    -- MRN0007: Headache, back pain, differential diagnoses
    (13, 'R51',       'Headache',                                      TRUE,  'CONFIRMED'),
    (13, 'M54.2',     'Cervicalgia',                                   FALSE, 'PRESUMED'),
    (14, 'M54.5',     'Low back pain',                                 TRUE,  'CONFIRMED'),
    (14, 'M51.9',     'Intervertebral disc disorder, unspecified',     FALSE, 'PRESUMED'),

    -- MRN0008: Historic HTN only
    (15, 'I10',       'Essential (primary) hypertension',              TRUE,  'CONFIRMED');

-- ---------------------------------------------------------------------
-- MEDICATIONS
-- Scenarios:
-- - Chronic oral meds for diabetes, HTN, lipids.
-- - Insulin initiation.
-- - Short-course steroids and inhalers for asthma.
-- - Dual antiplatelet therapy for ACS.
-- - PRN pain meds, mixed routes, multilingual instructions.
-- ---------------------------------------------------------------------
INSERT INTO emr.medications
    (encounter_id, drug_name,         dose,     route, frequency, start_date,   end_date,     is_chronic, instructions)
VALUES
    -- MRN0001: Diabetes/HTN medications
    (1, 'Metformin',        '500 mg', 'PO', 'BID', '2023-01-01', NULL,         TRUE,  'Take with meals.'),
    (1, 'Amlodipine',       '5 mg',   'PO', 'OD',  '2023-01-01', NULL,         TRUE,  'Monitor blood pressure.'),
    (2, 'Metformin',        '1000 mg','PO', 'BID', '2023-06-01', NULL,         TRUE,  'Dose increased due to HbA1c.'),
    (3, 'Insulin glargine', '10 Units','SC','OD',  CURRENT_DATE, NULL,         TRUE,  'Inject at bedtime.'),

    -- MRN0002: ACS / Cardiology
    (4, 'Aspirin',          '75 mg',  'PO', 'OD',  CURRENT_DATE - INTERVAL '9 days', NULL, TRUE, 'DO NOT STOP unless advised.'),
    (5, 'Clopidogrel',      '75 mg',  'PO', 'OD',  CURRENT_DATE - INTERVAL '9 days', NULL, TRUE, 'Post-PCI dual antiplatelet.'),
    (5, 'Atorvastatin',     '40 mg',  'PO', 'OD',  CURRENT_DATE - INTERVAL '9 days', NULL, TRUE, 'High-intensity statin.'),

    -- MRN0003: Chinese patient
    (6, '二甲双胍 / Metformin','500 mg','PO', 'BID', CURRENT_DATE - INTERVAL '60 days', NULL, TRUE, '随餐服用 / take with meals.'),
    (7, '胰岛素甘精 / Insulin glargine','12 Units','SC','OD', CURRENT_DATE - INTERVAL '5 days', NULL, TRUE, '睡前注射 / inject at bedtime.'),

    -- MRN0004: Pediatric asthma
    (8, 'Salbutamol inhaler','2 puffs','INH','PRN', CURRENT_DATE - INTERVAL '20 days', CURRENT_DATE - INTERVAL '18 days', FALSE, 'Use with spacer.'),
    (8, 'Prednisolone',     '1 mg/kg','PO', 'OD',  CURRENT_DATE - INTERVAL '20 days', CURRENT_DATE - INTERVAL '15 days', FALSE, 'Short course.'),
    (9, 'Inhaled corticosteroid','2 puffs','INH','BD', CURRENT_DATE - INTERVAL '7 days', NULL, TRUE, 'Controller inhaler.'),

    -- MRN0005: Elderly
    (10,'Hydrochlorothiazide','12.5 mg','PO','OD', CURRENT_DATE - INTERVAL '120 days', NULL, TRUE, 'Monitor electrolytes.'),

    -- MRN0007: Pain management
    (13,'Paracetamol',      '500 mg', 'PO', 'TID', CURRENT_DATE - INTERVAL '40 days', CURRENT_DATE - INTERVAL '35 days', FALSE, 'As needed for pain.'),
    (14,'Ibuprofen',        '400 mg', 'PO', 'TID', CURRENT_DATE - INTERVAL '3 days', CURRENT_DATE + INTERVAL '4 days', FALSE, 'WITH FOOD / भोजन के साथ लें.');

-- ---------------------------------------------------------------------
-- LAB_RESULTS
-- Scenarios:
-- - HbA1c high/normal for diabetes patients.
-- - Troponin positive/negative for ACS.
-- - Pediatric CBC with mild eosinophilia.
-- - Mixed units and abnormal flags.
-- ---------------------------------------------------------------------
INSERT INTO emr.lab_results
    (encounter_id, test_code, test_name,           result_value, unit, reference_low, reference_high, abnormal_flag, collected_at,                        reported_at)
VALUES
    -- MRN0001: HbA1c over time
    (1, 'HbA1c',  'Glycated hemoglobin', 7.2, '%', 4.0, 5.6, 'H', NOW() - INTERVAL '180 days', NOW() - INTERVAL '179 days'),
    (2, 'HbA1c',  'Glycated hemoglobin', 8.4, '%', 4.0, 5.6, 'H', NOW() - INTERVAL '90 days',  NOW() - INTERVAL '89 days'),
    (3, 'HbA1c',  'Glycated hemoglobin', 9.1, '%', 4.0, 5.6, 'H', NOW() - INTERVAL '30 days',  NOW() - INTERVAL '29 days'),

    -- MRN0002: Troponin, lipid profile
    (4, 'TROPONIN', 'Cardiac troponin I', 0.15, 'ng/mL', 0.00, 0.04, 'H', NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days'),
    (4, 'LDL',      'Low-density lipoprotein cholesterol', 160, 'mg/dL', 0, 100, 'H', NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days'),
    (5, 'TROPONIN', 'Cardiac troponin I', 0.03, 'ng/mL', 0.00, 0.04, 'N', NOW() - INTERVAL '9 days',  NOW() - INTERVAL '9 days'),

    -- MRN0003: Chinese patient HbA1c
    (6, 'HbA1c',    '糖化血红蛋白 / HbA1c', 8.8, '%', 4.0, 5.6, 'H', NOW() - INTERVAL '60 days', NOW() - INTERVAL '59 days'),
    (7, 'HbA1c',    '糖化血红蛋白 / HbA1c', 9.5, '%', 4.0, 5.6, 'H', NOW() - INTERVAL '5 days',  NOW() - INTERVAL '4 days'),

    -- MRN0004: Pediatric CBC
    (8, 'CBC_EOS',  'Eosinophils', 8.0, '%', 1.0, 4.0, 'H', NOW() - INTERVAL '20 days', NOW() - INTERVAL '19 days'),

    -- MRN0005: Elderly - creatinine, sodium
    (10,'CREAT',    'Serum Creatinine', 1.6, 'mg/dL', 0.6, 1.2, 'H', NOW() - INTERVAL '120 days', NOW() - INTERVAL '120 days'),
    (10,'NA',       'Serum Sodium',    130, 'mmol/L', 135, 145, 'L', NOW() - INTERVAL '120 days', NOW() - INTERVAL '120 days'),

    -- MRN0007: None (no labs) - to test join scenarios with missing labs

    -- MRN0008: Old normal labs
    (15,'CREAT',    'Serum Creatinine', 0.9, 'mg/dL', 0.6, 1.2, 'N', NOW() - INTERVAL '365 days', NOW() - INTERVAL '365 days');

-- ---------------------------------------------------------------------
-- BILLING
-- Scenarios:
-- - Fully paid encounters (SELF, INSURANCE).
-- - Pending bills, partially paid bills.
-- - Denied insurance claim.
-- - Historical paid bill for inactive patient.
-- ---------------------------------------------------------------------
INSERT INTO emr.billing
    (encounter_id, patient_id, gross_amount, discount_amount, net_amount,
     currency, payer_type, insurance_payer, claim_number, bill_status, created_at,           paid_at)
VALUES
    -- MRN0001: Diabetes OPD visits
    (1, 1, 1500.00, 0.00, 1500.00, 'INR', 'SELF',      NULL,         NULL,             'PAID',           NOW() - INTERVAL '180 days', NOW() - INTERVAL '179 days'),
    (2, 1, 1800.00, 300.00,1500.00, 'INR', 'INSURANCE', 'HealthCo', 'HC-CLAIM-0001',  'PAID',           NOW() - INTERVAL '90 days',  NOW() - INTERVAL '88 days'),
    (3, 1, 2000.00, 0.00, 2000.00, 'INR', 'SELF',      NULL,         NULL,             'PENDING',        NOW() - INTERVAL '30 days',  NULL),

    -- MRN0002: ED + IPD
    (4, 2, 8000.00, 0.00, 8000.00, 'INR', 'INSURANCE', 'MediCare',  'MC-ED-0001',     'PAID',           NOW() - INTERVAL '10 days',  NOW() - INTERVAL '9 days'),
    (5, 2,120000.00,0.00,120000.00,'INR','INSURANCE', 'MediCare',   'MC-IPD-0001',    'PARTIALLY_PAID', NOW() - INTERVAL '9 days',   NOW() - INTERVAL '5 days'),

    -- MRN0003: Chinese patient
    (6, 3, 300.00,  0.00, 300.00,  'CNY','SELF',      NULL,         NULL,             'PAID',           NOW() - INTERVAL '60 days',  NOW() - INTERVAL '59 days'),
    (7, 3, 450.00,  0.00, 450.00,  'CNY','INSURANCE', 'CN-Health',  'CN-CLM-0001',    'PENDING',        NOW() - INTERVAL '5 days',   NULL),

    -- MRN0004: Pediatric asthma
    (8, 4, 5000.00, 0.00, 5000.00, 'INR','SELF',      NULL,         NULL,             'PAID',           NOW() - INTERVAL '20 days',  NOW() - INTERVAL '19 days'),
    (9, 4, 1500.00, 0.00, 1500.00, 'INR','SELF',      NULL,         NULL,             'PENDING',        NOW() - INTERVAL '7 days',   NULL),

    -- MRN0005: Elderly patient with complex billing
    (10,5, 2000.00, 0.00, 2000.00, 'INR','INSURANCE', 'SeniorHealth','SH-0001',       'DENIED',         NOW() - INTERVAL '120 days', NULL),
    (11,5, 6000.00, 500.00,5500.00,'INR','SELF',      NULL,         NULL,             'PENDING',        NOW() - INTERVAL '15 days',  NULL),

    -- MRN0006: Cancelled encounter (no charge)
    (12,6,  0.00,   0.00, 0.00,    'INR','SELF',      NULL,         NULL,             'WRITEOFF',       NOW() - INTERVAL '2 days',   NULL),

    -- MRN0007: Multiple visits, one paid, one pending
    (13,7,  1200.00,0.00,1200.00,  'INR','SELF',      NULL,         NULL,             'PAID',           NOW() - INTERVAL '40 days',  NOW() - INTERVAL '39 days'),
    (14,7,  3000.00,0.00,3000.00,  'INR','SELF',      NULL,         NULL,             'PENDING',        NOW() - INTERVAL '3 days',   NULL),

    -- MRN0008: Historical inactive patient - all paid
    (15,8,  1000.00,0.00,1000.00,  'INR','SELF',      NULL,         NULL,             'PAID',           NOW() - INTERVAL '365 days', NOW() - INTERVAL '364 days');

-- =====================================================================
-- END OF HEALTH / EMR SEED
-- =====================================================================
