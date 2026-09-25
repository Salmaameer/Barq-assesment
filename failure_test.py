#!/usr/bin/env python3
"""
test stops one app backend, measures traffic and errors during the
outage, restores it, and proves it serves requests again.

Because nginx is configured with passive health detection (max_fails/fail_timeout)
and bounded failover (proxy_next_upstream), most CLIENT-facing requests will still
succeed during the outage - that is the correct, intended behavior, not a bug.
So this script proves the failure actually happened two ways:
  1. Client-facing availability stays high (the resilience working as designed)
  2. nginx's own access log shows failed upstream attempts during the window
     (the failure being real, not silently absent)

"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

PROJECT = "barq-assessment"
PORT = "8080"
BASE_URL = f"http://127.0.0.1:{PORT}"
TARGET = "app-02"          # chosen backend to kill for this test
OUTAGE_WINDOW_SECONDS = 15
REQUESTS_DURING_OUTAGE = 30
RECOVERY_BOUND_SECONDS = 20
POLL_INTERVAL = 1

results = []


def record(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def http_get(path, timeout=3):
    try:
        with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception:
        return None, None


def instance_ids(n=20, delay=0.1):
    seen = set()
    for _ in range(n):
        code, body = http_get("/instance")
        if code == 200 and body:
            try:
                seen.add(json.loads(body).get("instance_id"))
            except json.JSONDecodeError:
                pass
        time.sleep(delay)
    return seen


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def nginx_logs_since(seconds):
    out = subprocess.run(
        ["docker", "compose", "-p", PROJECT, "logs", "nginx", "--since", f"{seconds}s", "--no-color"],
        capture_output=True, text=True,
    )
    return out.stdout


def main():
    # 1. Baseline: confirm both backends are actually serving before we break anything.
    baseline = instance_ids()
    record("Baseline: both backends serving", {"app-01", "app-02"} <= baseline, f"saw={sorted(baseline)}")
    if not ({"app-01", "app-02"} <= baseline):
        print("Aborting: cannot run a meaningful failure test without both backends healthy first.")
        sys.exit(1)

    stopped = False
    try:
        # 2. Stop one backend.
        stop = docker("stop", TARGET)
        record(f"Stopped {TARGET}", stop.returncode == 0, stop.stderr.strip())
        stopped = True

        # 3. Measure client-facing traffic during the outage window.
        success, failure = 0, 0
        start = time.time()
        while time.time() - start < OUTAGE_WINDOW_SECONDS:
            code, _ = http_get("/instance")
            if code == 200:
                success += 1
            else:
                failure += 1
            time.sleep(OUTAGE_WINDOW_SECONDS / REQUESTS_DURING_OUTAGE)

        total = success + failure
        availability = success / total if total else 0
        record(
            "Client-facing availability during outage",
            availability >= 0.8,  # generous bound: a few requests may land mid-failover
            f"{success}/{total} succeeded ({availability:.0%})",
        )

        # 4. Confirm the outage was real by checking nginx's own log, not just
        #    the client-facing view, since failover can hide it from the client.
        log_text = nginx_logs_since(OUTAGE_WINDOW_SECONDS + 5)
        saw_failure_in_log = '"upstream_status":"502' in log_text or '"upstream_status":"503' in log_text \
            or f'{TARGET}' in log_text and ("502" in log_text or "refused" in log_text.lower())
        record(
            "nginx log shows the outage actually happened",
            saw_failure_in_log,
            "found failed upstream attempt(s) in nginx log" if saw_failure_in_log
            else "no failed upstream attempts found - outage may not have been exercised",
        )

        # 5. Restore.
        start_result = docker("start", TARGET)
        record(f"Restarted {TARGET}", start_result.returncode == 0, start_result.stderr.strip())
        stopped = False

        # 6. Prove recovery: both backends must serve again within a bounded wait.
        deadline = time.time() + RECOVERY_BOUND_SECONDS
        recovered = False
        seen_during_recovery = set()
        while time.time() < deadline:
            seen_during_recovery |= instance_ids(n=5, delay=0.1)
            if {"app-01", "app-02"} <= seen_during_recovery:
                recovered = True
                break
            time.sleep(POLL_INTERVAL)
        record(
            "Recovered backend serves requests again",
            recovered,
            f"saw={sorted(seen_during_recovery)} within {RECOVERY_BOUND_SECONDS}s bound",
        )

    finally:
        
        if stopped:
            print(f"Cleanup: ensuring {TARGET} is restarted...")
            docker("start", TARGET)

    print("\n--- Summary ---")
    failed = [name for name, ok, _ in results if not ok]
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}: {name}")

    if failed:
        print(f"\n{len(failed)} check(s) FAILED.")
        sys.exit(1)

    print("\nAll checks PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
