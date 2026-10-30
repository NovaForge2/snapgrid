# Pods per service

Invented data in the awkward shape: **one line per pod**, so a service being
replaced has two of them. It exists to show what snapgrid does when no column
names a row on its own, and nothing is contacted.

## See it

```bash
./server.py --dir examples
```

Press **Run now** a few times, a minute apart, then set the second dropdown to
**Compare: last 2 runs**. The services that were redeployed show the new image
in the cell, with the one it replaced beneath it.

## Why this shape is awkward

A cluster lists pods, not services. While one is being replaced there are two
lines for the same service, and **neither the pod name nor the image can name a
row**: the pod name is new on every deployment, and the image is the thing that
changed. Name the row by what is still the same tomorrow:

```toml
[table]
key = ["Environment", "Service"]
```

The two pods share that name, so they are merged into the row they name, and
the cells where they differ hold both values - a line each:

```
Environment  Service       Pod                Status   Image
SIT2         payments-api  payments-api-1a3   Running  2.14.1
                           payments-api-9f2   Running  2.15.1
```

Comparing marks the lines where they are: a value that arrived is marked on its
left edge, one that went is kept on screen and struck through. The count under
the toolbar reads `42 rows - 55 lines printed`, so a key that merges more than
expected is visible rather than silent.

## What else is worth reading it for

- **`[compare] ignore` on the age of a pod.** It is counted from the clock, so
  it is different on every single run. Left in the comparison, every row would
  read as changed every run and `[history] keep = 20` would fill with readings
  of one table. Named there, it is still shown, sorted and exported - it is
  only out of the question "did this change?", and out of "is this a new
  result?" with it.
- **A colour on two columns and no more.** `Status` is coloured only where
  something is wrong, because a green pill on every row of a healthy cluster
  says nothing. `Restarts` goes amber above zero and red above ten.
- **An empty value where nothing is known.** A line that does not know its
  branch leaves the field empty, and an empty value is not written as a line of
  its own in a merged cell.

## Making it move

The data drifts on a clock, the same way `version-matrix` does: two runs inside
the same minute print the same table and do not spend a history slot, while a
run later on has moved something. `DEV` and `SIT` are redeployed constantly,
`PROD` almost never - `STABILITY` in `main.py` says how often each one moves.
