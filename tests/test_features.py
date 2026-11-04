import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # so "import features" finds the repo files
import chess, pytest
import features

def tags(fen, me=chess.WHITE, moves=()):
    board = chess.Board(fen)
    for san in moves:
        board.push_san(san)
    return set(features.tags(board, me))

@pytest.mark.parametrize("fen, me, expected, not_expected", [
    # White king castled queenside, Black's c-file pawn gone (half-open toward my king), bishop + queen aiming at it
    ("r3k2r/pp3ppp/8/8/1b6/q7/PPP5/2KR4 w kq - 0 20", chess.WHITE,
     {"king_castled_queenside", "enemy_halfopen_file_to_my_king", "my_king_attacked", "enemy_piece_on_my_2nd_or_3rd_rank"},
     {"king_castled_kingside", "queens_off"}),
    # Two black pawns storming White's kingside king (g4, h4 are Black's 5th rank)
    ("6k1/5p2/8/8/6pp/8/5PPP/6K1 w - - 0 30", chess.WHITE, {"king_castled_kingside", "pawn_storm_toward_my_king", "queens_off"},
     set()),
    # Nd4-c2+ forks White's king and rook
    ("6k1/8/8/8/3n4/8/8/R3K3 b - - 0 40", chess.WHITE, {"my_queen_and_rook_knight_forkable", "material_up"}, set()),
    # Black passed pawn on its 6th rank (a3), White a rook up
    ("8/5pk1/6p1/3P4/8/p5P1/5PK1/R7 w - - 0 40", chess.WHITE,
     {"enemy_passer_6th", "enemy_passed_pawn", "my_passed_pawn", "material_up", "queens_off", "rook_endgame"}, {"material_down"}),
    # the same from Black's side: material down, own passer on the 6th
    ("8/5pk1/6p1/3P4/8/p5P1/5PK1/R7 w - - 0 40", chess.BLACK, {"material_down", "my_passer_6th"}, {"material_up"}),
    # an undefended white knight attacked by a pawn; a pinned black knight
    ("4k3/3n4/8/1B6/8/8/8/4K3 w - - 0 30", chess.WHITE, {"enemy_piece_pinned"}, {"my_piece_pinned"}),   # Bb5 pins Nd7
    ("4k3/8/8/8/8/2p5/1N6/4K3 w - - 0 30", chess.WHITE, {"my_piece_attacked_undefended"}, set()),
    # White rook on a1 on the long diagonal of a black bishop on e5
    ("4k3/8/8/4b3/8/8/1P6/R3K3 w - - 0 30", chess.WHITE, {"my_rook_on_enemy_bishop_diagonal"}, set()),
    # Black knight in the corner: b6 covered by the a5 pawn, c7 by the e5 bishop
    ("n3k3/8/8/P3B3/8/8/8/4K3 w - - 0 30", chess.WHITE, {"enemy_knight_on_rim_trapped"}, set()),
    ("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 30", chess.BLACK, {"my_back_rank_weak"}, set()),
    ("8/4k3/8/3P4/3K4/8/8/8 w - - 0 50", chess.WHITE, {"pawn_endgame", "queens_off"}, {"rook_endgame"}),
])
def test_tags(fen, me, expected, not_expected):
    found = tags(fen, me)
    assert expected <= found, expected - found
    assert not (not_expected & found)

def test_history_tags():
    start = chess.STARTING_FEN
    assert "my_queen_moved_twice" in tags(start, chess.WHITE, ["e4", "e5", "Qh5", "Nc6", "Qf3", "Nf6"])
    assert "my_piece_retreated_recently" in tags(start, chess.WHITE, ["e4", "e5", "Bc4", "Nf6", "Be2", "Nc6"])
    assert "my_piece_retreated_recently" not in tags(start, chess.WHITE, ["e4", "e5", "Bc4", "Nf6"])
    assert "my_queen_moved_twice" not in tags(chess.Board().fen())   # a board without history

def test_every_tag_has_a_description_and_returns_bool():
    board = chess.Board("r3k2r/pp3ppp/8/8/1b6/q7/PPP5/2KR4 w kq - 0 20")
    for name, (description, test) in features.TAGS.items():
        assert description and isinstance(test(board, chess.WHITE), bool), name
    assert set(features.tags(board, chess.WHITE)) <= set(features.TAGS)

def test_numeric_features():
    f = features.features(chess.Board("r3k2r/pp3ppp/8/8/1b6/q7/PPP5/2KR4 w kq - 0 20"), chess.WHITE)
    assert f["my_king_attackers"] >= 2 and f["open_file_count"] >= 2 and f["pawn_storm"] == 0
