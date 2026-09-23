# Technical decisions

Record at least 5 decisions. Include assumptions and limits.

## Decision
- Choice:
- Why:
- Alternative:
- Trade-off:
- Evidence / commit:
- Production improvement:

Cover your base image, health checks, networks, timeouts/retries, restart/resource settings,
storage and any other meaningful choices.

## Decision
- Choice: DATABASE_URL and REDIS_URL are not hardcoded anywhere. They are
  built inside docker-compose.yml from a single set of variables
  (${POSTGRES_USER}, ${POSTGRES_PASSWORD}, ${POSTGRES_DB}) sourced from
  .env, using postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
  and redis://redis:6379/0. The same variables also set the postgres
  service's own POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB. The :? syntax
  makes Compose refuse to start if a variable is missing from .env.
- Why: config/app.env originally hardcoded these URLs as literal strings,
  typed independently from postgres's own credentials. Its password  did not match postgres's actual POSTGRES_PASSWORD , and its
  ports (5433, 6380) did not match what postgres/redis actually listen on
  (5432, 6379), so the app could never authenticate or connect. Deriving
  both from one source makes that kind of drift structurally impossible,
  since there is only one place the password is ever typed.

- Alternative: (1) Leave the URLs in config/app.env and just correct the
  literal values - rejected, since it fixes the symptom but leaves two
  independently-editable copies of the same secret, which is how the bug
  happened, and leaves a plaintext password in a file that gets committed to
  git. (2) Put the full URLs as literal values directly in .env instead of
  composing them from smaller variables - rejected, since it still requires
  typing the password twice (once for POSTGRES_PASSWORD, once inside the URL
  string), reintroducing the same drift risk. 

- Trade-off: the password is still visible in plaintext to anything with
  access to `docker compose config` output. Compose's `:?` check only fires when a compose command actually runs, not at commit or review time, so a missing .env is only caught late.
  .env must be relied on to never be committed; enforced via .gitignore.
- Evidence / commit: 59c700e
- Production improvement: use a secrets manager or Kubernetes Secrets, or AWS  Secrets Manager/HashiCorp Vault instead of environment variables


## Decision
- Choice: app-01/app-02 use `depends_on: condition: service_healthy` for
  postgres and redis, instead of the Compose default (service_started).
  They stay on both `frontend` (nginx) and `backend` (real postgres/redis).
- Why: "started" only means the process began, not that Postgres/Redis can
  accept connections yet. Without health-gating, the apps could start and
  fail their first request purely due to startup timing, not app bugs.
- Alternative: default depends_on (started) - doesn't wait for readiness.
  App-side retry logic alone - hides a real ordering issue instead of
  declaring it. A wait-for-it wrapper script - redundant, since Compose
  already has the healthchecks needed.
- Trade-off: slower cold start, since apps wait through postgres's and
  redis's full healthcheck intervals/retries before starting at all.
- Evidence / commit: 375b28e 
- Production improvement: use orchestrator-native readiness/liveness probes
  (e.g. Kubernetes).

  ## Decision
- Choice: upstream servers use `max_fails=1 fail_timeout=5s`  and `proxy_next_upstream error timeout http_502 http_503 http_504`
  with `proxy_next_upstream_tries 2` (bounded failover), replacing the
  starter `max_fails=0` / `proxy_next_upstream off`.
- Why: the starter config sends every request to whichever backend is next
  in round-robin regardless of health, and never retries a failed request on
  the other backend , which is not how a load balancer should behave, and
  directly answers "which single points of failure remain, how would you
  fix them in production.
- Alternative: keep max_fails=0/proxy_next_upstream off (starter config)
  - rejected on reconsideration; it makes failures visible to the client
    directly, which is simpler to demonstrate, but is not a realistic or
    resilient load-balancer configuration .
- Trade-off: none.
- Evidence / commit: 4bb4924
- Production improvement: this is the production-appropriate setting.

