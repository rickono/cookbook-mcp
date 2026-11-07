-- Reader session authority. Provision explicitly; runtime never migrates schema.
CREATE TABLE reader_session_owners (
    epoch text NOT NULL,
    subject text NOT NULL,
    generation bigint NOT NULL DEFAULT 1,
    PRIMARY KEY (epoch, subject)
);

CREATE TABLE reader_device_sessions (
    epoch text NOT NULL,
    key text NOT NULL,
    subject text NOT NULL,
    generation bigint NOT NULL,
    created double precision NOT NULL,
    seen double precision NOT NULL,
    csrf text NOT NULL,
    access bytea NOT NULL,
    refresh bytea,
    refresh_id text,
    credential_version bigint NOT NULL DEFAULT 1,
    ended boolean NOT NULL DEFAULT false,
    lease text,
    renewing double precision,
    admission double precision,
    settled text,
    PRIMARY KEY (epoch, key),
    FOREIGN KEY (epoch, subject) REFERENCES reader_session_owners,
    CHECK ((lease IS NULL) = (renewing IS NULL)),
    CHECK ((refresh IS NULL) = (refresh_id IS NULL))
);
CREATE INDEX reader_session_owner ON reader_device_sessions (epoch, subject);

-- One exchange permission for every reference to a token, across devices.
-- A settled rotating exchange permanently fences the consumed identity.
CREATE TABLE reader_session_exchanges (
    epoch text NOT NULL,
    subject text NOT NULL,
    refresh_id text NOT NULL,
    nonce text NOT NULL,
    started double precision NOT NULL,
    settled boolean NOT NULL DEFAULT false,
    failed boolean NOT NULL DEFAULT false,
    PRIMARY KEY (epoch, subject, refresh_id),
    FOREIGN KEY (epoch, subject) REFERENCES reader_session_owners
);

-- A retirement is permanent within this authority epoch. Sign-in cannot reuse it.
CREATE TABLE reader_session_retirements (
    epoch text NOT NULL,
    subject text NOT NULL,
    refresh_id text NOT NULL,
    token bytea NOT NULL,
    completed boolean NOT NULL DEFAULT false,
    claim text,
    retry_at double precision NOT NULL DEFAULT 0,
    PRIMARY KEY (epoch, subject, refresh_id),
    FOREIGN KEY (epoch, subject) REFERENCES reader_session_owners
);
