DROP TABLE IF EXISTS dataset;
CREATE TABLE dataset (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  data TEXT NOT NULL,
  description TEXT NOT NULL
);
INSERT INTO dataset (
  id, data, description)
VALUES (
  0, '{}', 'Initial empty dataset.');

DROP TABLE IF EXISTS patch_request;
CREATE TABLE patch_request (
  id integer PRIMARY KEY AUTOINCREMENT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by TEXT NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_by TEXT NOT NULL,

  open BOOLEAN NOT NULL DEFAULT 1,
  merged BOOLEAN NOT NULL DEFAULT 0,
  merged_at TIMESTAMP,
  merged_by TEXT,

  created_from INTEGER NOT NULL,
  applied_to INTEGER,
  resulted_in INTEGER,
  affected_entities TEXT NOT NULL,

  original_patch TEXT NOT NULL,
  applied_patch TEXT,

  FOREIGN KEY(created_by) REFERENCES user(id),
  FOREIGN KEY(merged_by) REFERENCES user(id),

  FOREIGN KEY(created_from) REFERENCES dataset(id),
  FOREIGN KEY(applied_to) REFERENCES dataset(id)
  FOREIGN KEY(resulted_in) REFERENCES dataset(id)
);

DROP TRIGGER IF EXISTS update_patch;
CREATE TRIGGER update_patch UPDATE OF original_patch ON patch_request
BEGIN
  UPDATE patch_request SET updated_at = CURRENT_TIMESTAMP WHERE id = old.id;
END;

DROP TABLE IF EXISTS user;
CREATE TABLE user (
  id TEXT PRIMARY KEY NOT NULL,
  name TEXT NOT NULL,
  permissions TEXT NOT NULL DEFAULT '[["action", "submit-patch"]]',
  b64token TEXT UNIQUE NOT NULL,
  token_expires_at_unixtime INTEGER NOT NULL,
  credentials TEXT NOT NULL,
  credentials_updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO USER (
  id, name, permissions, b64token, token_expires_at_unixtime, credentials)
VALUES (
  'initial-data-loader', 'initial data loader', '', '', 0, '');

DROP TRIGGER IF EXISTS update_user_credentials;
CREATE TRIGGER update_user_credentials UPDATE OF credentials ON user
BEGIN
  UPDATE user SET credentials_updated_at = CURRENT_TIMESTAMP WHERE id = old.id;
END;

