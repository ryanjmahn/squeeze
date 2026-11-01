# Using Squeeze

| Command | What it does |
|---|---|
| `sq pytest -x` | Run a command and squeeze its output. Arguments pass straight through. |
| `sq -s "cd api && pytest"` | Run a shell string, for pipes and `&&`. |
| `sq --raw pytest` | Show the normal output live. The log is still saved. |
| `sq init` | Print the `CLAUDE.md` snippet. |
| `sq stats` | Your tokens saved. Also `--month`, `--all`, `--repo`, `--reset`. |
| `sq card` | Make a shareable HTML and SVG card. Also `--month`, `--all`. |

Flags for `sq` go before the command, so `sq pytest --raw` passes `--raw` to pytest. To run a real program called `init`, `stats` or `card`, use `sq -- init`. When a command's output is so short that squeezing wouldn't save anything, `sq` prints it with a one-line header and skips the stats and log path. The log is still saved. Set `SQUEEZE_KEEP_LOGS` to keep more or fewer than 50 logs.

## Stats

Squeezing should feel like logging a workout. This example uses made-up numbers:

```
🍋 SQUEEZE · this week                       Oct 26 – Nov 1

   463k tokens saved         ▲ 27% vs last week
   57 commands squeezed      🔥 9-day streak
   ≈ 2.3 context windows · ≈ 3.9 novels' worth of log spam you didn't read

   Mon ▇▇▇▇▇▇▇▇▇▇▇   87k
   Tue ▇▇▇▇          30k
   Wed ▇▇▇▇▇▇▇       54k
   Thu ▇▇▇▇▇▇▇▇▇▇▇▇  93k
   Fri ▇▇▇▇▇▇▇▇▇▇    78k
   Sat ▇▇▇▇▇▇▇▇▇▇▇   85k
   Sun ▇▇▇▇          35k
```

Comparisons use the same point in the last period, so a Wednesday is compared with Monday to Wednesday of last week. A run that sets a personal record or unlocks a badge prints one extra line about it.

## Privacy

`~/.squeeze/history.jsonl` stores command names, the repo's folder name, and numbers. It never stores arguments or output.

The saved logs do hold full command output, including any secrets a command prints, so they stay in the gitignored `.squeeze/` folder. `sq card` leaves repo names off, but the card does name the command behind your biggest squeeze.
