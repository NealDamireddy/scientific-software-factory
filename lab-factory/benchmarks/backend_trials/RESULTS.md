# Backend component trials

These trials compare 30 implementations of ten individual backend interfaces at baseline commit `62badef`. One separate live baseline exercised the existing Mac author. The trials ran against temporary files, SQLite databases and simulated measurements. They provide component-level evidence for an architecture decision. They did not deploy the alternatives, benchmark Vercel or a managed database, connect physical instruments, or collect data on reliability or cost under a real lab's workload.

## Results and decisions

The numbers are **passed cases / cases tested** for one implementation. Each area's three contenders received the same inputs. One case may cover multiple requests, predictions, transactions or processes. A tie leaves the implementation choice to engineering judgment. [Case-level results and exact source fingerprints](evidence/scores.json)

| Area | Competing implementations | Decision supported by this trial |
| --- | --- | --- |
| Reference retrieval | Lexical 14/16, concept expansion 14/16, evidence graph 14/16 | Use revision- and model-filtered lexical retrieval as a baseline. It found the manufacturer manual that the other two missed, but abstained on equally relevant sources. None bridged the salinity paraphrase. Collect real unanswered lab searches before expanding the index. |
| Work-order review | Transactions 10/10, event replay 10/10, database constraints 10/10 | Keep transactional state and append-only audit events. Four processes produced one winner. Stale approvals, repeated requests and process restarts behaved correctly under all three designs. These cases do not justify migrating a working lifecycle to full event replay. |
| Analysis authoring | Templates 3/10, compiler 6/10, synthesis 3/10 | Retain the existing author plus independent verification for free-text protocols. The compiler has a possible role when a protocol already uses a controlled vocabulary. The baseline results and the distinction between abstention and a wrong answer are below. |
| Numerical verification | Control panel 15/17, interval checks 17/17, metamorphic checks 16/17 | Pilot interval checks for declared mathematical properties in addition to independent controls. The control panel released an expression that dipped below zero between control levels. The two sampling-based designs withheld a valid one-control example. A passing expression check alone cannot establish that a method or calibration is scientifically appropriate. |
| Optical trace integration | Trapezoids 13/13, shape fit 13/13, peak segmentation 13/13 | Start with endpoint correction plus trapezoids for this narrow input. All three integrated five simulated single peaks and abstained on eight invalid or ambiguous traces. The tests supply sampled endpoints, fixed windows and linear background. Raw instrument exports, nonlinear baselines and real peak identification need separate evidence. |
| Structured procedure checks | Direct rules 15/15, typed compiler 15/15, simulator preflight 15/15 | Keep direct validation for ordered steps, citations, precise settings, units and inclusive limits. The simulation covered an optical display and a thermometer. Real hardware interlocks and execution were outside this comparison. |
| Worker queue | Leases 8/8, journal 8/8, outbox 8/8 | Start with transactionally acquired leases and fencing tokens. An outbox is worth another trial when dispatch must coordinate an external side effect. These local restart and race cases do not establish exactly-once behavior across network failures or continuous cloud worker availability. |
| Procedure drafting from prose | Extraction 14/16, grammar 10/16, evidence-first 14/16 | Extraction and evidence-first tied and abstained on the same two valid inputs, a shared SOP and a temperature procedure. The closed grammar abstained on six valid inputs. All three correctly withheld drafts on the negative cases. Keep generated drafts under independent validation and review. |
| Reviewer and agent access | Role matrix 18/18, capability model 18/18, declarative policy 18/18 | Keep a small explicit role/mode matrix for this policy. The 18 groups contained 206 decisions per contender. Principals were already authenticated inputs. Token verification, revocation, browser behavior, isolation across deployed services and identity-provider integration were outside scope. |
| Durable storage | Capped snapshot 7/8, database 8/8, immutable objects 8/8 | Prefer transactional metadata for expected growth and keep separately addressed original uploads. Both alternatives retained and verified 24 half-MiB records. The capped snapshot accepted 15 and preserved all 15 after refusing later writes. This is a local simulated storage workload. |

### What the authoring comparison measured

Seven protocols required an executable calculation, including direct density, forward and inverse calibration, and blank correction. Three protocols omitted essential information and required a clarification. The interpreter evaluated the source against independently specified values, including different batches of standards. A generic nonempty question earns a point on the three clarification cases. The field-name list was the official input. An implementation that requires a field mapping can conservatively ask for clarification even when the protocol is otherwise complete.

On the seven executable cases, templates and synthesis returned no runnable programs and the compiler solved three. Their misses were abstentions. All three requested clarification on the three incomplete protocols. These ten cases cannot estimate an author's field success rate.

For the live baseline, the existing signed-in Mac driver received each protocol, field names, unit and normal authoring instructions. The runner excluded evaluation readings, independently expected values and case labels from its input. The saved outputs included seven runnable functions matching **24/24 numerical predictions** and three clarifications for missing inputs. The offline replay scored **10/10**. The saved evidence includes one fresh model response per case, with the CLI version, duration and driver fingerprint. Replay verifies those specific outputs. A fresh model execution may differ, and this sample does not measure the long-term success rate of agent authoring. [Captured baseline responses](evidence/author_baseline.json)

### Deployment implications

The current hosted service stores original uploaded files separately as digest-addressed Blob objects. Its 8 MiB cap applies to the SQLite metadata/history snapshot. Our growth case used synthetic 512 KiB payloads in a generic immutable store, larger than today's 128 KiB per-file upload limit. It demonstrates a limitation of replicating that capped snapshot strategy for a growing store. Backup, restore, provider outages, network concurrency, hosting cost and migration of existing production data require deployment-level trials. Keeping both metadata and addressed objects requires restoring both together.

The three queue implementations used local database serialization and logical time. The winner of a lease race persisted across processes, but a real remote worker also needs process supervision, credential management and recovery when a request succeeds and its acknowledgement is lost. Public review remains a product choice. Authorization trials used preverified identities and had no effect on access to the deployed service.

## Reproduce

Run from `lab-factory/` on macOS or Linux with Python 3.11 or newer and a Python runtime that supports the multiprocessing `fork` context.

```sh
uv sync --locked
uv run --locked pytest -q
uv run --locked python benchmarks/backend_trials/run.py
uv run --locked python benchmarks/backend_trials/author_baseline.py
```

Use `run.py --area storage` to rerun a single comparison or `run.py --json` to emit the per-case evidence. A contender's failed case is an experimental finding. The command exits nonzero for a runner error such as a missing file. The Mac baseline replays its saved outputs by default. Fresh collection requires the signed-in Codex worker and is a separate operation.
