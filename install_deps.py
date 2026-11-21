"""Installs the core requirements and reports exactly which package failed.

Usage:  python install_deps.py requirements.txt
Exit code 0 = everything installed, 1 = at least one package failed (install.bat then stops and says so).
"""
import subprocess
import sys

PIP = [sys.executable, "-m", "pip", "install", "--retries", "10", "--timeout", "60"]
DNS_MARKERS = ("failed to resolve", "nameresolutionerror", "getaddrinfo failed", "temporary failure in name resolution",
               "connection aborted", "max retries exceeded")


def read_requirements(path):
    items = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.split("#", 1)[0].strip()
            if line:
                items.append(line)
    return items


def run_pip(args, runner=None):
    """Run pip, stream its output live, return (returncode, full_output)."""
    if runner is not None:
        return runner(args)
    proc = subprocess.Popen(PIP + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    lines = []
    for line in proc.stdout:
        print(line, end="")
        lines.append(line)
    proc.wait()
    return proc.returncode, "".join(lines)


def install(path, runner=None, out=print):
    requirements = read_requirements(path)
    if not requirements:
        out(f"ERROR: no packages found in {path}")
        return 1
    code, text = run_pip(["-r", path], runner)
    if code == 0:
        return 0
    network = any(m in text.lower() for m in DNS_MARKERS)
    out("")
    out("Bulk install failed. Checking each package to find the one that failed...")
    failed = []
    for requirement in requirements:
        c, t = run_pip([requirement], runner)
        if c != 0:
            failed.append(requirement)
            network = network or any(m in t.lower() for m in DNS_MARKERS)
    out("")
    if failed:
        out("FAILED PACKAGES: " + ", ".join(failed))
    else:
        out("Each package installed on its own; the bulk install may have failed because of a temporary network error.")
        out("Run install.bat again.")
    if network:
        out("This looks like a DNS / internet problem (not a Kira bug).")
        out("Try: turn VPN on or off, change Windows DNS to 1.1.1.1 and 8.8.8.8, then run install.bat again.")
        out("To test, open CMD and run:  nslookup files.pythonhosted.org")
    return 1



if __name__ == "__main__":
    sys.exit(install(sys.argv[1] if len(sys.argv) > 1 else "requirements.txt"))
