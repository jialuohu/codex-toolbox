# Synthetic FIFO explanation acceptance fixture

This fixture illustrates first-in, first-out (FIFO) scheduling on one server.
It is a small mathematical model, not a measured production workload. Jobs are
already ordered by arrival time; equal arrivals retain input order. Service is
non-preemptive: a job runs to completion once it starts. Arrival and service
times are nonnegative seconds; zero service and an empty queue are valid.

For job i, let a_i be its arrival time, s_i its service duration, and f_(i-1)
the previous finish time (initially zero). The independently checked contract is:

    start_i = max(a_i, f_(i-1))
    finish_i = start_i + s_i
    wait_i = start_i - a_i

`queue-model.mjs` implements this contract. `cases.json` supplies ordinary,
idle-server, equal-arrival/zero-service, fractional, and empty examples.
`queue.svg` is the static presentation of the ordinary case: job A occupies
0–3 seconds, job B waits from its arrival at 1 until time 3, then occupies
3–5 seconds. The diagram's dependency arrow connects A's finish to B's start.

The evaluator runs the actual JavaScript and checks its outputs against
independent Python calculations, then checks SVG labels, mark coordinates,
canvas bounds, and the dependency against that source trace. Mutation tests
exercise incorrect results, labels, geometry, and dependency direction.

This is objective fixture verification only. The Python evaluator does not launch
a browser, operate an HTML control, inspect pixels, render a video, validate
arbitrary user artifacts, or measure learning effectiveness.

`queue.html` adds one arrival-time control and reset button using the same model.
The optional `tests/explanation-browser-evidence.mjs` harness uses the already
installed, pinned Archify test browser helper and Chrome. It performs keyboard
input and reset checks, checks ordinary and idle-server results, and captures
320/736-pixel light/dark layouts with reduced motion. It closes its owned browser
and loopback server in `finally`. It never installs a runtime or publishes.

From the repository root, save the read-only `archify runtime-info --json` receipt
outside the repository, then run:

```sh
node plugins/diagram-tools/tests/explanation-browser-evidence.mjs \
  /absolute/task-output/runtime-info.json /absolute/task-output/new-browser-evidence
```

The evidence directory must not exist. The browser receipt marks visual review
pending until someone inspects the saved screenshots; learning effectiveness
remains unverified. Missing Chrome or a different helper runtime fails instead
of silently claiming browser coverage. These synthetic fixtures do not verify
the external Visualize or Remotion integration.
