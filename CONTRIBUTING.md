# Contributing to snapgrid

Thanks for your interest in the project.

Writing a plugin rather than changing snapgrid itself? [AGENTS.md](AGENTS.md)
is the plugin specification, written to be handed to an AI assistant but equally
usable by a person.

## Reporting bugs and ideas

Open an issue. For a bug, please include:

- what you did and what you expected
- the `plugin.toml` involved, with any secrets removed
- the output of running your plugin directly in a terminal
- your Python version and operating system

## Pull requests

snapgrid has no dependencies outside the Python standard library, and that is a
deliberate design constraint rather than an accident. It has to run in locked
down environments where nothing can be installed. Pull requests that add a
third party dependency will not be merged.

Please keep changes small and focused, and open an issue first for anything
larger than a bug fix.

**Update the README in the same pull request.** Anything that changes how
snapgrid behaves or is configured - a new setting, a renamed option, a different
default, a new command - belongs in the README as part of the change, not
afterwards. Where a setting accepts a fixed set of values, list all of them and
what each one means. A README that trails the code is worse than no README,
because people trust it.

## The pictures in the README

Every screenshot, beside each example and in `docs/`, plus `docs/diff.gif`, is
rebuilt in one go:

```bash
./server.py start --dir examples
./tools/make-screenshots.py
```

It drives headless Chrome against the running server, one shot per state, and
joins the animation's frames with `tools/make-gif.py` - which makes a GIF out
of PNGs using only the standard library, no ffmpeg, no ImageMagick, no Pillow.
A GIF rather than an animated PNG because plenty of locked down machines will
not animate the latter, and those machines are the audience.

Chrome is the one thing in this repository that has to be installed, and only
to rebuild the pictures. It is a maintainer's tool: the results are committed,
so nobody reading or running snapgrid needs it.

**Redo them whenever the interface changes**, in the same change. A picture of
something the program no longer does is worse than no picture, for the same
reason a README that trails the code is.

`docs/demo.gif` is the exception: its frames are a column being sorted, a
filter opened, a search typed - states the address bar cannot name, so it is
still recaptured by hand.

## Tests

```bash
./run-tests.py
```

Please run them before opening a pull request, and add tests for what you
change. They use only the standard library, like the rest of the project.

## Contributor terms

By submitting a contribution you confirm that you are the author of it, that
you have the right to submit it, and that it is contributed under the Apache
License 2.0, like the rest of the project.

## The browser tests

`web/compare.js` decides what changed between two runs, and a wrong answer
there is worse than an error - "nothing changed" is a claim. It is kept free
of the page and of shared state so it can be tested directly:

```bash
node --test tests/compare.test.js
```

`./run-tests.py` runs them too. node's test runner is part of node, so there
is nothing to install, no `package.json`, and `tools/check-imports.py` fails
the build if any JavaScript ever starts requiring something that is not
node's own or a file beside it.

**node is a development tool here, like git.** Nothing about running snapgrid
needs it: the browser executes that file, as it always did.

## Versions and releases

The version lives in **one place**, `snapgrid/__init__.py`, and `./server.py
--version` prints it. There is no packaging metadata to keep in step, because
there is nothing to install.

Numbering is ordinary semantic versioning, read from the point of view of
somebody who has written plugins:

- **patch** - a fix that changes nothing about how a plugin is written;
- **minor** - a new `plugin.toml` key, or something new in the page. Existing
  plugins keep working;
- **major** - a plugin that worked before would have to be changed.

To cut a release:

1. Move the **Unreleased** entries in `CHANGELOG.md` under the new number.
2. Update `__version__`.
3. Commit, tag `vX.Y.Z`, push the tag.
4. Write the GitHub release from the changelog entry.

That is the whole process, and it should stay that small. A project that
nothing depends on does not need a release train.
