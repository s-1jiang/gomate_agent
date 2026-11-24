ALTER TABLE messages ADD COLUMN map_result_json TEXT;
ALTER TABLE runs ADD COLUMN workflow_json TEXT NOT NULL DEFAULT '[]';
