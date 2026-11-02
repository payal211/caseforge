"""python -m caseforge.harness <command>
  new-pack NAME        scaffold a runnable no-code industry pack
  check-pack NAME|DIR  validate it and run its scenarios plus injection attacks
  sandbox-setup        download the sandbox image (needs a container runtime)
  sandbox-check        self-test: network, filesystem, memory, time and root restrictions
  evals                run every pack's scenarios and all attacks (CI gate)"""
import sys
from pathlib import Path

from ..core import config
from .checks import check_pack
from .evals import main as evals_main
from .scaffold import PACKS_DIR, new_pack


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config.LLM_MODE = "mock"
    if len(argv) >= 2 and argv[0] == "new-pack":
        root = new_pack(argv[1])
        print(f"created {root}\nnext: python -m caseforge.harness check-pack {argv[1]}")
        return 0
    if len(argv) >= 2 and argv[0] == "check-pack":
        root = Path(argv[1]) if Path(argv[1]).exists() else PACKS_DIR / argv[1]
        res = check_pack(root)
        for r in res:
            print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['name']}" + ("" if r["pass"] or not r["detail"] else f": {r['detail']}"))
        ok = all(r["pass"] for r in res)
        print("\npack is ready" if ok else "\nfix the FAIL lines above")
        return 0 if ok else 1
    if argv[:1] == ["sandbox-setup"]:
        import subprocess
        from .sandbox import INSTALL_HINT, Sandbox
        sb = Sandbox(enabled=True)
        if not sb.cmd:
            print("No container runtime found. " + INSTALL_HINT)
            return 1
        print(f"pulling {sb.cfg.image} with {sb.runtime_name} ...")
        return subprocess.run([*sb.cmd, "pull", sb.cfg.image]).returncode
    if argv[:1] == ["sandbox-check"]:
        from .sandbox import Sandbox, self_test
        sb = Sandbox(enabled=True)
        ok, why = sb.status(fresh=True)
        print(("READY: " if ok else "NOT READY: ") + why)
        if not ok:
            return 1
        res = self_test(sb)
        for r in res:
            print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['name']}" + ("" if r["pass"] else f"   ({r['detail']})"))
        good = all(r["pass"] for r in res)
        print("\nsandbox is safe to enable: set CASEFORGE_SANDBOX=on and CASEFORGE_AGENTIC=on" if good else "\ndo NOT enable the sandbox until every line passes")
        return 0 if good else 1
    if argv[:1] == ["evals"]:
        return evals_main()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
