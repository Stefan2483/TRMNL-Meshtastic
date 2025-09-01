#!/bin/bash
# Meshtastic TRMNL Plugin Installation Script for Raspberry Pi
# Fixes protobuf compatibility issues

set -e

echo "🚀 Installing Meshtastic TRMNL Plugin on Raspberry Pi..."
echo "🔧 This script will fix protobuf compatibility issues..."

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo; then
    echo "⚠️  Warning: This doesn't appear to be a Raspberry Pi"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create project directory
PROJECT_DIR="$HOME/meshtastic-trmnl"
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# Update system packages
echo "📦 Updating system packages..."
sudo apt update

# Install Python and required system packages
echo "🐍 Installing Python dependencies..."
sudo apt install -y python3-pip python3-venv git

# Create virtual environment
echo "🔧 Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Clean any existing installations that might cause conflicts
echo "🧹 Cleaning existing installations..."
pip uninstall -y meshtastic protobuf google || true

# Install Python packages with compatible versions
echo "📦 Installing compatible Python packages..."
pip install --upgrade pip setuptools wheel

# Install specific protobuf version that works with meshtastic
pip install "protobuf>=3.19.0,<4.0.0"

# Install other dependencies
pip install requests

# Install meshtastic
pip install meshtastic

# Verify installation
echo "🧪 Testing meshtastic installation..."
python -c "import meshtastic; print('✅ Meshtastic library successfully installed!')" || {
    echo "❌ Meshtastic import failed, trying alternative protobuf version..."
    pip uninstall -y protobuf
    pip install "protobuf==3.19.6"
    python -c "import meshtastic; print('✅ Meshtastic library working with protobuf 3.19.6!')"
}

# Download the Python backend script
echo "📥 Downloading Meshtastic TRMNL backend..."
cat > meshtastic_trmnl.py << 'EOF'
#!/usr/bin/env python3
"""
TRMNL Meshtastic Plugin Backend for Raspberry Pi
Connects to Meshtastic device via USB and sends data to TRMNL display
"""

import json
import time
import requests
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
import threading
import os
import sys
import signal

try:
    import meshtastic
    import meshtastic.serial_interface
    from pubsub import pub
except ImportError:
    print("Please install required packages:")
    print("pip install meshtastic requests")
    sys.exit(1)

# Configuration
TRMNL_WEBHOOK_URL = os.getenv('TRMNL_WEBHOOK_URL', '')
UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', '300'))  # 5 minutes default
MAX_RECENT_MESSAGES = 10
MAX_RECONNECT_ATTEMPTS = 5
ONLINE_THRESHOLD_MINUTES = 30

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('meshtastic-trmnl.log')
    ]
)
logger = logging.getLogger(__name__)

class MeshtasticTRMNL:
    def __init__(self, device_path=None, webhook_url=None):
        self.device_path = device_path
        self.webhook_url = webhook_url or TRMNL_WEBHOOK_URL
        self.interface = None
        self.running = False
        
        # Data storage
        self.recent_messages = deque(maxlen=MAX_RECENT_MESSAGES)
        self.nodes = {}
        self.channels = {}
        self.message_stats = defaultdict(int)
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Setup pub-sub subscribers
        pub.subscribe(self.on_receive, "meshtastic.receive")
        pub.subscribe(self.on_connection, "meshtastic.connection.established")
        pub.subscribe(self.on_node_updated, "meshtastic.node.updated")
        
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    def connect(self):
        """Connect to Meshtastic device"""
        try:
            logger.info(f"Connecting to Meshtastic device...")
            # Auto-detect device if no path specified
            if self.device_path:
                logger.info(f"Using specified device: {self.device_path}")
                self.interface = meshtastic.serial_interface.SerialInterface(
                    devPath=self.device_path
                )
            else:
                logger.info("Auto-detecting Meshtastic device...")
                self.interface = meshtastic.serial_interface.SerialInterface()
                
            logger.info("✅ Successfully connected to Meshtastic device")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to connect to Meshtastic device: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from Meshtastic device"""
        if self.interface:
            try:
                self.interface.close()
                logger.info("Disconnected from Meshtastic device")
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
    
    def on_connection(self, interface, topic=pub.AUTO_TOPIC):
        """Called when connected to radio"""
        logger.info("📡 Connection established with Meshtastic device")
        self.update_node_data()
        self.update_channel_data()
    
    def on_receive(self, packet, interface):
        """Called when a packet arrives"""
        try:
            # Process text messages
            decoded = packet.get('decoded', {})
            if hasattr(decoded, 'text') or 'text' in decoded:
                message_text = decoded.get('text', '')
                if message_text:
                    from_id = packet.get('fromId', 'Unknown')
                    channel = packet.get('channel', 0)
                    timestamp = datetime.fromtimestamp(packet.get('rxTime', time.time()))
                    
                    # Get node info for better display name
                    node_info = self.nodes.get(packet.get('from', 0), {})
                    display_name = node_info.get('shortName', from_id)
                    
                    self.recent_messages.append({
                        'text': message_text,
                        'from': display_name,
                        'from_id': from_id,
                        'channel': channel,
                        'time': timestamp.strftime('%H:%M'),
                        'timestamp': timestamp
                    })
                    
                    # Update message stats
                    self.message_stats[from_id] += 1
                    self.message_stats['total'] += 1
                    
                    logger.info(f"💬 Message from {display_name}: {message_text[:50]}...")
            
        except Exception as e:
            logger.error(f"Error processing received packet: {e}")
    
    def on_node_updated(self, node):
        """Called when node information is updated"""
        try:
            node_id = node.get('num', 0)
            if node_id:
                user_info = node.get('user', {})
                self.nodes[node_id] = {
                    'id': node_id,
                    'longName': user_info.get('longName', 'Unknown'),
                    'shortName': user_info.get('shortName', 'UNK'),
                    'lastHeard': node.get('lastHeard', 0),
                    'snr': node.get('snr', 0),
                    'position': node.get('position', {}),
                    'telemetry': node.get('deviceMetrics', {})
                }
                logger.debug(f"🔄 Updated node: {user_info.get('shortName', node_id)}")
        except Exception as e:
            logger.error(f"Error updating node data: {e}")
    
    def update_node_data(self):
        """Update node database from interface"""
        if not self.interface:
            return
        
        try:
            nodes = self.interface.nodes
            for node_id, node in nodes.items():
                self.on_node_updated(node)
            logger.info(f"📊 Updated {len(nodes)} nodes in database")
        except Exception as e:
            logger.error(f"Error updating node data: {e}")
    
    def update_channel_data(self):
        """Update channel information"""
        if not self.interface:
            return
        
        try:
            # Get local node info first
            local_node = self.interface.getMyNodeInfo()
            if local_node and hasattr(local_node, 'channels'):
                channels = local_node.channels
                for i, channel in enumerate(channels):
                    if hasattr(channel.settings, 'name') and channel.settings.name:
                        self.channels[i] = {
                            'index': i,
                            'name': channel.settings.name,
                            'psk': len(channel.settings.psk) > 0 if hasattr(channel.settings, 'psk') else False,
                            'role': getattr(channel, 'role', 'secondary')
                        }
            logger.info(f"📻 Updated {len(self.channels)} channels")
        except Exception as e:
            logger.error(f"Error updating channel data: {e}")
    
    def get_online_nodes(self):
        """Get nodes that have been heard recently"""
        threshold = datetime.now() - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
        threshold_timestamp = threshold.timestamp()
        
        online_nodes = []
        for node_id, node in self.nodes.items():
            last_heard = node.get('lastHeard', 0)
            if last_heard > threshold_timestamp:
                last_heard_time = datetime.fromtimestamp(last_heard)
                online_nodes.append({
                    'name': node.get('shortName', 'UNK'),
                    'longName': node.get('longName', 'Unknown'),
                    'lastHeard': last_heard_time.strftime('%H:%M'),
                    'snr': round(node.get('snr', 0), 1),
                    'id': node_id
                })
        
        # Sort by last heard (most recent first)
        online_nodes.sort(key=lambda x: x['lastHeard'], reverse=True)
        return online_nodes
    
    def get_message_summary(self):
        """Get summary of recent message activity"""
        if not self.recent_messages:
            return {'total': 0, 'recent': []}
        
        recent_list = list(self.recent_messages)
        recent_list.reverse()  # Most recent first
        
        return {
            'total': self.message_stats.get('total', 0),
            'recent': recent_list[:8],  # Last 8 messages for display
            'active_users': len([k for k, v in self.message_stats.items() if k != 'total' and v > 0])
        }
    
    def get_network_stats(self):
        """Get network statistics"""
        online_nodes = self.get_online_nodes()
        
        return {
            'total_nodes': len(self.nodes),
            'online_nodes': len(online_nodes),
            'channels': len(self.channels),
            'last_update': datetime.now().strftime('%H:%M:%S')
        }
    
    def prepare_trmnl_data(self):
        """Prepare data for TRMNL webhook"""
        online_nodes = self.get_online_nodes()
        message_summary = self.get_message_summary()
        network_stats = self.get_network_stats()
        
        data = {
            'network_stats': network_stats,
            'online_nodes': online_nodes[:10],  # Limit for display
            'recent_messages': message_summary['recent'],
            'message_stats': {
                'total': message_summary['total'],
                'active_users': message_summary['active_users']
            },
            'channels': list(self.channels.values())[:6],
            'status': 'connected' if self.interface else 'disconnected',
            'timestamp': datetime.now().isoformat(),
            'device_info': {
                'platform': 'Raspberry Pi',
                'meshtastic_device': 'Heltec v3'
            }
        }
        
        return data
    
    def send_to_trmnl(self):
        """Send data to TRMNL webhook"""
        if not self.webhook_url:
            logger.error("❌ TRMNL webhook URL not configured")
            return False
        
        try:
            data = self.prepare_trmnl_data()
            
            payload = {
                'merge_variables': data
            }
            
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("✅ Successfully sent data to TRMNL")
                logger.info(f"📊 Stats: {data['network_stats']['online_nodes']} online, {data['message_stats']['total']} messages")
                return True
            else:
                logger.error(f"❌ TRMNL webhook failed with status {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error sending data to TRMNL: {e}")
            return False
    
    def run_update_loop(self):
        """Main update loop"""
        self.running = True
        reconnect_attempts = 0
        
        logger.info(f"🚀 Starting Meshtastic TRMNL daemon...")
        logger.info(f"⏱️  Update interval: {UPDATE_INTERVAL} seconds")
        logger.info(f"🌐 Webhook: {'✅ Configured' if self.webhook_url else '❌ NOT CONFIGURED'}")
        
        while self.running:
            try:
                # Connect if not connected
                if not self.interface:
                    if self.connect():
                        reconnect_attempts = 0
                    else:
                        reconnect_attempts += 1
                        if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                            logger.error("❌ Max reconnection attempts reached, exiting")
                            break
                        logger.warning(f"🔄 Reconnect attempt {reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS} in 30s...")
                        time.sleep(30)
                        continue
                
                # Update data and send to TRMNL
                logger.info("🔄 Updating Meshtastic data and sending to TRMNL...")
                self.update_node_data()
                self.send_to_trmnl()
                
                # Wait for next update
                logger.info(f"😴 Sleeping for {UPDATE_INTERVAL} seconds...")
                for i in range(UPDATE_INTERVAL):
                    if not self.running:
                        break
                    time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("🛑 Received interrupt signal, shutting down...")
                break
            except Exception as e:
                logger.error(f"❌ Error in update loop: {e}")
                logger.info("⏳ Waiting 60 seconds before retry...")
                time.sleep(60)
        
        self.running = False
        self.disconnect()
        logger.info("👋 Meshtastic TRMNL daemon stopped")

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Meshtastic TRMNL Plugin Backend for Raspberry Pi')
    parser.add_argument('--device', '-d', help='Meshtastic device path (e.g., /dev/ttyUSB0, /dev/ttyACM0)')
    parser.add_argument('--webhook-url', '-w', help='TRMNL webhook URL')
    parser.add_argument('--interval', '-i', type=int, default=UPDATE_INTERVAL, 
                       help=f'Update interval in seconds (default: {UPDATE_INTERVAL})')
    parser.add_argument('--test', '-t', action='store_true', 
                       help='Test connection and send one update')
    parser.add_argument('--debug', action='store_true', 
                       help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Override global interval
    global UPDATE_INTERVAL
    UPDATE_INTERVAL = args.interval
    
    # Create plugin instance
    plugin = MeshtasticTRMNL(
        device_path=args.device,
        webhook_url=args.webhook_url
    )
    
    if args.test:
        logger.info("🧪 Running in test mode...")
        if plugin.connect():
            plugin.update_node_data()
            plugin.update_channel_data()
            result = plugin.send_to_trmnl()
            if result:
                logger.info("✅ Test successful!")
            else:
                logger.error("❌ Test failed!")
        plugin.disconnect()
    else:
        plugin.run_update_loop()

if __name__ == "__main__":
    main()
EOF

# Make script executable
chmod +x meshtastic_trmnl.py

# Create systemd service file
sudo tee /etc/systemd/system/meshtastic-trmnl.service > /dev/null << EOF
[Unit]
Description=Meshtastic TRMNL Plugin
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$PROJECT_DIR/venv/bin
ExecStart=$PROJECT_DIR/venv/bin/python $PROJECT_DIR/meshtastic_trmnl.py
EnvironmentFile=$PROJECT_DIR/.env
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create environment file template
cat > .env << EOF
# TRMNL Webhook URL (get this from your TRMNL Private Plugin settings)
TRMNL_WEBHOOK_URL=

# Update interval in seconds (minimum 300 = 5 minutes due to TRMNL rate limits)
UPDATE_INTERVAL=300

# Optional: Specific device path (leave empty for auto-detection)
# DEVICE_PATH=/dev/ttyUSB0
EOF

echo ""
echo "✅ Installation complete!"
echo ""
echo "🔍 Testing Meshtastic device connection..."

# Test USB device detection
echo "📱 Looking for USB devices..."
lsusb | grep -i "heltec\|esp32\|cp210\|ch340" || echo "⚠️  No obvious Meshtastic device found via lsusb"

# Check for serial devices
echo "🔌 Available serial devices:"
ls /dev/tty* | grep -E "(USB|ACM)" || echo "⚠️  No USB serial devices found"

echo ""
echo "🧪 Testing meshtastic CLI..."
meshtastic --version || {
    echo "❌ Meshtastic CLI test failed"
    echo "💡 Try: source venv/bin/activate && python -m meshtastic --version"
}

echo ""
echo "📋 Next steps:"
echo "1. Edit .env file and add your TRMNL webhook URL"
echo "2. Test the connection: ./meshtastic_trmnl.py --test"
echo "3. Start the service: sudo systemctl enable --now meshtastic-trmnl"
echo ""
echo "📁 Project location: $PROJECT_DIR"
echo "📝 Log file: $PROJECT_DIR/meshtastic-trmnl.log"
echo ""
echo "🔧 Configuration:"
echo "   - Edit: $PROJECT_DIR/.env"
echo "   - Service: sudo systemctl [start|stop|status] meshtastic-trmnl"
echo "   - Logs: journalctl -u meshtastic-trmnl -f"
echo ""
echo "🐛 Troubleshooting:"
echo "   - Test CLI: source venv/bin/activate && meshtastic --info"
echo "   - Check device: ls /dev/tty* | grep -E '(USB|ACM)'"
echo "   - Debug script: ./meshtastic_trmnl.py --test --debug"
echo "   - Check logs: tail -f meshtastic-trmnl.log"
EOF

chmod +x install.sh
