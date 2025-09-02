#!/usr/bin/env python3
"""
Simple TRMNL BYOS Server for ARM Raspberry Pi
Compatible with 32-bit ARM (armv7) architecture
"""

from flask import Flask, request, jsonify, render_template_string
import json
import logging
from datetime import datetime
import os
import threading
import time
from werkzeug.serving import run_simple

# Flask app setup
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global data storage
current_display_data = {}
device_info = {}

# HTML template for TRMNL display
TRMNL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Meshtastic Network Monitor</title>
    <style>
        body {
            margin: 0;
            padding: 20px;
            font-family: 'Courier New', monospace;
            background: white;
            color: black;
            width: 760px;
            height: 440px;
            overflow: hidden;
        }
        
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            border-bottom: 2px solid black;
            padding-bottom: 10px;
        }
        
        .title {
            font-size: 24px;
            font-weight: bold;
            margin: 0;
        }
        
        .status {
            font-size: 14px;
            display: flex;
            align-items: center;
        }
        
        .status-dot {
            width: 10px;
            height: 10px;
            background: black;
            border-radius: 50%;
            margin-right: 5px;
        }
        
        .stats-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
            font-size: 16px;
        }
        
        .stat-item {
            text-align: center;
        }
        
        .stat-value {
            font-size: 28px;
            font-weight: bold;
            display: block;
        }
        
        .stat-label {
            font-size: 12px;
            text-transform: uppercase;
            margin-top: 2px;
        }
        
        .content {
            display: flex;
            gap: 30px;
        }
        
        .column {
            flex: 1;
        }
        
        .section-title {
            margin: 0 0 15px 0;
            font-size: 16px;
            border-bottom: 1px solid #ccc;
            padding-bottom: 5px;
        }
        
        .node-list {
            max-height: 250px;
            overflow-y: hidden;
        }
        
        .node-item {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            border-bottom: 1px solid #eee;
            font-size: 14px;
        }
        
        .node-info {
            color: #666;
            font-size: 12px;
        }
        
        .message-item {
            margin-bottom: 12px;
            padding: 6px;
            border-left: 3px solid black;
            padding-left: 8px;
            font-size: 11px;
        }
        
        .message-header {
            display: flex;
            justify-content: space-between;
            font-weight: bold;
            margin-bottom: 2px;
        }
        
        .message-text {
            font-size: 12px;
            line-height: 1.3;
        }
        
        .footer {
            position: absolute;
            bottom: 10px;
            left: 50%;
            transform: translateX(-50%);
            font-size: 10px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1 class="title">📡 Meshtastic Network</h1>
        <div class="status">
            <span class="status-dot"></span>
            {{ status|title }}
        </div>
    </div>
    
    <div class="stats-row">
        <div class="stat-item">
            <span class="stat-value">{{ network_stats.online_nodes or 0 }}</span>
            <span class="stat-label">Online</span>
        </div>
        <div class="stat-item">
            <span class="stat-value">{{ network_stats.total_nodes or 0 }}</span>
            <span class="stat-label">Total</span>
        </div>
        <div class="stat-item">
            <span class="stat-value">{{ message_stats.total or 0 }}</span>
            <span class="stat-label">Messages</span>
        </div>
        <div class="stat-item">
            <span class="stat-value">{{ network_stats.channels or 0 }}</span>
            <span class="stat-label">Channels</span>
        </div>
    </div>
    
    <div class="content">
        <div class="column">
            <h3 class="section-title">🟢 Online Nodes ({{ online_nodes|length or 0 }})</h3>
            <div class="node-list">
                {% for node in online_nodes[:10] %}
                <div class="node-item">
                    <div>
                        <strong>{{ node.longName[:18] }}</strong>
                        <span class="node-info">({{ node.name }})</span>
                    </div>
                    <div class="node-info">
                        {{ node.lastHeard }} • SNR: {{ node.snr }}dB
                    </div>
                </div>
                {% else %}
                <div style="text-align: center; color: #666; font-style: italic; padding: 20px;">
                    No nodes currently online
                </div>
                {% endfor %}
            </div>
        </div>
        
        <div class="column">
            <h3 class="section-title">💬 Recent Messages</h3>
            <div>
                {% for message in recent_messages[:8] %}
                <div class="message-item">
                    <div class="message-header">
                        <span>{{ message.from[:15] }}</span>
                        <span>{{ message.time }}</span>
                    </div>
                    <div class="message-text">{{ message.text[:85] }}{% if message.text|length > 85 %}...{% endif %}</div>
                </div>
                {% else %}
                <div style="text-align: center; color: #666; font-style: italic; padding: 20px;">
                    No recent messages
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    
    <div class="footer">
        Last updated: {{ network_stats.last_update or "Never" }} • Platform: Raspberry Pi • Device: {{ device_info.meshtastic_device or "Heltec v3" }}
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    """Main dashboard"""
    return f"""
    <html>
    <head><title>TRMNL BYOS Server</title></head>
    <body style="font-family: Arial; padding: 20px;">
        <h1>🏠 TRMNL BYOS Server</h1>
        <p>Server is running on port 4567</p>
        <h2>Endpoints:</h2>
        <ul>
            <li><a href="/display">/display</a> - TRMNL display endpoint</li>
            <li><a href="/api/screen">/api/screen</a> - POST endpoint for screen updates</li>
            <li><a href="/status">/status</a> - Server status</li>
        </ul>
        <h2>Current Display Data:</h2>
        <pre>{json.dumps(current_display_data, indent=2)}</pre>
    </body>
    </html>
    """

@app.route('/status')
def status():
    """Server status endpoint"""
    return jsonify({
        'status': 'running',
        'timestamp': datetime.now().isoformat(),
        'last_update': current_display_data.get('timestamp', 'Never'),
        'data_available': bool(current_display_data)
    })

@app.route('/display')
def display():
    """TRMNL display endpoint - returns rendered HTML for e-ink display"""
    return render_template_string(TRMNL_TEMPLATE, **current_display_data)

@app.route('/api/display', methods=['GET'])
def api_display():
    """TRMNL API display endpoint - returns image URL for device"""
    # This mimics the TRMNL cloud API format
    return jsonify({
        'image_url': f'http://{request.host}/display',
        'refresh_rate': 300,  # 5 minutes
        'filename': f'meshtastic-{int(time.time())}',
        'update_firmware': False
    })

@app.route('/api/screen', methods=['POST'])
def api_screen():
    """Endpoint for receiving screen updates from Meshtastic script"""
    global current_display_data
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Store the data
        current_display_data = data
        current_display_data['timestamp'] = datetime.now().isoformat()
        
        logger.info(f"📥 Received screen update with {len(data)} fields")
        
        return jsonify({
            'success': True,
            'message': 'Screen data updated successfully',
            'timestamp': current_display_data['timestamp']
        })
        
    except Exception as e:
        logger.error(f"Error processing screen update: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/setup', methods=['POST'])
def api_setup():
    """TRMNL device setup endpoint"""
    device_id = request.headers.get('ID', 'unknown')
    
    logger.info(f"📱 Device setup request from: {device_id}")
    
    return jsonify({
        'api_key': 'simple-byos-key',
        'friendly_id': device_id[:6].upper(),
        'image_url': f'http://{request.host}/display',
        'message': f'Connected to Simple BYOS Server'
    })

@app.route('/api/log', methods=['POST'])
def api_log():
    """TRMNL device log endpoint"""
    device_id = request.headers.get('ID', 'unknown')
    log_data = request.get_json()
    
    logger.info(f"📝 Log from device {device_id}: {log_data}")
    return jsonify({'success': True})

def start_server():
    """Start the Flask server"""
    port = int(os.getenv('BYOS_PORT', 4567))
    host = os.getenv('BYOS_HOST', '0.0.0.0')
    
    logger.info(f"🚀 Starting Simple BYOS Server on {host}:{port}")
    logger.info(f"📱 TRMNL device should connect to: http://YOUR_PI_IP:{port}")
    
    # Use werkzeug's development server for simplicity
    run_simple(
        hostname=host,
        port=port,
        application=app,
        use_reloader=False,
        use_debugger=False,
        threaded=True
    )

if __name__ == '__main__':
    start_server()
