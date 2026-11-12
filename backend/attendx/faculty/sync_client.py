"""HTTPS-only central client. Durable retry metadata; conflicts never delete local events."""

import secrets
from urllib.parse import urlparse

import httpx


class CentralClient:
    def __init__(self, url, *, ca_bundle=True, client=None):
        if urlparse(url).scheme != "https":
            raise ValueError("central synchronization requires verified HTTPS")
        self.url = url.rstrip("/")
        self.client = client or httpx.Client(base_url=self.url, verify=ca_bundle, timeout=30, follow_redirects=False)

    def provision(self, username, password, name, device_id=None):
        result = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
            headers={"X-Requested-With": "attendx"},
        )
        result.raise_for_status()
        user = result.json()
        if user["role"] != "faculty":
            self.client.cookies.clear()
            raise ValueError("this application permits faculty accounts only")
        try:
            response = self.client.post(
                "/api/v2/faculty/devices",
                json={"name": name, "device_id": device_id},
                headers={"X-CSRF-Token": user["csrf_token"]},
            )
            response.raise_for_status()
            return response.json()
        finally:
            self.client.post("/api/auth/logout", headers={"X-CSRF-Token": user["csrf_token"]})
            self.client.cookies.clear()

    def download(self, credential, runtime=None):
        response = self.client.get("/api/v2/sync/snapshot", headers={"Authorization": "Bearer " + credential})
        if runtime is not None and response.status_code in (401, 403):
            runtime.privacy_lock()
        response.raise_for_status()
        return response.json()

    def classroom_certificate(self, credential, csr_pem, address):
        response = self.client.post(
            "/api/v2/sync/classroom-certificate",
            headers={"Authorization": "Bearer " + credential},
            json={"csr_pem": csr_pem, "address": address},
        )
        response.raise_for_status()
        return response.json()

    def synchronize(self, runtime):
        config = runtime.store.kv_get("central")
        if config is None:
            raise ValueError("faculty device has not been centrally provisioned")
        headers = {"Authorization": "Bearer " + config["credential"]}
        now = runtime.now().replace(tzinfo=__import__("datetime").UTC).timestamp()
        result = {"acknowledged": 0, "pending": len(runtime.pending_events()), "error": ""}
        for event in runtime.store.pending(due_at=now):
            try:
                response = self.client.post("/api/v2/sync/events", json=event, headers=headers)
                response.raise_for_status()
                runtime.acknowledge(response.json())
                result["acknowledged"] += 1
            except (httpx.HTTPError, ValueError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                label = (
                    "conflict; faculty/admin reconciliation required"
                    if status == 409
                    else (
                        "device authorization expired or revoked"
                        if status in (401, 403)
                        else "central server unavailable"
                    )
                )
                if status in (401, 403):
                    runtime.privacy_lock()
                with runtime.store.transaction() as db:
                    attempts = (
                        db.execute("SELECT attempts FROM outbox WHERE id=?", (event["event_id"],)).fetchone()[0] + 1
                    )
                    delay = min(3600, 2 ** min(attempts, 11)) + secrets.randbelow(5)
                    db.execute(
                        "UPDATE outbox SET attempts=?,next_attempt=?,last_error=? WHERE id=?",
                        (attempts, now + delay, label, event["event_id"]),
                    )
                result["error"] = label
                break  # keep revision ordering; do not upload amendments ahead of their base
        result["pending"] = len(runtime.pending_events())
        return result
