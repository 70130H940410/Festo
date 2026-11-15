-- Baseline v1: no live orders, MES identifiers, or receipts in this file.
CREATE TABLE order_list (
    order_id TEXT PRIMARY KEY NOT NULL,
    date DATETIME NOT NULL,
    customer_name TEXT NOT NULL,
    product TEXT NOT NULL,
    amount INTEGER NOT NULL,
    total_price INTEGER NOT NULL,
    step_name TEXT NOT NULL,
    note TEXT,
    rejected_at TEXT,
    status TEXT DEFAULT 'active',
    cancelled_at TEXT,
    estimated_delivery TEXT,
    priority INTEGER DEFAULT 0,
    contact_name TEXT,
    contact_phone TEXT,
    company TEXT,
    address TEXT,
    source TEXT DEFAULT 'web',
    mes_ono INTEGER,
    supabase_order_id INTEGER,
    mes_request TEXT,
    mes_dispatch_state TEXT,
    mes_dispatch_error TEXT,
    mes_receipts TEXT
);
CREATE TABLE factory_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_order_id TEXT,
    current_step_order INTEGER,
    busy_until TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    last_tick_ts REAL DEFAULT 0
);
CREATE TABLE station_state (
    station TEXT PRIMARY KEY,
    current_order_id TEXT,
    current_step_order INTEGER,
    busy_until TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    current_piece_no INTEGER,
    is_error INTEGER DEFAULT 0
);
CREATE TABLE piece_step_progress (
    order_id TEXT NOT NULL,
    piece_no INTEGER NOT NULL,
    step_order INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (order_id, piece_no, step_order)
);
CREATE TABLE order_step_progress (
    order_id TEXT NOT NULL,
    step_order INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    done_qty INTEGER NOT NULL DEFAULT 0,
    total_qty INTEGER NOT NULL DEFAULT 1,
    total_pieces INTEGER DEFAULT 0,
    PRIMARY KEY (order_id, step_order)
);
CREATE TABLE order_piece_state (
    order_id TEXT NOT NULL,
    piece_no INTEGER NOT NULL,
    next_step_idx INTEGER NOT NULL DEFAULT 0,
    next_step_order INTEGER,
    in_process INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id, piece_no)
);
CREATE TABLE order_runtime (
    order_id TEXT PRIMARY KEY,
    total_pieces INTEGER NOT NULL DEFAULT 0,
    completed_pieces INTEGER NOT NULL DEFAULT 0,
    runtime_state TEXT NOT NULL DEFAULT 'waiting',
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE station_jobs (
    step_order INTEGER PRIMARY KEY,
    order_id TEXT,
    piece_no INTEGER,
    done_at REAL
);
PRAGMA user_version = 1;
