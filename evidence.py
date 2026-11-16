"""Cross-game evidence for learn.py's "principles" mode: what the winners did and why the losers lost.
Everything here is computed in code from review_<i>.jsonl + game_<i>.pgn (no Claude call); report() returns it as XML."""
import chess, chess.pgn, glob, json, os, re
from xml.sax.saxutils import escape, quoteattr
import features

BAD_LOSS = 5.0            # a move that lost this much win% (Inaccuracy or worse) is a "bad move"
AHEAD, BEHIND = 65, 35    # win% before the move: ahead / behind / level in between
MAX_TURNING_POINTS = 14   # Claude's costliest moves over all games ...
TURNING_PER_GAME = 3      # ... at most this many from one game, so one bad game doesn't decide everything
MAX_WINNER_MOVES = 6      # the winners' hardest-to-find moves ...
WINNER_PER_GAME = 2
MIN_TAG_POSITIONS = 5     # a position feature counts as a weakness only with this many positions from 2+ games
MAX_WEAK_FEATURES = 8
VALUES = features.VALUES
TRAITS = {   # what kind of move it is, checked in code for the played move and for the engine's best move
    "capture": "takes something", "trade": "takes a piece of the same value as the capturing piece",
    "check": "gives check", "threat": "the moved piece now attacks an undefended or more valuable enemy piece",
    "quiet": "no capture, check or threat", "pawn_push": "pawn move that is not a capture", "castle": "castles",
    "king_move": "king move (not castling)", "queen_move": "queen move",
    "advance": "piece moves toward the enemy side without capturing", "retreat": "piece moves back toward its own side without capturing",
    "leaves_piece_loose": "after the move a knight, bishop, rook or queen of the mover is newly attacked and undefended, or attacked by a cheaper piece"}
CAUSES = {   # why a bad move was bad, from comparing it with the engine's best move and the opponent's reply
    "missed_forcing_move": "the best move was a capture or check; the move played was neither",
    "too_passive": "a quiet move was played where the best move made a threat",
    "left_piece_loose": "the move left a piece undefended or attackable by a cheaper piece",
    "punished_at_once": "the opponent's reply was a capture or check and the engine's best move",
    "greedy_capture": "a capture was played where the best move was not a capture",
    "weakening_pawn_push": "a pawn was pushed where the best move was not a pawn push",
    "bad_king_move": "the king was moved where the best move was not a king move",
    "trade_when_not_ahead": "pieces were traded while level or behind, where the best move kept them",
    "retreat": "a piece was pulled back where the best move was not a retreat",
    "other": "none of the above: a quiet positional choice"}

def boards(game):   # ply -> the board before that move, with the move history (some tags look at recent moves)
    board, found = game.board(), {}
    for ply, move in enumerate(game.mainline_moves(), 1):
        found[ply] = board.copy()
        board.push(move)
    return found

def loose(board, color):   # squares of color's N/B/R/Q that are attacked and undefended, or attacked by a cheaper piece
    found = set()
    for square, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type in (chess.PAWN, chess.KING):
            continue
        attackers = board.attackers(not color, square)
        if attackers and (not board.is_attacked_by(color, square)
                          or min(VALUES[board.piece_type_at(a)] for a in attackers) < VALUES[piece.piece_type]):
            found.add(square)
    return found

def traits(board, move):   # the TRAITS of this move, as a sorted list
    me, found = board.turn, set()
    piece = board.piece_type_at(move.from_square)
    capture, castle = board.is_capture(move), board.is_castling(move)
    if capture:
        victim = board.piece_type_at(move.to_square) or chess.PAWN   # en passant: the target square is empty
        found.add("capture")
        if piece != chess.PAWN and VALUES[victim] == VALUES[piece]:
            found.add("trade")
    if board.gives_check(move):
        found.add("check")
    if castle:
        found.add("castle")
    if piece == chess.PAWN and not capture:
        found.add("pawn_push")
    if piece == chess.KING and not castle:
        found.add("king_move")
    if piece == chess.QUEEN:
        found.add("queen_move")
    if piece not in (chess.PAWN, chess.KING) and not capture:
        forward = features.relative_rank(move.to_square, me) - features.relative_rank(move.from_square, me)
        if forward:
            found.add("advance" if forward > 0 else "retreat")
    after = board.copy(stack=False)
    after.push(move)
    mover = after.piece_type_at(move.to_square)
    for square in after.attacks(move.to_square):
        target = after.piece_at(square)
        if target and target.color != me and target.piece_type != chess.KING and (
                VALUES[target.piece_type] > VALUES[mover] or not after.is_attacked_by(not me, square)):
            found.add("threat")
    if loose(after, me) - loose(board, me) - {move.from_square}:
        found.add("leaves_piece_loose")
    if not found & {"capture", "check", "threat"}:
        found.add("quiet")
    return sorted(found)

def causes(row, reply):   # the CAUSES of a bad move; reply = the opponent's next move (a row) or None
    played, best, found = set(row["traits"]), set(row["best_traits"]), []
    forcing = {"capture", "check"}
    if best & forcing and not played & forcing:
        found.append("missed_forcing_move")
    if "quiet" in played and "threat" in best and not best & forcing:
        found.append("too_passive")
    if "leaves_piece_loose" in played:
        found.append("left_piece_loose")
    if reply and set(reply["traits"]) & forcing and reply["cls"] in ("Best", "Great"):
        found.append("punished_at_once")
    if "capture" in played and "capture" not in best:
        found.append("greedy_capture")
    if "pawn_push" in played and "pawn_push" not in best:
        found.append("weakening_pawn_push")
    if "king_move" in played and "king_move" not in best:
        found.append("bad_king_move")
    if "trade" in played and "trade" not in best and row["win_before"] < AHEAD:
        found.append("trade_when_not_ahead")
    if "retreat" in played and "retreat" not in best:
        found.append("retreat")
    return found or ["other"]

def load_games(folder):
    """Every finished, reviewed game in the folder: dict(game, result, winner, claude_side, outcome, rows, boards).
    Each row (one per move, both sides) gets: game, role (winner/loser/drawn), traits, best_traits, tags, causes."""
    games = []
    paths = glob.glob(os.path.join(folder, "review_*.jsonl"))
    for path in sorted(paths, key=lambda p: int(re.search(r"review_(\d+)\.jsonl$", p).group(1))):
        i = int(re.search(r"review_(\d+)\.jsonl$", path).group(1))
        pgn = os.path.join(folder, f"game_{i}.pgn")
        if not os.path.exists(pgn):
            continue
        game = chess.pgn.read_game(open(pgn, encoding="utf-8"))
        result = game.headers.get("Result")
        rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        before = boards(game)
        if result not in ("1-0", "0-1", "1/2-1/2") or len(rows) != len(before) or not rows:
            continue   # unfinished, or the review is of an older version of the game
        winner = {"1-0": "white", "0-1": "black"}.get(result)
        claude_side = next((r["side"] for r in rows if r["player"] == "Claude"), "white")
        for r in rows:
            board = before[r["ply"]]
            r["game"] = i
            r["role"] = "drawn" if winner is None else "winner" if r["side"] == winner else "loser"
            r["traits"] = traits(board, board.parse_san(r["san"]))
            r["best_traits"] = traits(board, board.parse_san(r["best_san"]))
            r["tags"] = features.tags(board, board.turn)
        for k, r in enumerate(rows):
            r["causes"] = causes(r, rows[k + 1] if k + 1 < len(rows) else None) if r["loss"] >= BAD_LOSS else []
        games.append(dict(game=i, result=result, winner=winner, claude_side=claude_side, rows=rows, boards=before,
                          outcome="drew" if winner is None else "won" if winner == claude_side else "lost"))
    return games

def all_rows(games, **where):   # every row of every game matching e.g. player="Claude" or role="winner"
    return [r for g in games for r in g["rows"] if all(r.get(k) == v for k, v in where.items())]

def average_loss(rows):
    return sum(r["loss"] for r in rows) / len(rows) if rows else 0.0

def record(games):
    outcomes = [g["outcome"] for g in games]
    return f"{outcomes.count('won')} wins, {outcomes.count('drew')} draws, {outcomes.count('lost')} losses"

def rule_values(games):
    """How the moves went on which Claude cited each rule/principle id: {id: dict(cited, avg_loss, games)}.
    Compare avg_loss with average_loss of all Claude moves: lower = moves made with this principle were better than usual."""
    found = {}
    for r in all_rows(games, player="Claude"):
        for x in r.get("cited") or []:
            entry = found.setdefault(x, dict(cited=0, loss=0.0, games=set()))
            entry["cited"] += 1
            entry["loss"] += r["loss"]
            entry["games"].add(r["game"])
    return {x: dict(cited=e["cited"], avg_loss=e["loss"] / e["cited"], games=sorted(e["games"])) for x, e in found.items()}

def game_story(g):   # one <game .../> line: how and where Claude's game was decided
    mine = [r for r in g["rows"] if r["player"] == "Claude"]
    by_phase = {}
    for r in mine:
        by_phase[r["phase"]] = by_phase.get(r["phase"], 0.0) + r["loss"]
    attrs = dict(id=g["game"], claude=g["claude_side"], result=g["outcome"], moves=len(mine),
                 win_pct_lost_by_phase=", ".join(f"{p} {v:.0f}" for p, v in by_phase.items()))
    if g["outcome"] == "lost":   # the last Claude move that still started from a playable position (40%+)
        alive = [r for r in mine if r["win_before"] >= 40]
        attrs["never_recovered_after_move"] = (alive[-1]["ply"] + 1) // 2 if alive else 1
    return "  <game " + " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items()) + "/>"

def trait_table(games):   # winners vs losers: how often each kind of move, and how good those moves were
    winner, loser = all_rows(games, role="winner"), all_rows(games, role="loser")
    lines = []
    if not winner or not loser:
        return lines
    for name in TRAITS:
        w, l = [r for r in winner if name in r["traits"]], [r for r in loser if name in r["traits"]]
        lines.append(f'  <move_kind name="{name}" winner_share="{len(w) / len(winner):.0%}" winner_avg_loss="{average_loss(w):.1f}" '
                     f'loser_share="{len(l) / len(loser):.0%}" loser_avg_loss="{average_loss(l):.1f}">{TRAITS[name]}</move_kind>')
    for name, test in (("ahead", lambda r: r["win_before"] >= AHEAD), ("behind", lambda r: r["win_before"] <= BEHIND),
                       ("level", lambda r: BEHIND < r["win_before"] < AHEAD)):
        w, l = [r for r in winner if test(r)], [r for r in loser if test(r)]
        share = lambda rows, trait: f"{sum(trait in r['traits'] for r in rows) / len(rows):.0%}" if rows else "-"
        lines.append(f'  <situation name="{name}" winner_moves="{len(w)}" winner_avg_loss="{average_loss(w):.1f}" '
                     f'winner_trades="{share(w, "trade")}" winner_quiet="{share(w, "quiet")}" '
                     f'loser_moves="{len(l)}" loser_avg_loss="{average_loss(l):.1f}" '
                     f'loser_trades="{share(l, "trade")}" loser_quiet="{share(l, "quiet")}"/>')
    return lines

def cause_table(games):   # Claude's bad moves by cause, costliest first
    bad = [r for r in all_rows(games, player="Claude") if r["causes"]]
    found = {}
    for r in bad:
        for c in r["causes"]:
            entry = found.setdefault(c, dict(moves=0, loss=0.0, games=set()))
            entry["moves"] += 1
            entry["loss"] += r["loss"]
            entry["games"].add(r["game"])
    return [f'  <cause name="{c}" bad_moves="{e["moves"]}" games="{len(e["games"])}" win_pct_lost="{e["loss"]:.0f}">{CAUSES[c]}</cause>'
            for c, e in sorted(found.items(), key=lambda pair: -pair[1]["loss"])]

def weak_features(games):   # position features where Claude loses more per move than its own average
    mine, theirs = all_rows(games, player="Claude"), all_rows(games, player="Stockfish")
    baseline, described = average_loss(mine), dict(line[2:].split(": ", 1) for line in features.tag_list().splitlines() if ": " in line)
    found = []
    for tag in features.TAGS:
        rows = [r for r in mine if tag in r["tags"]]
        if len(rows) >= MIN_TAG_POSITIONS and len({r["game"] for r in rows}) >= 2 and average_loss(rows) > baseline:
            found.append(((average_loss(rows) - baseline) * len(rows), tag, rows))
    lines = []
    for excess, tag, rows in sorted(found, key=lambda x: -x[0])[:MAX_WEAK_FEATURES]:
        lines.append(f'  <feature name="{tag}" positions="{len(rows)}" games="{len({r["game"] for r in rows})}" '
                     f'claude_avg_loss="{average_loss(rows):.1f}" '
                     f'stockfish_avg_loss="{average_loss([r for r in theirs if tag in r["tags"]]):.1f}">{escape(described.get(tag, ""))}</feature>')
    return baseline, lines

def spread(rows, key, total, per_game):   # the top rows by key, at most per_game from one game
    picked, used = [], {}
    for r in sorted(rows, key=key):
        if used.get(r["game"], 0) < per_game and len(picked) < total:
            used[r["game"]] = used.get(r["game"], 0) + 1
            picked.append(r)
    return picked

def turning_points(games):   # Claude's costliest moves over all games
    bad = [r for r in all_rows(games, player="Claude") if r["loss"] >= BAD_LOSS]
    return spread(bad, lambda r: -r["loss"], MAX_TURNING_POINTS, TURNING_PER_GAME)

def winner_moves(games):   # the winners' Great moves: the only good move, found
    great = [r for r in all_rows(games, role="winner") if r["cls"] == "Great" and not r.get("recapture")]
    return spread(great, lambda r: -(r.get("multipv_gap") or 0), MAX_WINNER_MOVES, WINNER_PER_GAME)

def move_number(row):
    return f"{(row['ply'] + 1) // 2}{'.' if row['side'] == 'white' else '...'}"

def report(games):
    """(xml, items): the evidence as XML, and items = {"E1": row, "W1": row, ...} for the turning points / winner moves in it."""
    by_game = {g["game"]: g for g in games}
    baseline, weak = weak_features(games)
    items, points, wins = {}, [], []
    for n, r in enumerate(turning_points(games), 1):
        items[f"E{n}"] = r
        rows = by_game[r["game"]]["rows"]
        reply = rows[r["ply"]] if r["ply"] < len(rows) else None   # rows[ply] is the move after ply (plies start at 1)
        points.append(
            f'  <turning_point id="E{n}" game="{r["game"]}" move="{move_number(r)}" phase="{r["phase"]}" win_pct_lost="{r["loss"]:.1f}" '
            f'causes="{" ".join(r["causes"])}" principles_cited="{" ".join(x for x in r.get("cited") or [] if x.startswith("R")) or "none"}">\n'
            f'    <fen>{r["fen_before"]}</fen>\n'
            f'    <played kind="{" ".join(r["traits"])}">{escape(r["san"])}</played>\n'
            f'    <best kind="{" ".join(r["best_traits"])}">{escape(r["best_san"])}</best>\n'
            f'    <best_line>{escape(r["best_pv_san"])}</best_line>\n'
            + (f'    <opponent_reply kind="{" ".join(reply["traits"])}">{escape(reply["san"])}</opponent_reply>\n' if reply else "")
            + f'    <position_features>{", ".join(r["tags"]) or "none"}</position_features>\n'
            f'    <my_reason_then>{escape(r.get("why") or "(none)")}</my_reason_then>\n'
            f'  </turning_point>')
    for n, r in enumerate(winner_moves(games), 1):
        items[f"W{n}"] = r
        wins.append(
            f'  <winner_move id="W{n}" game="{r["game"]}" move="{move_number(r)}" by="{r["player"]}" phase="{r["phase"]}" '
            f'second_best_was_worse_by="{r.get("multipv_gap") or 0:.1f}">\n'
            f'    <fen>{r["fen_before"]}</fen>\n'
            f'    <played kind="{" ".join(r["traits"])}">{escape(r["san"])}</played>\n'
            f'    <line>{escape(r["best_pv_san"])}</line>\n'
            f'    <position_features note="from the winner\'s side">{", ".join(r["tags"]) or "none"}</position_features>\n'
            f'  </winner_move>')
    block = lambda tag, note, lines: f'<{tag} note={quoteattr(note)}>\n' + ("\n".join(lines) or "  (nothing yet)") + f'\n</{tag}>'
    xml = "\n".join([
        f'<evidence games="{len(games)}" claude_record="{record(games)}" claude_avg_win_pct_lost_per_move="{baseline:.1f}">',
        block("games", "one line per game, from Claude's side", [game_story(g) for g in games]),
        block("winner_vs_loser", "all moves of the side that won each game against all moves of the side that lost it. "
              "share = part of that side's moves of this kind; avg_loss = win% those moves lost on average (0 = the engine's best move)",
              trait_table(games)),
        block("why_claude_lost", f"Claude's moves that lost {BAD_LOSS:.0f}+ win%, grouped by cause, costliest first; one move can have several causes",
              cause_table(games)),
        block("weak_positions", f"position features (true before Claude's move) where Claude loses more than its average of {baseline:.1f} win% per move",
              weak),
        block("turning_points", "Claude's costliest moves over all games", points),
        block("winner_moves", "the winners' hardest moves: the only good move in the position, and they found it", wins),
        "</evidence>"])
    return xml, items

if __name__ == "__main__":   # python evidence.py [games folder]: print the evidence
    import sys
    print(report(load_games(sys.argv[1] if len(sys.argv) > 1 else "games"))[0])
