import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # so "import experiment" finds the repo files
import chess, chess.pgn, pytest
import match, experiment, parallel

def test_outcome_from_claudes_side():
    assert match.outcome("1-0", chess.WHITE) == "win" and match.outcome("1-0", chess.BLACK) == "loss"
    assert match.outcome("0-1", chess.BLACK) == "win" and match.outcome("1/2-1/2", chess.BLACK) == "draw"
    assert match.outcome("*", chess.WHITE) == "*"

def test_players_and_pgn_follow_claude_color(tmp_path, monkeypatch):
    monkeypatch.setattr(match, "GAMES_DIR", str(tmp_path))
    monkeypatch.setattr(match, "CLAUDE_COLOR", chess.BLACK)
    assert match.players().startswith("Stockfish") and match.players().endswith("(Black)")
    match.save_pgn(1, chess.Board())
    headers = chess.pgn.read_headers(open(tmp_path / "game_1.pgn"))
    assert headers["White"].startswith("Stockfish") and headers["Black"].startswith("Claude")

@pytest.mark.skipif(not os.path.exists(match.STOCKFISH), reason="Stockfish not found")
def test_resume_a_game_stopped_halfway(tmp_path, monkeypatch):
    monkeypatch.setattr(match, "GAMES_DIR", str(tmp_path))
    monkeypatch.setattr(match, "log", lambda text: match.log_file(text))   # keep the test output quiet
    calls = {"n": 0, "seen": []}
    def fake(board):
        calls["n"] += 1
        calls["seen"].append(list(match.assessments))
        if calls["n"] == 4:
            raise KeyboardInterrupt   # stopped while Claude is thinking about its 4th move
        match.last_move = dict(retrieved=[], cited=[], self_eval=0.5, trend="same", why=f"move {calls['n']}")
        return sorted(board.legal_moves, key=str)[0]
    monkeypatch.setattr(match, "claude_move", fake)
    with pytest.raises(KeyboardInterrupt):
        match.play_game(i=1)
    before = list(chess.pgn.read_game(open(tmp_path / "game_1.pgn")).mainline_moves())
    assert len(before) == 6 and chess.pgn.read_headers(open(tmp_path / "game_1.pgn"))["Result"] == "*"
    calls["seen"].clear()
    match.play_game(i=1, resume=True)
    after = list(chess.pgn.read_game(open(tmp_path / "game_1.pgn")).mainline_moves())
    assert after[:6] == before and len(after) > 6                               # went on from the same position
    assert [a["why"] for a in calls["seen"][0]] == ["move 1", "move 2", "move 3"]   # Claude's own assessments came back
    plies = [m["ply"] for m in match.knowledge.load_jsonl(str(tmp_path / "moves_1.jsonl"))]
    assert plies == sorted(set(plies)) and plies[:4] == [1, 3, 5, 7]           # no duplicate or lost move lines
    assert "resumed after 6 half-moves" in (tmp_path / "game_1.log").read_text()

def test_configs_differ_only_in_what_they_add():
    m = {name: c["match"] for name, c in experiment.CONFIGS.items()}
    assert m["baseline"]["PROTOCOL"] == "basic" and m["baseline"]["LEARN_MODE"] == "rules"
    assert m["review"]["LEARN_MODE"] == "lessons" and m["review"]["PROTOCOL"] == "basic"
    assert m["protocol"]["PROTOCOL"] == "full" and m["protocol"]["SELF_ASSESSMENT"] and not m["protocol"]["ENDGAME_MODE"]
    assert m["full"]["ENDGAME_MODE"] and m["full"]["CLAUDE_EFFORT_ENDGAME"] == "high"
    assert experiment.with_folder("full")["match"]["GAMES_DIR"] == "games_full"
    assert "GAMES_DIR" not in experiment.CONFIGS["full"]["match"]   # with_folder doesn't change the config itself

def test_apply_sets_module_constants(monkeypatch):
    monkeypatch.setattr(match, "PROTOCOL", "full")
    parallel.apply({"match": {"PROTOCOL": "basic"}})
    assert match.PROTOCOL == "basic"

def fake_game(folder, i, claude_white, result, counts, moves, accuracy, mae=None, slides=0):
    side = dict(player="Claude", moves=moves, accuracy=accuracy,
                accuracy_by_phase={"opening": 95.0, "middlegame": accuracy, "endgame": None},
                counts=dict({c: 0 for c in ("Book", "Great", "Best", "Excellent", "Good", "Inaccuracy", "Mistake", "Miss", "Blunder")}, **counts))
    other = dict(side, player="Stockfish")
    sides = {"white": side, "black": other} if claude_white else {"white": other, "black": side}
    json.dump(dict(sides=sides, calibration=dict(mae=mae, missed_slides=[{}] * slides)), open(folder / f"review_{i}.json", "w"))
    claude, sf = "Claude (test)", "Stockfish (skill 10)"
    (folder / f"game_{i}.pgn").write_text(f'[White "{claude if claude_white else sf}"]\n[Black "{sf if claude_white else claude}"]\n'
                                          f'[Result "{result}"]\n\n{result}\n')
    with open(folder / f"moves_{i}.jsonl", "w") as f:
        for _ in range(2):
            f.write(json.dumps(dict(tokens_in=1000, tokens_out=200, cost=0.02, seconds=10)) + "\n")

def test_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "games_full"
    folder.mkdir()
    fake_game(folder, 1, True, "0-1", {"Inaccuracy": 3, "Mistake": 1, "Great": 2}, moves=40, accuracy=90.0, mae=1.0, slides=1)
    fake_game(folder, 2, False, "0-1", {"Inaccuracy": 1, "Miss": 1}, moves=20, accuracy=80.0, mae=2.0)   # Claude Black: a WIN
    rows = experiment.summarize(["full", "baseline"])                                                   # baseline has no folder
    assert len(rows) == 1
    r = rows[0]
    assert (r["wins"], r["draws"], r["losses"]) == (1, 0, 1) and r["score"] == 0.5
    assert r["accuracy"] == 85.0 and r["accuracy_std"] == pytest.approx(7.07, abs=0.01)
    assert r["inacc_mistakes_per_40"] == pytest.approx((4 + 2) / 2)        # 4 per 40 moves, and 1 in 20 moves = 2 per 40
    assert r["great"] == 1 and r["miss"] == 0.5 and r["calibration_mae"] == 1.5 and r["missed_slides"] == 0.5
    assert r["acc_endgame"] is None and r["tokens_per_move"] == 1200 and r["cost_per_move"] == pytest.approx(0.02)
    assert (tmp_path / "experiments" / "summary.csv").exists()
    assert "| full | 2 | 1/0/1 |" in (tmp_path / "experiments" / "summary.md").read_text()
