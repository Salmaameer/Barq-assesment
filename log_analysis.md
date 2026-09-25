# Log analysis


Use all three supplied logs. Answer every question with commands/scripts and actual output.
## Commands / scripts

All analysis was done with a single reusable loader (Python 3, stdlib only — `json`,
`collections`), since the access and application logs are JSON-lines and the error log
is nginx's plain-text error format. Originals were never modified (verified: `sha256sum`
of the uploaded files was recorded before this analysis began).

```python
import json

def load_json_lines(path):
    """Return (list of parsed dicts, list of 1-based line numbers that failed to parse)."""
    good, bad_lines = [], []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            try:
                good.append(json.loads(s))
            except Exception:
                bad_lines.append(i)
    return good, bad_lines

acc, acc_bad = load_json_lines('access.log')
app, app_bad = load_json_lines('application.log')
```

error.log lines were parsed with a small regex against nginx's standard error format,
pulling out `request_id` and the upstream IP:

```bash
grep -c 'Connection refused' error.log
grep -c 'timed out' error.log
grep -oE 'upstream: "http://[0-9.]+:' error.log | sort | uniq -c
```


1. What UTC interval is covered? How many valid, malformed and duplicate lines are in each file?

    - All three logs cover **2026-08-20T11:00:00.015Z to 2026-08-20T11:29:57.578Z** (UTC),~30 minutes. error.log ends with `11:30:00 [notice] log collector rotated stream`
    - | File | Raw lines | Malformed | Valid lines | duplicate lines |
    |---|---|---|---|---|
    | access.log | 726 | 1 (line 311) | 725 | 10 lines (5 pairs) |
    | application.log | 730 | 1 (line 401) | 729 | 4 lines (2 pairs) |
    | error.log | 68 | 0 (all lines matched the expected format) | 68 | 0 |
    - script:
        ```python
        good, bad = load_json_lines('access.log')       
        good, bad = load_json_lines('application.log')  
        ```
2. How many distinct client requests occurred? How did you deduplicate and avoid counting retries twice?
    - 720 distinct client requests using access.log.
        Script:
        ```python
        acc_ids = set(d['request_id'] for d in acc)
        len(acc_ids)
        ```
    -  for access.log file ->  README.md states a Comma-separated upstream
    values describe attempts for one client request. 19 access.log lines have a
    comma-separated `upstream` ("172.23.0.12:8080, 172.23.0.11:8080") — these are
    oen client request, retried once by nginx, not two. They are already counted
    once in the 720, since each retry produces a single access.log line with one
    `request_id`, not two lines.
    - application.log : an app instance logs a separate `dependency_error` event
    *and* a separate `http_request` outcome event for the same `request_id` when a
    dependency check fails. This is not a duplicate — it's two distinct facts about the
    same request (cause, then outcome) — and both are used, not discarded:

    ```python
    app_by_id = {}
    for d in app:
        if d['event'] == 'http_request':
            app_by_id.setdefault(d['request_id'], []).append(d['instance_id'])
    ```
3. What are the final client status counts and error rate? State your denominator.
    - | Status | Count |
        |---|---|
        | 200 | 620 |
        | 404 | 10 |
        | 502 | 40 |
        | 503 | 47 |
        | 504 | 8 |
       

       script: 
    from collections import Counter
    status_counts = Counter(d['status'] for d in acc)
    - Error rate: 105 / 725 = 14.4%, counting 502 + 503 + 504 + 404 as errors.
    - Denominator: 725** — every valid access.log line,
        before removing the 5 exact-duplicate pairs. Duplicates are counted here because
        each duplicate line represents a real response nginx actually sent to the client at that moment

4. Which paths, time windows and backends account for the failures?
| UTC start–end |Status | Count | Backend(s) | Paths |
|---|---|---|---|---|
| 11:05:02–11:09:57 | 502 | 40 | app-02 only (`172.23.0.12`) | `/health /ready /records /counter /instance /` (round-robin targets) |
| 11:12:09–11:21:45 | 503 | 47 | both app-01 and app-02 | `/ready`, `/counter` (redis); `/ready`, `/records` (postgres) |
| 11:25:14–11:26:47 | 504 | 8 | both app-01 and app-02, alternating | `/records` only |


5. What are the median and p95 client latencies? State the percentile method and units.
Percentile method: linear interpolation on sorted `request_time` (seconds, per
README: *"request_time is seconds"*), the client-facing round-trip time recorded by
nginx.

```python
def pctl(data, p):
    data = sorted(data)
    k = (len(data)-1) * (p/100)
    f, c = int(k), min(int(k)+1, len(data)-1)
    return data[f] if f == c else data[f] + (data[c]-data[f])*(k-f)
```

| Scope | n | Median | p95 |
|---|---|---|---|
| All requests (incl. errors) | 725 | 0.054 s | 2.001 s |
| Status 200 only | 620 | 0.055 s | 0.093 s |

6. Which requests retried upstream? How many succeeded after retrying?
    - 19 requests retried, 19 of 19 succeeded (100%) , all with
`upstream_status: "502, 200"` (first attempt to `app-02` refused, second attempt to
`app-01` succeeded).
    - script 
    ```python
      retry = [d for d in acc if ',' in d['upstream']]
      len(retry)                                    
      Counter(d['status'] for d in retry) 
    ```
              
7. Build an incident timeline using evidence from access, error AND application logs.


| Time (UTC) | Source | Event |
|---|---|---|
| 11:00:00 | access/application | Normal traffic begins, round-robin across app-01/app-02, ~55ms responses |
| 11:05:02 | error.log | First `Connection refused` connecting to `172.23.0.12:8080` (app-02) |
| 11:05:02–11:09:57 | error/access | 59 total connection-refused attempts to app-02; 19 client requests retried successfully to app-01 (200); 40 client requests returned 502 with no retry; app-01 continues serving normally throughout |
| 11:09:57 | error.log | Last connection-refused entry — app-02 becomes reachable again (implied; not explicitly logged as a recovery event) |
| ~11:10:00–11:12:09 | access | Normal traffic resumes on both backends |
| 11:12:09 | application.log | First `dependency_error` (`redis`, `TimeoutError`) on app-02, immediately followed by an `http_request` 503 for the same request_id on `/ready` |
| 11:12:09–11:15:52 | application/access | 31 redis `TimeoutError` events across both app-01 and app-02, affecting `/ready` and `/counter`; each produces a client-facing 503 |
| 11:20:07 | application.log | First `dependency_error` (`postgres`, `TimeoutError`) |
| 11:20:07–11:21:45 | application/access | 16 postgres `TimeoutError` events across both instances, affecting `/ready` and `/records`; each produces a client-facing 503 |
| ~11:21:45–11:25:14 | access | Normal traffic resumes |
| 11:25:14 | error.log | First `upstream timed out (110)` reading response header from `172.23.0.12:8080` on `/records` |
| 11:25:14–11:26:47 | error/access/application | 8 timeouts alternating between app-01 and app-02, all on `/records`; nginx returns 504 to the client ~2.0s in, while the app itself actually completes the same request ~0.7s later with a 200 (see Q8) — the client-visible failure and the eventual backend success are two different outcomes for the same request |
| 11:29:57 | access/application | Last recorded request of the window, status 200 |
| 11:30:00 | error.log | `log collector rotated stream` — end of capture |

8. Show one correlated failed request and one successful request. Include IDs and timestamps.
**Failed** (`request_id: lab-000292`):
```
access.log:      {"timestamp":"2026-08-20T11:12:09.525Z","request_id":"lab-000292",
                   "method":"GET","path":"/ready","status":503,
                   "upstream":"172.23.0.12:8080","upstream_status":"503",
                   "request_time":2.025}
application.log:  {"timestamp":"2026-08-20T11:12:09.524Z","level":"ERROR",
                   "event":"dependency_error","request_id":"lab-000292",
                   "instance_id":"app-02","dependency":"redis","error_type":"TimeoutError"}
application.log:  {"timestamp":"2026-08-20T11:12:09.525Z","level":"WARN",
                   "event":"http_request","request_id":"lab-000292",
                   "instance_id":"app-02","path":"/ready","status":503,
                   "duration_ms":2025.0}
```
**Successful** (`request_id: lab-000004`):
```
access.log:      {"timestamp":"2026-08-20T11:00:07.566Z","request_id":"lab-000004",
                   "method":"GET","path":"/ready","status":200,
                   "upstream":"172.23.0.12:8080","upstream_status":"200",
                   "request_time":0.066}
application.log:  {"timestamp":"2026-08-20T11:00:07.566Z","level":"INFO",
                   "event":"http_request","request_id":"lab-000004",
                   "instance_id":"app-02","path":"/ready","status":200,
                   "duration_ms":66.0}
```

9. Which errors appear to be proxy/connectivity issues versus dependency/application issues? What proves it?

Two categories, distinguished by whether the request_id ever reaches application.log:

| Status | Ever appears in application.log? | Category | Why |
|---|---|---|---|
| 502 | **Never** (checked all 40) | Proxy/connectivity | nginx couldn't even open a TCP connection (`Connection refused`, error.log). The request never reached any Flask process — there is nothing for the app to log. `request_time` for these is ~0.003s: near-instant, consistent with an immediate OS-level connection refusal, not a timeout. |
| 504 | **Always** (checked all 8) | Mixed: proxy-level symptom, application-level root cause | The app *did* receive these requests and *did* eventually finish them — application.log shows a 200 with `duration_ms: 2700` for every one — but nginx's own timeout (`request_time: 2.001s` exactly, matching a fixed proxy read-timeout) fired first and returned 504 to the client ~0.7s *before* the app finished. So the proxy layer is what the client saw, but the root cause is the backend being too slow, not nginx itself. |
| 503 | **Always** | Application/dependency | The app itself detected a failing dependency (`dependency_error` event naming `redis` or `postgres` and `TimeoutError`) and deliberately returned 503, per its own contract (`APPLICATION.md`: "Dependency failures return 503"). nginx passed this through unchanged (`upstream_status` and `status` are identical: `503` both times) — nginx did nothing wrong here. |


10. What do the logs not prove? What would you check next in a running environment?
**What they don't prove:**
- app-02 was unreachable for 5 minutes (W1) — no process/container lifecycle
  events are in these application-level logs, only the symptom (connection refused)
  from nginx's side.
- redis and postgres timed out (W2) — no redis/postgres server-side logs are
  included, only the app's client-side view (a timeout waiting for a response).
- Whether W1, W2 and W3 share a single root cause (e.g. host resource exhaustion
  affecting everything in sequence) or are three unrelated incidents — the logs show
  *when* things failed, not *why*, and there's no CPU/memory/host metric data here.

**What to check in a running environment:**
- `docker stats` / host metrics during a reproduction, to see if CPU, memory or disk
  I/O correlates with any of the three windows.
- redis and postgres's own logs (not present here) for the same time range.
- Whether app-02's container had actually crashed/restarted during W1.


## Commands / scripts
## Results
## Timeline and correlated examples
## Conclusions and limits
