"""What is on the board, in plain terms, so the right lessons can be picked for a position. Pure python-chess, no engine."""
import chess
import review   # phase()

LETTERS = ((chess.QUEEN, "Q"), (chess.ROOK, "R"), (chess.BISHOP, "B"), (chess.KNIGHT, "N"))
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}

def relative_rank(square, color):   # 1..8 from color's side
    rank = chess.square_rank(square) + 1
    return rank if color == chess.WHITE else 9 - rank

def passed_pawns(board, color):   # no enemy pawn in front on the same or a neighbouring file
    enemy = board.pieces(chess.PAWN, not color)
    passed = []
    for sq in board.pieces(chess.PAWN, color):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        ahead = range(r + 1, 8) if color == chess.WHITE else range(0, r)
        if not any(chess.square(ff, rr) in enemy for ff in (f - 1, f, f + 1) if 0 <= ff < 8 for rr in ahead):
            passed.append(sq)
    return passed

def hanging(board, color):   # pieces and pawns (not the king) attacked by the enemy and not defended
    return [sq for sq, p in board.piece_map().items() if p.color == color and p.piece_type != chess.KING
            and board.is_attacked_by(not color, sq) and not board.is_attacked_by(color, sq)]

def king_in_center(board, color):   # king on files c-f, still on its first two ranks
    k = board.king(color)
    return k is not None and 2 <= chess.square_file(k) <= 5 and relative_rank(k, color) <= 2

def open_files(board):   # no pawns at all
    return [chess.FILE_NAMES[f] for f in range(8) if not any(chess.square_file(sq) == f for sq in board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK))]

def half_open_files(board, color):   # none of my pawns, some enemy pawns
    files = lambda c: {chess.square_file(sq) for sq in board.pieces(chess.PAWN, c)}
    return [chess.FILE_NAMES[f] for f in sorted(files(not color) - files(color))]

def material(board, color):   # e.g. "R+B+3P"
    parts = [(f"{n}{letter}" if n > 1 else letter) for pt, letter in LETTERS if (n := len(board.pieces(pt, color)))]
    pawns = len(board.pieces(chess.PAWN, color))
    return "+".join(parts + ([f"{pawns}P"] if pawns else [])) or "K"

def material_value(board, color):
    return sum(VALUES[p.piece_type] for p in board.piece_map().values() if p.color == color)

def back_rank_weak(board, color):   # king on its first rank, every square in front of it blocked by its own pawns
    k = board.king(color)
    if k is None or relative_rank(k, color) != 1 or not (board.pieces(chess.ROOK, not color) | board.pieces(chess.QUEEN, not color)):
        return False
    step = 8 if color == chess.WHITE else -8
    front = [k + step + d for d in (-1, 0, 1) if 0 <= chess.square_file(k) + d < 8]
    return all(board.piece_at(sq) == chess.Piece(chess.PAWN, color) for sq in front)

def knight_fork(board, attacker):   # can a knight of attacker jump to a square hitting 2+ of the king/queen/rooks?
    targets = board.pieces(chess.KING, not attacker) | board.pieces(chess.QUEEN, not attacker) | board.pieces(chess.ROOK, not attacker)
    for n in board.pieces(chess.KNIGHT, attacker):
        for to in board.attacks(n):
            piece = board.piece_at(to)
            if (piece is None or piece.color != attacker) and len(chess.SquareSet(chess.BB_KNIGHT_ATTACKS[to]) & targets) >= 2:
                return True
    return False

def features(board, me):
    them = not me
    return dict(
        phase=review.phase(board),
        signature=f"{material(board, me)} vs {material(board, them)}",
        material_diff=material_value(board, me) - material_value(board, them),
        passed_mine=[(chess.square_name(sq), relative_rank(sq, me)) for sq in passed_pawns(board, me)],
        passed_theirs=[(chess.square_name(sq), relative_rank(sq, them)) for sq in passed_pawns(board, them)],
        king_in_center=king_in_center(board, me),
        hanging_mine=[chess.square_name(sq) for sq in hanging(board, me)],
        hanging_theirs=[chess.square_name(sq) for sq in hanging(board, them)],
        open_files=open_files(board),
        half_open_mine=half_open_files(board, me),
        pinned_mine=[chess.square_name(sq) for sq, p in board.piece_map().items() if p.color == me and board.is_pinned(me, sq) and p.piece_type != chess.KING],
        back_rank_weak=back_rank_weak(board, me),
        fork_threat=knight_fork(board, them),
        fork_chance=knight_fork(board, me),
        only_kings_and_pawns=all(p.piece_type in (chess.KING, chess.PAWN) for p in board.piece_map().values()),
        rooks_on=bool(board.pieces(chess.ROOK, me) or board.pieces(chess.ROOK, them)),
        blocked_pawns=any(board.piece_at(sq + (8 if me == chess.WHITE else -8)) == chess.Piece(chess.PAWN, them)
                          for sq in board.pieces(chess.PAWN, me) if 0 <= sq + (8 if me == chess.WHITE else -8) < 64))

def motifs(f):   # the lesson motifs this position calls for
    found = set()
    endgame = f["phase"] == "endgame"
    if f["passed_mine"] or f["passed_theirs"]:
        found.add("passed_pawn")
        if endgame and (f["passed_mine"] and f["passed_theirs"] or any(r >= 6 for _, r in f["passed_mine"] + f["passed_theirs"])):
            found.add("pawn_race")
    if endgame:
        found.add("king_activity")
        if f["only_kings_and_pawns"]:
            found.add("opposition")
    elif f["king_in_center"]:
        found.add("king_safety")
    if f["rooks_on"] and (f["open_files"] or f["half_open_mine"]):
        found.add("rook_activity")
    if f["hanging_mine"] or f["hanging_theirs"]:
        found.add("hanging_piece")
    if f["pinned_mine"]:
        found.add("pin")
    if f["fork_threat"] or f["fork_chance"]:
        found.add("fork")
    if f["back_rank_weak"]:
        found.add("back_rank")
    if f["blocked_pawns"] and not endgame:
        found.add("pawn_break")
    if f["phase"] == "middlegame":
        found.add("piece_activity")
    if f["material_diff"] >= 2:
        found.add("conversion")
    return found

def header(f):   # one line, e.g. "endgame, R+3P vs R+2P, passed pawns: mine d5 (5th), theirs a3 (6th)"
    sq = lambda pawns: ", ".join(f"{s} ({r}th)" for s, r in pawns)
    parts = [f["phase"], f["signature"]]
    if f["passed_mine"] or f["passed_theirs"]:
        parts.append("passed pawns: " + "; ".join(x for x in (f"mine {sq(f['passed_mine'])}" if f["passed_mine"] else "",
                                                          f"theirs {sq(f['passed_theirs'])}" if f["passed_theirs"] else "") if x))
    if f["king_in_center"] and f["phase"] != "endgame":
        parts.append("my king is still in the center")
    if f["hanging_mine"]:
        parts.append("my undefended attacked pieces: " + ", ".join(f["hanging_mine"]))
    if f["hanging_theirs"]:
        parts.append("their undefended attacked pieces: " + ", ".join(f["hanging_theirs"]))
    if f["open_files"]:
        parts.append("open files: " + ", ".join(f["open_files"]))
    if f["half_open_mine"]:
        parts.append("half-open for me: " + ", ".join(f["half_open_mine"]))
    return ", ".join(parts)

def rate(lesson):   # help rate with a prior, so a new lesson counts as 50%
    return (lesson.get("helped", 0) + 1) / (lesson.get("retrieved", 0) + 2)

def retrieve(lessons, f, n):
    """The n best active lessons: phase match first, then motif overlap, then help rate; ties go to the newest.
    Lessons for a different phase are left out."""
    wanted = motifs(f)
    phase_score = lambda l: 2 if l["phase"] == f["phase"] else 1 if l["phase"] == "any" else 0
    newest = lambda l: int(l["id"][1:]) if l["id"][1:].isdigit() else 0
    fitting = [l for l in lessons if l.get("status") == "active" and phase_score(l)]
    return sorted(fitting, key=lambda l: (-phase_score(l), -len(wanted & set(l["motifs"])), -rate(l), -newest(l)))[:n]

# --- endgame reference positions ------------------------------------------------------------------

def counts(board):   # (Q, R, B, N, P) for white and black
    return [tuple(len(board.pieces(pt, c)) for pt in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN))
            for c in (chess.WHITE, chess.BLACK)]

def signature_distance(board, ref_board):   # how different the material is; pawns count half, colors may be swapped
    a, b = counts(board), counts(ref_board)
    d = lambda x, y: sum(abs(p - q) * (0.5 if k == 4 else 1) for side in (0, 1) for k, (p, q) in enumerate(zip(x[side], y[side])))
    return min(d(a, b), d(a, b[::-1]))

def closest_refs(board, refs, n=2):   # the closest one, plus a second if it is about as close
    ranked = sorted(refs, key=lambda r: signature_distance(board, chess.Board(r["fen"])))[:n]
    if len(ranked) == 2 and signature_distance(board, chess.Board(ranked[1]["fen"])) > signature_distance(board, chess.Board(ranked[0]["fen"])) + 1:
        ranked = ranked[:1]
    return ranked
