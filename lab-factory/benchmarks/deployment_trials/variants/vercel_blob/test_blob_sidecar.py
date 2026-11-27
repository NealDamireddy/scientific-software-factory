"""Exercise the sidecar wire protocol across writers and process-equivalent cold opens."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
import json
import secrets
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from blob_sidecar import BlobServer, KEY


@contextmanager
def serve(directory, token, log):
    with BlobServer(0, directory, token, log) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()


def request(origin, token, key, data=None, match=None):
    headers = {"Authorization": "Bearer " + token}
    if data is None:
        path = f"/{key}?cache=0"
        headers["Accept-Encoding"] = "identity"
        method = "GET"
    else:
        path = "/api/blob/?" + urlencode({"pathname": key})
        method = "PUT"
        headers.update({"x-api-version": "13", "x-vercel-blob-access": "private",
                        "x-add-random-suffix": "0", "x-content-type": "application/octet-stream",
                        "x-allow-overwrite": "1" if match else "0"})
        if match:
            headers["x-if-match"] = match
    req = Request(origin + path, method=method, headers=headers, data=data)
    try:
        response = build_opener(ProxyHandler({})).open(req, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers.get("ETag"), response.read()


def test_snapshot_conflicts_originals_and_cold_open(tmp_path):
    token = secrets.token_hex(24)
    original = b"column1,column2\n1,2\n"
    original_key = "labfactory/uploads/" + sha256(original).hexdigest()
    events = tmp_path / "events.jsonl"
    directory = tmp_path / "store"
    with serve(directory, token, events) as origin:
        assert request(origin, "bad", KEY)[0] == 401
        assert request(origin, token, KEY)[0] == 404
        assert request(origin, token, KEY, b"initial")[0] == 200
        duplicate, _, body = request(origin, token, KEY, b"rejected")
        assert duplicate == 400 and "already exists" in json.loads(body)["error"]["message"]
        status, match, payload = request(origin, token, KEY)
        assert status == 200 and payload == b"initial"
        with ThreadPoolExecutor(2) as pool:
            updates = [b"one", b"two"]
            results = list(pool.map(lambda x: request(origin, token, KEY, x, match)[0], updates))
        assert sorted(results) == [200, 412]
        retained = updates[results.index(200)]
        assert request(origin, token, original_key, original)[0] == 200
        assert request(origin, token, original_key, original)[0] == 400

    with serve(directory, token, events) as origin:
        expected = '"' + sha256(retained).hexdigest() + '"'
        assert request(origin, token, KEY) == (200, expected, retained)
        assert request(origin, token, original_key)[2] == original
    entries = [json.loads(line) for line in events.read_text().splitlines()]
    assert sum(e["status"] == 412 for e in entries) == 1
    assert any(e["object_type"] == "original" and e["object_bytes"] == len(original) for e in entries)
    assert token not in events.read_text()
