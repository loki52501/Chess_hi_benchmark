"""The move prompts. "basic" = the old prompt (kept for A/B tests), "full" = the forcing structure with rules and lessons."""
import chess
from xml.sax.saxutils import escape
import knowledge

ENDGAME_PRINCIPLES = """ENDGAME - in this phase:
- Activate the king first: bring it toward the center and the pawns.
- Create a passed pawn or push the one you have; stop the enemy's.
- Rule of the square: a king catches a passed pawn only if it can step into the pawn's square.
- Opposition: in king and pawn endings, stand opposite the enemy king with one square between, with the enemy to move.
- Rooks belong behind passed pawns, yours and the enemy's.
- In any pawn race, count the tempi for both sides: who moves first, and does a new queen give check?
- Don't trade into a lost pawn ending: count the pawn ending out before trading the last pieces."""

ANSWER_FORMAT = """Answer in exactly this structure, each section short (about 6 lines at most):
THREATS: the opponent's checks, captures and threats now
FORCING: my checks, captures and threats
CANDIDATES: 2 or 3 moves, each with the opponent's best reply
PLAN: one line, the long-term plan; name the R/L ids you used, or "none apply"; if your own assessments have been sliding or the plan hasn't made progress in 5 moves, say so and change the plan
EVAL: <-5.0 to +5.0 in pawns, from my side> | TREND: better|same|worse | WHY: <one short reason>
MOVE: <move copied exactly from the legal moves list>"""

def color_name(color):
    return "White" if color == chess.WHITE else "Black"

def position_block(board):
    legal = [board.san(m) for m in board.legal_moves]
    history = chess.Board().variation_san(board.move_stack) or "(none - game start)"
    return (f"Moves so far: {history}\n"
            f"Board (uppercase = White, lowercase = Black):\n{board}\n"
            f"FEN: {board.fen()}\n"
            f"Legal moves: {', '.join(legal)}\n")

def basic_prompt(board, rules_text):   # the old prompt
    return (f"You are playing {color_name(board.turn)} in a chess game against the most strongest chess player in the world, "
            "prepare your move expecting the worst.\n"
            + (f"Rules you learned from your previous games - follow them:\n{rules_text}\n" if rules_text else "")
            + position_block(board) + "\n"
            "First think: describe the position and your thought on what you should do.\n"
            "Then finish with one last line in exactly this format:\n"
            "MOVE: <move>\n"
            "where <move> is copied exactly from the legal moves list.")

def assessments_block(assessments):   # Claude's own EVAL/TREND/WHY from its last moves - never anything from the engine
    if not assessments:
        return ""
    evaluation = lambda a: "?" if a["self_eval"] is None else f"{a['self_eval']:+.1f}"
    lines = "\n".join(f"  {a['move_number']}. {evaluation(a)} {a['trend'] or '?'} - {a['why'] or '(no reason given)'}"
                      for a in assessments)
    return ("Your own assessments from your last moves:\n" + lines + "\n"
            "If your assessments have been sliding, or your plan hasn't produced progress in 5 moves, "
            "say so in PLAN and change the plan.\n\n")

def full_prompt(board, skill, rules, lessons, header, refs=(), endgame=False, assessments=()):
    always = "\n".join(f"[{r['id']}] {r['rule']} | CHECK: {r['check']}" for r in rules) or "(none)"
    specific = "\n".join(f"[{l['id']}] When: {l['trigger'].rstrip('.')}. Check: {l['check']}" for l in lessons) or "(no lessons fit this position yet)"
    end = ""
    if endgame:
        end = ENDGAME_PRINCIPLES + "\n" + "".join(
            f"Reference - {r['name']}: FEN {r['fen']}\n  Principle: {r['principle']}\n  Plan: {r['plan']}\n" for r in refs) + "\n"
    return (f"You are playing {color_name(board.turn)} against Stockfish at skill {skill}. "
            "It is strong but makes small inaccuracies; look to punish them.\n\n"
            + position_block(board) + "\n"
            f"ALWAYS - your general rules:\n{always}\n\n"
            f"FOR THIS POSITION: {header}\n{specific}\n\n"
            + end + assessments_block(assessments) + ANSWER_FORMAT)

# --- "principles" mode: the same content as XML, so each part of the prompt is unambiguous for the model -------------

XML_ANSWER_FORMAT = """<answer_format>
Go through <principles> from top to bottom: for each one whose <when> is true in <position>, answer its <check> for your
candidate move. A candidate that fails a check is dropped or fixed first. Then answer in exactly this structure, each
section short (about 6 lines at most), as plain lines, not XML:
THREATS: the opponent's checks, captures and threats now
FORCING: my checks, captures and threats
CANDIDATES: 2 or 3 moves, each with the opponent's best reply
PLAN: one line, the long-term plan; name the principle ids (R..) whose <when> was true and that you used, or "none apply"; if your own assessments have been sliding or the plan hasn't made progress in 5 moves, say so and change the plan
EVAL: <-5.0 to +5.0 in pawns, from my side> | TREND: better|same|worse | WHY: <one short reason>
MOVE: <move copied exactly from the legal moves list>
</answer_format>"""

def xml_prompt(board, skill, principles, header, refs=(), endgame=False, assessments=()):
    legal = [board.san(m) for m in board.legal_moves]
    history = chess.Board().variation_san(board.move_stack) or "(none - game start)"
    parts = [f"<task>You are playing {color_name(board.turn)} against Stockfish at skill {skill}. Choose your next move. "
             "It is strong but makes small inaccuracies; look to punish them.</task>",
             "<position>\n"
             f"  <moves_so_far>{escape(history)}</moves_so_far>\n"
             f'  <board note="uppercase = White, lowercase = Black">\n{board}\n  </board>\n'
             f"  <fen>{board.fen()}</fen>\n"
             f"  <summary>{escape(header)}</summary>\n"
             f"  <legal_moves>{escape(', '.join(legal))}</legal_moves>\n"
             "</position>",
             knowledge.format_principles(principles, note="learned from all your earlier games: what the winners did and why the "
                                         "loser lost. In order of priority").rstrip()]
    if endgame:
        parts.append("<endgame>\n" + escape(ENDGAME_PRINCIPLES) + "\n" + "".join(
            f'  <reference name="{escape(r["name"])}">\n    <fen>{r["fen"]}</fen>\n    <principle_here>{escape(r["principle"])}</principle_here>\n'
            f'    <plan>{escape(r["plan"])}</plan>\n  </reference>\n' for r in refs) + "</endgame>")
    if assessments:
        evaluation = lambda a: "?" if a["self_eval"] is None else f"{a['self_eval']:+.1f}"
        parts.append('<my_recent_assessments note="your own, never the engine\'s. If they have been sliding, or your plan '
                     'has not made progress in 5 moves, say so in PLAN and change the plan">\n' + "".join(
            f'  <assessment move="{a["move_number"]}" eval="{evaluation(a)}" trend="{a["trend"] or "?"}">'
            f'{escape(a["why"] or "(no reason given)")}</assessment>\n' for a in assessments) + "</my_recent_assessments>")
    return "\n\n".join(parts + [XML_ANSWER_FORMAT])
