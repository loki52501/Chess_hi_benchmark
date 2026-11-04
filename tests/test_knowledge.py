import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # so "import knowledge" finds the repo files
import knowledge

GOOD = dict(rule="When the enemy has a passed pawn on the 6th, put a piece on its promotion square first.",
            trigger="enemy passed pawn on my 3rd rank", check="Is a piece of mine on the promotion square? If not, put one there.",
            phase="endgame", motifs=["passed_pawn"], features=["enemy_passer_6th"])

def test_seed_rules_follow_the_format():
    rules = knowledge.load_rules(knowledge.SEEDS_DIR)
    assert 0 < len(rules) <= knowledge.MAX_RULES
    assert [r["id"] for r in rules] == [f"R{n:02d}" for n in range(1, len(rules) + 1)]
    for r in rules:
        assert knowledge.words(r["rule"]) <= knowledge.MAX_RULE_WORDS, r["id"]
        assert knowledge.CHESS_NOUN.search(r["rule"]), r["id"]
        assert r["check"].endswith("?"), r["id"]

def test_rules_round_trip(tmp_path):
    rules = [dict(id="R01", rule="Keep the king behind its pawns.", check="Is my king behind its pawns?")]
    knowledge.save_rules(tmp_path, rules)
    assert knowledge.load_rules(tmp_path) == rules

def test_good_lesson_passes():
    assert knowledge.problems_with(GOOD) == []

def test_lesson_problems():
    assert knowledge.problems_with(dict(GOOD, rule="Be careful in endgames.")) == ["rule names no piece, pawn, square, file or king"]
    assert "missing trigger" in knowledge.problems_with(dict(GOOD, trigger=""))
    assert any("motifs" in p for p in knowledge.problems_with(dict(GOOD, motifs=["tactics"])))
    assert any("phase" in p for p in knowledge.problems_with(dict(GOOD, phase="late")))
    long_rule = "Move the king toward the pawns " + "and then keep it there " * 5 + "near the e4 pawn."
    assert any("words" in p for p in knowledge.problems_with(dict(GOOD, rule=long_rule)))

def test_pattern_not_squares():
    square_rule = dict(GOOD, rule="With my king on b1 and an enemy bishop on b4, play Bd4 to guard the pawns.")
    assert any("exact squares (b1, b4, d4)" in p for p in knowledge.problems_with(square_rule))
    example_rule = dict(GOOD, rule="Never leave my queen and a rook forkable by one enemy knight, e.g. Qc3 and Re3 from d5.")
    assert knowledge.problems_with(example_rule) == []
    assert any("e.g." in p for p in knowledge.problems_with(dict(GOOD, rule="Attack the pinned knight, e.g. Bg5, e.g. h4.")))
    assert any("trigger names exact squares (a1, h8)" in p for p in knowledge.problems_with(dict(GOOD, trigger="my queen on the a1-h8 diagonal")))
    assert knowledge.problems_with(dict(GOOD, trigger="my queen on the long diagonal pins a knight to its rook")) == []
    assert "missing features" in knowledge.problems_with(dict(GOOD, features=[]))

def test_partial_update_checks_only_given_fields():
    assert knowledge.problems_with({"check": "Is my rook behind the pawn?"}, fields=["check"]) == []
    assert knowledge.problems_with({"rule": "Think harder."}, fields=["rule"]) == ["rule names no piece, pawn, square, file or king"]

def test_ids_are_never_reused():
    lessons = [dict(id="L001"), dict(id="L007", status="retired")]
    assert knowledge.next_lesson_id(lessons) == "L008"
    assert knowledge.next_rule_id([dict(id="R03")], {"R11": {}}) == "R12"

def test_help_rate():
    assert knowledge.help_rate(dict(retrieved=0, helped=0)) is None
    assert knowledge.help_rate(dict(retrieved=4, helped=3)) == 0.75

def test_init_new_folder_both_modes(tmp_path):
    new, old = tmp_path / "new", tmp_path / "old"
    knowledge.init_folder(new, "lessons")
    assert knowledge.load_rules(new) == knowledge.load_rules(knowledge.SEEDS_DIR)
    assert knowledge.load_lessons(new) == [] and set(knowledge.load_stats(new)) == {r["id"] for r in knowledge.load_rules(new)}
    knowledge.init_folder(old, "rules")
    assert (old / "rules.md").read_text(encoding="utf-8") == (open(os.path.join(knowledge.SEEDS_DIR, "rules_legacy.md"), encoding="utf-8").read())
    assert not (old / "lessons.jsonl").exists()

def test_migrate_current_rules(tmp_path):
    legacy = open(os.path.join(knowledge.SEEDS_DIR, "rules_legacy.md"), encoding="utf-8").read()
    (tmp_path / "rules.md").write_text(legacy, encoding="utf-8")
    rules = knowledge.migrate(tmp_path)
    assert (tmp_path / "rules_legacy.md").read_text(encoding="utf-8") == legacy
    assert rules == knowledge.load_rules(knowledge.SEEDS_DIR) == knowledge.load_rules(tmp_path)
    assert knowledge.load_lessons(tmp_path) == [] and (tmp_path / "lessons.jsonl").exists()

def test_migrate_other_old_list(tmp_path):
    (tmp_path / "rules.md").write_text("- Keep rooks on open files.\n- Push passed pawns.\n", encoding="utf-8")
    rules = knowledge.migrate(tmp_path)
    assert [r["id"] for r in rules] == ["R01", "R02"] and rules[0]["rule"] == "Keep rooks on open files."
