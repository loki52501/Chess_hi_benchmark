import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # so "import match" finds the repo files
import chess, pytest
import match, features, knowledge, prompts

ROOK_ENDING = chess.Board("8/5pk1/6p1/3P4/8/p5P1/5PK1/R7 w - - 0 40")   # White: Ra1, d5 passer; Black: a3 passer

# --- features ---------------------------------------------------------------------------------------

def test_passed_pawns_and_signature():
    f = features.features(ROOK_ENDING, chess.WHITE)
    assert f["phase"] == "endgame" and f["signature"] == "R+3P vs 3P"
    assert f["passed_mine"] == [("d5", 5)] and f["passed_theirs"] == [("a3", 6)]
    assert {"passed_pawn", "pawn_race", "king_activity", "rook_activity", "conversion"} <= features.motifs(f)
    assert "endgame, R+3P vs 3P, passed pawns: mine d5 (5th); theirs a3 (6th)" in features.header(f)

def test_hanging_king_center_and_files():
    board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2")   # 2.Nf3 hits the undefended e5
    f = features.features(board, chess.WHITE)
    assert f["king_in_center"] and f["phase"] == "opening"
    assert f["hanging_theirs"] == ["e5"] and f["hanging_mine"] == []
    assert f["open_files"] == [] and f["half_open_mine"] == []
    open_d = chess.Board("4k3/pp4pp/8/8/8/8/PP4PP/3RK3 w - - 0 30")
    g = features.features(open_d, chess.WHITE)
    assert {"c", "d", "e", "f"} == set(g["open_files"]) and not g["king_in_center"] is None

def test_back_rank_and_fork():
    board = chess.Board("6k1/5ppp/8/8/8/2n5/5PPP/R3R1K1 w - - 0 25")   # g1 king boxed in by its own pawns
    f = features.features(board, chess.WHITE)
    assert f["back_rank_weak"] is False                                 # Black has no rook or queen
    fork = chess.Board("6k1/8/8/8/3n4/8/8/R3K3 b - - 0 40")             # Nd4-c2+ forks Ke1 and Ra1
    assert features.features(fork, chess.WHITE)["fork_threat"]

# --- retrieval ----------------------------------------------------------------------------------------

def lesson(id, phase, motifs, retrieved=0, helped=0, status="active"):
    return dict(id=id, rule="r", trigger=f"t{id}", check=f"c{id}", phase=phase, motifs=motifs,
                retrieved=retrieved, helped=helped, status=status)

def test_retrieve_order():
    f = features.features(ROOK_ENDING, chess.WHITE)
    lessons = [lesson("L001", "opening", ["passed_pawn"]),                  # wrong phase: left out
               lesson("L002", "any", ["passed_pawn"]),                      # phase "any" ranks after "endgame"
               lesson("L003", "endgame", ["fork"]),                         # endgame, no motif overlap
               lesson("L004", "endgame", ["passed_pawn", "pawn_race"]),     # endgame, 2 motifs
               lesson("L005", "endgame", ["passed_pawn"], retrieved=10, helped=2),
               lesson("L006", "endgame", ["passed_pawn"], retrieved=10, helped=9),
               lesson("L007", "endgame", ["passed_pawn"]),                  # same as L008 but older
               lesson("L008", "endgame", ["passed_pawn"]),
               lesson("L009", "endgame", ["passed_pawn", "pawn_race"], status="retired")]
    picked = [l["id"] for l in features.retrieve(lessons, f, 10)]
    assert picked == ["L004", "L006", "L008", "L007", "L005", "L003", "L002"]
    assert len(features.retrieve(lessons, f, 5)) == 5

# --- parsing Claude's answer ---------------------------------------------------------------------------

@pytest.mark.parametrize("line, expected", [
    ("EVAL: +0.8 | TREND: same | WHY: rook more active", (0.8, "same", "rook more active")),
    ("**EVAL:** -1.5 | **TREND:** Worse | **WHY:** pawn on a3 is fast", (-1.5, "worse", "pawn on a3 is fast")),
    ("EVAL: 7 | TREND: better | WHY: up a rook", (5.0, "better", "up a rook")),          # clipped to +5
    ("EVAL: about even | TREND: same | WHY: equal", (None, "same", "equal")),             # number malformed
    ("no assessment at all", (None, None, None))])
def test_parse_assessment(line, expected):
    assert match.parse_assessment(f"THREATS: none\n{line}\nMOVE: Kf3") == expected

def test_parse_cited_keeps_only_shown_ids():
    reply = "PLAN: push the d-pawn, using R09 and L004 (and R99)\nEVAL: +1 | TREND: same | WHY: x\nMOVE: d6"
    assert match.parse_cited(reply, {"R09", "L004"}) == ["R09", "L004"]
    assert match.parse_cited("PLAN: none apply\nMOVE: d6", {"R09"}) == []

# --- the prompt and the move ------------------------------------------------------------------------------

@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(match, "rule_list", knowledge.load_rules(knowledge.SEEDS_DIR))
    monkeypatch.setattr(match, "lessons", [lesson("L004", "endgame", ["passed_pawn"])])
    monkeypatch.setattr(match, "rules", "- old rule")
    monkeypatch.setattr(match, "log", lambda text: None)

def test_full_prompt_order_and_content(setup):
    prompt, retrieved, shown, phase = match.build_prompt(ROOK_ENDING)
    order = ["You are playing White against Stockfish at skill", "Moves so far:", "ALWAYS - your general rules:",
             "FOR THIS POSITION: endgame", "ENDGAME - in this phase:", "Reference - ", "THREATS:", "FORCING:",
             "CANDIDATES:", "PLAN:", "EVAL:", "MOVE:"]
    positions = [prompt.index(text) for text in order]
    assert positions == sorted(positions)
    assert "most strongest" not in prompt and "[L004] When: tL004. Check: cL004" in prompt
    assert retrieved == ["L004"] and "R01" in shown and phase == "endgame"

def test_no_endgame_block_in_middlegame_or_when_off(setup, monkeypatch):
    assert "ENDGAME - in this phase" not in match.build_prompt(chess.Board())[0]
    monkeypatch.setattr(match, "ENDGAME_MODE", False)
    assert "ENDGAME - in this phase" not in match.build_prompt(ROOK_ENDING)[0]

def test_basic_prompt_is_the_old_one(setup, monkeypatch):
    monkeypatch.setattr(match, "PROTOCOL", "basic")
    prompt, retrieved, shown, _ = match.build_prompt(ROOK_ENDING)
    assert "most strongest chess player" in prompt and "- old rule" in prompt and "THREATS:" not in prompt
    assert retrieved == [] and shown == set()

def test_claude_move_effort_and_missing_eval(setup, monkeypatch):
    calls, reply = [], {"text": "PLAN: R09\nMOVE: Ra2"}   # no EVAL line: accepted, no retry
    def fake(prompt, timeout=None, effort=None):
        calls.append(effort)
        match.last_call = dict(seconds=2.0, tokens_in=100, tokens_out=50, cost=0.01)
        return reply["text"]
    monkeypatch.setattr(match, "ask_claude", fake)
    move = match.claude_move(ROOK_ENDING)
    assert ROOK_ENDING.san(move) == "Ra2" and calls == ["high"]
    assert match.last_move["self_eval"] is None and match.last_move["cited"] == ["R09"] and match.last_move["attempts"] == 1
    calls.clear()
    reply["text"] = "MOVE: e4"
    match.claude_move(chess.Board())
    assert calls == ["medium"]

# --- endgame references -------------------------------------------------------------------------------------

def test_endgame_refs_are_valid():
    refs = knowledge.load_jsonl(match.ENDGAME_REFS)
    assert len(refs) >= 10
    for r in refs:
        board = chess.Board(r["fen"])
        assert board.is_valid() and not board.is_game_over(), r["name"]
        assert r["principle"] and r["plan"]

def test_closest_refs():
    refs = knowledge.load_jsonl(match.ENDGAME_REFS)
    names = [r["name"] for r in features.closest_refs(chess.Board("8/8/3k4/8/3PK3/8/8/8 w - - 0 50"), refs)]
    assert names[0] in ("Opposition", "Rule of the square")
    rook = [r["name"] for r in features.closest_refs(chess.Board("8/3k4/8/3P4/3K4/8/r7/7R w - - 0 50"), refs)]
    assert rook[0] in ("Lucena position", "Philidor defence")
