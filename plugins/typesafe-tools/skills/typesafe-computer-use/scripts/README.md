# Compact controller payload

`controller.js` is the readable source of truth. Generate the pasteable
`controller.compact.js` with:

```sh
python3 plugins/typesafe-tools/skills/typesafe-computer-use/scripts/build-controller-compact.py
```

The script uses the pinned development tool `terser@5.39.0` through `npm exec`.
It may download Terser during generation; the generated controller has no npm,
filesystem, or network dependency in `cua_repl`. The artifact records the
SHA-256 digest of its readable source. No generation or network access is needed
to run the parity tests:

```sh
python3 -m unittest tests.test_typesafe_computer_use_controller
```

That command runs all controller scenarios against both sources and rejects a
compact artifact whose source digest is stale. For an exact byte comparison after
regeneration, run the generation script with `--check`.
