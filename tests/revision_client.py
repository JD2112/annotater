"""A ``TestClient`` that behaves like one browser tab of the React frontend.

The API binds execution to the dataset revisions a tab displays and binds
result reads/exports to the result revision it displays (release-gate
finding F1). The frontend remembers the revisions returned by load-sample,
upload, apply-mapping and execute and echoes them back; this client does the
same, so endpoint tests written before revisions existed keep exercising the
same flows. Revisions the test passes explicitly are never overridden, and
nothing is injected for state this "tab" never received, so missing and
mismatching revisions remain testable with it or with a plain ``TestClient``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


class RevisionClient(TestClient):
    """One tab: tracks the revisions it was given and echoes them."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.revisions: dict[str, str] = {}

    def request(self, method, url, *args, **kwargs):
        path = str(url).split("?", 1)[0]
        method = method.upper()

        if method == "POST" and path == "/api/execute":
            body = kwargs.get("json")
            if isinstance(body, dict):
                body = dict(body)
                for role in ("query", "annot"):
                    if role in self.revisions:
                        body.setdefault(f"{role}_rev", self.revisions[role])
                # A custom chromosome mapping is bound to a run by revision,
                # exactly like a dataset: the tab echoes the revision of the
                # mapping it displays. A bundled assembly is a different
                # chromosome source, so it is never combined with one.
                registry_rev = self.revisions.get("registry")
                if (
                    registry_rev
                    and "assembly" not in body
                    and body.get("chr_naming")
                ):
                    body.setdefault("registry_rev", registry_rev)
                kwargs["json"] = body
        elif method == "POST" and path == "/api/apply-mapping":
            body = kwargs.get("json")
            if isinstance(body, dict) and "query" in self.revisions:
                body = dict(body)
                body.setdefault("query_rev", self.revisions["query"])
                kwargs["json"] = body
        elif method == "POST" and path == "/api/dataset/clear":
            # Issue #51: a clear that names no revision is refused (428) once a
            # dataset is stored, so a tab must echo the revision it owns. This
            # mirrors the frontend, which only ever clears a revision it
            # received (and sends nothing when it knows none). Tests that need
            # the missing-revision path use a client that never received one.
            body = kwargs.get("json")
            if isinstance(body, dict):
                body = dict(body)
                role = body.get("role")
                if role in self.revisions:
                    body.setdefault("revision", self.revisions[role])
                kwargs["json"] = body
        elif method == "GET" and (path.startswith("/api/results/") or path.startswith("/api/export/")):
            if "result" in self.revisions and "result_rev=" not in str(url):
                params = dict(kwargs.get("params") or {})
                params.setdefault("result_rev", self.revisions["result"])
                kwargs["params"] = params

        response = super().request(method, url, *args, **kwargs)
        self._record(method, path, response)
        return response

    def _record(self, method, path, response):
        if response.status_code != 200:
            return
        if method == "DELETE" and path == "/api/registry":
            # Like the frontend, a tab that discards the custom mapping also
            # drops the result it displayed for it.
            self.revisions.pop("registry", None)
            return
        if method != "POST":
            return
        try:
            body = response.json()
        except ValueError:
            return
        if path == "/api/load-sample":
            self.revisions["query"] = body["query"]["revision"]
            self.revisions["annot"] = body["annot"]["revision"]
        elif path == "/api/upload":
            self.revisions[body["role"]] = body["revision"]
        elif path == "/api/apply-mapping":
            self.revisions["query"] = body["revision"]
        elif path == "/api/execute":
            self.revisions["result"] = body["result_revision"]
        elif path == "/api/dataset/clear":
            # Like the frontend, a tab that discards a dataset also drops the
            # result it displayed for it.
            self.revisions.pop(body.get("cleared"), None)
            self.revisions.pop("result", None)
        elif path == "/api/registry":
            registry = body.get("registry")
            if registry:
                self.revisions["registry"] = registry["revision"]
