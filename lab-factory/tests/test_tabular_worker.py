import asyncio
from pathlib import Path

from labfactory import tabular_worker as worker


def test_author_receives_only_public_analysis_and_tool_free_prompt(monkeypatch):
    import json
    import subprocess

    def invoke(command, *, cwd, env, input, **kwargs):
        assert "private!control" not in input and "private!control" not in str(env)
        assert "experiment" in input and "real protocol" in input and "public feedback" in input
        assert "--ignore-user-config" in command and "shell_tool" in command and "apps" in command
        Path(cwd, "answer.json").write_text(json.dumps({"question":"What is the dilution?", "source":"",
                                                        "explanation":"", "tests":[]}))
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(worker.subprocess, "run", invoke)
    monkeypatch.setenv("LAB_FACTORY_AGENT_TOKEN","private!control")
    ctx = {"instructions":"host syntax", "analysis":{"protocol":"real protocol"}, "private":"private!control"}
    assert worker.generate(ctx, ["public feedback"]) == {"needs_input":"What is the dilution?"}


def test_blind_failure_uses_one_candidate_and_stops(monkeypatch):
    counts = {"author":0, "submission":0}
    async def call(session, name, args):
        if name == "get_work_order_context":
            return {"work_order":{"status":"open","worker":None}, "analysis":{
                "protocol":"test", "awaiting_fresh_control":bool(counts["submission"])}}
        if name == "claim_work_order":
            return {"claim_id": 1}
        assert name == "submit_artifact"
        assert args["claim_id"] == 1
        counts["submission"] += 1
        return {"submission":1,"status":"in_progress","artifact_digest":"abc","passed":False,"results":[]}
    def author(context, feedback):
        counts["author"] += 1
        return {"source":"submitted code"}
    monkeypatch.setattr(worker,"_call",call)
    assert asyncio.run(worker.process(None,"WO-10","Author",author))
    assert counts == {"author":1, "submission":1}


def test_resumed_worker_keeps_starting_claim_across_feedback_refresh(monkeypatch):
    submitted = []

    async def call(session, name, args):
        if name == "get_work_order_context":
            claim_id = 2 if submitted else 1
            return {"work_order": {"status": "in_progress", "worker": "Author", "claim_id": claim_id},
                    "analysis": {"protocol": "test"}}
        assert name == "submit_artifact"
        submitted.append(args["claim_id"])
        return {"submission": len(submitted), "status": "in_progress",
                "artifact_digest": "abc", "passed": False, "results": []}

    monkeypatch.setattr(worker, "_call", call)
    assert asyncio.run(worker.process(None, "WO-10", "Author", lambda context, feedback: {"source": "code"}))
    assert submitted == [1, 1, 1, 1]


def test_unrelated_order_and_pending_clarification_are_skipped(monkeypatch):
    async def check(context):
        async def call(session,name,args):
            assert name=="get_work_order_context"
            return {"work_order":{"status":"open"}, **context}
        monkeypatch.setattr(worker,"_call",call)
        return await worker.process(None,"WO-12","Author")
    assert not asyncio.run(check({}))
    assert not asyncio.run(check({"analysis":{"needs_input":"Please identify the units."}}))
