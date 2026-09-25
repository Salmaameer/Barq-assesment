# Security and production-readiness review

Record at least 8 concrete risks or improvements relevant to your final solution.
This is a review requirement, not the number of hidden faults.

- Risk and evidence: plaintext password exposed in "config/app.env"
- Impact:anyone with read access to the repository (or its git history) could
  read a real-looking PostgreSQL credential.
- Implemented fix / commit: removed the hardcoded DATABASE_URL/REDIS_URL from
  config/app.env; both are now built in docker-compose.yml from
  ${POSTGRES_USER}/${POSTGRES_PASSWORD}/${POSTGRES_DB}, sourced from a
  git-ignored .env file.
  <59c700e>
- Production follow-up: use a secrets manager like AWS Secrets Manager
- How to verify:`grep -n "DATABASE_URL\|REDIS_URL" config/app.env` now shows nothing;
  `git check-ignore .env` confirms the real value is never committed going
  forward.
######
- Risk and evidence: server_tokens off; in nginx.confg
- Impact: without this directive, nginx includes its exact version number in
  the `Server:` response header and on default error pages. This is a minor
  reconnaissance aid to an attacker: it narrows down which known
  vulnerabilities to try against this specific nginx version, for no
  functional benefit to the service.
- Implemented fix / commit: added `server_tokens off;` inside the `http {}`
  block of nginx.conf.
  <4bb4924>
- Production follow-up:none.
- How to verify:  `curl -i http://127.0.0.1:8080/` and check the `Server:`
  header shows no version number
######
- Risk and evidence: `USER root` in the dockerfile
- Impact: the container ran the Flask process as root despite the Dockerfile
  already creating a dedicated non-root user (`app`, uid 10001).
- Implemented fix / commit: changed to `USER app` in the Dockerfile -> <8fffa33>
- Production follow-up: add a CI check that fails the build if any Dockerfile
  in the repo contains `USER root`.
- How to verify: `docker exec app-01 whoami` and `docker exec app-01 id`
  both show `app` / `uid=10001(app)`


###
- Risk and evidence: No dependency check for the services. nginx waits for app-01 and app-02 to be healthy, 
  and the apps wait for PostgreSQL and Redis to be healthy. 
- Impact: A dependency could become unavailable after startup, 
  causing application errors or failed requests. 
  The application needs to handle these failures properly rather than relying only on startup checks.
- Implemented fix / commit: Added Docker healthchecks for PostgreSQL, Redis, and both application instances, and used depends_on with condition:        service_healthy so services start only after their dependencies are healthy.
<93dab38>
- Production follow-up: 
- How to verify: docker compose ps -> healthy status shown for each container.
####

- Risk and evidence: Services could remain down after an unexpected container
  crash or Docker restart if no restart policy was configured.
- Impact: A temporary failure could cause unnecessary downtime and require manual intervention to bring the service back up.
- Implemented fix / commit: Added `restart: unless-stopped` to the services 
  so Docker automatically restarts them after unexpected failures or host/Docker restarts.
- Production follow-up: 
- How to verify:docker inspect --format='{{.HostConfig.RestartPolicy.Name}}' app-01

######
- Risk and evidence: docker-compose.yml originally published PostgreSQL
  (host 15432) and Redis (host 16379) directly to the host.
- Impact: anything able to reach the host machine's network could connect
  directly to the database or cache.
- Implemented fix / commit: removed the `ports:` entries from both the
  postgres and redis services. They remain reachable only from containers on
  the internal `backend` network. 
- Production follow-up: in a real deployment, also restrict which hosts can
  reach the Docker host's exposed port at all (security group / firewall
  rules)
- How to verify: host port mapping only for `nginx` in docker-compose.yml
######
- Risk and evidence: docker-compose.yml originally placed the `nginx` service
  on both the `frontend` and `backend` networks, meaning nginx could resolve
  and directly connect to postgres/redis even though nothing in the current
  app code makes it do so.
- Impact: Even if nginx doesn't do this now, a misconfiguration could 
  give it access to the database/cache.
- Implemented fix / commit: removed `backend` from nginx's `networks:` list,
  leaving it on `frontend` only (where it can still reach app-01/app-02, its
  only actual dependency). See troubleshooting.md Entry 8.
- Production follow-up: 
- How to verify: `docker exec nginx getent hosts postgres redis` returns
  nothing .
#####
- Risk and evidence: A single failed application backend could cause client requests to fail even though another healthy backend is available.
- Impact: One backend failure could unnecessarily cause application downtime.
- Implemented fix / commit: enabled proxy_next_upstream with bounded retries.
- Production follow-up: Monitor upstream failures and tune timeout/retry values based on real traffic.
- How to verify: Stop one app, send requests through nginx, and confirm the other app continues serving them successfully.


Cover secrets, ports, container user, image selection, networks, persistence/backup,
logging/monitoring and availability. Separate completed work from planned improvements.