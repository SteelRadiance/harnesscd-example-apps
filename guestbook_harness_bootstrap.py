#!/usr/bin/env python3
"""
Apply guestbook Harness CD resources via Harness NG REST API.

Requires:
  - ~/.harness/auth.json from `hc auth login`
  - HARNESS_GITHUB_PAT or GITHUB_TOKEN (GitHub PAT for the connector secret)

Optional environment (defaults suit github.com/SteelRadiance/harnesscd-example-apps, branch master):
  - HARNESS_GITHUB_USER
  - HARNESS_GIT_REPO           repo name (not full URL)
  - HARNESS_GIT_BRANCH         must match service manifest branch in service.yml
  - HARNESS_PIPELINE_FILE      path to rolling pipeline yaml in repo
  - HARNESS_GITHUB_CONNECTOR   Harness GitHub connector identifier
  - HARNESS_DELEGATE_NAME      K8s delegate selector
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

AUTH_PATH = Path.home() / ".harness" / "auth.json"
BASE = "https://app.harness.io"
ORG = "default"
PROJECT = "default_project"
ACCOUNT = None
TOKEN = None
GITHUB_USER = os.environ.get("HARNESS_GITHUB_USER", "SteelRadiance")
DELEGATE_SELECTOR = os.environ.get("HARNESS_DELEGATE_NAME", "kubernetes-delegate")
# Git coordinates for REMOTE pipeline + service manifests (default matches this fork)
HARNESS_GIT_REPO = os.environ.get("HARNESS_GIT_REPO", "harnesscd-example-apps")
HARNESS_GIT_BRANCH = os.environ.get("HARNESS_GIT_BRANCH", "master")
# Default path is resolved at runtime from the clone; override with HARNESS_PIPELINE_FILE.
HARNESS_PIPELINE_FILE = os.environ.get("HARNESS_PIPELINE_FILE")
HARNESS_GITHUB_CONNECTOR = os.environ.get("HARNESS_GITHUB_CONNECTOR", "harnessgitconnector")


def load_auth() -> None:
    global ACCOUNT, TOKEN
    if not AUTH_PATH.is_file():
        print(f"Missing {AUTH_PATH}; run: hc auth login --non-interactive ...", file=sys.stderr)
        sys.exit(1)
    data = json.loads(AUTH_PATH.read_text())
    ACCOUNT = data["account_id"]
    TOKEN = data["token"]


def qs(extra: str = "") -> str:
    q = f"accountIdentifier={ACCOUNT}&orgIdentifier={ORG}&projectIdentifier={PROJECT}"
    return f"{q}&{extra}" if extra else q


def request_json(
    method: str,
    path: str,
    body: dict | None = None,
    content_type: str = "application/json",
) -> tuple[int, dict | str]:
    url = f"{BASE}{path}"
    if "?" not in path:
        url = f"{url}?{qs()}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-api-key", TOKEN)
    if body is not None:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def request_yaml(method: str, path: str, yaml_body: str) -> tuple[int, dict | str]:
    if "?" in path:
        url = f"{BASE}{path}"
    else:
        url = f"{BASE}{path}?{qs()}"
    req = urllib.request.Request(url, data=yaml_body.encode(), method=method)
    req.add_header("x-api-key", TOKEN)
    req.add_header("Content-Type", "application/yaml")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def _is_duplicate(code: int, resp: dict | str) -> bool:
    msg = str(resp) if not isinstance(resp, dict) else json.dumps(resp)
    m = msg.lower()
    if code == 409:
        return True
    if "already exists" in m or "duplicate" in m or "resource_already_exists" in m:
        return True
    if isinstance(resp, dict) and resp.get("code") in ("RESOURCE_ALREADY_EXISTS", "DUPLICATE_FIELD"):
        return True
    return False


def ensure_secret_text(identifier: str, name: str, value: str) -> None:
    body = {
        "secret": {
            "type": "SecretText",
            "name": name,
            "identifier": identifier,
            "orgIdentifier": ORG,
            "projectIdentifier": PROJECT,
            "tags": {},
            "description": "",
            "spec": {
                "type": "SecretText",
                "secretManagerIdentifier": "harnessSecretManager",
                "valueType": "Inline",
                "value": value,
            },
        }
    }
    code, resp = request_json("POST", "/ng/api/v2/secrets", body)
    if code in (200, 201):
        print(f"OK secret {identifier} created")
        return
    if _is_duplicate(code, resp):
        print(f"OK secret {identifier} already exists")
        return
    print(f"FAIL secret {identifier} HTTP {code}: {resp}", file=sys.stderr)
    sys.exit(1)


def ensure_connector_github() -> None:
    connector = {
        "name": "harness_gitconnector",
        "identifier": "harnessgitconnector",
        "description": "",
        "orgIdentifier": ORG,
        "projectIdentifier": PROJECT,
        "tags": {},
        "type": "Github",
        "spec": {
            "url": f"https://github.com/{GITHUB_USER}/harnesscd-example-apps",
            "authentication": {
                "type": "Http",
                "spec": {
                    "type": "UsernameToken",
                    "spec": {
                        "username": GITHUB_USER,
                        "tokenRef": "harness_gitpat",
                    },
                },
            },
            "apiAccess": {"type": "Token", "spec": {"tokenRef": "harness_gitpat"}},
            "executeOnDelegate": False,
            "type": "Repo",
        },
    }
    code, resp = request_json("POST", "/ng/api/connectors", {"connector": connector})
    if code in (200, 201):
        print("OK GitHub connector created")
        return
    if _is_duplicate(code, resp):
        print("OK GitHub connector already exists")
        return
    print(f"FAIL GitHub connector HTTP {code}: {resp}", file=sys.stderr)
    sys.exit(1)


def ensure_connector_k8s() -> None:
    connector = {
        "name": "harness_k8sconnector",
        "identifier": "harnessk8sconnector",
        "description": "",
        "orgIdentifier": ORG,
        "projectIdentifier": PROJECT,
        "tags": {},
        "type": "K8sCluster",
        "spec": {
            "credential": {"type": "InheritFromDelegate"},
            "delegateSelectors": [DELEGATE_SELECTOR],
        },
    }
    code, resp = request_json("POST", "/ng/api/connectors", {"connector": connector})
    if code in (200, 201):
        print("OK K8s connector created")
        return
    if _is_duplicate(code, resp):
        print("OK K8s connector already exists")
        return
    print(f"FAIL K8s connector HTTP {code}: {resp}", file=sys.stderr)
    sys.exit(1)


def ensure_environment_v2(yaml_path: Path) -> None:
    yaml_text = yaml_path.read_text()
    body = {
        "orgIdentifier": ORG,
        "projectIdentifier": PROJECT,
        "identifier": "harnessdevenv",
        "name": "harnessdevenv",
        "type": "PreProduction",
        "yaml": yaml_text,
    }
    code, resp = request_json("POST", "/ng/api/environmentsV2", body)
    if code in (200, 201):
        print(f"OK environment from {yaml_path.name}")
        return
    if _is_duplicate(code, resp):
        print(f"OK environment already exists ({yaml_path.name})")
        return
    print(f"FAIL environment HTTP {code}: {resp}", file=sys.stderr)
    sys.exit(1)


def ensure_infrastructure(yaml_path: Path) -> None:
    yaml_text = yaml_path.read_text()
    body = {
        "yaml": yaml_text,
        "orgIdentifier": ORG,
        "projectIdentifier": PROJECT,
        "environmentRef": "harnessdevenv",
        "identifier": "harnessk8sinfra",
        "name": "harness_k8sinfra",
        "type": "KubernetesDirect",
    }
    code, resp = request_json("POST", "/ng/api/infrastructures", body)
    if code in (200, 201):
        print(f"OK infrastructure from {yaml_path.name}")
        return
    if _is_duplicate(code, resp):
        print(f"OK infrastructure already exists ({yaml_path.name})")
        return
    print(f"FAIL infrastructure HTTP {code}: {resp}", file=sys.stderr)
    sys.exit(1)


def ensure_service_v2(yaml_path: Path) -> None:
    yaml_text = yaml_path.read_text()
    body = {
        "orgIdentifier": ORG,
        "projectIdentifier": PROJECT,
        "identifier": "harnessguestbook",
        "name": "harness_guestbook",
        "yaml": yaml_text,
    }
    code, resp = request_json("POST", "/ng/api/servicesV2", body)
    if code in (200, 201):
        print(f"OK service from {yaml_path.name}")
        return
    if _is_duplicate(code, resp):
        print(f"OK service already exists ({yaml_path.name})")
        return
    print(f"FAIL service HTTP {code}: {resp}", file=sys.stderr)
    sys.exit(1)


def get_pipeline_detail(pipeline_identifier: str) -> dict | None:
    """Return pipeline GET `data` object, or None if missing."""
    url = (
        f"{BASE}/pipeline/api/pipelines/{pipeline_identifier}?"
        f"accountIdentifier={ACCOUNT}&orgIdentifier={ORG}&projectIdentifier={PROJECT}"
    )
    req = urllib.request.Request(url, method="GET")
    req.add_header("x-api-key", TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"FAIL pipeline GET HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        sys.exit(1)
    return body.get("data")


def delete_pipeline(pipeline_identifier: str) -> None:
    url = (
        f"{BASE}/pipeline/api/pipelines/{pipeline_identifier}?"
        f"accountIdentifier={ACCOUNT}&orgIdentifier={ORG}&projectIdentifier={PROJECT}"
    )
    req = urllib.request.Request(url, method="DELETE")
    req.add_header("x-api-key", TOKEN)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode()
    if resp.status not in (200, 204):
        print(f"WARN pipeline DELETE HTTP {resp.status}: {raw[:300]}", file=sys.stderr)


def import_pipeline_from_git(pipeline_file_path: str) -> None:
    """Create pipeline with storeType REMOTE (YAML pulled from Git on each run)."""
    params = urlencode(
        {
            "accountIdentifier": ACCOUNT,
            "orgIdentifier": ORG,
            "projectIdentifier": PROJECT,
            "repoName": HARNESS_GIT_REPO,
            "filePath": pipeline_file_path,
            "branch": HARNESS_GIT_BRANCH,
            "connectorRef": HARNESS_GITHUB_CONNECTOR,
        }
    )
    url = f"{BASE}/pipeline/api/pipelines/import?{params}"
    req = urllib.request.Request(url, data=json.dumps({}).encode(), method="POST")
    req.add_header("x-api-key", TOKEN)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        print(f"FAIL pipeline import HTTP {e.code}: {e.read().decode()[:800]}", file=sys.stderr)
        sys.exit(1)
    print(f"OK pipeline imported from Git ({HARNESS_GIT_BRANCH}:{pipeline_file_path})")


def ensure_pipeline_remote_from_git(pipeline_identifier: str, pipeline_file_path: str) -> None:
    """
    Ensure the pipeline is stored in Git (REMOTE). Then UI runs always use the latest
    commit on the configured branch for that file path.
    """
    detail = get_pipeline_detail(pipeline_identifier)
    need_import = False
    if detail is None:
        need_import = True
        print(f"Pipeline {pipeline_identifier} missing; importing from Git…")
    elif detail.get("storeType") != "REMOTE":
        need_import = True
        print(f"Pipeline {pipeline_identifier} is INLINE; replacing with Git-backed (REMOTE)…")
        delete_pipeline(pipeline_identifier)
    else:
        gd = detail.get("gitDetails") or {}
        if (
            gd.get("filePath") != pipeline_file_path
            or gd.get("branch") != HARNESS_GIT_BRANCH
            or gd.get("repoName") != HARNESS_GIT_REPO
        ):
            need_import = True
            print(f"Pipeline {pipeline_identifier} Git pointer changed; re-importing…")
            delete_pipeline(pipeline_identifier)

    if need_import:
        import_pipeline_from_git(pipeline_file_path)
    else:
        print(
            f"OK pipeline {pipeline_identifier} already REMOTE ({HARNESS_GIT_BRANCH}:{pipeline_file_path} "
            f"in {HARNESS_GIT_REPO})"
        )


def verify_delegate() -> None:
    url = f"{BASE}/ng/api/delegate-setup/listDelegates?{qs('all=true')}"
    body = {"filterType": "Delegate", "pageIndex": 0, "pageSize": 50}
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("x-api-key", TOKEN)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as resp:
        obj = json.loads(resp.read().decode())
    res = obj.get("resource") or []
    names = [r.get("name") for r in res]
    if DELEGATE_SELECTOR not in names:
        print(f"WARN delegate '{DELEGATE_SELECTOR}' not in list {names}", file=sys.stderr)
    else:
        for r in res:
            if r.get("name") == DELEGATE_SELECTOR:
                print(
                    f"OK delegate {DELEGATE_SELECTOR} connected={r.get('connected')} "
                    f"replicas={len(r.get('delegateReplicas') or [])}"
                )


def verify_pipeline(pipeline_identifier: str) -> None:
    url = (
        f"{BASE}/pipeline/api/pipelines/{pipeline_identifier}?"
        f"accountIdentifier={ACCOUNT}&orgIdentifier={ORG}&projectIdentifier={PROJECT}"
    )
    req = urllib.request.Request(url, method="GET")
    req.add_header("x-api-key", TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"OK pipeline {pipeline_identifier} present (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        print(f"FAIL pipeline {pipeline_identifier} verify HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    ghpat = os.environ.get("HARNESS_GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    if not ghpat:
        print(
            "Set HARNESS_GITHUB_PAT (or GITHUB_TOKEN) to your GitHub PAT for this project.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Script lives in Code/harness/; example repo is Code/harnesscd-example-apps
    repo_root = Path(__file__).resolve().parent.parent / "harnesscd-example-apps"
    pipe_dir = repo_root / "guestbook" / "harnesscd-pipeline"
    if not pipe_dir.is_dir():
        print(f"Missing {pipe_dir}; clone SteelRadiance/harnesscd-example-apps under Code/", file=sys.stderr)
        sys.exit(1)

    load_auth()
    verify_delegate()

    ensure_secret_text("harness_gitpat", "harness_gitpat", ghpat)
    ensure_connector_github()
    ensure_connector_k8s()

    ensure_environment_v2(pipe_dir / "environment.yml")
    ensure_infrastructure(pipe_dir / "infrastructure-definition.yml")
    ensure_service_v2(pipe_dir / "service.yml")

    rolling = pipe_dir / "rolling-pipeline.yml"
    rolling_rel = HARNESS_PIPELINE_FILE or rolling.relative_to(repo_root).as_posix()
    ensure_pipeline_remote_from_git("guestbook_rolling_pipeline", rolling_rel)
    verify_pipeline("guestbook_rolling_pipeline")

    testing_rel = (pipe_dir / "testing-pipeline.yml").relative_to(repo_root).as_posix()
    ensure_pipeline_remote_from_git("testing", testing_rel)
    verify_pipeline("testing")

    print("Done.")


if __name__ == "__main__":
    main()