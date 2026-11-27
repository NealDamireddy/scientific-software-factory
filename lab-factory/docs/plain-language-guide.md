# Lab Factory in plain language

This guide explains the project, the words we use, and the plan, without assuming a software background. It is written for the project owner. Future chat sessions are told (in `CLAUDE.md` at the top of the repository) to use the same words the same way, so what you learn here keeps applying.

Last updated: 2026-11-27, after reviewing the public repository at commit `10bad3f`.

## 1. What Lab Factory is

A research lab writes down what it has (its instruments and their limits, its standard procedures) and what an experiment needs. Lab Factory keeps those records. When someone needs a procedure or a piece of analysis software, an AI writes a draft, Lab Factory **checks the draft against the lab's records with ordinary code**, and a named person approves it before anyone uses it.

The whole value of the project is in that middle step. An AI can write something that sounds right and is wrong. Lab Factory's promise is that nothing reaches a person as "checked" unless code really checked it, and nothing is released unless a person really approved it.

## 2. The parts, and where they live

Everything is in one repository (one project folder, stored on GitHub).

| Part | Folder | What it is, in one line |
|---|---|---|
| The engine | `lab-factory/src/labfactory/` | The program that stores records, runs the checks and records approvals. Written in Python. |
| The reviewer site | `lab-factory/public/` | The web page reviewers use today. It talks to the real engine. This is the one that is live on the internet. |
| The researcher site | `lab-factory/web/` | A newer, nicer web page for researchers. Today it only shows made-up sample data; it is not connected to the engine yet. |
| EVOLVE | the top-level folders `factory/`, `app/` | The older demo project this grew out of. It is shown inside the reviewer site under an "EVOLVE" link. |
| The tests | `lab-factory/tests/`, `lab-factory/web/e2e/`, `tests/` | Small programs that check the real programs still behave. |
| The documents | `lab-factory/docs/` | Designs ("specs"), step-by-step build instructions ("plans"), and this guide. |

## 3. How one piece of work flows through

1. A person asks for something (say, a procedure for measuring vitamin B12). That request is a **work order**.
2. An AI **agent** picks up the work order and writes a draft. The draft it hands in is a **submission**. Submissions are numbered: 1, 2, 3.
3. The engine runs its **checks** on the submission. Example: "is 550 nm inside the range this instrument can do?"
4. If every check passes, a person looks at that numbered submission and **approves** it. Approved work is **released**.
5. For analysis software there is one more safety step, the **control**, explained next.

### The control, in plain terms

Suppose the software turns an instrument reading into a concentration. How do you know the software is right? You include one sample whose true answer you already know. That sample is the **control**. You tell Lab Factory the true answer privately. The AI never sees it. If the software's answer for the control is close enough to the truth (within the **tolerance** you set), the software is trusted for the rest of that set of samples. If not, Lab Factory **withholds** the results.

A set of samples measured together, usually one spreadsheet file, is a **batch**.

## 4. Glossary

**Words about the project's history and storage**

- **Repository (repo):** the project folder, with its full history, stored on GitHub.
- **Commit:** one saved change, with a note saying what changed. Each has an ID like `10bad3f`.
- **Branch:** a separate copy of the project where work happens without disturbing the main copy.
- **Main:** the official copy. What is on main is what counts.
- **Pull request (PR):** a proposal to bring a branch's changes into main. People (and tools) review it first.
- **Merge:** accepting a pull request, so its changes become part of main.
- **Stale branch:** an old branch whose changes are already in main. Safe to delete.

**Words about programs**

- **Backend:** the part that runs on a server and does the real work. Here: the engine.
- **Frontend / UI:** the part a person sees and clicks in a browser. Here: the reviewer site and the researcher site.
- **API:** the list of requests a frontend (or any program) is allowed to send to the backend, and what comes back. Think of a restaurant menu.
- **Endpoint:** one item on that menu, for example "give me order number 5".
- **Contract:** a written agreement about what the menu will be. The researcher site was built against a contract the backend does not serve yet.
- **Deploy:** put a program on the internet so people can use it. **Vercel** is the company whose servers this project deploys to.
- **Package:** the program bundled into one file so it can be installed elsewhere.
- **Schema:** the layout of the database: which tables exist and what columns they have. A **migration** is a careful change to that layout.

**Words about AI helpers**

- **Agent / worker:** an AI program that picks up a work order and writes a submission.
- **MCP:** the standard "socket" an AI agent plugs into to talk to Lab Factory. Lab Factory gives agents four buttons only: list orders, claim one, read its background, hand in work. There is deliberately no "approve" button for agents.
- **Claim:** an agent saying "I'm working on this order". A **lease** is a claim that expires if the agent goes silent, so the order is not stuck forever. (Leases are not built yet.)

**Words about trust and safety**

- **Check:** a rule enforced by ordinary code, not by an AI's opinion.
- **Digest / hash / SHA-256:** a fingerprint of a file. Change one character and the fingerprint changes completely. Used to prove "this is exactly the file that was approved".
- **Receipt:** the saved record of one analysis run: which software, which file, which control, who approved, what came out.
- **Provenance / traceability:** being able to follow a result back to exactly what produced it.
- **Bypass:** a way around a safety rule.
- **Sandbox:** a locked room where untrusted code runs so it cannot touch anything else.
- **Pyodide:** a way to run Python inside the web browser. The researcher site uses it.
- **Security header (CSP):** an instruction a website sends to the browser, such as "this page may only talk to its own server". The browser enforces it.
- **Session / cookie / login:** how the site remembers who you are after you sign in.

**Words about making software carefully**

- **Test:** a small program that checks the real program. "340 tests pass" means 340 such checks ran and none failed.
- **CI (continuous integration):** a robot on GitHub that runs all the tests every time the code changes.
- **Regression:** something that used to work and got broken by a later change. Tests exist to catch these.
- **Spec:** a document saying *what* the software should do and why.
- **Plan:** a document saying *how* to build it, one small step at a time.
- **Test-first (TDD):** write the test that describes the right behavior, watch it fail, then write the code until it passes. That way you know the test really tests something.

## 5. Where things stand

**Working well**

- The engine's core idea is built and sound: records with history, work orders, checks, approval by a named person.
- All automatic tests pass: 340 for the engine, and the researcher site's own tests.
- The reviewer site is live and resists the most common web attack (planting hostile code in text fields).

**Not right yet**

Three problems hit the central promise ("nothing is shown as checked unless code checked it"):

1. **A draft can fake a "checked" line.** An AI's free-text note, padded with thousands of spaces, wraps on screen into what looks like a separate checked instrument setting. A reviewer could approve a setting no code checked.
2. **The control can be sidestepped.** If the original spreadsheet fails its control, saving the same spreadsheet again in a slightly different format makes the engine think it is a brand-new batch. The reviewer may then type in any control value they like, and the results come back looking normal.
3. **The researcher site's "locked room" has a gap.** Analysis code is supposed to be unable to send data out of the browser. One route out was missed, and the instruction that would close it for good is written in the documentation but not actually sent by the site.

**The larger issue**

There are now two websites built on different assumptions. The reviewer site makes people sign in; the researcher site lets people type a name. The engine checks and approves analysis software on the server; the researcher site runs analysis software in the browser with no approval. The researcher site expects 31 menu items (endpoints); the engine serves none of them as written.

Nothing is broken by this today, because the researcher site only shows sample data. But the two cannot be joined until some choices are made.

## 6. The roadmap

Five phases, in order. Each later phase depends on the ones before it.

| Phase | Name | In plain terms | Status |
|---|---|---|---|
| 1 | Make the checks trustworthy | Fix the three problems above, plus a few close relatives. Small, safe changes. | **Plan written:** `plans/2026-11-27-trust-fixes.md` |
| 2 | Decide the shape | Three choices only the owner can make (below). No code. | Waiting on you |
| 3 | Strengthen the foundations | Make the engine easier to extend: a version number for the database layout, one common mould for analysis methods (instead of three hand-built ones), claims that expire, more measurement units (grams, mg/L), basic logging and backups. | Not started; plan to be written after Phase 2 |
| 4 | Connect the researcher site to real data | Build the menu items the researcher site expects, in the order it needs them. | Not started; depends on Phase 2 |
| 5 | The rest of the original design | Automatic procedure drafting, running instruments directly, roles such as PI and student. | Not started |

### The three Phase 2 choices

1. **One website or two?** Either the researcher site replaces the reviewer site (and must learn everything the reviewer site can do), or both stay and share one address.
   *Suggested:* aim for one, the researcher site, and retire the reviewer site once nothing would be lost.
2. **Sign in, or type a name?** The original design says only a signed-in person can release work, because otherwise anyone (or any AI) could type "Dr Rivera".
   *Suggested:* sign in. The researcher site changes to match.
3. **Where does analysis software run, and is it reviewed?** In the browser with no approval (fast, private, but unchecked), or on the server after approval (the original promise).
   *Suggested:* reviewed and approved first, always. Running it in the browser afterwards is fine.

## 7. How to work with Claude on this project

- Ask "what does X mean?" at any time. The answer should be one or two plain sentences and, if useful, a pointer to the glossary above.
- Ask "where are we?" to get the roadmap table with current status.
- When a word is missing from the glossary, ask for it to be added. This guide is meant to grow.
- Each phase gets its own plan file in `lab-factory/docs/plans/`. A plan is a checklist; boxes get ticked as work is done.
