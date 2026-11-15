-- Baseline v1: external supply inventory, not the 32 ASRS positions.
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    base_price INTEGER NOT NULL,
    stock NUMERIC NOT NULL
);
CREATE TABLE raw_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE bom (
    product_id INTEGER NOT NULL,
    material_id INTEGER NOT NULL,
    quantity_required INTEGER NOT NULL,
    PRIMARY KEY (product_id, material_id)
);
CREATE TABLE product_name (product TEXT PRIMARY KEY NOT NULL, amount INTEGER NOT NULL);
CREATE TABLE standard_process (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    step_order INTEGER NOT NULL,
    step_name TEXT NOT NULL,
    station TEXT,
    description TEXT,
    estimated_time_sec INTEGER
);
PRAGMA user_version = 1;
