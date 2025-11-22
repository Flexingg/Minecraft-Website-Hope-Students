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
        command2 = f'whitelist add .{username}'  # For Bedrock with prefix
        print(command)
    
        
        debug_log(f"Port is open. Attempting RCON Login/Command: {command}")
        
        with MCRcon(RCON_HOST, RCON_PASS, port=RCON_PORT) as mcr:
            # Broadcast the new signup to everyone online
            mcr.command(f'say {username} has signed up for the server!')

            response = mcr.command(command)
            debug_log(f"RCON Response 1: {response}")
            response2 = mcr.command(command2)
            debug_log(f"RCON Response 2: {response2}")
            
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
    # platform = data.get('platform') # Get platform selection
    
    if not raw_username:
        return jsonify({"success": False, "message": "Username required"}), 400

    username = sanitize_username(raw_username)
    if not username:
        return jsonify({"success": False, "message": "Invalid username format"}), 400

    # --- New Whitelisting Logic ---
    # Attempt to whitelist as Java (or direct Bedrock if already prefixed)
    java_success, java_response_msg = send_rcon_command(username)
    debug_log(f"RCON Command Result (Java attempt): Success={java_success}, Message='{java_response_msg}'")

    bedrock_success = False
    bedrock_response_msg = ""
    bedrock_username = ""

    # If the initial attempt failed and the username doesn't already start with the bedrock prefix,
    # try whitelisting with the bedrock prefix.
    if not java_success and not username.startswith(BEDROCK_PREFIX):
        bedrock_username = f"{BEDROCK_PREFIX}{username}"
        bedrock_success, bedrock_response_msg = send_rcon_command(bedrock_username)
        debug_log(f"RCON Command Result (Bedrock attempt): Success={bedrock_success}, Message='{bedrock_response_msg}'")

    # Combine results and determine final response
    if java_success or bedrock_success:
        final_success = True
        messages = []
        
        # Process Java attempt response
        if java_success:
            if "Added" in java_response_msg:
                messages.append(f"Success! {username} added to the whitelist.")
            elif "already" in java_response_msg:
                messages.append(f"{username} is already whitelisted.")
            elif "does not exist" in java_response_msg:
                messages.append(f"Java username '{username}' not found. Check spelling.")
            else:
                messages.append(f"Java attempt response: {java_response_msg}")
        
        # Process Bedrock attempt response
        if bedrock_success:
            if "Added" in bedrock_response_msg:
                messages.append(f"Success! {bedrock_username} (Bedrock) added to the whitelist.")
            elif "already" in bedrock_response_msg:
                messages.append(f"{bedrock_username} (Bedrock) is already whitelisted.")
            elif "does not exist" in bedrock_response_msg:
                messages.append(f"Bedrock username '{bedrock_username}' not found. Ensure Floodgate is installed and username is correct.")
            else:
                messages.append(f"Bedrock attempt response: {bedrock_response_msg}")
        
        final_message = " ".join(messages) if messages else "Whitelist operation completed."
        
        return jsonify({
            "success": final_success, 
            "message": final_message
        })
    else:
        # Both attempts failed
        error_messages = []
        if java_response_msg:
            error_messages.append(f"Java attempt failed: {java_response_msg}")
        if bedrock_response_msg:
            error_messages.append(f"Bedrock attempt failed: {bedrock_response_msg}")
        
        # If no specific error messages, provide a generic one
        if not error_messages:
            error_messages.append("Failed to whitelist username. Please try again or contact support.")

        final_error_message = " ".join(error_messages)
        
        return jsonify({
            "success": False, 
            "message": final_error_message
        }), 500

if __name__ == '__main__':
    # Print initial config on startup
    print(f"--- STARTING FLASK ---")
    print(f"Target RCON: {RCON_HOST}:{RCON_PORT}")
    if not RCON_PASS:
        print("WARNING: RCON_PASSWORD is empty in .env!")
    print("----------------------")
    app.run(host='0.0.0.0', port=5000, debug=True)