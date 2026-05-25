-- Add is_test boolean column to tenants table
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT FALSE;
