# CHANGES

The harness now reviews every game the way chess.com does, learns two layers of knowledge from that review
(general rules + specific lessons), retrieves only the lessons that fit the position, asks Claude for a
forcing move structure with its own evaluation, and can run A/B experiments.

**Hard rule kept throughout:** during play the engine never chooses, suggests or evaluates Claude's moves, and no
engine output reaches Claude mid-game. Stockfish is used only by `review.py` after the game (and by `learn.py`,
which calls it). Stockfish's skill (10) and time per move (0.1 s) are unchanged.

## Removed (from the earlier versions of the spec)

- **Engine drift alarm:** never built. There is no `DRIFT_PCT`, no engine eval during play, no drift prompt line.
  Step 5 (self-assessment) replaces it: Claude only sees its *own* earlier EVAL/TREND/WHY lines.
- `seed_lessons.jsonl` (12 tagged lessons with `retrieved/helped` but no trigger/check): replaced by
  `seeds/rules.md` (the same rules rewritten into the new rule format) and an empty `lessons.jsonl`.
- The single global `rules.md` that `learn.py` rewrote after every game: still available as
  `LEARN_MODE = "rules"` (used by the experiment's baseline), no longer the default.
- `learn.review_moves()` with its own depth-14 / 100 cp check: replaced by `review.py`.
- The `lessons_used` argument of `review.review_game()`: replaced by `games/moves_<i>.jsonl`.

## Per step (one git commit each; `git log --oneline`)

The folder was not a git repository, so I ran `git init` and added a `.gitignore` that leaves out `lichess-tauri/`
(it has its own repo), `archive/`, the game data folders (`games/`, `games_*/`) and `experiments/`.

| commit | step |
|---|---|
| Baseline | the code as it was |
| Step 1 / 1b / 1c | `review.py`: per-move classifier, annotated PGN, per-move list, Great/Miss pairs, `multipv_gap` |
| Step 2 | `knowledge.py`: rules.md (new format) + lessons.jsonl, validation, seeds, `migrate.py` |
| Step 3 | `learn.py` rewritten around the review: sections, add/update/retire, promotion, demotion, retirement |
| Step 4 | `features.py` + `prompts.py`: retrieval, the full prompt, endgame block + refs, `CLAUDE_EFFORT_ENDGAME` |
| Step 5 | self-assessment: own last 5 EVAL lines in the prompt, calibration and missed slides in the review |
| Step 6 | `CLAUDE_COLOR`, `parallel.run_games`, `experiment.py` |

### Step 1: `review.py`
- Every move of both sides is classified: Book, Great, Best, Excellent, Good, Inaccuracy, Mistake, Miss, Blunder.
  win% from the mover's side, mate = ±10000 cp, the class boundaries, accuracy formula and phases as specified.
- Depth 18, MultiPV 2, one engine per game. Each position is analysed **once**: the position after move n is the
  position before move n+1, so one analysis gives both evals (same numbers, half the time, ~3 min per game).
- **Book:** a tiny built-in list of 20 main lines; a move in the first 8 plies is Book if the game so far is the
  start of one of them.
- **Choices where the spec left room:** a move that is the engine's top move gets loss 0 (so it is Best/Great and
  accuracy 100); Miss is checked right after Best/Great, so a missed win is a Miss even if the win% lost would make it
  a Blunder; Great needs a second legal move (an only legal move is Best).
- Outputs `review_<i>.jsonl`, `review_<i>.json`, `game_<i>_annotated.pgn` (NAGs `$3 $1 $6 $2 $4` + comments like
  `{Mistake, -12.4%, best was Kd5}`; standard PGN that python-chess reads back), and prints the table, the per-move
  list (`!! ? ?? MISS` marked), Stockfish's Great moves paired with Claude's move before, Claude's Misses paired with
  the Stockfish move that allowed them, and (step 5) calibration.
- Note: the accuracy formula averaged per move gives higher numbers than chess.com's (e.g. 94 vs 97 instead of
  80 vs 87); the gap between the sides is what to compare.

### Step 2: two layers of knowledge (`knowledge.py`)
- `rules.md`: at most 12 lines `- [R01] <rule, <= 25 words> | CHECK: <yes/no question>`; `rules_stats.json` per rule.
- `lessons.jsonl`: one lesson per line with exactly the fields of the spec (id, rule, trigger, check, phase, motifs,
  source, kind, created_game, retrieved, helped, status [+ promoted_to]).
- Validation (`knowledge.problems_with`): missing field, motif or phase not on the list, rule over 25 words,
  no piece/pawn/square/file/king in the rule.
- `seeds/rules.md`: the 12 rules from the old `games/rules.md`, rewritten by hand into the new format with overlaps
  merged (old 1 + 5 -> R01, 11 rules in total). `seeds/rules_legacy.md`: the old list (for `LEARN_MODE="rules"`).
- `migrate.py` (one-time): backs up the old `rules.md` as `rules_legacy.md`, writes the new-format rules, an empty
  `lessons.jsonl` and `rules_stats.json`. It was run on the old `games/` (now archived, see the end). A new games
  folder is seeded automatically.

### Step 3: `learn.py`
- `learn_from_game(i)`, `learn_<i>.log` and `rules_after_game_<i>.md` are kept (plus `lessons_after_game_<i>.jsonl`).
  It no longer rewrites `rules.md` after every game.
- Prompt sections: ACCURACY (per phase + class counts, both sides), MISTAKES `[M1..]` (max 10, worst first: FEN, phase,
  move, best + PV, win% lost, Claude's own WHY), GOOD MOVES `[G1..]` (Great/Best with `multipv_gap >= 10`, max 3),
  OPPONENT SHOTS `[S1..]` (Stockfish Great moves, max 3, with Claude's previous move and FEN), MISSED SLIDES `[D1..]`,
  the rules with stats, the active lessons for the phases involved, and the "what makes a good lesson" text verbatim.
- Claude answers `{"add": [...], "update": [{"id": ...}], "retire": [...]}` between `<lessons>` tags. Each new lesson
  names the item it came from (`"source": "M2"`), so the code fills in `source` (game, move, FEN, played, best, loss,
  class) and `kind` (M = mistake, G = good_move, S = opponent_shot, D = self_assessment). Invalid answers are re-asked
  once, then only the valid entries are kept. At most 3 new lessons per game.
- In code after each game: citation stats, **retirement** (cited 10+ times, help rate below Claude's overall
  Good-or-better rate), **promotion** (3+ active lessons from 3+ games with the same first motif + phase; Claude confirms
  and words the rule; if rules.md is full the rule with the lowest help rate among those cited 10+ times is replaced;
  a declined group is remembered in `promotions_declined.json` so it isn't asked again), **demotion** (a rule cited in
  10+ games below the baseline becomes a lesson with a trigger Claude writes, or is dropped). Every one is logged.
- Additions not in the spec: a demoted rule becomes a lesson with `kind: "demoted_rule"` (none of the four kinds fits);
  a lesson from a missed slide must carry the motif `self_assessment` or `prophylaxis`.

### Step 4: retrieval and the new move prompt
- `features.py` (pure python-chess): phase, passed pawns with ranks, king in the center, hanging pieces, open and
  half-open files, pins, back rank, knight forks, material signature (`R+3P vs 3P`) -> a set of motifs.
- Retrieval: top `LESSONS_PER_MOVE = 5` active lessons by phase match, motif overlap, help rate (with a 50% prior so a
  new lesson isn't last), newest first on ties. **Lessons for a different phase are left out**, not just ranked lower.
- `prompts.py`, `PROTOCOL = "full"` (default) or `"basic"` (the old prompt, for A/B tests). Full prompt order:
  opponent line (no "most strongest... expecting the worst"), position, ALWAYS (rules with CHECK), FOR THIS POSITION
  (feature header + `[id] When: <trigger>. Check: <check>`), ENDGAME block + 1-2 closest reference positions, own
  assessments (step 5), then THREATS / FORCING / CANDIDATES / PLAN / EVAL / MOVE.
- MOVE parsing and retries unchanged. PLAN ids (only ids that were actually shown) and EVAL/TREND/WHY are parsed;
  missing or malformed -> `None`, never a retry. `CLAUDE_EFFORT_ENDGAME = "high"` once the position is an endgame.
- **`endgame_refs.jsonl` is in the repo root, not `games/`:** `games/` is per-run data (not in git) and every
  experiment config has its own folder, so a copy in `games/` would be missing everywhere else. 10 positions
  (Lucena, Philidor, opposition / key squares, the square, outside passer, rook behind passer, wrong-colored bishop,
  pawn race, don't trade into a lost pawn ending, queen vs pawn on the 7th). Every FEN is checked with python-chess,
  and every claim was checked with Stockfish (one bad position, where the "trade" was really mate, was replaced).
- Per Claude move: a `[move info]` line in `claude_<i>.log` and a line in `moves_<i>.jsonl` (retrieved, cited,
  self_eval, trend, why, effort, attempts, seconds, tokens, cost). `review.py` copies these onto Claude's moves.
- Stats: for each rule/lesson **cited** on a move, retrieved +1 and helped +1 if the move was Good or better (as
  specified). Lessons that were shown but not cited are not counted.

### Step 5: self-assessment
- The full prompt shows "Your own assessments from your last moves" (move number, EVAL, TREND, WHY of the last 5 of
  Claude's own answers) and the instruction to say so in PLAN if they have been sliding. Never engine output.
- `review_<i>.json` -> `calibration`: `moves_with_eval`, `mae` (pawns, both clipped to ±5, engine eval after the move),
  `correlation` (Pearson), `missed_slides` (engine win% fell 8+ over 5 Claude moves while every TREND said same/better;
  overlapping windows merged; move range, win% drop, trends, WHY lines, FEN at start and end, best line at the start).
- learn.py sends them as `[D1..]` items.

### Step 6: colors and experiments
- `CLAUDE_COLOR` in match.py drives whose turn it is, forfeits, PGN headers and the header line; `outcome()` counts
  win/draw/loss from Claude's side (series/parallel summaries); gui.py flips the board when Claude is Black.
- `parallel.run_games(numbers, parallel, overrides, colors)`: settings and color are applied inside each worker
  process (they start from the defaults); learning stays sequential in the main process.
- `experiment.py`: `baseline` (basic prompt, old-style rules, no lessons, no endgame block, no self-assessment),
  `review` (+ new learn.py), `protocol` (+ full prompt with retrieval and self-assessment), `full` (+ endgame block,
  refs, `CLAUDE_EFFORT_ENDGAME`). Folders `games_<config>/` (the "+" was left out of the names), alternating colors.

## How to run

```
cd F:\chess_comp
python match.py                     # one game in games/ with the defaults (= the full config), then learning
python gui.py                       # the same, on a board
python review.py 3                  # (re-)review game 3: table, per-move list, pairs, calibration
python review.py 1 --dir games_full # a game in another folder
python series.py                    # 50 games one after another, learning after each (TOTAL_GAMES at the top);
                                    # stop with Ctrl+C any time, run it again to continue (games/series_checkpoint.json)
python parallel.py                  # 50 games, PARALLEL at a time, learning after each as it finishes
python experiment.py                # all 4 configs, 10 games each, 2 at a time
python experiment.py full baseline --games 6 --parallel 2
python experiment.py --summary      # rebuild experiments/summary.csv + summary.md from the folders
python migrate.py games             # one-time migration of an old-style rules.md in a folder
python -m pytest tests -p no:asyncio   # 77 tests
```

Settings are module constants at the top of `match.py` (model, effort, `CLAUDE_COLOR`, `PROTOCOL`, `LEARN_MODE`,
`LESSONS_PER_MOVE`, `ENDGAME_MODE`, `SELF_ASSESSMENT`, ...), `review.py` (`REVIEW_DEPTH`, `SLIDE_*`), `learn.py`
(limits and thresholds) and `experiment.py` (`GAMES_PER_CONFIG`, `PARALLEL`).

## Files and formats (in a games folder)

| file | written by | format |
|---|---|---|
| `game_<i>.pgn`, `game_<i>.log` | match.py | PGN; one line per move |
| `claude_<i>.log` | match.py | every prompt and answer, `[move info]` line per Claude move |
| `moves_<i>.jsonl` | match.py | per Claude move: ply, san, phase, effort, attempts, retrieved, cited, self_eval, trend, why, seconds, tokens_in, tokens_out, cost |
| `review_<i>.jsonl` | review.py | per move: ply, side, player, fen_before, san, best_san, best_pv_san, cp_before, cp_after, win_before, win_after, loss, cls, phase, multipv_gap (+ self_eval, trend, why, retrieved, cited for Claude) |
| `review_<i>.json` | review.py | per side: player, moves, accuracy, accuracy_by_phase, moves_by_phase, counts; calibration |
| `game_<i>_annotated.pgn` | review.py | PGN with NAGs + comments |
| `learn_<i>.log` | learn.py | the learning prompts and answers, every promotion/demotion/retirement |
| `rules.md`, `rules_stats.json` | knowledge.py / learn.py | `- [Rnn] rule | CHECK: question`; {id: retrieved, helped, created_game, cited_games} |
| `lessons.jsonl` | learn.py | one lesson per line (step 2 fields) |
| `rules_after_game_<i>.md`, `lessons_after_game_<i>.jsonl` | learn.py | history copies |
| `rules_legacy.md` | migrate.py | backup of the old list |
| `promotions_declined.json` | learn.py | lesson groups Claude said were not one idea |
| `series_checkpoint.json` | series.py | first game, total, and per game: result, learned |
| `stats_counted_games.json` | learn.py | games whose citations are already in the stats (so a re-run doesn't count twice) |

Repo files: `seeds/rules.md`, `seeds/rules_legacy.md`, `endgame_refs.jsonl`; experiment output in `experiments/`.

## Skipped or worth knowing

- The full experiment (4 configs x 10 games = ~40 games, each ~40+ Claude calls plus learning) was **not run**; it costs
  a lot of usage. It was tested end to end with a stand-in for Claude, and one real game was played with the full
  config. Start small, e.g. `python experiment.py baseline full --games 4 --parallel 2`.
- Within one config, games that run in parallel don't see each other's new lessons (learning is sequential, but a game
  that has already started keeps the knowledge it started with).
- Games 1-10 (the old `games/` folder, already migrated and with games 1-9 reviewed) were moved to
  `archive/run_2026-11-03_2336/games/`. Their `review_<i>.json` files were made before steps 4-5, so they have no
  `calibration` (those games have no EVAL lines anyway); to refresh one:
  `python review.py 3 --dir archive/run_2026-11-03_2336/games`. Game 10 is a partial game (Result `*`): the old series
  was stopped during it. A new `games/` starts from `seeds/rules.md` and an empty `lessons.jsonl`.
- Old games played with the "basic" prompt have no PLAN ids, so they add nothing to the citation stats.
