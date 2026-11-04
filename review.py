import chess, chess.engine, chess.pgn, json, math, os, sys
import match   # Stockfish path and games folder

REVIEW_DEPTH = 18     # how deep full-strength Stockfish checks every position
REVIEW_THREADS = 2    # CPU threads for the review engine
MATE_CP = 10000       # a forced mate counts as +-10000 centipawns
CLASSES = ["Book", "Great", "Best", "Excellent", "Good", "Inaccuracy", "Mistake", "Miss", "Blunder"]
GOOD_OR_BETTER = {"Book", "Great", "Best", "Excellent", "Good"}
WORSE_THAN_GOOD = {"Inaccuracy", "Mistake", "Miss", "Blunder"}
PHASES = ["opening", "middlegame", "endgame"]
NAGS = {"Great": chess.pgn.NAG_BRILLIANT_MOVE, "Best": chess.pgn.NAG_GOOD_MOVE, "Inaccuracy": chess.pgn.NAG_DUBIOUS_MOVE,
        "Mistake": chess.pgn.NAG_MISTAKE, "Miss": chess.pgn.NAG_MISTAKE, "Blunder": chess.pgn.NAG_BLUNDER}   # !! ! ?! ? ? ??
MARKS = {"Great": "!!", "Mistake": "?", "Miss": "MISS", "Blunder": "??"}   # flagged in the printed move list

# a few main lines; a move in the first 8 plies is "Book" if the game so far is the start of one of these
BOOK_LINES = [line.split() for line in [
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6", "e4 e5 Nf3 Nc6 Bb5 Nf6 O-O Nxe4", "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6",
    "e4 e5 Nf3 Nc6 Bc4 Nf6 d3 Be7", "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Nf6", "e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4",
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6", "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6", "e4 c5 Nf3 e6 d4 cxd4 Nxd4 Nf6",
    "e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7", "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5", "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6",
    "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7", "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4", "d4 d5 c4 dxc4 Nf3 Nf6 e3 e6",
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6", "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O", "d4 Nf6 c4 e6 Nf3 b6 g3 Ba6",
    "c4 e5 Nc3 Nf6 Nf3 Nc6 g3 d5", "Nf3 d5 g3 Nf6 Bg2 e6 O-O Be7"]]

def win_pct(cp):   # chance of winning (0-100) for the side whose eval this is
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)

def move_accuracy(loss):   # 100 = perfect move, 0 = threw the game away
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * loss) - 3.1669))

def phase(board):
    if board.fullmove_number <= 10:
        return "opening"
    def material(color):   # knights, bishops, rooks, queens (not pawns)
        return sum(len(board.pieces(p, color)) * v for p, v in ((chess.KNIGHT, 3), (chess.BISHOP, 3), (chess.ROOK, 5), (chess.QUEEN, 9)))
    no_queens = not board.pieces(chess.QUEEN, chess.WHITE) and not board.pieces(chess.QUEEN, chess.BLACK)
    if no_queens or (material(chess.WHITE) <= 13 and material(chess.BLACK) <= 13):
        return "endgame"
    return "middlegame"

def is_book(sans):   # sans = every move of the game up to and including this one
    return len(sans) <= 8 and any(line[:len(sans)] == sans for line in BOOK_LINES)

def classify(loss, played_best, cp_best, cp_after, win_best, win_second=None, book=False):
    """chess.com-style class. All numbers are from the mover's side; win_second = engine's 2nd-best line (None if only one move)."""
    if book:
        return "Book"
    if played_best:
        return "Great" if win_second is not None and win_best - win_second >= 15 else "Best"
    if cp_best >= 200 and cp_after < 100:   # was winning (or had a mate) and let it slip
        return "Miss"
    for limit, name in ((2, "Excellent"), (5, "Good"), (10, "Inaccuracy"), (20, "Mistake")):
        if loss < limit:
            return name
    return "Blunder"

def evaluate(engine, board):
    """[(cp, pv), ...] for the top 2 lines, cp from the side to move. A finished game is scored directly."""
    if board.is_checkmate():
        return [(-MATE_CP, [])]
    if board.is_game_over():   # stalemate, insufficient material, 75-move rule, repetition
        return [(0, [])]
    infos = engine.analyse(board, chess.engine.Limit(depth=REVIEW_DEPTH), multipv=2)
    return [(info["score"].pov(board.turn).score(mate_score=MATE_CP), info.get("pv", [])) for info in infos]

def move_number(row):   # "23." for White, "23..." for Black
    return f"{(row['ply'] + 1) // 2}{'.' if row['side'] == 'white' else '...'}"

def label(row):   # "Best", or "Mistake, -12.4%, best was Kd5" for anything worse than Good
    if row["cls"] in WORSE_THAN_GOOD:
        return f"{row['cls']}, -{row['loss']:.1f}%, best was {row['best_san']}"
    return row["cls"]

def pv_san(board, pv, plies=5):
    return board.copy().variation_san(pv[:plies]) if pv else ""

def players(game):   # {chess.WHITE: "Claude", chess.BLACK: "Stockfish"} from the PGN headers
    return {color: "Claude" if game.headers.get(side, "").startswith("Claude") else "Stockfish"
            for color, side in ((chess.WHITE, "White"), (chess.BLACK, "Black"))}

CLAUDE_FIELDS = ("self_eval", "trend", "why", "retrieved", "cited")   # copied from moves_<i>.jsonl onto Claude's moves

def review_pgn(game, engine, claude_moves=None):
    """One dict per move (both sides). Each position is analysed once: the position after move n is the one before n+1.
    claude_moves: ply -> what match.py recorded for Claude's move (its own EVAL/TREND/WHY, lesson ids)."""
    claude_moves = claude_moves or {}
    who = players(game)
    board, moves, sans = game.board(), list(game.mainline_moves()), []
    lines = evaluate(engine, board)
    rows = []
    for ply, move in enumerate(moves, 1):
        mover, fen, ph = board.turn, board.fen(), phase(board)
        (cp_best, best_pv), second = lines[0], (lines[1] if len(lines) > 1 else None)
        san = board.san(move)
        best_san = board.san(best_pv[0]) if best_pv else san
        best_line = pv_san(board, best_pv)
        sans.append(san)
        board.push(move)
        lines = evaluate(engine, board)
        cp_after = -lines[0][0]                      # back to the mover's side
        played_best = bool(best_pv) and move == best_pv[0]
        win_before, win_after = win_pct(cp_best), win_pct(cp_after)
        loss = 0.0 if played_best else max(0.0, win_before - win_after)
        win_second = win_pct(second[0]) if second else None
        cls = classify(loss, played_best, cp_best, cp_after, win_before, win_second, is_book(sans))
        row = dict(ply=ply, side="white" if mover == chess.WHITE else "black", player=who[mover],
                   fen_before=fen, san=san, best_san=best_san, best_pv_san=best_line,
                   cp_before=cp_best, cp_after=cp_after, win_before=round(win_before, 2),
                   win_after=round(win_after, 2), loss=round(loss, 2), cls=cls, phase=ph,
                   multipv_gap=round(win_before - win_second, 2) if second else None)   # how much worse the 2nd-best move was
        if row["player"] == "Claude":
            recorded = claude_moves.get(ply, {})
            row.update({k: recorded.get(k, [] if k in ("retrieved", "cited") else None) for k in CLAUDE_FIELDS})
        rows.append(row)
    return rows

def load_claude_moves(games_dir, i):   # ply -> the line match.py wrote for that Claude move
    p = f"{games_dir}/moves_{i}.jsonl"
    return {m["ply"]: m for m in (json.loads(l) for l in open(p, encoding="utf-8") if l.strip())} if os.path.exists(p) else {}

def write_annotated(game, rows, summary, path):
    """game_<i>_annotated.pgn: every move gets its class as a comment and a NAG (!!, !, ?!, ?, ??)."""
    node = game
    for row in rows:
        node = node.variations[0]
        if row["cls"] in NAGS:
            node.nags.add(NAGS[row["cls"]])
        node.comment = label(row)
    w, b = summary["sides"]["white"], summary["sides"]["black"]
    game.headers["Annotator"] = f"review.py, Stockfish depth {REVIEW_DEPTH}"
    game.comment = f"Accuracy: White {w['accuracy']}, Black {b['accuracy']}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(game) + "\n\n")

def print_moves(rows):
    print("\nClaude's moves:")
    for r in rows:
        if r["player"] == "Claude":
            detail = f"(-{r['loss']:.1f}%, best {r['best_san']})" if r["cls"] in WORSE_THAN_GOOD else ""
            print(f"{MARKS.get(r['cls'], ''):>5}  {move_number(r) + ' ' + r['san']:14}{r['cls']:12}{detail}")

def print_pairs(rows):
    before = lambda k: rows[k - 1] if k else None
    print("\nStockfish's Great moves - what Claude didn't see coming:")
    greats = [(k, r) for k, r in enumerate(rows) if r["player"] == "Stockfish" and r["cls"] == "Great"]
    for k, r in greats:
        prev = before(k)
        after = f"after Claude's {move_number(prev)} {prev['san']} ({prev['cls']}), " if prev else ""
        print(f"  {after}Stockfish found {move_number(r)} {r['san']}!! (the next best move was {r['multipv_gap']:.1f}% worse)")
    if not greats:
        print("  (none)")
    print("\nClaude's misses - what Claude could have won:")
    misses = [(k, r) for k, r in enumerate(rows) if r["player"] == "Claude" and r["cls"] == "Miss"]
    for k, r in misses:
        prev = before(k)
        after = f"after Stockfish's {move_number(prev)} {prev['san']} ({prev['cls']}), " if prev else ""
        print(f"  {after}Claude played {move_number(r)} {r['san']} instead of {r['best_san']} "
              f"({r['cp_before'] / 100:+.1f} -> {r['cp_after'] / 100:+.1f}); line: {r['best_pv_san']}")
    if not misses:
        print("  (none)")

def summarize(rows, game):
    sides = {}
    for side in ("white", "black"):
        mine = [r for r in rows if r["side"] == side]
        acc = lambda rs: round(sum(move_accuracy(r["loss"]) for r in rs) / len(rs), 1) if rs else None
        sides[side] = dict(player=next((r["player"] for r in mine), None), moves=len(mine), accuracy=acc(mine),
                           accuracy_by_phase={p: acc([r for r in mine if r["phase"] == p]) for p in PHASES},
                           moves_by_phase={p: sum(r["phase"] == p for r in mine) for p in PHASES},
                           counts={c: sum(r["cls"] == c for r in mine) for c in CLASSES})
    return dict(white=game.headers.get("White"), black=game.headers.get("Black"), result=game.headers.get("Result"),
                depth=REVIEW_DEPTH, sides=sides)

def print_table(summary):
    w, b = summary["sides"]["white"], summary["sides"]["black"]
    print(f"{'':16}{w['player'] + ' (White)':>20}{b['player'] + ' (Black)':>20}")
    print(f"{'Accuracy':16}{w['accuracy'] or 0:>20.1f}{b['accuracy'] or 0:>20.1f}")
    for c in CLASSES:
        print(f"{c:16}{w['counts'][c]:>20}{b['counts'][c]:>20}")
    for p in PHASES:
        fmt = lambda s: f"{s['accuracy_by_phase'][p]:.1f} ({s['moves_by_phase'][p]})" if s['accuracy_by_phase'][p] is not None else "-"
        print(f"{'acc ' + p:16}{fmt(w):>20}{fmt(b):>20}")

def review_game(i, games_dir=None, engine=None, quiet=False):
    """Review game i, write review_<i>.jsonl + review_<i>.json, return (rows, summary)."""
    games_dir = games_dir or match.GAMES_DIR
    own_engine = engine is None
    if own_engine:
        engine = chess.engine.SimpleEngine.popen_uci(match.STOCKFISH)   # no Skill Level = full strength
        engine.configure({"Threads": REVIEW_THREADS, "Hash": 64})
    game = chess.pgn.read_game(open(f"{games_dir}/game_{i}.pgn", encoding="utf-8"))
    try:
        rows = review_pgn(game, engine, load_claude_moves(games_dir, i))
    finally:
        if own_engine:
            engine.quit()
    summary = dict(game=i, **summarize(rows, game))
    with open(f"{games_dir}/review_{i}.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    with open(f"{games_dir}/review_{i}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    write_annotated(game, rows, summary, f"{games_dir}/game_{i}_annotated.pgn")
    if not quiet:
        print(f"\nReview of game {i} ({summary['result']}), depth {REVIEW_DEPTH}")
        print_table(summary)
        print_moves(rows)
        print_pairs(rows)
    return rows, summary

if __name__ == "__main__":   # python review.py 3 [4 5 ...] [--dir games_full]
    args = sys.argv[1:]
    games_dir = args[args.index("--dir") + 1] if "--dir" in args else None
    numbers = [int(a) for a in args if a.isdigit()]
    if not numbers:
        sys.exit("usage: python review.py <game number> [more numbers] [--dir games_folder]")
    for n in numbers:
        review_game(n, games_dir)
