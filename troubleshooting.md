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
  show `GET /healthz` returning 404 every ~5s 

- Hypothesis: (a) healthcheck path /healthz does not exist; (b) APP_HOST=127.0.0.1
  makes the app unreachable from NGINX; (c) app-02 has INSTANCE_ID "app-01".
- Command or test: docker compose -p barq-assessment logs --no-color


- Actual output: app-02    | 127.0.0.1 - - [20/Sep/2026 18:09:58] "GET /healthz HTTP/1.1" 404 -
app-02    | {"timestamp": "2026-09-20T18:10:03.641+00:00", "level": "WARN", "service": "barq-api", "event": "http_request", "instance_id": "app-01", "request_id": "554d8fcabae44ad8884f592ab4ba6394", "method": "GET", "path": "/healthz", "status": 404, "duration_ms": 0.578}

- Failed attempt and what changed your thinking: 
- Root cause:  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"] 
- Fix: correct the url to "http://127.0.0.1:8080/health" matched the document endpoint.
- Retest evidence: docker inspect --format '{{.State.Health.Status}}' app-01 app-02 → healthy
- Related commit: <pending>
- Remaining uncertainty: DB/Redis connectivity not yet tested; nginx.conf not yet reviewed.




Do not fabricate a failed attempt just to fill the template. Record actual attempts.
