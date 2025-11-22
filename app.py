import os
import re
import socket
import sys
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from mcrcon import MCRcon

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev_key")

# Configuration
RCON_HOST = os.getenv("RCON_HOST", "127.0.0.1")
# Fallback to 25575 if not set, convert to int safely
try:
    RCON_PORT = int(os.getenv("RCON_PORT", 25575))
except ValueError:
    print("Error: RCON_PORT in .env is not a number. Using default 25575.")
    RCON_PORT = 25575

RCON_PASS = os.getenv("RCON_PASSWORD")
BEDROCK_PREFIX = os.getenv("BEDROCK_PREFIX", ".")

def debug_log(message):
    """Prints to console immediately"""
    print(f"[DEBUG] {message}", file=sys.stdout)
    sys.stdout.flush()

def sanitize_username(username):
    """Strictly validate username."""
    # Allow dot (.) for Bedrock prefixes, spaces for Xbox, and underscores
    safe_name = re.sub(r'[^a-zA-Z0-9_ \.]', '', username)
    return safe_name.strip()

def check_port_open(host, port):
    """Checks if a TCP port is open before trying RCON"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2) # 2 second timeout
    result = sock.connect_ex((host, port))
    sock.close()
    return result == 0

def send_rcon_command(username):
    """
    Connects to Minecraft RCON and executes the whitelist command.
    """
    debug_log(f"Starting RCON connection to {RCON_HOST}:{RCON_PORT}")

    # 1. PRE-CHECK: Is the port even open?
    if not check_port_open(RCON_HOST, RCON_PORT):
        msg = f"Port {RCON_PORT} on {RCON_HOST} is CLOSED or blocked."
        debug_log(f"FAILURE: {msg}")
        debug_log("TIP: Check server.properties. Is 'enable-rcon=true'? Is 'rcon.port' correct? Did you restart the server?")
        return False, "Server is not listening on the RCON port. Ask admin to check server.properties."

    try:
        # 2. ATTEMPT RCON CONNECTION
        # We use quotes around username for Xbox names with spaces
        command = f'whitelist add {username}'
        print(command)
        
        debug_log(f"Port is open. Attempting RCON Login/Command: {command}")
        
        with MCRcon(RCON_HOST, RCON_PASS, port=RCON_PORT) as mcr:
            # Broadcast the new signup to everyone online
            mcr.command(f'say {username} has signed up for the server!')

            response = mcr.command(command)
            debug_log(f"RCON Response 1: {response}")
            
            # Force save
            mcr.command('whitelist reload')
            
            return True, response

    except ConnectionRefusedError:
        debug_log("FAILURE: Connection Refused by remote host.")
        return False, "Connection Refused. Server running?"
        
    except Exception as e:
        error_str = str(e)
        debug_log(f"FAILURE: Exception: {error_str}")
        
        if "Authentication failed" in error_str:
            return False, "RCON Authentication failed. Check password in .env"
        elif "timed out" in error_str:
             return False, "Connection timed out."
             
        return False, f"RCON Error: {error_str}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/whitelist', methods=['POST'])
def whitelist_user():
    data = request.json
    raw_username = data.get('username')
    platform = data.get('platform') # Get platform selection
    
    if not raw_username:
        return jsonify({"success": False, "message": "Username required"}), 400

    username = sanitize_username(raw_username)
    if not username:
        return jsonify({"success": False, "message": "Invalid username format"}), 400

    # --- FIX: Handle Bedrock Prefix ---
    # Floodgate needs the prefix (default '.') to distinguish Bedrock players
    # from Java players when the server is in Online Mode.
    if platform == 'bedrock':
        # If it doesn't already start with the prefix, add it.
        if not username.startswith(BEDROCK_PREFIX):
            username = f"{BEDROCK_PREFIX}{username}"
            debug_log(f"Bedrock platform selected. Adjusted username to: {username}")

    success, response_msg = send_rcon_command(username)
    print(f"RCON Command Result: Success={success}, Message='{response_msg}'")

    if success:
        # Check various success messages from Vanilla/Spigot/Paper
        if "Added" in response_msg:
            user_msg = f"Success! {username} added to the whitelist."
        elif "already" in response_msg:
            user_msg = f"{username} is already whitelisted."
        elif "does not exist" in response_msg:
            # Specific help for this error
            if platform == 'java':
                user_msg = "Server could not find that Java username. Check your spelling?"
            else:
                user_msg = "Server could not verify Bedrock account. Ensure Floodgate is installed."
            # We mark this as false so the UI shows red
            return jsonify({"success": False, "message": user_msg}), 400
        else:
            user_msg = f"Server response: {response_msg}"

        return jsonify({
            "success": True, 
            "message": user_msg
        })
    else:
        return jsonify({
            "success": False, 
            "message": response_msg
        }), 500

if __name__ == '__main__':
    # Print initial config on startup
    print(f"--- STARTING FLASK ---")
    print(f"Target RCON: {RCON_HOST}:{RCON_PORT}")
    if not RCON_PASS:
        print("WARNING: RCON_PASSWORD is empty in .env!")
    print("----------------------")
    app.run(host='0.0.0.0', port=5000, debug=True)