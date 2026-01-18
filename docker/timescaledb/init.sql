-- MTP Gateway WebUI Database Schema
-- TimescaleDB initialization for time-series data storage
-- Compatible with PostgreSQL 14+ and TimescaleDB 2.x

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Roles table (must be created before users due to foreign key)
CREATE TABLE roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(32) UNIQUE NOT NULL,        -- 'operator', 'engineer', 'admin'
    permissions JSONB NOT NULL
);

-- Default roles with permissions
INSERT INTO roles (name, permissions) VALUES
    ('operator', '{"tags:read": true, "services:read": true, "services:command": true, "alarms:read": true, "alarms:ack": true}'),
    ('engineer', '{"tags:read": true, "tags:write": true, "services:read": true, "services:command": true, "alarms:read": true, "alarms:ack": true, "alarms:shelve": true, "config:read": true}'),
    ('admin', '{"tags:read": true, "tags:write": true, "services:read": true, "services:command": true, "alarms:read": true, "alarms:ack": true, "alarms:shelve": true, "config:read": true, "config:write": true, "users:read": true, "users:write": true}');

-- Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role_id INTEGER REFERENCES roles(id),
    is_active BOOLEAN DEFAULT TRUE,
    failed_login_attempts INTEGER DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Alarms table (ISA-18.2 compliant states)
CREATE TABLE alarms (
    id SERIAL PRIMARY KEY,
    alarm_id VARCHAR(64) NOT NULL,
    source VARCHAR(128) NOT NULL,
    priority INTEGER CHECK (priority BETWEEN 1 AND 4),
    state VARCHAR(32) NOT NULL,              -- active/acknowledged/cleared/shelved
    message TEXT NOT NULL,
    value DOUBLE PRECISION,
    raised_at TIMESTAMPTZ DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by INTEGER REFERENCES users(id),
    cleared_at TIMESTAMPTZ,
    shelved_until TIMESTAMPTZ
);

-- Create index on alarm state for common queries
CREATE INDEX idx_alarms_state ON alarms(state);
CREATE INDEX idx_alarms_raised_at ON alarms(raised_at DESC);

-- Tag history table (TimescaleDB hypertable)
CREATE TABLE tag_history (
    time TIMESTAMPTZ NOT NULL,
    tag_name VARCHAR(255) NOT NULL,
    value DOUBLE PRECISION,
    quality VARCHAR(50) NOT NULL
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('tag_history', 'time');

-- Create index on tag_name for efficient queries
CREATE INDEX idx_tag_history_tag_name ON tag_history(tag_name, time DESC);

-- Audit log table (TimescaleDB hypertable)
CREATE TABLE audit_log (
    id BIGSERIAL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id INTEGER REFERENCES users(id),
    username VARCHAR(64),
    action VARCHAR(64) NOT NULL,
    target VARCHAR(255),
    details JSONB,
    success BOOLEAN DEFAULT TRUE,
    ip_address INET
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('audit_log', 'timestamp');

-- Create index for common audit queries
CREATE INDEX idx_audit_log_user ON audit_log(user_id, timestamp DESC);
CREATE INDEX idx_audit_log_action ON audit_log(action, timestamp DESC);

-- Create default admin user (password: admin - CHANGE IN PRODUCTION!)
-- Password hash is argon2id for 'admin'
INSERT INTO users (username, email, password_hash, role_id)
SELECT 'admin', 'admin@localhost', '$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$RdescudvJCsgt3ub+b+dWRWJTmaaJObG', roles.id
FROM roles WHERE roles.name = 'admin';
