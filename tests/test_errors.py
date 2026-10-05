"""Errors nobody planned for: logged, scrubbed, and put in front of the user.

The release is a windowed build with no console. Before these hooks, an
exception in a button, a background thread or at startup went nowhere: the
button did nothing and there was nothing to report. No dialog is shown here
and the real clipboard is never touched.
"""
import contextlib
import io
import os
import sys
import threading

from helpers import Checker, hidden_tk, sandbox

SB = sandbox("errors")
root, pump, _ = hidden_tk()
import palmods_gui as G                    # noqa: E402
import palpaths                            # noqa: E402

check = Checker()
home = os.path.expanduser("~")
log = palpaths.data_dir() / "error.log"
shown = []


class FakeDialog:
    def __init__(self, master, details, log):
        shown.append((details, log))

    def wait_window(self):
        pass


real_dialog = G.ErrorDialog
G.ErrorDialog = FakeDialog
reporter = G.ErrorReporter()
reporter.attach(root)
# A crash in this script should still print; the app's hook is called by hand.
sys.excepthook = sys.__excepthook__


def log_text():
    return log.read_text("utf8") if log.is_file() else ""


def entries():
    return sum(1 for ln in log_text().splitlines() if ln.startswith("=== "))


@contextlib.contextmanager
def console():
    """The hooks echo to a console when there is one; catch that here."""
    sys.stderr = io.StringIO()
    try:
        yield sys.stderr
    finally:
        sys.stderr = sys.__stderr__


# ==========================================================================
check.section("the home folder never leaves the machine")
for raw in (home + r"\AppData\Local\x.json",
            home.replace("\\", "\\\\") + r"\\AppData\\x.json",
            home.replace("\\", "/") + "/x.json",
            home.upper() + r"\x.json"):
    out = G.scrub(raw)
    check(f"{raw[:40]}... -> %USERPROFILE%",
          out.startswith("%USERPROFILE%") and "x.json" in out, out)
check("a folder that only starts with the same name is left alone",
      G.scrub(home + "2\\x") == home + "2\\x")

# ==========================================================================
check.section("a button that fails")


def broken_button():
    raise PermissionError(13, "Access is denied",
                          os.path.join(home, "AppData", "registry.json"))


with console() as out:
    root.after(0, broken_button)
    pump(0.2)
text = log_text()
check("run from a console, it's printed there too", "PermissionError" in out.getvalue())
check("the traceback is in error.log",
      "PermissionError" in text and "broken_button" in text, text[-300:])
check("the user is told", len(shown) == 1 and "PermissionError" in shown[0][0])
check("the dialog knows where the log is", shown and shown[0][1] == log)
check("no trace of the home folder, even repr()'d, in the log or the details",
      not any(h.lower() in s.lower() for h in (home, home.replace("\\", "\\\\"))
              for s in (text, shown[0][0])) and "%USERPROFILE%" in shown[0][0])

with console():
    root.after(0, broken_button)
    pump(0.2)
check("the same bug again isn't reported twice", len(shown) == 1 and entries() == 1,
      entries())

# ==========================================================================
check.section("a background thread that fails")


def broken_worker():
    raise ValueError("GitHub said something odd")


worker = threading.Thread(target=broken_worker, name="Fetch")
with console():
    worker.start()
    worker.join()
check("logged straight away", "GitHub said something odd" in log_text())
check("but not shown from the worker thread", len(shown) == 1)
pump(0.6)
check("the Tk thread shows it", len(shown) == 2
      and shown[1][0].startswith("In the Fetch thread")
      and "GitHub said something odd" in shown[1][0], shown[1:])

# ==========================================================================
check.section("when even error.log can't be written")
real_data_dir = palpaths.data_dir


def disk_gone():
    raise OSError("the disk went away")


palpaths.data_dir = disk_gone
with console():
    root.after(0, lambda: {}["missing key"])
    pump(0.2)
palpaths.data_dir = real_data_dir
check("the user is still told, with nothing claimed about a log",
      len(shown) == 3 and "KeyError" in shown[2][0] and shown[2][1] is None, shown[2:])

# ==========================================================================
check.section("the dialog")
G.ErrorDialog = real_dialog
copied = []
G.ErrorDialog.clipboard_clear = lambda self: copied.clear()
G.ErrorDialog.clipboard_append = lambda self, s: copied.append(s)


def texts(widget):
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        try:
            out.append(w.cget("text"))
        except Exception:
            pass
    return [t.strip() for t in out if isinstance(t, str) and t.strip()]


details = "Traceback (most recent call last):\nValueError: x"
d = G.ErrorDialog(root, details, log)
pump(0.1)
words = texts(d)
check("says what happened", "Something went wrong" in words, words)
check("and where the details went", "Details were saved to error.log." in words, words)
check("with a way to copy them, and to find the log",
      {"Copy details", "Show error.log", "Close"} <= set(words), words)
d.copy_btn.invoke()
check("Copy details copies exactly the details", copied == [details], copied)
check("and says so", d.copy_btn.cget("text").strip() == "Copied")
d.destroy()

d = G.ErrorDialog(root, details, None)
pump(0.1)
words = texts(d)
check("with no log it asks to copy them, and offers no log to show",
      any("couldn't be saved" in w for w in words) and "Show error.log" not in words,
      words)
d.destroy()

# ==========================================================================
check.section("a crash that stops the app")
G.ErrorDialog = FakeDialog
try:
    raise RuntimeError("Tcl couldn't start")
except RuntimeError:
    with console():
        reporter.fatal(*sys.exc_info())
check("logged and shown", "Tcl couldn't start" in log_text()
      and "Tcl couldn't start" in shown[-1][0])
try:
    root.winfo_exists()
    gone = False
except Exception:
    gone = True
check("Tk is closed down, so copied text outlives the app", gone)

# ==========================================================================
check.section("main() has the hooks in place before anything can fail")
import tkinter as tk                       # noqa: E402

made = []


class HiddenTk(tk.Tk):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.withdraw()
        made.append(self)


class Boom(Exception):
    pass


def failing_app(root, pending_install=None):
    raise Boom("the main window couldn't be built")


real_tk, real_app = G.tk.Tk, G.App
G.tk.Tk, G.App = HiddenTk, failing_app
try:
    with console():
        try:
            G.main()
        except Boom:
            sys.excepthook(*sys.exc_info())     # what the __main__ block does
finally:
    G.tk.Tk, G.App = real_tk, real_app
installed = sys.excepthook
check("sys.excepthook and threading.excepthook are the app's",
      getattr(installed, "__self__", None).__class__ is G.ErrorReporter
      and threading.excepthook is not threading.__excepthook__)
check("and so is the Tk root's report_callback_exception",
      made and made[0].report_callback_exception.__self__ is installed.__self__)
check("a crash while starting up is logged and shown",
      "the main window couldn't be built" in log_text()
      and "the main window couldn't be built" in shown[-1][0])

sys.excepthook = sys.__excepthook__
threading.excepthook = threading.__excepthook__
check.finish()
