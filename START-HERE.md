# Start here

You are the human. This file is for you, not for Claude Code.

## 1. Get the folder onto your machine

```bash
unzip openrestore.zip
cd openrestore
git init && git add -A && git commit -m "specs"
```

Committing first matters: from here on you can `git diff` every change Claude Code makes, and revert a task that goes sideways without losing the specs.

## 2. Start Claude Code

```bash
claude
```

It reads `CLAUDE.md` automatically on startup. That file tells it the project rules, the stack, and where the specs live. You don't need to paste the specs.

## 3. Work one task at a time

The `tasks/` folder has ten numbered task files. Each is a self-contained brief with the specs to read, what to build, and how to know it's done.

For each one, in a fresh Claude Code session:

```
Read tasks/01-scaffold.md and do it.
```

That's the whole prompt. Then:

1. Read the diff. `git diff` or ask Claude Code to walk you through what it changed.
2. Run the tests it wrote. Actually run them; don't take "tests pass" on faith.
3. Commit: `git commit -am "task 01: scaffold"`
4. `/clear` and start the next task fresh.

**Do not run several tasks in one session.** Context fills with irrelevant detail from earlier tasks and quality drops. One task, one session, one commit.

## 4. Task order and what you need

| Task | Builds | Hardware needed |
|---|---|---|
| 01 | Project scaffold, tooling, CI | none |
| 02 | Light interface, curves, MockLight | none |
| 03 | Sunrise engine + tests | none |
| 04 | Scheduler (alarms, DST) | none |
| 05 | Routine engine | none |
| 06 | Audio playback | your laptop's speakers |
| 07 | REST + WebSocket API | none |
| 08 | Web UI | none |
| 09 | LIFX driver | **the bulb** |
| 10 | Packaging + deploy | **the Pi** |

Tasks 01–08 need no hardware at all. Build those on your laptop first.

## 5. When to buy things

- **After task 03.** Open `tools/sunrise-visualizer.html` in a browser and tune the curve keyframes until a ramp looks right to you. Free.
- **Before task 09.** Buy the LIFX Color A19 (~$20). Run the bulb acceptance test in `docs/02-light-driver.md` before writing driver code — it's the one purchase that can invalidate the design.
- **Before task 10.** Buy the Pi (~$40). By then you're deploying working software instead of debugging on a slow board over SSH.

## 6. If a task goes badly

Revert it (`git reset --hard HEAD`), then re-run it with a note about what went wrong appended to your prompt:

```
Read tasks/05-routine-engine.md and do it. Last attempt put the state
machine in the API layer — keep it in core/ and out of api/.
```

Fixing a bad attempt inside the same session usually costs more than starting clean.
