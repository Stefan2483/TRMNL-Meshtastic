#!/usr/bin/env python3
"""
Simple BYOS Meshtastic Plugin for ARM Raspberry Pi
Works with the simple Flask-based BYOS server
"""

import json
import time
import requests
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
import os
import sys
import signal

try:
    import meshtastic
    import meshtastic.serial_interface
    from pubsub import pub
except ImportError:
    print("❌ Please install required packages:")
    print("pip install meshtastic requests")
    sys.exit(1)

# Configuration defaults
DEFAULT_UPDATE_INTERVAL = 300
DEFAULT_BYOS_URL = "http://localhost:4567"
MAX_RECENT_MESSAGES = 10
MAX_RECONNECT_ATTEMPTS = 5
ONLINE_THRESHOLD_MINUTES = 30

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('meshtastic-simple-byos.log')
    ]
)
logger = logging.getLogger(__name__)

class SimpleMeshtasticBYOS:
    def __init__(self, device_path=None, byos_url=None, update_interval=DEFAULT_UPDATE_INTERVAL):
        self.device_path = device_path
        self.byos_url = byos_url or DEFAULT_BYOS_URL
        self.update_interval = update_interval
        self.interface = None
        self.running = False
        
        # Data storage
        self.recent_messages = deque(maxlen=MAX_RECENT_MESSAGES)
        self.nodes = {}
        self.channels = {}
        self.message_stats = defaultdict(int)
        
        # Setup signal handlers
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
            logger.info("🔌 Connecting to Meshtastic device...")
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
    
    def on_connection(self, interface=None, topic=pub.AUTO_TOPIC):
        """Called when connected to radio"""
        logger.info("📡 Connection established with Meshtastic device")
        self.update_node_data()
        self.update_channel_data()
    
    def on_receive(self, packet, interface=None):
        """Called when a packet arrives"""
        try:
            decoded = packet.get('decoded', {})
            message_text = None
            
            # Handle different message formats
            if hasattr(decoded, 'text'):
                message_text = decoded.text
            elif isinstance(decoded, dict) and 'text' in decoded:
                message_text = decoded['text']
            elif hasattr(decoded, 'data') and hasattr(decoded.data, 'text'):
                message_text = decoded.data.text
            
            if message_text and message_text.strip():
                from_id = packet.get('fromId', packet.get('from', 'Unknown'))
                channel = packet.get('channel', 0)
                rx_time = packet.get('rxTime', packet.get('time', time.time()))
                timestamp = datetime.fromtimestamp(rx_time)
                
                from_num = packet.get('from', 0)
                node_info = self.nodes.get(from_num, {})
                display_name = node_info.get('shortName', str(from_id))
                
                message_data = {
                    'text': message_text,
                    'from': display_name,
                    'from_id': str(from_id),
                    'channel': channel,
                    'time': timestamp.strftime('%H:%M'),
                    'timestamp': timestamp.isoformat()
                }
                
                self.recent_messages.append(message_data)
                self.message_stats[str(from_id)] += 1
                self.message_stats['total'] += 1
                
                logger.info(f"💬 Message from {display_name}: {message_text[:50]}...")
            
        except Exception as e:
            logger.error(f"Error processing received packet: {e}")
    
    def on_node_updated(self, node, interface=None):
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
            channels_found = 0
            
            try:
                local_node = self.interface.getMyNodeInfo()
                if local_node and hasattr(local_node, 'channels'):
                    channels = local_node.channels
                    for i, channel in enumerate(channels):
                        if hasattr(channel, 'settings'):
                            name = getattr(channel.settings, 'name', f"Channel {i}")
                            if name and name.strip():
                                self.channels[i] = {
                                    'index': i,
                                    'name': name,
                                    'psk': len(getattr(channel.settings, 'psk', b'')) > 0,
                                    'role': getattr(channel, 'role', 'secondary')
                                }
                                channels_found += 1
            except Exception as e:
                logger.debug(f"Channel detection failed: {e}")
            
            if channels_found == 0:
                self.channels[0] = {
                    'index': 0,
                    'name': 'Default',
                    'psk': True,
                    'role': 'primary'
                }
                channels_found = 1
            
            logger.info(f"📻 Updated {channels_found} channels")
            
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
        
        online_nodes.sort(key=lambda x: x['lastHeard'], reverse=True)
        return online_nodes
    
    def get_message_summary(self):
        """Get summary of recent message activity"""
        if not self.recent_messages:
            return {'total': 0, 'recent': []}
        
        recent_list = list(self.recent_messages)
        recent_list.reverse()
        
        return {
            'total': self.message_stats.get('total', 0),
            'recent': recent_list[:10],
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
    
    def prepare_display_data(self):
        """Prepare data for BYOS display"""
        online_nodes = self.get_online_nodes()
        message_summary = self.get_message_summary()
        network_stats = self.get_network_stats()
        
        data = {
            'network_stats': network_stats,
            'online_nodes': online_nodes[:12],
            'recent_messages': message_summary['recent'][:10],
            'message_stats': {
                'total': message_summary['total'],
             #   'active_users': message_summary['active_users']
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
    
    def send_to_byos(self):
        """Send data to Simple BYOS server"""
        try:
            data = self.prepare_display_data()
            
            url = f"{self.byos_url}/api/screen"
            
            logger.info(f"📤 Sending data to Simple BYOS server: {self.byos_url}")
            
            response = requests.post(
                url,
                json=data,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            if response.status_code in [200, 201]:
                logger.info("✅ Successfully sent data to BYOS server")
                logger.info(f"📊 Stats: {data['network_stats']['online_nodes']} online, {data['message_stats']['total']} messages")
                return True
            else:
                logger.error(f"❌ BYOS server failed with status {response.status_code}")
                logger.error(f"Response: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error sending data to BYOS server: {e}")
            return False
    
    def run_update_loop(self):
        """Main update loop"""
        self.running = True
        reconnect_attempts = 0
        
        logger.info(f"🚀 Starting Simple Meshtastic BYOS daemon...")
        logger.info(f"⏱️  Update interval: {self.update_interval} seconds")
        logger.info(f"🌐 BYOS URL: {self.byos_url}")
        
        while self.running:
            try:
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
                
                logger.info("🔄 Updating Meshtastic data and sending to BYOS...")
                self.update_node_data()
                self.send_to_byos()
                
                logger.info(f"😴 Sleeping for {self.update_interval} seconds...")
                for i in range(self.update_interval):
                    if not self.running:
                        break
                    time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("🛑 Received interrupt signal, shutting down...")
                break
            except Exception as e:
                logger.error(f"❌ Error in update loop: {e}")
                time.sleep(60)
        
        self.running = False
        self.disconnect()
        logger.info("👋 Simple Meshtastic BYOS daemon stopped")

def load_env_file():
    """Load .env file if it exists"""
    if os.path.exists('.env'):
        logger.info("📁 Loading configuration from .env file")
        try:
            with open('.env', 'r') as f:
                for line in f:
                    if line.strip() and not line.startswith('#') and '=' in line:
                        key, value = line.strip().split('=', 1)
                        if key not in os.environ:
                            os.environ[key] = value
        except Exception as e:
            logger.warning(f"⚠️  Error loading .env file: {e}")

def main():
    """Main function"""
    import argparse
    
    load_env_file()
    
    byos_url = os.getenv('BYOS_URL', DEFAULT_BYOS_URL)
    update_interval = int(os.getenv('UPDATE_INTERVAL', str(DEFAULT_UPDATE_INTERVAL)))
    
    parser = argparse.ArgumentParser(description='Simple Meshtastic BYOS Plugin for ARM Raspberry Pi')
    parser.add_argument('--device', '-d', help='Meshtastic device path')
    parser.add_argument('--byos-url', '-u', default=byos_url, help=f'BYOS server URL (default: {byos_url})')
    parser.add_argument('--interval', '-i', type=int, default=update_interval, help='Update interval in seconds')
    parser.add_argument('--test', action='store_true', help='Test connection and send one update')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    plugin = SimpleMeshtasticBYOS(
        device_path=args.device,
        byos_url=args.byos_url,
        update_interval=args.interval
    )
    
    if args.test:
        logger.info("🧪 Running in test mode...")
        if plugin.connect():
            logger.info("⏳ Waiting 5 seconds for device to initialize...")
            time.sleep(5)
            
            plugin.update_node_data()
            plugin.update_channel_data()
            
            online_nodes = plugin.get_online_nodes()
            logger.info(f"📊 Found {len(plugin.nodes)} nodes, {len(plugin.channels)} channels")
            logger.info(f"🟢 {len(online_nodes)} nodes are currently online")
            
            result = plugin.send_to_byos()
            if result:
                logger.info("✅ Test successful!")
                logger.info(f"🌐 Check display at: {plugin.byos_url}/display")
            else:
                logger.error("❌ Test failed!")
        else:
            logger.error("❌ Connection test failed!")
        plugin.disconnect()
    else:
        plugin.run_update_loop()

if __name__ == "__main__":
    main()
