CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- для gen_random_uuid()

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    display_name    VARCHAR(255) NOT NULL,
    role            VARCHAR(20)  NOT NULL DEFAULT 'USER' CHECK (role IN ('USER', 'ADMIN')),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE researches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_researches_owner_id ON researches(owner_id);

CREATE TABLE processing_jobs (
    id              UUID PRIMARY KEY,
    research_id     UUID NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
    requested_by    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', 'PARTIAL')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_processing_jobs_research_id ON processing_jobs(research_id);

CREATE TABLE scans (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    research_id             UUID NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
    job_id                  UUID NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
    original_filename       VARCHAR(500) NOT NULL,

    study_uid               VARCHAR(255),
    image_uid               VARCHAR(255),
    anatomical_region       VARCHAR(50),
    quality_class           SMALLINT,
    violation_type          VARCHAR(500),
    comment                 TEXT,

    processing_status       VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                                CHECK (processing_status IN
                                    ('PENDING', 'QUEUED', 'PROCESSING', 'SUCCESS', 'FAILED')),
    error_message           TEXT,
    time_of_processing       DOUBLE PRECISION,

    thumbnail_png_b64       TEXT,

    uploaded_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at            TIMESTAMPTZ
);

CREATE INDEX idx_scans_research_id ON scans(research_id);
CREATE INDEX idx_scans_job_id ON scans(job_id);
