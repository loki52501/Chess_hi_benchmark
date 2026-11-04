# Learning fix (after games 1-3)

What was wrong after 3 games, and what changed. One commit per fix (`git log --oneline`), 129 tests passing.

## A. Pattern-based lessons (`c8749e7`)
- **features.py** has `TAGS`: named yes/no facts about the position from Claude's side, checked by code:
  `king_castled_kingside/queenside`, `king_in_center`, `my_king_attacked` (2+ enemy pieces hit squares around my king),
  `my_king_pawn_shield_weak`, `enemy_halfopen_file_to_my_king`, `pawn_storm_toward_my_king` (2+ enemy pawns advanced on
  my king's wing), `enemy_knight_near_my_king`, `enemy_piece_on_my_2nd_or_3rd_rank`, `my_queen_and_rook_knight_forkable`,
  `my_knight_fork_chance`, `my_piece_attacked_undefended`, `enemy_piece_attacked_undefended`, `my/enemy_piece_pinned`,
  `my_rook_on_enemy_bishop_diagonal`, `enemy_knight_on_rim_trapped`, `my/enemy_back_rank_weak`, `my/enemy_passed_pawn`,
  `my_passer_6th`, `enemy_passer_6th`, `queens_off`, `material_down/up`, `two_plus_open_files`, `rook_endgame`,
  `pawn_endgame`, `minor_piece_endgame`, `my_piece_retreated_recently`, `my_queen_moved_twice` (32 tags).
  `features()` also returns the numbers `open_file_count`, `my_king_attackers`, `pawn_storm`.
- Every lesson has **`features`**: 1-4 tags. learn.py lists the tags true at each item ("Tags true here") and rejects,
  then re-asks once, a lesson whose tags don't exist or aren't true at its source position.
- **rule and trigger describe the pattern**: knowledge.py rejects exact squares in a trigger, and in a rule except once
  after "e.g."; the prompt lists the relative terms to use (my king / castled side / the enemy's half-open file toward
  my king / my 2nd or 3rd rank / ...).
- **migrate_lessons.py** rewrote L001-L009 (one Claude call each, ids/stats/source/kind kept; 3 needed the one retry
  for >25 words). Before/after: `lessons_migration.md`.
- Also: `series.py` only runs as a script now (importing it started a series once during this work; it was stopped
  before writing anything).

## B. Retrieval by features (`797710b`)
- score = 3 x (lesson tags true here) + 1 if the phase matches + help rate (0..1) once cited 3+ times; ties to the newest.
- A lesson with no matching tag is never retrieved, except phase-"any" lessons as filler when fewer than 5 match.
- `claude_<i>.log` gets a `[retrieval]` block per move: tags true here, top 10 lessons with score, matched tags, PICKED.
- `tests/test_retrieval_real.py` (games 1-3 + migrated lessons as fixtures): every lesson is retrieved at its own
  source position, its tags are true there, and L004/L006 lead at the position that lost game 2.

## C. Promotion that can happen (`e5b3b5c`)
- Similar = same primary motif + Jaccard of feature tags >= 0.5, computed in code. A group of 3+ similar lessons from
  3+ games is promoted; Claude only writes the merged rule + CHECK (pattern rules, re-asked once if invalid).
- `learn_<i>.log` prints **Promotion candidates** after every game (groups of 2+, shared tags, games, READY or not).

## D. Great moves and opponent shots (`2cc60f0`)
- review.py: a recapture on the square the previous move captured on is never Great (an only legal move already
  wasn't); it stays Best. Rows have `recapture`.
- An opponent shot = a Stockfish Great move that isn't a recapture; Claude gets its own move before the shot and the one
  before that (FENs + classes) and is asked which one allowed it.

## E. Separate allowances (`24806a1`)
- `MAX_NEW = {mistake: 2, opponent_shot: 1, self_assessment: 1, good_move: 1}`; an unused slot isn't given to another kind.
- A new lesson sharing 50%+ of its tags with an active lesson updates that lesson instead (id, stats, source kept).

## F. The "retire L007" (`2ddb00f`)
- Not a parsing or saving bug: `"retire": ["L007"]` in learn_1-3.log is in the **request**, the example JSON at the end of
  the lessons prompt (it also said `"update": [{"id": "L003"...}]`). Claude's replies all had `"retire": []`, so nothing was
  retired. The danger was real, though: once L003/L007 existed Claude could copy the example. The example now uses `Lxxx`
  and `"retire": []`. Tests: a reply retiring one id leaves it `retired` in lessons.jsonl and lessons_after_game_<i>.jsonl
  after retirement/promotion/demotion ran; the example contains no real id.

## Before / after

**Great moves (games 1-3, recapture fix).** Before: 10 Greats, 5 of them recaptures on the square just captured on
(19.Rxd5, 45...Nxe2 in game 1; 7...cxd4, 19.Qxc4, 29...Qxa6 in game 3). After, game 1 (re-reviewed): Claude 1 -> 0,
Stockfish 4 -> 3 (21...c5, 23...Nd5, 24...Nxe3 kept; 45...Nxe2 gone). Games 2-3: see G.

**Retrieval at Claude's 13 mistake moves in games 1-3** (before = old retrieval + old lessons; after = tags + migrated lessons):

| | before | after |
|---|---|---|
| different lesson sets retrieved | 2 | 10 |
| same 5 lessons at 12 of 13 moves | yes (L001, L005, L006, L007, L008) | no |
| L004/L006 (queenside king, lost game 2) | L004 never; L006 everywhere | both, at all 5 game-2 mistakes only |
| L002 at 43.Kh1 (where it came from) | no | yes |

**Rules:** still the 11 seed rules; with tag-based similarity a promotion needs 3 similar lessons from 3 games.

## G. Re-learning games 1-3
Backups in `games/backup_before_fix/` (lessons.jsonl, rules.md, rules_stats.json, stats_counted_games.json from before
the migration; lessons_migrated.jsonl; the old review_1-3, learn_1-3 and *_after_game_1-3 files).
The re-run (`learn.learn_from_game(1)`, `(2)`, `(3)` in order) was stopped by Claude Code for low memory during game 1's
learning call: game 1 was re-reviewed, nothing else changed (lessons.jsonl is still the migrated version, game files
unchanged). **Pending: re-run.**

## Resume the series
Pending step G.
