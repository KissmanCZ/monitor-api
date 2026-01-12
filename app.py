from flask import Flask, jsonify, request, render_template, redirect, url_for, flash
import subprocess
import re

app = Flask(__name__)
app.secret_key = "monitor-switcher-secret-key-change-in-production"

BUS = "2"
I2C_ADDR = "0x50"

VCP_INPUT_SELECT = "0xF4"
VCP_POWER_MODE = "0xFE"

INPUT_COMMANDS = {
    "dp": [
        "sudo", "ddcutil", "-b", BUS,
        "setvcp", VCP_INPUT_SELECT, "0x00D0",
        "--i2c-source-addr=" + I2C_ADDR
    ,
        "--i2c-source-addr=" + I2C_ADDR
    ],
    "usbc": [
        "sudo", "ddcutil", "-b", BUS,
        "setvcp", VCP_INPUT_SELECT, "0x00D1",
        "--i2c-source-addr=" + I2C_ADDR
    ]
}

INPUT_STATE_MAP = {
    "12": "dp",
    "3": "usbc"
}


def get_monitor_input():
    """Read current monitor input state from VCP 0xFE"""
    try:
        result = subprocess.run(
            ["sudo", "ddcutil", "-b", BUS, "getvcp", VCP_POWER_MODE],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse output to extract current value from sl (set low byte)
        # Expected format: "VCP code 0xfe (...): mh=0x00, ml=0xff, sh=0x00, sl=0x03"
        match = re.search(r'sl=0x([0-9a-fA-F]+)', result.stdout)
        if match:
            # Convert hex value to decimal
            value = str(int(match.group(1), 16))
            mapped = INPUT_STATE_MAP.get(value)
            if mapped:
                return mapped, f"Command ok: Output: {result.stdout}"
            else:
                # Unknown value - return with command output for debugging
                return "unknown", f"Unknown value detected: sl=0x{match.group(1)} (decimal: {value})\nFull output: {result.stdout.strip()}"
        
        return "unknown", f"Could not parse output. Full command output:\n{result.stdout.strip()}"
    except subprocess.CalledProcessError as e:
        return "unknown", f"Command failed: {str(e)}\nOutput: {e.stdout if e.stdout else 'N/A'}"


@app.route("/")
def index():
    """Display HTML page with radio buttons"""
    current, debug_info = get_monitor_input()
    if debug_info:
        flash(f"Unknown display detected. Debug info:\n{debug_info}", "warning")
    return render_template("index.html", current=current)


@app.route("/switch", methods=["POST", "GET"])
def switch_input():
    """Handle form submission to switch input"""
    try:
        target = request.form.get("input", "").lower()
        
        if target not in INPUT_COMMANDS:
            flash("Invalid input selection", "error")
            return redirect(url_for("index"))
        
        subprocess.run(INPUT_COMMANDS[target], check=True)
        flash(f"Successfully switched to {target.upper()}", "success")
        return redirect(url_for("index"))
    
    except subprocess.CalledProcessError as e:
        flash(f"Error switching input: {str(e)}", "error")
        return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
