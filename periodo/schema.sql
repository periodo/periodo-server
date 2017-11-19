DROP TABLE IF EXISTS dataset;
CREATE TABLE dataset (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at INTEGER DEFAULT (strftime('%s', 'now')),
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
  created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
  created_by TEXT NOT NULL,
  updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
  updated_by TEXT NOT NULL,

  open BOOLEAN NOT NULL DEFAULT 1,
  merged BOOLEAN NOT NULL DEFAULT 0,
  merged_at INTEGER,
  merged_by TEXT,

  created_from INTEGER NOT NULL,
  applied_to INTEGER,
  resulted_in INTEGER,
  created_entities TEXT NOT NULL DEFAULT '[]',
  updated_entities TEXT NOT NULL,
  removed_entities TEXT NOT NULL,
  identifier_map TEXT,

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
  UPDATE patch_request
  SET updated_at = (strftime('%s', 'now'))
  WHERE id = old.id;
END;

DROP TABLE IF EXISTS patch_request_comment;
CREATE TABLE patch_request_comment (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  posted_at INTEGER DEFAULT (strftime('%s', 'now')),
  patch_request_id INTEGER NOT NULL,
  author TEXT NOT NULL,
  message TEXT NOT NULL,

  FOREIGN KEY (patch_request_id) REFERENCES patch_request(id),
  FOREIGN KEY (author) REFERENCES user(id)
);

DROP TABLE IF EXISTS bag;
CREATE TABLE bag (
  uuid TEXT NOT NULL,
  version integer NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
  created_by TEXT NOT NULL,
  owners TEXT NOT NULL,
  data TEXT NOT NULL,

  PRIMARY KEY(uuid, version),
  FOREIGN KEY(created_by) REFERENCES user(id)
);

DROP TABLE IF EXISTS user;
CREATE TABLE user (
  id TEXT PRIMARY KEY NOT NULL,
  name TEXT NOT NULL,
  permissions TEXT NOT NULL DEFAULT '[["action", "submit-patch", "create-bag"]]',
  b64token TEXT UNIQUE NOT NULL,
  token_expires_at INTEGER NOT NULL,
  credentials TEXT NOT NULL,
  credentials_updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
INSERT INTO USER (
  id, name, permissions, b64token, token_expires_at, credentials)
VALUES (
  'initial-data-loader', 'initial data loader', '', '', 0, '');

DROP TRIGGER IF EXISTS update_user_credentials;
CREATE TRIGGER update_user_credentials UPDATE OF credentials ON user
BEGIN
  UPDATE user
  SET credentials_updated_at = (strftime('%s', 'now'))
  WHERE id = old.id;
END;
