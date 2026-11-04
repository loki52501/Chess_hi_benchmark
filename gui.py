import tkinter as tk, threading, queue, time, chess
import match, learn   # reuses claude_move, play_game, the log file etc. + learning after the game

SQ = 64          # size of one square in pixels
MOVE_DELAY = 2   # seconds to pause after every move, so you can follow the game
PIECES = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
          "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}
updates = queue.Queue()   # the game thread puts messages here, the window reads them

# everything match.py logs (Claude's thinking, moves) also goes to the window
file_log = match.log
def gui_log(text):
    file_log(text)
    updates.put(("text", text))
match.log = gui_log

def draw(board):
    canvas.delete("all")
    last = board.peek() if board.move_stack else None
    for sq in chess.SQUARES:
        col, row = chess.square_file(sq), 7 - chess.square_rank(sq)   # row 0 = top = rank 8
        color = "#f0d9b5" if (col + row) % 2 == 0 else "#b58863"
        if last and sq in (last.from_square, last.to_square):
            color = "#cdd26a"   # highlight the last move
        x, y = col * SQ, row * SQ
        canvas.create_rectangle(x, y, x + SQ, y + SQ, fill=color, outline="")
        piece = board.piece_at(sq)
        if piece:
            canvas.create_text(x + SQ / 2, y + SQ / 2, text=PIECES[piece.symbol()], font=("Segoe UI Symbol", 40))

def on_move(board):   # called by play_game (in the game thread) after every move
    updates.put(("board", board.copy()))
    time.sleep(MOVE_DELAY)   # wait before the next player moves

def poll():   # runs every 100 ms in the window thread
    while not updates.empty():
        kind, data = updates.get()
        if kind == "board":
            draw(data)
        else:
            log_box.insert("end", data + "\n")
            log_box.see("end")   # auto-scroll to the newest text
    root.after(100, poll)

root = tk.Tk()
root.title("Claude vs Stockfish")
canvas = tk.Canvas(root, width=8 * SQ, height=8 * SQ)
canvas.pack(side="left")
log_box = tk.Text(root, width=60, wrap="word", font=("Consolas", 10))
log_box.pack(side="right", fill="both", expand=True)
draw(chess.Board())

def run():   # play one game, then learn from it (the new rules show up in the right panel)
    i = match.next_game_number()
    match.play_game(on_move, i=i)
    learn.learn_from_game(i)

# the game runs in a background thread so the window doesn't freeze while Claude thinks
threading.Thread(target=run, daemon=True).start()
poll()
root.mainloop()
