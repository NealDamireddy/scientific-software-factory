# Backend comparison contracts

These are local experiments based on Lab Factory at `62badef`. Each candidate exports `solve(request)` from its own `candidate.py`. Inputs and outputs are Python dictionaries or lists of ordinary values. Implement the assigned approach using the standard library and the checked-in Lab Factory package. Trial code and data stay outside the application. The independent graders supply records, requests, temporary databases and numerical oracles at runtime. Report limitations and use the stated abstention outcome when evidence is insufficient.

## memory

Input has `documents` (each has `id` in FAMILY@REV format, integer `revision`, string `model`, `kind` and `text`), a requested `model`, integer `as_of` revision and free text `query`. Return at most three relevant IDs, ordered best first. Permit only the exact requested model and shared model `*`. Use the newest eligible edition of each family as of the revision, even if an obsolete edition has a stronger text match. Return an empty list for an unsupported or ambiguous request. Do not hardcode fixture IDs.

## review

Requests contain a path `db`, `op`, `order`, `actor`, and `role` (reviewer or agent). The database may initially be absent. A reviewer creates an open order; one agent claims it; that owner may submit an ASCII `artifact`; a reviewer approves or rejects only the current numbered submission using integer `submission`. A rejection reopens the order and clears ownership. Approval releases the order. A repeated operation cannot append another event. Responses contain boolean `ok`. Read returns `status` (open, in_progress, in_review or released), `owner` (string or null), `submission` (latest integer, initially 0), `digest` (latest artifact SHA-256 hex or null), and `events` (ordered strings create/claim/submit/reject/approve). Keep numbering and historical decisions through rejection or restart. Concurrent calls may come from different processes. The supplied role models an identity already authenticated by the caller.

## author

Input has free-text `protocol`, `fields` with signal and factor, and output `unit`. Output either a nonempty clarification in `needs_input` or actual `source` defining exactly `analyze(standards, signal, factor)` under the existing arithmetic interpreter. Standards are [signal, known] pairs. See `src/labfactory/tabular_analysis.py` for allowed helpers. Examples of method families are fitted calibration with dilution, mass and volume, and blank correction. Respect stated regression direction, units, factors and order of operations. Ambiguous or incomplete instructions should request input. This trial evaluates offline alternatives for deriving code from protocol text.

## verify

Input has an arithmetic expression `program` with variables x and f, numeric constants and arithmetic operators; `controls` of {x,f,expected,tolerance}; inclusive `domain` [lo,hi]; `sample` {x,f}; and optional declared `properties` (nondecreasing and/or nonnegative). Return {decision: release or withhold, value: number or null}. Require independent controls, check all of them within their inclusive absolute tolerances, and check domain, stated properties, and finite arithmetic. No extrapolation; factors are positive. Screen at fixed f when reasoning about trends over x. Use a restricted numeric expression interpreter. Only test the properties actually declared. An evaluation failure withholds the result.

## trace

Input has numerical arrays `times`, `signals`, and inclusive integration `window` [lo,hi]. Both boundaries must be sampled. For an isolated synthetic triangular feature on a linear baseline, return {status: ok, area: number} above the line through window endpoints. Support irregular spacing and ignore off-window neighbors. Return {status: needs_input, area: null} for inconsistent data, truncated/off-grid windows, missing peaks, or multiple distinct maxima. These are simulated optical signals.

## plan

Input has descriptive `goal`, an already selected `sop` with id and ordered steps [{command,value,unit}], `manual` with id and commands mapping each name to {unit,min,max}, and boolean `released` and `online`. A parameterless command uses nulls. Convert compatible units (including um/nm and C/K), preserve precision and validate finite values against inclusive limits. Return {status,steps} where validated steps contain canonical command/value/unit and citations [sop id, manual id]. A valid plan is simulated only if released and online, otherwise draft. Invalid evidence, unknown commands or invalid quantities return needs_input and an empty list. Scope is an in-memory reference instrument. No hardware, network or automatic approval.

## ops

Each request carries a local database pathname `db`, operation `op` (enqueue/lease/finish/read), and applicable `job`, `worker`, integer `now`, positive integer `ttl`, `key`, `token` and string `payload`. Respond with boolean `ok`. Enqueue of the same job/key/payload is idempotent; mismatched retries conflict. Lease of a queued or expired job returns an opaque token; a live lease excludes competitors. A lease expires at now >= lease start + ttl. Finish needs a matching live token and worker, and repeats of an identical successful finish are idempotent. Read exposes status queued/leased/done and the exact result payload after completion. Persist state across processes and restarts. Test with logical time and temporary files.

## draft

Given {goal,model,documents,as_of}, turn applicable prose into an ordered, cited draft for a simulated optical reference or thermometer display. Each document has id (FAMILY@REV), revision, model (exact or *), kind (sop or manual), and text. Use latest eligible editions, prefer model-specific evidence over shared fallback, and resolve the goal to a unique applicable SOP. The SOP must supply the operations, order and values; the manual must support them and their limits. Permitted command names are zero, set_wavelength, read_display and set_temperature. Numeric actions use nm or C; zero and read use null value and unit. Each step has command, value, unit, citations (the two exact source IDs). Return {status:"draft",steps:[...]} on grounded success, or {status:"needs_input",steps:[]} when information is absent, ambiguous, contradictory, or out of limits. No instrument execution.

## access

Given {mode,action,lab,record_lab,principal,submission,latest,passed}, decide {allow:boolean,actor:string|null}. A principal already verified by the host is null or has id, role and lab. read_library is global. All other requests must target a record in the requested lab. In public_demo, read_upload, see_control and approve are accessible to any caller and the approval identity is "Public reviewer". In private_lab, these are for same-lab reviewers; same-lab observers may also read_upload. In either mode work_context and claim require a same-lab agent. Every approval requires a positive integer submission that is current and passing. Only allowed writes (approve and claim) have a non-null actor. Everything else defaults to denial. This is an offline policy trial for a possible private lab configuration; the principal records are fixtures.

## storage

Each request has root (temporary local directory), op (put/get/list), key (logical immutable ASCII ID where applicable), and bytes payload on put. Return a boolean ok, plus the lowercase SHA-256 hex digest on successful put or get. Get also returns the original bytes in payload; list returns a sorted keys list. Repeating a key and payload is idempotent; a different payload for an existing key conflicts. Data must survive independent processes and concurrent conflicting inserts. Include integrity under a growing workload. The snapshot comparator retains the current 8 MiB cap by design. Use a local stand-in for storage; keep all files beneath root. No network or cloud performance claims.
