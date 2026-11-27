"""Claim a supplemental example order through two independently running API workers."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
import runpy
from threading import Barrier


def cross_worker_claim(primary_url, peer_url, credentials_path):
    acceptance = runpy.run_path(str(Path(__file__).resolve().parents[2] / "acceptance.py"))
    require = acceptance["require"]
    workers = acceptance["WORKERS"]
    urls = [acceptance["read_origin"](raw, False)[0] for raw in (primary_url, peer_url)]
    require(urls[0] != urls[1], "Cross-worker claim requires two distinct loopback API origins")
    creds = acceptance["load_credentials"](Path(credentials_path), True)
    gate = Barrier(2)

    with ExitStack() as stack:
        wires = []
        for url in urls:
            wire = acceptance["Wire"](url, creds, True)
            stack.callback(wire.client.close)
            wires.append(wire)
        created = wires[0].exchange("/api/example", {}, 201)
        order_id = created.json()["id"]

        def contender(wire, worker):
            statuses = []
            wire.client.event_hooks["response"].append(lambda r: statuses.append(r.status_code))
            gate.wait(timeout=10)
            answer = acceptance["claim"](wire, worker, order_id)
            require(statuses == [200], "Cross-worker MCP claim did not complete via HTTP 200")
            return answer, statuses[0]

        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(contender, wires, workers))
        winners = [worker for worker, (answer, _) in zip(workers, replies, strict=True)
                   if answer.get("status") == "in_progress" and answer.get("worker") == worker
                   and answer.get("id") == order_id]
        require(len(winners) == 1, "Cross-worker race did not return exactly one correctly attributed winner")
        winner = winners[0]
        outcomes = {}
        for origin, worker, (answer, http_status) in zip(("primary", "peer"), workers, replies, strict=True):
            if worker != winner:
                require(answer.get("error") == f"{order_id} is in_progress, expected open",
                        "Losing cross-worker claim did not return the expected domain conflict")
            outcomes[origin] = {"worker": worker, "mcp_http_status": http_status,
                                "claim_result": "in_progress" if worker == winner else "already_claimed"}

        claim_counts = {}
        details = []
        for origin, wire in zip(("primary", "peer"), wires, strict=True):
            response = wire.exchange("/api/orders/" + order_id)
            detail = response.json()
            claims = [event for event in detail["history"] if event["event"] == "claimed"]
            require(len(claims) == 1 and claims[0]["actor"] == winner
                    and detail["order"]["worker"] == winner and detail["order"]["status"] == "in_progress"
                    and detail["order"]["id"] == order_id,
                    "Persisted order and claim history did not identify the single winning worker")
            details.append(detail)
            outcomes[origin]["read_http_status"] = response.status_code
            claim_counts[origin] = len(claims)
        require(details[0] == details[1], "API workers returned different order details after the claim")
        return {"status": "pass", "supplemental_order_id": order_id, "create_http_status": created.status_code,
                "winner": winner, "winner_count": len(winners), "claim_events_per_origin": claim_counts,
                "responses": outcomes, "identical_order_details": True}
