-- =====================================================================
-- MANUFACTURING / PRODUCTION & QUALITY DOMAIN
-- Combined schema + seed data (Postgres reference)
-- =====================================================================

-- ---------------------------------------------------------------------
-- Cleanup
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS mfg.quality_inspections CASCADE;
DROP TABLE IF EXISTS mfg.production_operations CASCADE;
DROP TABLE IF EXISTS mfg.production_orders CASCADE;
DROP TABLE IF EXISTS mfg.bom_components CASCADE;
DROP TABLE IF EXISTS mfg.bom_headers CASCADE;
DROP TABLE IF EXISTS mfg.materials CASCADE;
DROP TABLE IF EXISTS mfg.work_centers CASCADE;
DROP TABLE IF EXISTS mfg.plants CASCADE;

DROP SCHEMA IF EXISTS mfg CASCADE;

-- ---------------------------------------------------------------------
-- Schema
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS mfg;

-- =====================================================================
-- TABLE DEFINITIONS
-- =====================================================================

-- ---------------------------------------------------------------------
-- PLANTS: Manufacturing sites
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mfg.plants (
    plant_id    SERIAL PRIMARY KEY,
    plant_code  TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    country     TEXT NOT NULL,
    timezone    TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- WORK_CENTERS: Production resources / lines
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mfg.work_centers (
    work_center_id  SERIAL PRIMARY KEY,
    plant_id        INTEGER NOT NULL REFERENCES mfg.plants(plant_id),
    wc_code         TEXT NOT NULL,
    name            TEXT NOT NULL,
    wc_type         TEXT NOT NULL, -- ASSEMBLY, PAINT, TEST, PACKING, CNC, SMT, etc.
    capacity_per_day NUMERIC(10,2),
    is_critical     BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (plant_id, wc_code)
);

-- ---------------------------------------------------------------------
-- MATERIALS: Finished goods and components
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mfg.materials (
    material_id     SERIAL PRIMARY KEY,
    material_number TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    description     TEXT,
    base_unit       TEXT NOT NULL, -- EA, KG, M
    product_type    TEXT NOT NULL, -- FG (finished good), SFG, RM (raw material)
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    default_plant_id INTEGER REFERENCES mfg.plants(plant_id)
);

-- ---------------------------------------------------------------------
-- BOM_HEADERS: Bill-of-material headers for FG/SFG
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mfg.bom_headers (
    bom_id          SERIAL PRIMARY KEY,
    material_id     INTEGER NOT NULL REFERENCES mfg.materials(material_id),
    revision        TEXT NOT NULL,
    is_current      BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from      DATE NOT NULL,
    valid_to        DATE,
    status          TEXT NOT NULL, -- ACTIVE, OBSOLETE
    UNIQUE (material_id, revision)
);

-- ---------------------------------------------------------------------
-- BOM_COMPONENTS: Components per BOM
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mfg.bom_components (
    bom_component_id    SERIAL PRIMARY KEY,
    bom_id              INTEGER NOT NULL REFERENCES mfg.bom_headers(bom_id),
    component_material_id INTEGER NOT NULL REFERENCES mfg.materials(material_id),
    quantity_per        NUMERIC(18,4) NOT NULL,
    unit                TEXT NOT NULL,
    scrap_percent       NUMERIC(5,2) NOT NULL DEFAULT 0.00
);

-- ---------------------------------------------------------------------
-- PRODUCTION_ORDERS: Discrete manufacturing orders
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mfg.production_orders (
    order_id        SERIAL PRIMARY KEY,
    order_number    TEXT NOT NULL UNIQUE,
    plant_id        INTEGER NOT NULL REFERENCES mfg.plants(plant_id),
    material_id     INTEGER NOT NULL REFERENCES mfg.materials(material_id),
    order_quantity  NUMERIC(18,2) NOT NULL,
    unit            TEXT NOT NULL,
    start_date      DATE NOT NULL,
    due_date        DATE NOT NULL,
    status          TEXT NOT NULL, -- PLANNED, RELEASED, IN_PROCESS, COMPLETED, CANCELLED
    priority        TEXT NOT NULL, -- LOW, NORMAL, HIGH, URGENT
    customer_name   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- PRODUCTION_OPERATIONS: Routing steps per order
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mfg.production_operations (
    operation_id    SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES mfg.production_orders(order_id),
    work_center_id  INTEGER NOT NULL REFERENCES mfg.work_centers(work_center_id),
    op_number       INTEGER NOT NULL,
    description     TEXT NOT NULL,
    planned_start   TIMESTAMPTZ NOT NULL,
    planned_end     TIMESTAMPTZ NOT NULL,
    actual_start    TIMESTAMPTZ,
    actual_end      TIMESTAMPTZ,
    status          TEXT NOT NULL, -- PLANNED, IN_PROCESS, DONE, SKIPPED
    scrap_quantity  NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    UNIQUE (order_id, op_number)
);

-- ---------------------------------------------------------------------
-- QUALITY_INSPECTIONS: Order-level quality checks
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mfg.quality_inspections (
    inspection_id       SERIAL PRIMARY KEY,
    order_id            INTEGER NOT NULL REFERENCES mfg.production_orders(order_id),
    material_id         INTEGER NOT NULL REFERENCES mfg.materials(material_id),
    inspection_date     TIMESTAMPTZ NOT NULL,
    inspector_name      TEXT NOT NULL,
    result              TEXT NOT NULL, -- PASS, FAIL, REWORK
    defect_code         TEXT,
    defect_description  TEXT,
    scrap_quantity      NUMERIC(18,2) NOT NULL DEFAULT 0.00
);

-- =====================================================================
-- SEED DATA
-- =====================================================================

-- ---------------------------------------------------------------------
-- PLANTS
-- ---------------------------------------------------------------------
INSERT INTO mfg.plants (plant_code, name, country, timezone)
VALUES
    ('PLT-IN-BLR', 'Bengaluru Electronics Plant', 'India', 'Asia/Kolkata'),
    ('PLT-CN-SHZ', '深圳装配工厂 / Shenzhen Assembly Plant', 'China', 'Asia/Shanghai');

-- ---------------------------------------------------------------------
-- WORK_CENTERS
-- Scenarios:
-- - Critical SMT line, assembly, test, packing.
-- - Chinese plant with different names and multilingual.
-- ---------------------------------------------------------------------
INSERT INTO mfg.work_centers (plant_id, wc_code, name, wc_type, capacity_per_day, is_critical)
VALUES
    (1, 'SMT-01', 'Surface Mount Line 1', 'SMT', 10000.00, TRUE),
    (1, 'ASM-01', 'Final Assembly Line 1', 'ASSEMBLY', 800.00, TRUE),
    (1, 'TST-01', 'Functional Test Bench', 'TEST', 900.00, TRUE),
    (1, 'PKG-01', 'Packing Line 1', 'PACKING', 1200.00, FALSE),
    (2, 'SMT-CN1', 'SMT线1 / SMT Line 1', 'SMT', 12000.00, TRUE),
    (2, 'ASM-CN1', '组装线1 / Assembly Line 1', 'ASSEMBLY', 1000.00, TRUE);

-- ---------------------------------------------------------------------
-- MATERIALS
-- Scenarios:
-- - Finished goods (routers, IoT gateways).
-- - Semi-finished PCBA.
-- - Raw materials: PCB, chipset, casing, screws, labels.
-- - Multilingual names, case-sensitive material numbers.
-- ---------------------------------------------------------------------
INSERT INTO mfg.materials (
    material_number, name, description, base_unit, product_type, is_active, default_plant_id
)
VALUES
    ('FG-RTR-AC1200', 'WiFi Router AC1200', 'Dual-band wireless router', 'EA', 'FG', TRUE, 1),
    ('FG-IOT-GW-4G', 'IoT Gateway 4G', 'Industrial IoT gateway with 4G', 'EA', 'FG', TRUE, 1),
    ('SFG-RTR-PCBA', 'Router Main PCBA', 'Assembled PCB for router', 'EA', 'SFG', TRUE, 1),
    ('RM-PCB-6LAYER', '6-layer PCB', '6-layer HDI PCB', 'EA', 'RM', TRUE, 1),
    ('RM-CHIP-CPU1', 'CPU Chip R1', 'Router CPU SoC', 'EA', 'RM', TRUE, 1),
    ('RM-CASE-PLASTIC', 'Router Plastic Case', 'Injection-molded router casing', 'EA', 'RM', TRUE, 1),
    ('RM-SCREW-M2', 'Screw M2x8', 'M2x8 screw, stainless', 'EA', 'RM', TRUE, 1),
    ('RM-LABEL-EN', 'Label EN', 'English label', 'EA', 'RM', TRUE, 1),
    ('FG-AP-CN', '无线接入点 / Wireless AP', 'Ceiling mount AP for CN market', 'EA', 'FG', TRUE, 2),
    ('RM-LABEL-CN', '标签-中文 / Label CN', 'Chinese regulatory label', 'EA', 'RM', TRUE, 2);

-- ---------------------------------------------------------------------
-- BOM_HEADERS
-- Scenarios:
-- - Multiple revisions (A, B) for router FG, with current and obsolete BOMs.
-- - BOM for CN AP with Chinese labels.
-- ---------------------------------------------------------------------
INSERT INTO mfg.bom_headers (material_id, revision, is_current, valid_from, valid_to, status)
VALUES
    -- Router AC1200 BOM Rev A (obsolete)
    (1, 'A', FALSE, '2023-01-01', '2023-06-30', 'OBSOLETE'),
    -- Router AC1200 BOM Rev B (current)
    (1, 'B', TRUE, '2023-07-01', NULL, 'ACTIVE'),
    -- IoT Gateway BOM Rev A (current)
    (2, 'A', TRUE, '2023-01-01', NULL, 'ACTIVE'),
    -- Wireless AP CN BOM Rev A (current)
    (9, 'A', TRUE, '2023-01-01', NULL, 'ACTIVE');

-- ---------------------------------------------------------------------
-- BOM_COMPONENTS
-- Scenarios:
-- - Different scrap percentages, multiple components.
-- - Obsolete vs current BOM differences.
-- ---------------------------------------------------------------------
INSERT INTO mfg.bom_components (bom_id, component_material_id, quantity_per, unit, scrap_percent)
VALUES
    -- Router AC1200 Rev A (ID 1)
    (1, 3, 1.0000, 'EA', 1.00),  -- SFG PCBA
    (1, 6, 1.0000, 'EA', 0.50),  -- Plastic case
    (1, 7, 4.0000, 'EA', 2.00),  -- Screws
    (1, 8, 1.0000, 'EA', 0.00),  -- English label

    -- Router AC1200 Rev B (ID 2) - more screws due to design change
    (2, 3, 1.0000, 'EA', 1.00),
    (2, 6, 1.0000, 'EA', 0.50),
    (2, 7, 6.0000, 'EA', 3.00),
    (2, 8, 1.0000, 'EA', 0.00),

    -- IoT Gateway BOM Rev A (ID 3)
    (3, 3, 1.0000, 'EA', 1.50),
    (3, 6, 1.0000, 'EA', 1.00),
    (3, 7, 4.0000, 'EA', 2.00),
    (3, 8, 1.0000, 'EA', 0.00),

    -- Wireless AP CN BOM Rev A (ID 4)
    (4, 3, 1.0000, 'EA', 1.50),
    (4, 6, 1.0000, 'EA', 0.50),
    (4, 7, 4.0000, 'EA', 2.00),
    (4,10, 1.0000, 'EA', 0.00); -- Chinese label

-- ---------------------------------------------------------------------
-- PRODUCTION_ORDERS
-- Scenarios:
-- - On-time completed orders, late orders, in-process urgent orders.
-- - Cancelled order with BOM revision switch.
-- - Orders in different plants, with different FG materials.
-- ---------------------------------------------------------------------
INSERT INTO mfg.production_orders (
    order_number, plant_id, material_id, order_quantity, unit,
    start_date, due_date, status, priority, customer_name
)
VALUES
    -- Router AC1200, on time completed
    ('MO-2024-0001', 1, 1, 500.00, 'EA',
     '2024-01-01', '2024-01-10', 'COMPLETED', 'NORMAL', 'Kasetti Digital Pvt Ltd'),

    -- Router AC1200, delayed and high priority
    ('MO-2024-0002', 1, 1, 800.00, 'EA',
     '2024-01-15', '2024-01-25', 'IN_PROCESS', 'URGENT', 'Acme Corp'),

    -- IoT Gateway, in process, normal priority
    ('MO-2024-0003', 1, 2, 200.00, 'EA',
     '2024-02-01', '2024-02-20', 'IN_PROCESS', 'HIGH', 'Ravi & Sons Exports'),

    -- IoT Gateway, planned only
    ('MO-2024-0004', 1, 2, 100.00, 'EA',
     '2024-03-01', '2024-03-15', 'PLANNED', 'NORMAL', 'Internal Stock'),

    -- Wireless AP CN, completed in Chinese plant
    ('MO-2024-0005', 2, 9, 300.00, 'EA',
     '2024-01-05', '2024-01-20', 'COMPLETED', 'NORMAL', '上海云科有限公司'),

    -- Router AC1200, cancelled order
    ('MO-2024-0006', 1, 1, 1000.00, 'EA',
     '2024-01-10', '2024-01-30', 'CANCELLED', 'HIGH', 'EuroDistrib GmbH');

-- ---------------------------------------------------------------------
-- PRODUCTION_OPERATIONS
-- Scenarios:
-- - Full routing (SMT, Assembly, Test, Pack) with varying timing.
-- - Partial completion (some operations done, others planned).
-- - Scrap quantities recorded at test operations.
-- ---------------------------------------------------------------------
INSERT INTO mfg.production_operations (
    order_id, work_center_id, op_number, description,
    planned_start, planned_end, actual_start, actual_end,
    status, scrap_quantity
)
VALUES
    -- MO-2024-0001 (COMPLETED, on time)
    (1, 1, 10, 'SMT placement',  '2024-01-01 08:00', '2024-01-02 18:00',
                                 '2024-01-01 08:30', '2024-01-02 17:45', 'DONE', 5.00),
    (1, 2, 20, 'Final assembly', '2024-01-03 08:00', '2024-01-05 18:00',
                                 '2024-01-03 09:00', '2024-01-05 18:30', 'DONE', 3.00),
    (1, 3, 30, 'Functional test','2024-01-06 08:00', '2024-01-07 18:00',
                                 '2024-01-06 08:15', '2024-01-07 17:00', 'DONE', 10.00),
    (1, 4, 40, 'Packing',        '2024-01-08 08:00', '2024-01-10 18:00',
                                 '2024-01-08 08:30', '2024-01-10 16:00', 'DONE', 0.00),

    -- MO-2024-0002 (IN_PROCESS, SMT done, assembly ongoing)
    (2, 1, 10, 'SMT placement',  '2024-01-15 08:00', '2024-01-17 18:00',
                                 '2024-01-15 09:00', '2024-01-18 19:00', 'DONE', 15.00),
    (2, 2, 20, 'Final assembly', '2024-01-18 08:00', '2024-01-21 18:00',
                                 '2024-01-19 09:00', NULL,                 'IN_PROCESS', 5.00),
    (2, 3, 30, 'Functional test','2024-01-22 08:00', '2024-01-23 18:00',
                                 NULL,                NULL,                 'PLANNED', 0.00),
    (2, 4, 40, 'Packing',        '2024-01-24 08:00', '2024-01-25 18:00',
                                 NULL,                NULL,                 'PLANNED', 0.00),

    -- MO-2024-0003 (IoT Gateway, SMT done, rest planned)
    (3, 1, 10, 'SMT placement',  '2024-02-01 08:00', '2024-02-03 18:00',
                                 '2024-02-01 08:10', '2024-02-03 19:00', 'DONE', 8.00),
    (3, 2, 20, 'Final assembly', '2024-02-04 08:00', '2024-02-10 18:00',
                                 NULL,                NULL,               'PLANNED', 0.00),
    (3, 3, 30, 'Functional test','2024-02-11 08:00', '2024-02-15 18:00',
                                 NULL,                NULL,               'PLANNED', 0.00),

    -- MO-2024-0005 (CN plant, fully done)
    (5, 5, 10, 'SMT放置 / SMT placement', '2024-01-05 08:00', '2024-01-07 18:00',
                                         '2024-01-05 08:30', '2024-01-07 17:30', 'DONE', 6.00),
    (5, 6, 20, '终装 / Final assembly',   '2024-01-08 08:00', '2024-01-12 18:00',
                                         '2024-01-08 09:00', '2024-01-12 18:00', 'DONE', 4.00),
    (5, 3, 30, '测试 / Functional test',  '2024-01-13 08:00', '2024-01-15 18:00',
                                         '2024-01-13 08:15', '2024-01-15 17:00', 'DONE', 8.00),
    (5, 4, 40, '包装 / Packing',         '2024-01-16 08:00', '2024-01-20 18:00',
                                         '2024-01-16 08:20', '2024-01-20 17:00', 'DONE', 0.00);

-- ---------------------------------------------------------------------
-- QUALITY_INSPECTIONS
-- Scenarios:
-- - Pass with small scrap, fail with large scrap, rework.
-- - Orders with no inspections (for join edge cases).
-- ---------------------------------------------------------------------
INSERT INTO mfg.quality_inspections (
    order_id, material_id, inspection_date, inspector_name,
    result, defect_code, defect_description, scrap_quantity
)
VALUES
    -- MO-2024-0001: PASS with small scrap
    (1, 1, '2024-01-10 15:00', 'Inspector A', 'PASS', NULL, NULL, 5.00),

    -- MO-2024-0002: REWORK due to high failure rate
    (2, 1, '2024-01-25 16:00', 'Inspector B', 'REWORK', 'FUNC-FAIL',
     'High functional failure rate at test', 30.00),

    -- MO-2024-0003: Pending / not yet inspected (no row intentionally)

    -- MO-2024-0005: FAIL with scrap
    (5, 9, '2024-01-20 14:00', 'Inspector CN-1', 'FAIL', 'AP-COSMETIC',
     'Cosmetic defects on casing', 20.00);

-- =====================================================================
-- END OF MANUFACTURING / PRODUCTION SEED
-- =====================================================================
