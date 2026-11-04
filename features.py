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

def king_zone(board, color):   # the king's square and the squares around it
    k = board.king(color)
    return chess.SquareSet(chess.BB_KING_ATTACKS[k]) | chess.SquareSet([k]) if k is not None else chess.SquareSet()

def king_attackers(board, color):   # enemy knights/bishops/rooks/queens hitting a square around color's king
    found = set()
    for sq in king_zone(board, color):
        found |= {a for a in board.attackers(not color, sq) if board.piece_type_at(a) not in (chess.PAWN, chess.KING)}
    return len(found)

def wing_files(board, color):   # a-c for a king on the queenside, f-h on the kingside, c-f in the center
    k = board.king(color)
    f = chess.square_file(k) if k is not None else 4
    return range(0, 3) if f <= 2 else range(5, 8) if f >= 5 else range(2, 6)

def pawn_storm(board, color):   # enemy pawns on my king's wing, advanced to their 4th rank or further
    return sum(1 for sq in board.pieces(chess.PAWN, not color)
               if chess.square_file(sq) in wing_files(board, color) and relative_rank(sq, not color) >= 4)

def pawn_shield_weak(board, color):   # fewer than 2 of my pawns on the two ranks in front of my king (king on its first 2 ranks)
    k = board.king(color)
    if k is None or relative_rank(k, color) > 2:
        return False
    kf, kr = chess.square_file(k), relative_rank(k, color)
    shield = [sq for sq in board.pieces(chess.PAWN, color)
              if abs(chess.square_file(sq) - kf) <= 1 and 1 <= relative_rank(sq, color) - kr <= 2]
    return len(shield) < 2

def files_without_enemy_pawns_near_king(board, color):   # files on/next to my king the enemy's rooks can use
    k = board.king(color)
    if k is None:
        return []
    enemy_files = {chess.square_file(sq) for sq in board.pieces(chess.PAWN, not color)}
    return [f for f in range(chess.square_file(k) - 1, chess.square_file(k) + 2) if 0 <= f < 8 and f not in enemy_files]

def enemy_piece_deep(board, color):   # an enemy knight/bishop/rook/queen on my 2nd or 3rd rank
    return any(relative_rank(sq, color) in (2, 3) for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
               for sq in board.pieces(pt, not color))

def on_diagonal(a, b):
    return abs(chess.square_file(a) - chess.square_file(b)) == abs(chess.square_rank(a) - chess.square_rank(b))

def knight_trapped(board, owner):   # owner's knight on the edge with no safe square to go to
    for n in board.pieces(chess.KNIGHT, owner):
        if chess.square_file(n) in (0, 7) or chess.square_rank(n) in (0, 7):
            targets = [t for t in chess.SquareSet(chess.BB_KNIGHT_ATTACKS[n]) if not (board.piece_at(t) and board.color_at(t) == owner)]
            if targets and all(board.is_attacked_by(not owner, t) for t in targets):
                return True
    return False

def pinned_piece(board, color):
    return any(board.is_pinned(color, sq) for sq, p in board.piece_map().items() if p.color == color and p.piece_type != chess.KING)

def my_recent_moves(board, color, plies=6):   # [(piece type, from, to, was capture)] for color's moves in the last plies
    b, undone = board.copy(), []
    for _ in range(min(plies, len(b.move_stack))):
        undone.append(b.pop())
    moves = []
    for m in reversed(undone):
        if b.turn == color:
            moves.append((b.piece_type_at(m.from_square), m.from_square, m.to_square, b.is_capture(m)))
        b.push(m)
    return moves

def retreated_recently(board, color):   # one of my pieces moved back toward my side in my last 3 moves (not a capture)
    return any(pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN) and not capture
               and relative_rank(to, color) < relative_rank(frm, color) for pt, frm, to, capture in my_recent_moves(board, color))

def queen_moved_twice(board, color):   # my last two moves were both queen moves
    recent = my_recent_moves(board, color)
    return len(recent) >= 2 and all(pt == chess.QUEEN for pt, *_ in recent[-2:])

def only_types(board, allowed):   # every piece on the board (kings aside) is one of these types
    return all(p.piece_type in allowed | {chess.KING} for p in board.piece_map().values())

# Tags a lesson can list in "features": yes/no facts about the position from my side, checked by code.
TAGS = {
    "king_castled_kingside": ("my king is on the g- or h-file on my 1st rank",
                              lambda b, me: b.king(me) is not None and chess.square_file(b.king(me)) >= 6 and relative_rank(b.king(me), me) == 1),
    "king_castled_queenside": ("my king is on the a-, b- or c-file on my 1st rank",
                               lambda b, me: b.king(me) is not None and chess.square_file(b.king(me)) <= 2 and relative_rank(b.king(me), me) == 1),
    "king_in_center": ("my king is on the c- to f-file on my 1st or 2nd rank", lambda b, me: king_in_center(b, me)),
    "my_king_attacked": ("2+ enemy knights/bishops/rooks/queens hit squares around my king", lambda b, me: king_attackers(b, me) >= 2),
    "my_king_pawn_shield_weak": ("fewer than 2 of my pawns stand in front of my king", lambda b, me: pawn_shield_weak(b, me)),
    "enemy_halfopen_file_to_my_king": ("a file on or next to my king's file has no enemy pawn, so enemy rooks can use it",
                                       lambda b, me: bool(files_without_enemy_pawns_near_king(b, me))),
    "pawn_storm_toward_my_king": ("2+ enemy pawns are advanced (their 4th rank or further) on my king's wing",
                                  lambda b, me: pawn_storm(b, me) >= 2),
    "enemy_knight_near_my_king": ("an enemy knight is within 3 squares of my king",
                                  lambda b, me: b.king(me) is not None and any(chess.square_distance(n, b.king(me)) <= 3 for n in b.pieces(chess.KNIGHT, not me))),
    "enemy_piece_on_my_2nd_or_3rd_rank": ("an enemy knight, bishop, rook or queen stands on my 2nd or 3rd rank",
                                          lambda b, me: enemy_piece_deep(b, me)),
    "my_queen_and_rook_knight_forkable": ("an enemy knight can jump to a square attacking two of my king, queen and rooks",
                                          lambda b, me: knight_fork(b, not me)),
    "my_knight_fork_chance": ("my knight can jump to a square attacking two of the enemy king, queen and rooks",
                              lambda b, me: knight_fork(b, me)),
    "my_piece_attacked_undefended": ("one of my pieces or pawns is attacked and not defended", lambda b, me: bool(hanging(b, me))),
    "enemy_piece_attacked_undefended": ("an enemy piece or pawn is attacked by me and not defended", lambda b, me: bool(hanging(b, not me))),
    "my_piece_pinned": ("one of my pieces is pinned to my king", lambda b, me: pinned_piece(b, me)),
    "enemy_piece_pinned": ("an enemy piece is pinned to its king", lambda b, me: pinned_piece(b, not me)),
    "my_rook_on_enemy_bishop_diagonal": ("one of my rooks stands on a diagonal of an enemy bishop",
                                         lambda b, me: any(on_diagonal(r, x) for r in b.pieces(chess.ROOK, me) for x in b.pieces(chess.BISHOP, not me))),
    "enemy_knight_on_rim_trapped": ("an enemy knight on the edge of the board has no safe square", lambda b, me: knight_trapped(b, not me)),
    "my_back_rank_weak": ("my king is on my 1st rank, boxed in by its own pawns, and the enemy has a rook or queen",
                          lambda b, me: back_rank_weak(b, me)),
    "enemy_back_rank_weak": ("the enemy king is boxed in on its 1st rank and I have a rook or queen", lambda b, me: back_rank_weak(b, not me)),
    "my_passed_pawn": ("I have a passed pawn", lambda b, me: bool(passed_pawns(b, me))),
    "enemy_passed_pawn": ("the enemy has a passed pawn", lambda b, me: bool(passed_pawns(b, not me))),
    "my_passer_6th": ("I have a passed pawn on my 6th or 7th rank", lambda b, me: any(relative_rank(sq, me) >= 6 for sq in passed_pawns(b, me))),
    "enemy_passer_6th": ("the enemy has a passed pawn on its 6th or 7th rank",
                         lambda b, me: any(relative_rank(sq, not me) >= 6 for sq in passed_pawns(b, not me))),
    "queens_off": ("there are no queens on the board",
                   lambda b, me: not b.pieces(chess.QUEEN, chess.WHITE) and not b.pieces(chess.QUEEN, chess.BLACK)),
    "material_down": ("I am 2+ points of material down", lambda b, me: material_value(b, me) - material_value(b, not me) <= -2),
    "material_up": ("I am 2+ points of material up", lambda b, me: material_value(b, me) - material_value(b, not me) >= 2),
    "two_plus_open_files": ("2 or more files have no pawns at all", lambda b, me: len(open_files(b)) >= 2),
    "rook_endgame": ("only rooks and pawns are left besides the kings",
                     lambda b, me: only_types(b, {chess.ROOK, chess.PAWN}) and bool(b.pieces(chess.ROOK, chess.WHITE) | b.pieces(chess.ROOK, chess.BLACK))),
    "pawn_endgame": ("only kings and pawns are left", lambda b, me: only_types(b, {chess.PAWN})),
    "minor_piece_endgame": ("no queens or rooks, but knights or bishops are left",
                            lambda b, me: only_types(b, {chess.KNIGHT, chess.BISHOP, chess.PAWN}) and not only_types(b, {chess.PAWN})),
    "my_piece_retreated_recently": ("in my last 3 moves one of my pieces moved back toward my side",
                                    lambda b, me: retreated_recently(b, me)),
    "my_queen_moved_twice": ("my last two moves were both queen moves", lambda b, me: queen_moved_twice(b, me)),
}

def tags(board, me):   # the TAGS that are true in this position, from me's side
    return sorted(name for name, (_, test) in TAGS.items() if test(board, me))

def tag_list():   # for prompts: "- name: description"
    return "\n".join(f"- {name}: {description}" for name, (description, _) in TAGS.items())

def features(board, me):
    them = not me
    return dict(
        open_file_count=len(open_files(board)),
        my_king_attackers=king_attackers(board, me),
        pawn_storm=pawn_storm(board, me),
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
