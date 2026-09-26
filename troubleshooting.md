# Troubleshooting journal

Keep chronological entries. Copy this block for each meaningful investigation.

## Entry / date / time
- Symptom:
- Hypothesis:
- Command or test:
- Actual output:
- Failed attempt and what changed your thinking:
- Root cause:
- Fix:
- Retest evidence:
- Related commit:
- Remaining uncertainty:

## Entry 1 / 2026-09-20 / 18:11
- Symptom: After `up --build -d`, app containers never became healthy. app-02 logs
  show `GET /healthz` returning 404.

- Hypothesis: (a) healthcheck path /healthz does not exist; (b) APP_HOST=127.0.0.1
  makes the app unreachable from NGINX; (c) app-02 has INSTANCE_ID "app-01".
- Command or test: docker compose -p barq-assessment logs --no-color


- Actual output: app-02    | 127.0.0.1 - - [20/Sep/2026 18:09:58] "GET /healthz HTTP/1.1" 404 -
app-02    | {"timestamp": "2026-09-20T18:10:03.641+00:00", "level": "WARN", "service": "barq-api", "event": "http_request", "instance_id": "app-01", "request_id": "554d8fcabae44ad8884f592ab4ba6394", "method": "GET", "path": "/healthz", "status": 404, "duration_ms": 0.578}

- Failed attempt and what changed your thinking: 
- Root cause:  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"] 
- Fix: correct the url to "http://127.0.0.1:8080/health" matched the document endpoint.
- Retest evidence: docker inspect --format '{{.State.Health.Status}}' app-01 app-02 → healthy
- Related commit: 1926542
- Remaining uncertainty: DB/Redis connectivity not yet tested; nginx.conf not yet reviewed.

## Entry 2 / 2026-09-21 / 12:39am
- Symptom: After `docker compose -p barq-assessment up --build -d`, the app log
  reports `Running on http://127.0.0.1:8080`, so Flask listens only on the
  container's loopback interface. docker-compose.yml sets `APP_HOST: "127.0.0.1"`
  for both app services.

- Hypothesis: NGINX connects to app-01/app-02 from another container, so its
  traffic arrives on the app's frontend-network IP, not on loopback. Flask
  bound to 127.0.0.1 refuses those connections. Binding to 0.0.0.0 should fix
  this.
- Command or test:
      grep -n "APP_HOST" docker-compose.yml
        docker compose -p barq-assessment logs --no-color app-02 | grep -i "Running on"
   
- Actual output : 
      APP_HOST: "127.0.0.1"
      app-02  |  * Running on http://127.0.0.1:8080

- Failed attempt and what changed your thinking: none
- Root cause:  APP_HOST is 127.0.0.1 in docker-compose.yml, Flask therefore listens only on loopback. Other containers cannot open app-01:8080 / app-02:8080.
- Fix: Change APP_HOST to "0.0.0.0" in docker-compose.yml where it is set
  then recreate the apps.

- Retest evidence: app-02  |  * Running on all addresses (0.0.0.0)
app-02  |  * Running on http://127.0.0.1:8080
app-02  |  * Running on http://172.19.0.3:8080

docker exec nginx wget -qO- -T 3 http://app-01:8080/health

{"instance_id":"app-01","service":"barq-api","status":"alive","version":"2.0.0"}

- Related commit: #fix: b0855c1
- Remaining uncertainty: The NGINX -> app test only proves the app accepts the
  connection. It does not prove nginx.conf points at the right upstream name or
  port.

## Entry 3 / 2026-09-22 / 1:00 pm
- Symptom: app-02 logs and /instance both report instance_id "app-01", identical
  to app-01. Two backends cannot be told apart, so /instance and X-Instance-ID
  cannot prove NGINX is actually load-balancing across both.
- Hypothesis: INSTANCE_ID is set per-service in docker-compose.yml and was
  copy-pasted without changing the value for app-02.
- Command or test: grep -n "INSTANCE_ID" docker-compose.yml
- Actual output: 53:      INSTANCE_ID: "app-01"
59:      INSTANCE_ID: "app-01"
- Failed attempt and what changed your thinking: none
- Root cause: app-02's INSTANCE_ID was hardcoded to "app-01" in
  docker-compose.yml
- Fix: changed app-02's INSTANCE_ID to "app-02" in docker-compose.yml.
- Retest evidence: grep -n "INSTANCE_ID" docker-compose.yml
53:      INSTANCE_ID: "app-01"
59:      INSTANCE_ID: "app-02"
- Related commit: #fix: b0855c1
- Remaining uncertainty: none 

## Entry 4 / 2026-09-22 / 2:40pm
- Symptom: config/app.env hardcoded DATABASE_URL and REDIS_URL as literal
  strings. The password in DATABASE_URL (...8d) did not match postgres's own
  POSTGRES_PASSWORD (...8c), and the ports (5433, 6380) did not match the
  ports postgres/redis actually listen on (5432, 6379). See Entry 5 for the
  original discovery of this mismatch.

- Hypothesis: hardcoding the same secret independently in two places
  (config/app.env and the postgres service definition) is what let them
  drift apart in the first place. 

- Command or test: grep -n "DATABASE_URL\|REDIS_URL\|POSTGRES_PASSWORD"
  config/app.env docker-compose.yml
- Actual output: 
    config/app.env:1:DATABASE_URL=postgresql://barq_app:BarqLabOnly_7qN2vK8d@postgres:5433/barq_tasks
    config/app.env:2:REDIS_URL=redis://redis:6380/0
    docker-compose.yml:25:      POSTGRES_PASSWORD: BarqLabOnly_7qN2vK8c


- Failed attempt and what changed your thinking: none
- Root cause: DATABASE_URL/REDIS_URL were typed differentaly in config/app.env,
  disconnected from the actual POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB
  values defined on the postgres service, so nothing enforced agreement
  between them.
- Fix: removed the hardcoded URLs from config/app.env. DATABASE_URL and
  REDIS_URL are now built in docker-compose.yml as
  postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
  and redis://redis:6379/0, using the same .env-sourced variables that
  postgres itself uses, with :? guards so Compose fails fast if a variable
  is missing rather than starting with a broken credential.
- Retest evidence: Postgres credentials hidden and secured inside the .env, no access to it from the repo. consistency between all of the usages of the credentials, connection worked well.
- Related commit: 59c700e 
- Remaining uncertainty: config/app.env is still tracked in git with the
  old, wrong values as history; noted in security_review.md.

## Entry 5 / 2026-09-22 / 4:00 pm
- Symptom: task requires a created /records row to survive recreating the app
  and postgres containers, but postgres's data directory was configured with
  tmpfs, and the named volume was mounted at /var/lib/postgresql/backup
  instead of the actual Postgres data path.
- Hypothesis: any data written to Postgres lives only in the tmpfs (RAM) mount
  and is discarded on container recreation; the named volume is not actually
  backing the live data directory.
- Command or test: grep -n "tmpfs\|postgres-data" docker-compose.yml
- Actual output: < 37:    - postgres-data:/var/lib/postgresql/backup
39:    tmpfs: [/var/lib/postgresql/data]>
- Failed attempt and what changed your thinking: none
- Root cause: docker-compose.yml mounted the named volume at the wrong path
  (.../backup, which Postgres does not read as its data directory) and
  additionally mounted tmpfs over the real data directory
  (/var/lib/postgresql/data), so all writes lived only in memory.
- Fix: removed the tmpfs mount; postgres-data volume now mounts at
  /var/lib/postgresql/data.
  <!-- TODO -->
- Retest evidence: <pending. Paste: create a record via POST /records, then
  `docker compose -p barq-assessment up -d --force-recreate postgres app-01 app-02`
  (no --volumes), then GET /records showing the record still present.>
  grep -n "tmpfs\|postgres-data" docker-compose.yml
    37:      - postgres-data:/var/lib/postgresql/data
    89:  postgres-data:
- Related commit: 37c4a52
- Remaining uncertainty: not yet retested end-to-end; 

## Entry 6 / 2026-09-22 / 4:10 pm
- Symptom: task requires the Redis-backed /counter to be durable, but redis
  was started with --save "" --appendonly no, i.e. no persistence configured,
  and no volume was mounted for Redis at all.
- Hypothesis: a counter value would be lost on any redis container restart or
  recreation.
- Command or test: grep -n "command:" docker-compose.yml 
- Actual output: command: ["redis-server", "--save", "", "--appendonly", "no"]
- Failed attempt and what changed your thinking: none
- Root cause: Redis persistence was explicitly disabled in the startup command,
  and no volume existed to persist data even if it had been enabled.
- Fix: changed redis command to --appendonly yes --appendfsync everysec, and
  added a named redis-data volume mounted at /data.
- Retest evidence:
  `docker compose -p barq-assessment up -d --force-recreate redis` , counter  continued from the prior value
- Related commit: 37c4a52
- Remaining uncertainty: none.

## Entry 7 / 2026-09-22 / 4:15 pm
- Symptom: task requires "Publish only NGINX on host port 8080. Do not publish
  app, PostgreSQL or Redis ports," but docker-compose.yml published postgres
  on host 15432 and redis on host 16379.
- Hypothesis: these ports directly violate the requirement and are a security
  risk.
- Command or test: ports: attributes exists in the docker-compose.yml for postgres and redis
- Actual output:     
      - ports: ["127.0.0.1:15432:5432"]
      -     ports: ["127.0.0.1:16379:6379"]
- Failed attempt and what changed your thinking: none
- Root cause: docker-compose.yml explicitly published postgres and redis to
  127.0.0.1 on the host.
- Fix: removed the ports: entries from both the postgres and redis services.
  They remain reachable only on the internal backend network.
- Retest evidence: only ports: attribute for nginx
- Related commit: <37c4a52>
- Remaining uncertainty: none.

## Entry 8 / 2026-09-22 / 10:00 pm
- Symptom: task requires NGINX be blocked from directly reaching
  PostgreSQL/Redis, but docker-compose.yml put the nginx service on both the
  frontend and backend networks.
- Hypothesis: NGINX being on backend means it can resolve and connect to
  postgres/redis directly, defeating the network isolation the brief asks for,
  even though nothing in the app currently makes it do so.
- Command or test: docker exec nginx getent hosts postgres redis
  
- Actual output: <172.22.0.3        postgres  postgres>
- Failed attempt and what changed your thinking: none
- Root cause: nginx service's networks: list included backend unnecessarily;
  it only needs frontend to reach app-01/app-02, which are also on frontend.
- Fix: removed backend from nginx's networks: list, leaving it on frontend only.
- Retest evidence:  "docker exec nginx getent hosts postgres redis" -> return nothing, also i could reach app01&app02
  
- Related commit: <93dab38>
- Remaining uncertainty: none.

## Entry 9 / 2026-09-22 / 10:00 pm
- Symptom: nginx/nginx.conf lists "server app-01:8081" in the upstream block,
  but app-01 is configured with APP_PORT 8080, and the compose file maps the
  published host port to container port 81 while nginx.conf's server block
  says "listen 80".
- Hypothesis: requests routed to app-01 by nginx would fail to connect
  (wrong port), and/or the host-published port would not reach nginx's actual
  listener.
- Command or test: it just a modification that works after it.
- Actual output: 
- Failed attempt and what changed your thinking: none
- Root cause: two independent port mismatches in nginx configuration: (1) the
  upstream entry for app-01 used port 8081 instead of 8080; (2) nginx listens
  on 80 inside the container, but docker-compose.yml mapped the host port to
  container port 81.
- Fix: changed nginx.conf upstream entry to "server app-01:8080"; changed the
  nginx service's ports: mapping in docker-compose.yml to map the host port to
  container port 80, matching nginx's listen directive.
- Retest evidence:docker exec nginx nginx -t                                
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
- Related commit: <93dab38>
- Remaining uncertainty: none.

## Entry 10 / 2026-09-23 / 4:30pm
- Symptom: postgres log showed "password authentication failed for user
  barq_app"; app-01 logged a dependency_error on postgres and /ready
  returned 503 (confirmed via nginx access log: upstream_status 503,
  request_time 0.092).
- Hypothesis: POSTGRES_PASSWORD in .env had changed since postgres's named
  volume was first initialized. Postgres only applies POSTGRES_PASSWORD when
  initializing an empty data directory, and ignores it on every later start
  once data already exists - so a later .env change has no effect on an
  existing volume.
- Command or test: docker exec postgres env | grep POSTGRES_PASSWORD;
  grep POSTGRES_PASSWORD .env
- Actual output: both values were identical.
- Failed attempt and what changed your thinking: initially checked
  `docker exec postgres env | grep POSTGRES_PASSWORD` against .env and found
  them equal, which seemed to rule out a stale volume. This was a false
  negative: matching env vars only prove what Docker injected into the
  container's process environment, not what password Postgres actually
  stored for the role at first init. The env var is read once, at
  first startup on an empty volume, and never consulted again while
  the volume has existing data.
- Root cause: postgres volume was initialized under an earlier password value ,.env's POSTGRES_PASSWORD had  changed but postgres never re-read it.
- Fix: removed the old volume and let postgres reinitialize from current
  .env values:
    docker compose -p barq-assessment down
    docker volume rm barq-assessment_postgres-data
    docker compose -p barq-assessment up -d
- Retest evidence: after recreation, GET /ready returned 200 and no further
  "password authentication failed" entries appeared in
  `docker compose -p barq-assessment logs postgres`.
- Related commit: none 
- Remaining uncertainty: none

## Entry 11 / 2026-09-23 / 7:00pm
- Symptom: After change the `USER root` to `USER app` in the Dockerfile,  still reading the apps as the root.
- Hypothesis: Running app is still using the image where the default user is USER root.
- Command or test: `docker exec app-01 whoami` , docker exec app-01 id
- Actual output: 
    root 
    ,uid=0(root) gid=0(root) groups=0(root)
- Failed attempt and what changed your thinking:none
- Root cause: image still using the chached Dockerfile.
- Fix: rebuild the image again from the corrected Dockerfile
- Retest evidence:  docker exec app-02 whoami -> app
    docker exec app-01 id  -> uid=10001(app) gid=10001(app) groups=10001(app)
- Related commit:<8fffa33>
- Remaining uncertainty:none.

## Entry 12 / 2026-09-26 / 1:30pm
- Symptom: CI's "nginx config" step failed with `host not found in upstream
  "app-01:8080"`, even though the same nginx.conf had already passed
  `nginx -t` locally multiple times.
- Hypothesis: the CI step ran `nginx -t` in a standalone container with no
  other services, so app-01/app-02 could not resolve.
- Command or test: reviewed the failing CI step; confirmed nginx resolves
  static upstream server hostnames at config-load time.
- Root cause: the CI syntax-check step tested nginx.conf in isolation,
  before any other container existed on its network.
- Fix: moved the nginx config check to run via `docker exec nginx nginx -t`
  after `docker compose up -d`, once app-01/app-02 exist on the network.
- Retest evidence: pushed and nginx check is passed.
- Related commit: <9232588>
- Remaining uncertainty: none - this was a test-methodology bug in ci.yml,
  not in nginx.conf itself.

