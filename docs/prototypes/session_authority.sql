-- Research protocol prototype, not production schema or a complete SessionBook.
-- Time is synthetic seconds. Production must obtain authority time internally,
-- after locks for mutations. No JWT verification, token encryption, revocation
-- outbox, restore fence, migration, permissions, or failover is implemented here.
CREATE TABLE owners (subject text PRIMARY KEY, generation bigint NOT NULL);
CREATE TABLE sessions (
    device text PRIMARY KEY,
    subject text NOT NULL REFERENCES owners,
    generation bigint NOT NULL,
    created bigint NOT NULL DEFAULT 0,
    seen bigint NOT NULL DEFAULT 0,
    ended boolean NOT NULL DEFAULT false,
    refresh_generation integer NOT NULL DEFAULT 0,
    lease text,
    claimed_at bigint,
    settled_lease text,
    CHECK ((lease IS NULL) = (claimed_at IS NULL))
);

CREATE FUNCTION allowed(d text, t bigint) RETURNS boolean LANGUAGE sql AS $$
    SELECT EXISTS (
        SELECT 1 FROM sessions s JOIN owners o USING (subject)
        WHERE s.device=d AND NOT s.ended AND s.generation=o.generation
          AND t < s.seen+604800 AND t < s.created+2592000
    );
$$;

CREATE FUNCTION activity(d text, t bigint, delta bigint) RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE r sessions%ROWTYPE;
BEGIN
    PERFORM 1 FROM owners WHERE subject=(SELECT subject FROM sessions WHERE device=d) FOR SHARE;
    SELECT * INTO r FROM sessions WHERE device=d FOR UPDATE;
    IF NOT FOUND OR NOT allowed(d,t) OR r.lease IS NOT NULL THEN RETURN false; END IF;
    IF t-r.seen >= delta AND t > r.seen THEN
        UPDATE sessions SET seen=t WHERE device=d;
    END IF;
    RETURN true;
END;
$$;

CREATE FUNCTION end_device(d text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM owners WHERE subject=(SELECT subject FROM sessions WHERE device=d) FOR SHARE;
    UPDATE sessions SET ended=true WHERE device=d;
END;
$$;

CREATE FUNCTION end_all(who text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM owners WHERE subject=who FOR UPDATE;
    UPDATE owners SET generation=generation+1 WHERE subject=who;
    UPDATE sessions SET ended=true WHERE subject=who;
END;
$$;

CREATE FUNCTION begin_device(d text, who text, t bigint) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM owners WHERE subject=who FOR UPDATE;
    INSERT INTO sessions(device,subject,generation,created,seen)
        SELECT d,who,generation,t,t FROM owners WHERE subject=who;
END;
$$;

CREATE FUNCTION claim(d text, nonce text, expected_generation integer, t bigint) RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE r sessions%ROWTYPE;
BEGIN
    PERFORM 1 FROM owners WHERE subject=(SELECT subject FROM sessions WHERE device=d) FOR SHARE;
    SELECT * INTO r FROM sessions WHERE device=d FOR UPDATE;
    IF NOT FOUND OR NOT allowed(d,t) THEN RETURN false; END IF;
    IF r.lease IS NOT NULL THEN
        IF t-r.claimed_at >= 10 THEN UPDATE sessions SET ended=true WHERE device=d; END IF;
        RETURN false;
    END IF;
    IF r.refresh_generation != expected_generation THEN RETURN false; END IF;
    UPDATE sessions SET lease=nonce, claimed_at=t WHERE device=d;
    RETURN true;
END;
$$;

CREATE FUNCTION settle(d text, nonce text, expected_generation integer, t bigint) RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE r sessions%ROWTYPE;
BEGIN
    PERFORM 1 FROM owners WHERE subject=(SELECT subject FROM sessions WHERE device=d) FOR SHARE;
    SELECT * INTO r FROM sessions WHERE device=d FOR UPDATE;
    IF NOT FOUND OR NOT allowed(d,t) THEN RETURN false; END IF;
    IF r.settled_lease=nonce AND r.refresh_generation=expected_generation+1 THEN RETURN true; END IF;
    IF r.lease IS DISTINCT FROM nonce OR r.refresh_generation != expected_generation
       OR t-r.claimed_at >= 10 THEN RETURN false; END IF;
    UPDATE sessions SET refresh_generation=refresh_generation+1, lease=NULL,
        claimed_at=NULL, settled_lease=nonce WHERE device=d;
    RETURN true;
END;
$$;
