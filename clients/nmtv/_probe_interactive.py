# Interactive pin minimisation for the NM-TV-MINER v1.0 display - RUN THIS YOURSELF:
#
#   & D:\Projects\ESP\.venv\Scripts\python.exe clients\nmtv\_probe_interactive.py
#
# The display combo is already confirmed (SCK=14 MOSI=13 mode0 DC=19 CS=21, all other pins
# high). This run finds WHICH of those other pins the panel actually needs held high (its
# reset / enable) by ADDITIVE delta-debugging: every test configures a fresh, deterministic
# pin state (trial pins driven HIGH, all other candidates actively pulled LOW), fully
# re-initialises the panel with generous delays, toggles black/white, and asks you. A failed
# test cannot poison the next one, unlike the previous subtractive version.
#
# Requires the updated probe_one.py on the device (already copied).

import time

import serial

PORT = "COM5"
SCK, MOSI, MODE, DC, CS = 14, 13, 0, 19, 21
POOL = [0, 2, 4, 5, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33]


class RawRepl:
    def __init__(self, port):
        self.s = serial.Serial(port, 115200, timeout=2)
        time.sleep(0.2)
        self.s.write(b"\r\x03\x03")
        time.sleep(0.3)
        self.s.reset_input_buffer()
        self.s.write(b"\r\x01")
        time.sleep(0.3)
        self.s.reset_input_buffer()

    def exec(self, code, timeout=8):
        self.s.write(code.encode() + b"\x04")
        buf = b""
        end = time.time() + timeout
        while time.time() < end:
            n = self.s.in_waiting
            buf += self.s.read(n if n else 1)
            if buf.endswith(b"\x04>"):
                break
        if b"Traceback" in buf:
            raise RuntimeError(buf.decode("utf-8", "replace"))
        return buf

    def close(self):
        try:
            self.exec("probe_one.release()")
        except Exception:
            pass
        self.s.write(b"\r\x02")
        self.s.close()


def main():
    print("Connecting to", PORT, "...")
    r = RawRepl(PORT)
    r.exec("import probe_one")

    candidates = [n for n in POOL if n not in (SCK, MOSI, DC, CS)]
    asked = 0

    def test(high_subset, label):
        """Fresh state: DC/CS + high_subset driven high, everything else pulled low."""
        nonlocal asked
        asked += 1
        high = sorted(set(high_subset) | {DC, CS})
        r.exec("probe_one.setup_sets(%d, %d, %d, %r)" % (SCK, MOSI, MODE, high))
        # throwaway init (panels can need one after a hard reset release), then visible toggles
        r.exec("probe_one.probe(%d, %d, False)" % (DC, CS))
        time.sleep(0.3)
        for white in (True, False, True):
            r.exec("probe_one.probe(%d, %d, %s)" % (DC, CS, white))
            time.sleep(0.6)
        ans = input("  [%d] %s - did the screen toggle black/white? [y/Enter/q] "
                    % (asked, label)).strip().lower()
        if ans == "q":
            raise KeyboardInterrupt
        return ans == "y"

    print()
    print("Answer y (worked) / Enter (didn't) to each question. Screen shows a fresh")
    print("black->white->black->white toggle before every question.")
    print()

    # sanity anchors
    if not test(candidates, "ALL extra pins high (known-good sanity check)"):
        print("The known-good config failed?! Re-seat things and re-run; tell Claude if it persists.")
        r.close()
        return
    if test([], "NO extra pins high (expected to fail)"):
        print()
        print("Surprise: no extra pins are needed at all. The lean driver failure was something")
        print("else - paste this to Claude: REQUIRED = (none), minimal works.")
        r.close()
        return

    # ddmin: shrink the set of extra pins while it still works
    pool = candidates[:]
    chunk = max(1, len(pool) // 2)
    while chunk >= 1:
        i = 0
        while i < len(pool):
            trial = pool[:i] + pool[i + chunk:]
            dropped = pool[i:i + chunk]
            label = "without GPIO " + ", ".join(str(n) for n in dropped)
            if test(trial, label):
                pool = trial          # dropped pins weren't needed
            else:
                i += chunk            # something in `dropped` is needed; keep it, move on
        chunk //= 2

    print()
    print("Minimal required-high set found: %s" % (", ".join("GPIO%d" % n for n in pool) or "(none)"))
    print("Final confirmation with exactly that set...")
    ok = test(pool, "FINAL: only required pin(s) high")

    print()
    print("*** RESULT - paste this back to Claude ***")
    print("  SCK=GPIO%d MOSI=GPIO%d mode=%d DC=GPIO%d CS=GPIO%d" % (SCK, MOSI, MODE, DC, CS))
    print("  REQUIRED-HIGH:", ", ".join("GPIO%d" % n for n in pool) if pool else "(none)")
    print("  Final confirmation:", "PASS" if ok else "FAIL")
    r.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nQuit.")
