"""Credential-free HTTP smoke test for an isolated Compose stack."""

import json
import re
import time
import urllib.error
import urllib.request
import uuid


def request(path: str, *, method: str = "GET", body: dict | None = None,
            token: str | None = None, frontend: bool = False) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        ("http://127.0.0.1:3000" if frontend else "http://127.0.0.1:8000") + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def main() -> None:
    for _ in range(45):
        try:
            if request("/ready")[0] == 200 and request("/", frontend=True)[0] == 200:
                break
        except OSError:
            pass
        time.sleep(2)
    else:
        raise RuntimeError("Compose services did not become ready")
    status, html = request("/", frontend=True)
    assert status == 200
    stylesheet = re.search(rb'href="([^"]+\.css[^\"]*)"', html)
    assert stylesheet and request(stylesheet[1].decode(), frontend=True)[0] == 200
    assert request("/movie/not-a-uuid", frontend=True)[0] == 404
    assert request("/movie/" + str(uuid.uuid4()), frontend=True)[0] == 404
    assert request("/api/search/discover", method="POST", body={"query": "comedy"})[0] == 200
    status, body = request("/api/auth/register", method="POST", body={
        "email": f"smoke-{uuid.uuid4()}@example.com", "password": uuid.uuid4().hex,
    })
    assert status == 201, f"registration returned HTTP {status}: {body[:300]!r}"
    token = json.loads(body)["access_token"]
    status, body = request("/api/chat/message", method="POST", token=token, body={"message": "hey"})
    assert status == 200
    conversation = json.loads(body)["session_id"]
    assert request("/api/chat/sessions", token=token)[0] == 200
    assert request("/api/chat/sessions/" + conversation)[0] == 404
    assert request("/api/chat/sessions/" + conversation, method="DELETE", token=token)[0] == 204
    assert request("/api/chat/sessions/" + conversation, token=token)[0] == 404
    assert request("/api/ratings/history", token=token)[0] == 200
    print("Container smoke passed: readiness, assets, SSR-to-API routing, Discover, private chat history/deletion and rating history.")


if __name__ == "__main__":
    main()
