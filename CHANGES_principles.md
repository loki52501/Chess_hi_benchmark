# Principles mode (learning from all games, in XML)

`match.LEARN_MODE = "principles"` is now the default (`LEARN_MODE=lessons python series.py` gives the old behaviour back).

## What happens after every game
1. **evidence.py** (code only, no Claude) reads every reviewed game and writes `games/evidence_after_game_<i>.xml`:
   - `<winner_vs_loser>`: all moves of the side that won against all moves of the side that lost, by kind of move
     (capture, check, threat, quiet, retreat, pawn push, ...) and by situation (ahead / level / behind).
   - `<why_claude_lost>`: Claude's moves that lost 5+ win%, grouped by cause (missed forcing move, punished at once,
     retreat, greedy capture, too passive, weakening pawn push, ...), with how many games each cause appears in.
   - `<weak_positions>`: position features where Claude loses more than its average.
   - `<turning_points>` E1..E14 (Claude's costliest moves, at most 3 per game) and `<winner_moves>` W1..W6.
2. **learn.learn_principles** sends that XML to Claude and gets the whole list back as XML: at most 12 principles, each
   `<when>` / `<do>` / `<check>`, in order of priority. Code rejects a principle that names exact squares, names no piece,
   is too long, or whose evidence comes from fewer than 2 different games (asked again once).
3. **Test before adopting**: the new list and the current list each choose a move in 12 positions from earlier games
   (8 of Claude's costliest moves, 4 hard positions it got right). Stockfish scores the moves. The new list replaces
   `games/principles.xml` only if it loses less win%. Results: `games/principles_history.jsonl`; answers are cached in
   `games/validation_cache.json`, so the current list is not asked again.

During a game the move prompt is XML too (`<task>`, `<position>`, `<principles>`, `<endgame>`, `<my_recent_assessments>`,
`<answer_format>`), and no position-specific lessons are shown.

## Commands
- `python learn.py evidence`  print the evidence for the games in `games/`
- `python learn.py distill`   learn principles now from the games already played (about 25 Claude calls the first time)
- `python series.py`          play -> learn -> play, as before
- Cloud: `bash cloud_setup.sh` (Stockfish path now comes from `STOCKFISH` or the PATH)

## Limits
- This changes what Claude is told, not the model: the "reward" is Stockfish's score of the moves.
- The test uses 12 positions and Claude's answers vary, so a small difference can be luck. `VALIDATE_BAD` / `VALIDATE_GOOD`
  in learn.py make it bigger (and slower).
- The 8 "went wrong" test positions are among the turning points the principles were written from; the 4 "got right" ones
  guard against breaking good play. The real test is the next games.
- Not run end to end here: no Stockfish or logged-in Claude CLI was available. Covered by tests with scripted answers.
