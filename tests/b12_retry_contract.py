"""HTTP assertions shared by the standalone WO-16 and combined retry scenarios."""
import json


def check_retry_successors(test, request, first, readings):
    """Start with rejected A. Reject B, complete C, then replay A's retry key."""
    first_id = first["id"]
    retry_a = {"retry_of": first_id}
    rejected = request("/rerun", retry_a)
    test.assertEqual(len(rejected["acquisition_attempts"]), 2)
    original, second = rejected["acquisition_attempts"]
    second_id = second["id"]
    test.assertEqual(original, first)
    test.assertNotEqual(first_id, second_id)
    test.assertEqual(second["retry_of"], first_id)
    test.assertEqual(rejected["acquisition_attempt_id"], second_id)
    test.assertEqual((rejected["acquisition_status"], second["status"]), ("rejected", "rejected"))
    test.assertIn("blank", second["failure"]["reason"].lower())
    test.assertEqual(second["raw"], readings[1])

    retry_b = {"retry_of": second_id}
    completed = request("/rerun", retry_b)
    history = completed["acquisition_attempts"]
    test.assertEqual(history[:-1], [first, second])
    third = history[-1]
    third_id = third["id"]
    test.assertEqual(len({first_id, second_id, third_id}), 3)
    test.assertEqual(third["retry_of"], second_id)
    test.assertEqual(completed["acquisition_attempt_id"], third_id)
    test.assertEqual((completed["acquisition_status"], third["status"]), ("completed", "completed"))
    test.assertEqual(completed["result"]["status"], "ok")
    test.assertEqual(completed["measurement"]["attempt_id"], third_id)
    test.assertEqual(completed["measurement"]["raw"], readings[2])

    scored = request("/reveal", {})
    test.assertIsNotNone(scored["score"]["prepared_mg_l"])
    test.assertEqual(scored["score"]["predicted_mg_l"], completed["result"]["concentration_mg_l"])
    test.assertEqual(request("/rerun", retry_b), scored)
    previous = request("/rerun", retry_a)
    test.assertEqual(previous["acquisition_attempt_id"], second_id)
    test.assertEqual(previous["acquisition_status"], "rejected")
    test.assertEqual(previous["acquisition_attempts"], history)
    for key in ("measurement", "result", "score", "replay"):
        test.assertNotIn(key, previous)
    test.assertNotIn("prepared_mg_l", json.dumps(previous))
    test.assertEqual(request(""), scored)
    test.assertEqual(len(readings), 3)
