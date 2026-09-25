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

## The animation in the README

`docs/demo.gif` is built from screenshots with `tools/make-gif.py`, which joins
PNG frames into an animated GIF using only the standard library - no ffmpeg, no
ImageMagick, no Pillow. A GIF rather than an animated PNG because plenty of
locked down machines will not animate the latter, and those machines are the
audience.

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
