import asyncio
import json
from pathlib import Path
import subprocess

import pytest

from labfactory import tabular_worker as worker


@pytest.mark.parametrize("question", ["", "What is the dilution?"])
def test_author_receives_only_public_analysis_and_tool_free_prompt(monkeypatch, question):
    context = {"instructions": "host syntax", "analysis": {"protocol": "real protocol"}, "private": "private!control"}
    artifact = {"source": "candidate", "explanation": "calculation", "tests": []}
    workdirs = []

    def invoke(command, *, cwd, env, input, timeout, capture_output, text):
        work = Path(cwd)
        workdirs.append(work)
        assert command[:2] == ["codex", "exec"] and command[-1] == "-"
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert "--ignore-user-config" in command and "shell_tool" in command and "apps" in command
        assert timeout == 210 and capture_output and text
        assert "LAB_FACTORY_AGENT_TOKEN" not in env and "private!control" not in input
        assert json.loads(input.splitlines()[-1]) == {
            "experiment": context["analysis"], "instructions": "host syntax", "public_feedback": ["public feedback"],
        }
        schema = json.loads((work / command[command.index("--output-schema") + 1]).read_text())
        assert set(schema["required"]) == {"question", "source", "explanation", "tests"}
        answer = work / command[command.index("--output-last-message") + 1]
        answer.write_text(json.dumps({"question": question, **artifact}))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", invoke)
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: pytest.fail("Unexpected version lookup"))
    monkeypatch.setenv("LAB_FACTORY_AGENT_TOKEN", "private!control")
    expected = {"needs_input": question} if question else artifact
    assert worker.generate(context, ["public feedback"]) == expected
    assert len(workdirs) == 1 and not workdirs[0].exists()


@pytest.mark.parametrize("exit_code, output, error", [
    (1, "{}", RuntimeError), (0, None, RuntimeError), (0, "invalid", json.JSONDecodeError),
])
def test_failed_author_cleans_up_its_workspace(monkeypatch, exit_code, output, error):
    workdirs = []

    def invoke(command, *, cwd, **kwargs):
        work = Path(cwd)
        workdirs.append(work)
        if output is not None:
            (work / command[command.index("--output-last-message") + 1]).write_text(output)
        return subprocess.CompletedProcess(command, exit_code, "", "private diagnostic")

    monkeypatch.setattr(subprocess, "run", invoke)
    with pytest.raises(error) as exc:
        worker.generate({"analysis": {}, "instructions": "host syntax"})
    if error is RuntimeError:
        assert f"exit {exit_code}" in str(exc.value) and "private diagnostic" not in str(exc.value)
    assert len(workdirs) == 1 and not workdirs[0].exists()


def test_blind_failure_uses_one_candidate_and_stops(monkeypatch):
    counts = {"author":0, "submission":0}
    async def call(session, name, args):
        if name == "get_work_order_context":
            return {"work_order":{"status":"open","worker":None}, "analysis":{
                "protocol":"test", "awaiting_fresh_control":bool(counts["submission"])}}
        if name == "claim_work_order":
            return {}
        assert name == "submit_artifact"
        counts["submission"] += 1
        return {"submission":1,"status":"in_progress","artifact_digest":"abc","passed":False,"results":[]}
    def author(context, feedback):
        counts["author"] += 1
        return {"source":"submitted code"}
    monkeypatch.setattr(worker,"_call",call)
    assert asyncio.run(worker.process(None,"WO-10","Author",author))
    assert counts == {"author":1, "submission":1}


def test_unrelated_order_and_pending_clarification_are_skipped(monkeypatch):
    async def check(context):
        async def call(session,name,args):
            assert name=="get_work_order_context"
            return {"work_order":{"status":"open"}, **context}
        monkeypatch.setattr(worker,"_call",call)
        return await worker.process(None,"WO-12","Author")
    assert not asyncio.run(check({}))
    assert not asyncio.run(check({"analysis":{"needs_input":"Please identify the units."}}))
