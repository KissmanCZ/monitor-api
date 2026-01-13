from flask import Flask, jsonify, request, render_template, redirect, url_for, flash
import subprocess
import re

app = Flask(__name__)
app.secret_key = "monitor-switcher-secret-key-change-in-production"

# ===== CONFIG (default) =====
BUS = "2"            # fallback, will try to autodetect from `ddcutil detect`
I2C_ADDR = "0x50"

VCP_INPUT_SELECT = "0xF4"

# ===== INPUT COMMANDS =====
INPUT_COMMANDS = {
    "dp1": [
        "ddcutil", "-b", BUS,
        "setvcp", VCP_INPUT_SELECT, "0x00D0",
        "--i2c-source-addr=" + I2C_ADDR
    ],
    "usbc": [
        "ddcutil", "-b", BUS,
        "setvcp", VCP_INPUT_SELECT, "0x00D1",
        "--i2c-source-addr=" + I2C_ADDR
    ],
    "hdmi1": [
        "ddcutil", "-b", BUS,
        "setvcp", VCP_INPUT_SELECT, "0x0090",
        "--i2c-source-addr=" + I2C_ADDR
    ],
    "hdmi2": [
        "ddcutil", "-b", BUS,
        "setvcp", VCP_INPUT_SELECT, "0x0091",
        "--i2c-source-addr=" + I2C_ADDR
    ],
}

# Optional state mapping (decimal strings)
INPUT_STATE_MAP = {
    "208": "dp1",   # 0xD0 -> 208
    "209": "usbc",  # 0xD1 -> 209
    "144": "hdmi1", # 0x90 -> 144
    "145": "hdmi2", # 0x91 -> 145
}


def run_ddcutil(cmd):
    """Run ddcutil command and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except Exception as e:
        return -1, "", str(e)


def parse_vcp_input_output(output):
    """
    Parse ddcutil getvcp output and return decimal string value if found, else None.
    Tries several common patterns.
    """
    if not output:
        return None

    m = re.search(r'current value\s*=\s*0x([0-9A-Fa-f]+)', output)
    if m:
        try:
            return str(int(m.group(1), 16))
        except ValueError:
            pass

    m = re.search(r'current value\s*=\s*(\d+)', output)
    if m:
        return m.group(1)

    m = re.search(r'sl=0x([0-9A-Fa-f]+)', output)
    if m:
        try:
            return str(int(m.group(1), 16))
        except ValueError:
            pass

    m = re.search(r'0x([0-9A-Fa-f]{1,4})', output)
    if m:
        try:
            return str(int(m.group(1), 16))
        except ValueError:
            pass

    return None


def get_monitor_info():
    """
    Run `ddcutil detect` (no -b) and extract monitor manufacturer and model, and I2C bus if possible.
    Returns (manufacturer_or_None, model_or_None, debug_string_or_None).
    Also updates the global BUS variable if an I2C bus is discovered.
    """
    global BUS
    rc, out, err = run_ddcutil(["ddcutil", "detect"])
    raw = (out + "\n" + err).strip()

    if rc != 0 and not raw:
        return None, None, f"ddcutil detect failed rc={rc}, err={err}"

    # Extract I2C bus path like "/dev/i2c-2"
    bus_match = re.search(r'I2C bus:\s*(/dev/i2c-(\d+))', raw, re.IGNORECASE)
    if bus_match:
        detected_bus_num = bus_match.group(2)
        BUS = detected_bus_num  # override default
        # update commands' -b values in INPUT_COMMANDS so subsequent setvcp/getvcp uses new bus
        for k, cmd in INPUT_COMMANDS.items():
            if len(cmd) >= 3 and cmd[0] == "ddcutil" and cmd[1] == "-b":
                cmd[2] = BUS

    # Extract manufacturer and model (capture full name)
    mfg = None
    model = None
    m = re.search(r'Mfg id:\s*(.+)', raw)
    if m:
        mfg = m.group(1).strip()
    m = re.search(r'Model:\s*(.+)', raw)
    if m:
        model = m.group(1).strip()

    # fallback patterns
    if not mfg:
        m = re.search(r'Manufacturer:\s*(.+)', raw)
        if m:
            mfg = m.group(1).strip()
    if not model:
        m = re.search(r'Model name:\s*(.+)', raw)
        if m:
            model = m.group(1).strip()

    # If nothing found, return a short excerpt as debug
    if not mfg and not model:
        excerpt = raw.splitlines()[:6]
        dbg = "\n".join(l.strip() for l in excerpt if l) or None
        return None, None, dbg

    return mfg, model, None


def get_monitor_input():
    """Read current monitor input; return (input_name_or_unknown, debug_string_or_None)"""
    cmd = ["ddcutil", "-b", BUS, "getvcp", VCP_INPUT_SELECT, "--i2c-source-addr=" + I2C_ADDR]
    rc, out, err = run_ddcutil(cmd)
    raw = (out + "\n" + err).strip()
    value_dec = parse_vcp_input_output(raw)

    if value_dec:
        mapped = INPUT_STATE_MAP.get(value_dec)
        if mapped:
            return mapped, None
        return f"unknown ({value_dec})", None

    debug = f"ddcutil rc={rc}\nstdout:\n{out}\nstderr:\n{err}"
    return "unknown", debug


@app.route("/")
def index():
    # Run detect first so we can auto-discover bus + monitor name before querying VCP
    monitor_mfg, monitor_model, detect_debug = get_monitor_info()
    current, input_debug = get_monitor_input()
    if detect_debug:
        flash(detect_debug, "warning")
    if input_debug:
        flash(input_debug, "warning")

    return render_template(
        "index.html",
        current=current,
        monitor_mfg=monitor_mfg,
        monitor_model=monitor_model,
    )


@app.route("/switch", methods=["POST"])
def switch_input():
    target = request.form.get("input", "").lower()
    if target not in INPUT_COMMANDS:
        flash("Invalid input selection", "error")
        return redirect(url_for("index"))

    # Ensure the command uses current BUS value
    cmd = list(INPUT_COMMANDS[target])
    if "-b" in cmd:
        i = cmd.index("-b")
        if i + 1 < len(cmd):
            cmd[i + 1] = BUS

    rc, out, err = run_ddcutil(cmd)
    if rc == 0:
        flash(f"Switched to {target.upper()}", "success")
    else:
        flash(f"Switch command returned rc={rc}. stdout:\n{out}\nstderr:\n{err}", "error")

    return redirect(url_for("index"))


@app.route("/api/switch/<input_name>", methods=["GET"])
def api_switch(input_name):
    input_name = input_name.lower()
    if input_name not in INPUT_COMMANDS:
        return jsonify({"status": "error", "message": "Invalid input"}), 400

    cmd = list(INPUT_COMMANDS[input_name])
    if "-b" in cmd:
        i = cmd.index("-b")
        if i + 1 < len(cmd):
            cmd[i + 1] = BUS

    rc, out, err = run_ddcutil(cmd)
    if rc == 0:
        return jsonify({"status": "ok", "input": input_name})
    return jsonify({"status": "error", "message": f"rc={rc}", "stdout": out, "stderr": err}), 500


if __name__ == "__main__":
    # If you still see permission errors, run with sudo or configure appropriate permissions for /dev/i2c-*
    app.run(host="0.0.0.0", port=8080)
