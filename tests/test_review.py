import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # so "import review" finds the repo files
import chess, chess.engine, chess.pgn, pytest
import match, review

# --- win% and accuracy -------------------------------------------------------

def test_win_pct_even_is_50():
    assert review.win_pct(0) == 50

def test_win_pct_is_symmetric():
    for cp in (35, 100, 250, 900):
        assert review.win_pct(cp) + review.win_pct(-cp) == pytest.approx(100)

def test_win_pct_known_values():
    assert review.win_pct(100) == pytest.approx(59.1, abs=0.1)
    assert review.win_pct(-300) == pytest.approx(24.9, abs=0.1)
    assert review.win_pct(review.MATE_CP) > 99.9 and review.win_pct(-review.MATE_CP) < 0.1

def test_move_accuracy_range():
    assert review.move_accuracy(0) == pytest.approx(100, abs=0.001)
    assert review.move_accuracy(100) == 0
    assert 0 < review.move_accuracy(10) < review.move_accuracy(5) < 100

# --- class boundaries ----------------------------------------------------------

def cls(loss):   # a normal non-best move from an equal position
    return review.classify(loss, played_best=False, cp_best=0, cp_after=0, win_best=50)

@pytest.mark.parametrize("loss, expected", [
    (0, "Excellent"), (1.99, "Excellent"), (2, "Good"), (4.99, "Good"), (5, "Inaccuracy"),
    (9.99, "Inaccuracy"), (10, "Mistake"), (19.99, "Mistake"), (20, "Blunder"), (60, "Blunder")])
def test_loss_boundaries(loss, expected):
    assert cls(loss) == expected

def test_great_needs_15_percent_gap():
    assert review.classify(0, True, 300, 300, win_best=70, win_second=55) == "Great"
    assert review.classify(0, True, 300, 300, win_best=70, win_second=55.1) == "Best"
    assert review.classify(0, True, 300, 300, win_best=70, win_second=None) == "Best"   # only one legal move

def test_miss_boundaries():
    assert review.classify(30, False, cp_best=200, cp_after=99, win_best=67) == "Miss"
    assert review.classify(30, False, cp_best=review.MATE_CP - 3, cp_after=50, win_best=100) == "Miss"   # missed a mate
    assert review.classify(30, False, cp_best=199, cp_after=0, win_best=67) == "Blunder"            # wasn't winning
    assert review.classify(8, False, cp_best=300, cp_after=100, win_best=75) == "Inaccuracy"        # still +1

def test_book_wins():
    assert review.classify(50, False, 0, -500, 50, book=True) == "Book"
    assert review.is_book(["e4", "e5", "Nf3"]) and not review.is_book(["e4", "e5", "Qh5"])
    assert not review.is_book("e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O".split())   # past 8 plies

def test_book_lines_are_legal():
    for line in review.BOOK_LINES:
        board = chess.Board()
        for san in line:
            board.push_san(san)   # raises if a line has a typo

# --- phase ---------------------------------------------------------------------

def test_phase():
    assert review.phase(chess.Board()) == "opening"
    full = chess.Board(); full.fullmove_number = 11
    assert review.phase(full) == "middlegame"
    no_queens = chess.Board("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 20")
    assert review.phase(no_queens) == "endgame"
    q_r_each = chess.Board("3qk2r/5ppp/8/8/8/8/5PPP/3QK2R w - - 0 30")      # 9+5 = 14 each
    assert review.phase(q_r_each) == "middlegame"
    q_minor_each = chess.Board("3qkb2/5ppp/8/8/8/8/5PPP/3QKN2 w - - 0 30")  # 9+3 = 12 each
    assert review.phase(q_minor_each) == "endgame"

# --- Great and Miss with real Stockfish on a hand-made position ----------------
# White to move: the black queen on d5 hangs to Rd1 (and attacks Rd1 itself).
# Rxd5 is the only good move -> Great. Anything else lets Black take the rook -> Miss.

HANGING_QUEEN = "6k1/5ppp/8/3q4/8/8/5PPP/3R2K1 w - - 0 30"
needs_stockfish = pytest.mark.skipif(not os.path.exists(match.STOCKFISH), reason="Stockfish not found")

def review_one_move(fen, san):
    game = chess.pgn.Game(headers={"White": "Claude (test)", "Black": "Stockfish (test)"})
    board = chess.Board(fen)
    game.setup(board)
    game.add_variation(board.parse_san(san))
    engine = chess.engine.SimpleEngine.popen_uci(match.STOCKFISH)
    try:
        review.REVIEW_DEPTH, depth = 12, review.REVIEW_DEPTH   # quicker for tests
        return review.review_pgn(game, engine)[0]
    finally:
        review.REVIEW_DEPTH = depth
        engine.quit()

@needs_stockfish
def test_great_on_hanging_queen():
    row = review_one_move(HANGING_QUEEN, "Rxd5")
    assert row["cls"] == "Great" and row["best_san"] == "Rxd5" and row["loss"] == 0
    assert row["player"] == "Claude" and row["phase"] == "endgame"

@needs_stockfish
def test_miss_on_hanging_queen():
    row = review_one_move(HANGING_QUEEN, "h3")
    assert row["cls"] == "Miss" and row["best_san"] == "Rxd5"
    assert row["cp_before"] >= 200 and row["cp_after"] < 100
