# evolve

## Local EVOLVE presenter

From the repository root, run `uv sync`, then `uv run python -m factory.lab`. Open [the local presenter](http://127.0.0.1:8765). Fresh builds use the presenter's authenticated Codex CLI and require its model connection. The scientific app executes offline under macOS Seatbelt or Linux bubblewrap. EVOLVE uses local records under `runs/b12` and does not call 8090.

Submit a B12 request and inspect the task ID, actual worker receipt, source revision, generated files and independent tests. The simulated instrument implements 550 nm. Previously completed runs remain accessible on the presenter. The existing static EPR workbench is available with `npm run dev`.

Run the test suite with `uv run python -m unittest discover -s tests -v`. In an environment that forbids nested sandboxes, run the tests directly on the host so the scientific runner can apply its own restrictions.
