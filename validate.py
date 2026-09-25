#!/usr/bin/env python3
#!/usr/bin/env python3
"""
validate.py - checks the running environment against the assessment requirements.

Uses only the Python standard library (urllib, subprocess, json) so it runs
identically on a local machine and on a CI runner, with no pip install step.

Exit code 0  -> all checks passed
Exit code 1  -> at least one check failed
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

PROJECT = "barq-assessment"
PORT = os.environ.get("PUBLIC_PORT", "8080")
BASE_URL = f"http://127.0.0.1:{PORT}"
BOUNDED_WAIT_SECONDS = 60
POLL_INTERVAL = 2

results = []  


def record(name, passed, detail=""):
    results.append((name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


def http_get(path, timeout=3):
    """Return (status_code, body_text) or (None, error_text) on failure."""
    try:
        with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return None, str(e)


def http_post_json(path, payload, timeout=3):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return None, str(e)


def wait_until(check_fn, description, bound=BOUNDED_WAIT_SECONDS, interval=POLL_INTERVAL):
    """Retry check_fn() until it returns True or the bound elapses. Never loops forever."""
    deadline = time.time() + bound
    last_detail = ""
    while time.time() < deadline:
        ok, last_detail = check_fn()
        if ok:
            return True, last_detail
        time.sleep(interval)
    return False, f"timed out after {bound}s, last: {last_detail}"


def docker_ps():
    out = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip().splitlines()


def check_public_access():
    def _check():
        code, _ = http_get("/")
        return code == 200, f"status={code}"
    ok, detail = wait_until(_check, "public access")
    record("Public access on /", ok, detail)


def check_endpoint(path, expected_status=200):
    code, body = http_get(path)
    record(f"GET {path}", code == expected_status, f"status={code}")
    return code, body


def check_records_roundtrip():
    code, body = http_post_json("/records", {"title": "validation record"})
    record("POST /records", code == 201, f"status={code}")
    code, body = http_get("/records")
    ok = code == 200 and '"records"' in (body or "")
    record("GET /records", ok, f"status={code}")


def check_counter():
    code, body = http_get("/counter")
    record("GET /counter", code == 200, f"status={code}")


def check_readiness():
    def _check():
        code, _ = http_get("/ready")
        return code == 200, f"status={code}"
    ok, detail = wait_until(_check, "readiness (postgres + redis)")
    record("GET /ready (postgres + redis dependencies)", ok, detail)


def check_both_backends():
    """Hit /instance repeatedly and confirm both app-01 and app-02 respond."""
    seen = set()
    for _ in range(20):
        code, body = http_get("/instance")
        if code == 200 and body:
            try:
                seen.add(json.loads(body).get("instance_id"))
            except json.JSONDecodeError:
                pass
        time.sleep(0.1)
    ok = {"app-01", "app-02"} <= seen
    record("Both backends serve /instance", ok, f"saw={sorted(seen)}")


def check_only_nginx_published():
    lines = docker_ps()
    offenders = []
    for line in lines:
        name, ports = (line.split("\t") + [""])[:2]
        if name == "nginx":
            continue
        if "->" in ports:  # a published host mapping looks like 0.0.0.0:X->Y/tcp
            offenders.append(f"{name}: {ports}")
    record("Only nginx publishes a host port", not offenders, "; ".join(offenders) or "ok")


def check_network_isolation():
    """nginx must not be able to resolve postgres or redis (backend is internal
    and nginx is only on frontend)."""
    for target in ("postgres", "redis"):
        result = subprocess.run(
            ["docker", "exec", "nginx", "getent", "hosts", target],
            capture_output=True, text=True,
        )
        # getent exits non-zero and prints nothing when the name doesn't resolve
        isolated = result.returncode != 0 and not result.stdout.strip()
        record(f"nginx cannot resolve {target}", isolated, result.stdout.strip() or "not resolvable (expected)")


def main():
    print(f"\nValidating against {BASE_URL} (project={PROJECT})\n")

    check_public_access()
    check_endpoint("/health")
    check_readiness()
    check_endpoint("/instance")
    check_both_backends()
    check_records_roundtrip()
    check_counter()
    check_endpoint("/does-not-exist", expected_status=404)
    check_only_nginx_published()
    check_network_isolation()

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