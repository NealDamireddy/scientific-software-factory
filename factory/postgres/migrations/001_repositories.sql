CREATE FUNCTION evolve_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% records are immutable', TG_TABLE_NAME;
END
$$;

CREATE TABLE context_revisions (
    revision_id text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('lab', 'project')),
    lab_id text NOT NULL,
    project_id text NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    sha256 text NOT NULL,
    payload text NOT NULL,
    lab_revision integer,
    lab_sha256 text,
    UNIQUE (kind, lab_id, project_id, revision),
    CHECK ((kind = 'lab' AND project_id = '' AND lab_revision IS NULL AND lab_sha256 IS NULL)
        OR (kind = 'project' AND project_id <> '' AND lab_revision IS NOT NULL AND lab_sha256 IS NOT NULL))
);
CREATE TRIGGER immutable_context BEFORE UPDATE OR DELETE ON context_revisions
    FOR EACH ROW EXECUTE FUNCTION evolve_immutable();
CREATE TABLE instrument_owners (instrument_id text PRIMARY KEY, lab_id text NOT NULL);

CREATE TABLE scientific_blobs (digest text PRIMARY KEY, content bytea NOT NULL);
CREATE TABLE scientific_manifests (
    digest text PRIMARY KEY, content bytea NOT NULL, lab text NOT NULL, project text NOT NULL,
    seq bigint GENERATED ALWAYS AS IDENTITY
);
CREATE INDEX scientific_release_history ON scientific_manifests(lab, project, seq DESC);
CREATE TRIGGER immutable_blob BEFORE UPDATE OR DELETE ON scientific_blobs
    FOR EACH ROW EXECUTE FUNCTION evolve_immutable();
CREATE TRIGGER immutable_manifest BEFORE UPDATE OR DELETE ON scientific_manifests
    FOR EACH ROW EXECUTE FUNCTION evolve_immutable();
CREATE TABLE scientific_active (
    lab text, project text, experiment text, digest text NOT NULL REFERENCES scientific_manifests,
    PRIMARY KEY (lab, project, experiment)
);

CREATE TABLE instrument_queues (instrument text PRIMARY KEY);
CREATE TABLE experiment_runs (
    seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id text UNIQUE NOT NULL,
    submission_key text UNIQUE NOT NULL,
    instrument text NOT NULL REFERENCES instrument_queues,
    body json NOT NULL,
    UNIQUE (instrument, run_id)
);
CREATE INDEX experiment_fifo ON experiment_runs (instrument, seq)
    WHERE body->>'acquisition' = 'queued';
CREATE TABLE scheduling_leases (
    instrument text PRIMARY KEY,
    run_id text UNIQUE NOT NULL,
    FOREIGN KEY (instrument, run_id) REFERENCES experiment_runs(instrument, run_id)
);
