"""Run the Claude-vs-Stockfish series in an E2B cloud sandbox, from your own computer.

    pip install e2b
    set E2B_API_KEY=...          (Windows; "export" on Linux/Mac)   from https://e2b.dev/dashboard
    Claude Code's login inside the sandbox - set ONE of these:
    set CLAUDE_CODE_OAUTH_TOKEN=...   your Claude subscription: run "claude setup-token" on this computer and copy the token
    set ANTHROPIC_API_KEY=...         or an API key (billed per token)
    The model is match.CLAUDE_MODEL (claude-opus-5-5); "set CLAUDE_MODEL=..." here to use another one.

    python e2b_run.py start      new sandbox: install Stockfish, clone the repo, upload games/, start series.py, then watch
    python e2b_run.py watch      keep an already started sandbox going (run this again if your computer slept)
    python e2b_run.py status     last lines of the series output
    python e2b_run.py pull       download the sandbox's games/ folder into ./games
    python e2b_run.py distill    learn principles from the games already there, without playing
    python e2b_run.py stop       pull, then delete the sandbox

The free E2B plan stops a sandbox after 1 hour of continuous running. "watch" pauses and resumes it every 50 minutes,
which starts the hour again; the running series survives the pause. If "watch" isn't running, the sandbox pauses itself
after 55 minutes and nothing is lost: run "watch" again to continue.
"""
import io, os, sys, tarfile, time
from e2b import Sandbox

REPO = "https://github.com/loki52501/Chess_hi_benchmark.git"
TEMPLATE = "claude"            # E2B's ready-made template with the Claude Code CLI installed
HOME = "/home/user"
WORK = f"{HOME}/chess"
ID_FILE = ".e2b_sandbox"       # remembers the sandbox between commands
LIFETIME = 55 * 60             # seconds until the sandbox pauses itself if nobody renews it
CHUNK = 50 * 60                # "watch" pauses + resumes this often, which restarts E2B's 1-hour clock
CHECK_EVERY = 5 * 60           # "watch" prints the progress and saves games/ this often
RUN = "STOCKFISH=/usr/games/stockfish python3 -u"

def sh(sbx, command, timeout=600, check=True):
    """Run a shell command in the sandbox; returns its output (stdout + stderr)."""
    try:
        result = sbx.commands.run(f"cd {WORK} 2>/dev/null; {command}", timeout=timeout)
        return (result.stdout or "") + (result.stderr or "")
    except Exception as error:   # a command that exits with an error code raises
        if check:
            raise
        return str(error)

def connect():
    if not os.path.exists(ID_FILE):
        sys.exit(f"No sandbox yet ({ID_FILE} not found). Run: python e2b_run.py start")
    return Sandbox.connect(open(ID_FILE).read().strip(), timeout=LIFETIME)   # also resumes a paused sandbox

def upload_games(sbx):
    if not os.path.isdir("games"):
        print("No local games/ folder: the sandbox starts from the seed rules.")
        return
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz") as tar:
        tar.add("games", filter=lambda item: None if "backup_before_fix" in item.name else item)
    sbx.files.write(f"{HOME}/games.tar.gz", packed.getvalue())
    sh(sbx, f"tar xzf {HOME}/games.tar.gz -C {WORK}")
    print(f"Uploaded games/ ({len(packed.getvalue()) / 1e6:.1f} MB)")

def pull(sbx):
    sh(sbx, f"tar czf {HOME}/games_out.tar.gz games")
    data = sbx.files.read(f"{HOME}/games_out.tar.gz", format="bytes")
    with tarfile.open(fileobj=io.BytesIO(bytes(data)), mode="r:gz") as tar:
        tar.extractall(".")
    print(f"Saved the sandbox's games/ into ./games ({len(data) / 1e6:.1f} MB)")

def running(sbx):
    return "series.py" in sh(sbx, "pgrep -af 'python3 -u series.py' || true", check=False)

def status(sbx):
    print(sh(sbx, "grep -a '#####' series.out | tail -3; echo ...; tail -n 12 series.out", check=False))

def launch(sbx, script):   # start a long job that keeps running after this command returns
    sbx.commands.run(f"cd {WORK} && nohup {RUN} {script} >> series.out 2>&1", background=True, timeout=0)

def start():
    if not os.environ.get("E2B_API_KEY"):
        sys.exit("Set E2B_API_KEY first (see the top of this file).")
    login = next((k for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY") if os.environ.get(k)), None)
    if not login:
        sys.exit("Set CLAUDE_CODE_OAUTH_TOKEN (subscription) or ANTHROPIC_API_KEY first (see the top of this file).")
    envs = {login: os.environ[login]}   # only one: Claude Code complains when both are set
    if os.environ.get("CLAUDE_MODEL"):
        envs["CLAUDE_MODEL"] = os.environ["CLAUDE_MODEL"]
    sbx = Sandbox.create(TEMPLATE, timeout=LIFETIME, envs=envs, lifecycle={"on_timeout": "pause"})
    with open(ID_FILE, "w") as f:
        f.write(sbx.sandbox_id)
    print(f"Sandbox {sbx.sandbox_id} created. Installing Stockfish and python-chess ...")
    sh(sbx, "sudo apt-get update -qq && sudo apt-get install -y -qq stockfish python3 python3-pip git", timeout=900)
    sh(sbx, "pip3 install -q chess || pip3 install -q --break-system-packages chess", timeout=600)
    sh(sbx, f"git clone --depth 1 {REPO} {WORK}")
    upload_games(sbx)
    print(sh(sbx, "/usr/games/stockfish --help 2>&1 | head -1; claude --version; "
                  "python3 -c \"import chess, match; print('python-chess', chess.__version__, '| stockfish:', match.STOCKFISH)\"",
             check=False))
    answer = sh(sbx, "python3 -c \"import match; print(match.CLAUDE_MODEL, '->', match.ask_claude('Reply with the single word OK', timeout=120))\"",
                timeout=180, check=False)
    print(f"Claude Code check ({login}): {answer.strip()}")
    if "OK" not in answer.split("->")[-1]:
        sys.exit("Claude Code did not answer inside the sandbox, so no game was started. Fix the login, then run\n"
                 "'python e2b_run.py stop' and 'python e2b_run.py start' again.")
    launch(sbx, "series.py")
    print("series.py started.")
    watch(sbx)

def watch(sbx):
    last_pause = time.time()
    try:
        while True:
            time.sleep(CHECK_EVERY)
            status(sbx)
            pull(sbx)
            if not running(sbx):
                print("The series is not running any more (finished, or it stopped with an error - see above).\n"
                      "The sandbox is still there: 'python e2b_run.py stop' deletes it.")
                return
            if time.time() - last_pause >= CHUNK:
                print("Pausing and resuming the sandbox to restart E2B's 1-hour clock ...")
                sbx.pause()
                sbx = connect()
                last_pause = time.time()
    except KeyboardInterrupt:
        print("\nStopped watching. The sandbox keeps playing until it pauses itself; 'python e2b_run.py watch' continues.")

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "start":
        start()
    elif command == "watch":
        sbx = connect()
        if not running(sbx):   # e.g. the claude call in flight was cut by a pause and the series ended
            launch(sbx, "series.py")
            print("series.py was not running; started it again (it continues from its checkpoint).")
        watch(sbx)
    elif command == "status":
        status(connect())
    elif command == "pull":
        pull(connect())
    elif command == "distill":
        sbx = connect()
        print(sh(sbx, f"{RUN} learn.py distill 2>&1 | tail -n 40", timeout=3600, check=False))
        pull(sbx)
    elif command == "stop":
        sbx = connect()
        pull(sbx)
        sbx.kill()
        os.remove(ID_FILE)
        print("Sandbox deleted.")
    else:
        sys.exit(__doc__)
