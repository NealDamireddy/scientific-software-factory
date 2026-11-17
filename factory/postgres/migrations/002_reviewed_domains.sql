CREATE TABLE catalog_revisions (
    revision_id text PRIMARY KEY, lab_id text NOT NULL, kind text NOT NULL
        CHECK (kind IN ('catalog','source','evidence')), record_id text NOT NULL,
    revision integer NOT NULL CHECK (revision > 0), sha256 text NOT NULL, author text NOT NULL,
    created_at text NOT NULL, predecessor_id text REFERENCES catalog_revisions, payload text NOT NULL,
    UNIQUE (lab_id,kind,record_id,revision),
    CHECK ((revision=1) = (predecessor_id IS NULL))
);
CREATE TABLE catalog_approvals (
    revision_id text PRIMARY KEY REFERENCES catalog_revisions, approver text NOT NULL, approved_at text NOT NULL
);

CREATE TABLE sci_artifact_revision (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lab_id text NOT NULL, project_id text NOT NULL, kind text NOT NULL
        CHECK (kind IN ('knowledge','requirement','blueprint','specification')),
    artifact_id text NOT NULL, revision integer NOT NULL CHECK (revision>0), sha256 text NOT NULL,
    payload text NOT NULL, author_id text NOT NULL, predecessor_id bigint REFERENCES sci_artifact_revision,
    UNIQUE (lab_id,project_id,kind,artifact_id,revision)
);
CREATE TABLE sci_artifact_reference (
    owner_id bigint NOT NULL REFERENCES sci_artifact_revision,
    position integer NOT NULL, target_id bigint NOT NULL REFERENCES sci_artifact_revision,
    PRIMARY KEY (owner_id,position)
);
CREATE INDEX sci_artifact_dependents ON sci_artifact_reference(target_id);
CREATE TABLE sci_artifact_decision (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    specification_id bigint NOT NULL REFERENCES sci_artifact_revision,
    decision text NOT NULL CHECK (decision IN ('approved','rejected')), actor_id text NOT NULL,
    decided_at text NOT NULL, rationale text NOT NULL, limitations text NOT NULL
);
CREATE INDEX sci_artifact_receipts ON sci_artifact_decision(specification_id,id);
CREATE TABLE sci_artifact_reconciliation (
    owner_id bigint NOT NULL, position integer NOT NULL,
    successor_id bigint NOT NULL REFERENCES sci_artifact_revision, PRIMARY KEY (owner_id,position),
    FOREIGN KEY (owner_id,position) REFERENCES sci_artifact_reference(owner_id,position)
);

CREATE TABLE runtime_records (
    lab_id text NOT NULL, project_id text NOT NULL, work_order_id text NOT NULL,
    version bigint NOT NULL CHECK (version>0), key text NOT NULL, body text NOT NULL, sha256 text NOT NULL,
    PRIMARY KEY (lab_id,project_id,work_order_id,version), UNIQUE (lab_id,project_id,work_order_id,key)
);

DO $$
DECLARE
    name text;
BEGIN
    FOREACH name IN ARRAY ARRAY['catalog_revisions','catalog_approvals','sci_artifact_revision',
                                'sci_artifact_reference','sci_artifact_decision',
                                'sci_artifact_reconciliation','runtime_records'] LOOP
        EXECUTE format('CREATE TRIGGER immutable_records BEFORE UPDATE OR DELETE ON %I
            FOR EACH ROW EXECUTE FUNCTION evolve_immutable()', name);
    END LOOP;
END
$$;
