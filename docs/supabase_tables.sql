-- Supabase 建表 SQL
-- 在 Supabase Dashboard > SQL Editor 貼上執行

-- tblResource
CREATE TABLE IF NOT EXISTS tbl_resource (
  resource_id   INT PRIMARY KEY,
  resource_name TEXT,
  resource_type INT
);

-- tblResourceOperation
CREATE TABLE IF NOT EXISTS tbl_resource_operation (
  resource_id  INT,
  op_no        INT,
  working_time INT,
  offset_time  INT,
  PRIMARY KEY (resource_id, op_no)
);

-- tblWorkPlanDef
CREATE TABLE IF NOT EXISTS tbl_work_plan_def (
  wp_no       INT PRIMARY KEY,
  description TEXT,
  short       TEXT
);

-- tblStepDef
CREATE TABLE IF NOT EXISTS tbl_step_def (
  wp_no             INT,
  step_no           INT,
  description       TEXT,
  op_no             INT,
  next_step_no      INT,
  first_step        BOOLEAN,
  resource_id       INT,
  working_time_calc INT,
  PRIMARY KEY (wp_no, step_no)
);

-- tblMachineReport
CREATE TABLE IF NOT EXISTS tbl_machine_report (
  id             BIGINT PRIMARY KEY,
  resource_id    INT,
  timestamp      TIMESTAMPTZ,
  automatic_mode BOOLEAN,
  manual_mode    BOOLEAN,
  busy           BOOLEAN,
  reset          BOOLEAN,
  error_l0       BOOLEAN,
  error_l1       BOOLEAN,
  error_l2       BOOLEAN
);
CREATE INDEX IF NOT EXISTS idx_machine_report_resource ON tbl_machine_report(resource_id, id DESC);

-- tblOrder
CREATE TABLE IF NOT EXISTS tbl_order (
  ono         INT PRIMARY KEY,
  planed_start TIMESTAMPTZ,
  planed_end   TIMESTAMPTZ,
  start        TIMESTAMPTZ,
  "end"        TIMESTAMPTZ,
  state        INT,
  enabled      BOOLEAN,
  cno          INT
);

-- tblFinStep
CREATE TABLE IF NOT EXISTS tbl_fin_step (
  ono         INT,
  step_no     INT,
  wp_no       INT,
  description TEXT,
  resource_id INT,
  planed_start TIMESTAMPTZ,
  planed_end   TIMESTAMPTZ,
  start        TIMESTAMPTZ,
  "end"        TIMESTAMPTZ,
  PRIMARY KEY (ono, step_no)
);

-- Enable Row Level Security (allow public read for anon key)
ALTER TABLE tbl_resource         ENABLE ROW LEVEL SECURITY;
ALTER TABLE tbl_resource_operation ENABLE ROW LEVEL SECURITY;
ALTER TABLE tbl_work_plan_def    ENABLE ROW LEVEL SECURITY;
ALTER TABLE tbl_step_def         ENABLE ROW LEVEL SECURITY;
ALTER TABLE tbl_machine_report   ENABLE ROW LEVEL SECURITY;
ALTER TABLE tbl_order            ENABLE ROW LEVEL SECURITY;
ALTER TABLE tbl_fin_step         ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all" ON tbl_resource          FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON tbl_resource_operation FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON tbl_work_plan_def     FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON tbl_step_def          FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON tbl_machine_report    FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON tbl_order             FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON tbl_fin_step          FOR ALL USING (true) WITH CHECK (true);
