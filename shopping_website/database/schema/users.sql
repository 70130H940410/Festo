-- Baseline v1: structure only. Synthetic users are created by dev.py.
CREATE TABLE registration_key (
    Manager_name TEXT PRIMARY KEY NOT NULL,
    registration_key TEXT NOT NULL UNIQUE
);
CREATE TABLE User_profile (
    id TEXT PRIMARY KEY NOT NULL,
    account TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    registration_key TEXT REFERENCES registration_key(registration_key),
    full_name TEXT
);
PRAGMA user_version = 1;
