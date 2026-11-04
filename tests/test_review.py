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
    assert row["player"] == "Claude" and row["phase"] == "endgame" and row["gap"] >= 15

@needs_stockfish
def test_miss_on_hanging_queen():
    row = review_one_move(HANGING_QUEEN, "h3")
    assert row["cls"] == "Miss" and row["best_san"] == "Rxd5"
    assert row["cp_before"] >= 200 and row["cp_after"] < 100

# --- annotated PGN and printed lists ------------------------------------------

def fake_rows(classes):   # rows for 1.e4 e5 2.Nf3 Nc6 ... with the given classes, no engine needed
    sans = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nd4"][:len(classes)]
    return [dict(ply=n, side="white" if n % 2 else "black", player="Claude" if n % 2 else "Stockfish",
                 san=s, best_san="Nf3", best_pv_san="", cls=c, loss=12.4 if c in review.WORSE_THAN_GOOD else 0,
                 cp_before=250, cp_after=50, gap=20)
            for n, (s, c) in enumerate(zip(sans, classes), 1)]

def test_annotated_pgn_round_trip(tmp_path):
    classes = ["Book", "Great", "Inaccuracy", "Blunder", "Miss", "Best"]
    game = chess.pgn.Game()
    node = game
    for san in ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nd4"]:
        node = node.add_variation(node.board().parse_san(san))
    summary = {"sides": {"white": {"accuracy": 80.0}, "black": {"accuracy": 86.7}}}
    path = tmp_path / "game_1_annotated.pgn"
    review.write_annotated(game, fake_rows(classes), summary, str(path))
    back = chess.pgn.read_game(open(path, encoding="utf-8"))
    assert not back.errors
    nodes = list(back.mainline())
    assert [n.comment for n in nodes][:2] == ["Book", "Great"]
    assert nodes[1].nags == {chess.pgn.NAG_BRILLIANT_MOVE}
    assert nodes[2].nags == {chess.pgn.NAG_DUBIOUS_MOVE} and nodes[2].comment == "Inaccuracy, -12.4%, best was Nf3"
    assert nodes[3].nags == {chess.pgn.NAG_BLUNDER}
    assert nodes[4].nags == {chess.pgn.NAG_MISTAKE} and nodes[4].comment.startswith("Miss")
    assert nodes[5].nags == {chess.pgn.NAG_GOOD_MOVE}
    assert "$3" in path.read_text() and "$4" in path.read_text()   # standard NAG codes that GUIs read

def test_move_list_marks(capsys):
    review.print_moves(fake_rows(["Great", "Best", "Mistake", "Best", "Miss"]))
    out = capsys.readouterr().out
    assert "!!" in out and "2. Nf3" in out and "Mistake" in out and "(-12.4%, best Nf3)" in out and "MISS" in out

def test_pairs(capsys):
    review.print_pairs(fake_rows(["Best", "Great", "Best", "Mistake", "Miss"]))
    out = capsys.readouterr().out
    assert "Stockfish found 1... e5!!" in out and "after Stockfish's 2... Nc6 (Mistake), Claude played 3. Bc4 instead of Nf3" in out
