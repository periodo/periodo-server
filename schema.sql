DROP TABLE IF EXISTS dataset;
CREATE TABLE dataset (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	data TEXT NOT NULL
);

DROP TABLE IF EXISTS patch_request;
CREATE TABLE patch_request (
	id integer PRIMARY KEY AUTOINCREMENT,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	created_by TEXT NOT NULL,

	open BOOLEAN NOT NULL DEFAULT 1,
	merged BOOLEAN NOT NULL DEFAULT 0,
	merged_at TIMESTAMP,
	merged_by TEXT,

	created_from INTEGER NOT NULL,
	applied_to INTEGER,
	resulted_in INTEGER,

	FOREIGN KEY(created_from) REFERENCES dataset(id),
	FOREIGN KEY(applied_to) REFERENCES dataset(id)
	FOREIGN KEY(resulted_in) REFERENCES dataset(id)
);

DROP TABLE IF EXISTS patch_text;
CREATE TABLE patch_text (
	id integer PRIMARY KEY AUTOINCREMENT,
	created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	created_by TEXT NOT NULL,
	patch_request INTEGER NOT NULL,
	text TEXT NOT NULL,

	FOREIGN KEY(patch_request) REFERENCES patch_request(id)
);
