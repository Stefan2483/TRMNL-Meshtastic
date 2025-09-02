# Meshtastic TRMNL Integration

A Raspberry Pi-based integration that displays Meshtastic mesh network status on TRMNL e-ink displays. Monitor your mesh network with real-time node status, message activity, and network statistics.

## Features

- **Real-time monitoring** of Meshtastic mesh networks
- **E-ink optimized display** for TRMNL devices (760x440px)
- **Node tracking** with online status and signal strength
- **Message monitoring** with recent chat activity
- **Network statistics** including total/online nodes and channels
- **Auto-reconnection** with graceful error handling
- **BYOS (Bring Your Own Server)** architecture for local control

## Architecture

```
Meshtastic Device → USB → mesh_simple.py → HTTP → byos_server.py → TRMNL Display
```

The system consists of two main components:

1. **Meshtastic Monitor** (`mesh_simple.py`) - Connects to your Meshtastic device via USB, collects network data, and sends updates to the BYOS server
2. **BYOS Server** (`byos_server.py`) - Flask web server that serves HTML displays compatible with TRMNL devices

## Prerequisites

- Raspberry Pi (tested on Pi 4, should work on Pi 3/Zero)
- Python 3.7 or higher
- Meshtastic-compatible radio device (Heltec, T-Beam, etc.)
- TRMNL e-ink display device

## Installation

1. **Clone the repository:**
```bash
git clone https://github.com/Stefan2483/meshtastic-trmnl.git
cd meshtastic-trmnl
```

2. **Install dependencies:**
```bash
pip3 install meshtastic requests flask
```

3. **Optional: Use virtual environment:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install meshtastic requests flask
```

## Quick Start

1. **Connect your Meshtastic device** to the Raspberry Pi via USB

2. **Start the BYOS server:**
```bash
python3 byos_server.py
```

3. **In a new terminal, start the monitor:**
```bash
python3 mesh_simple.py
```

4. **Configure your TRMNL device** to point to your Pi's IP:
```
http://YOUR_PI_IP:4567
```

## Configuration

### Environment Variables

Create a `.env` file to customize settings:

```env
# BYOS server URL (default: http://localhost:4567)
BYOS_URL=http://192.168.1.100:4567

# Update frequency in seconds (default: 300)
UPDATE_INTERVAL=180

# Server configuration
BYOS_PORT=4567
BYOS_HOST=0.0.0.0
```

### Command Line Options

**Meshtastic Monitor:**
```bash
# Test mode (single update, no daemon)
python3 mesh_simple.py --test

# Custom device path
python3 mesh_simple.py --device /dev/ttyUSB0

# Custom BYOS URL
python3 mesh_simple.py --byos-url http://192.168.1.100:4567

# Debug logging
python3 mesh_simple.py --debug

# Custom update interval
python3 mesh_simple.py --interval 120
```

**BYOS Server:**
```bash
# Server runs on default port 4567
python3 byos_server.py
```

## API Endpoints

| Endpoint | Method | Description |
|----------|---------|-------------|
| `/display` | GET | Rendered HTML for TRMNL device |
| `/api/screen` | POST | Receive display data from monitor |
| `/status` | GET | Server health check |
| `/api/display` | GET | TRMNL-compatible image URL response |
| `/api/setup` | POST | TRMNL device setup endpoint |
| `/api/log` | POST | TRMNL device log endpoint |

## Testing

**Test the connection:**
```bash
# Test Meshtastic connection and send one update
python3 mesh_simple.py --test

# Check server status
curl http://localhost:4567/status

# View the display HTML
curl http://localhost:4567/display

# Test from another machine
curl http://YOUR_PI_IP:4567/status
```

## TRMNL Device Setup

1. Power on your TRMNL device
2. Navigate to the BYOS setup
3. Enter your Pi's URL: `http://YOUR_PI_IP:4567`
4. The device will auto-configure and start displaying your mesh network status

## Display Information

The e-ink display shows:

- **Online nodes** with signal strength (SNR) and last seen time
- **Recent messages** from the mesh network
- **Network statistics** (total nodes, online nodes, message count, channels)
- **Last update time** and device information

## Troubleshooting

**Common issues:**

1. **"No Meshtastic device found"**
   - Check USB connection
   - Verify device permissions: `ls -la /dev/ttyUSB*`
   - Try specifying device path: `--device /dev/ttyUSB0`

2. **"Connection refused to BYOS server"**
   - Ensure byos_server.py is running
   - Check firewall settings
   - Verify IP address and port

3. **"Permission denied on device"**
   - Add user to dialout group: `sudo usermod -a -G dialout $USER`
   - Logout and login again

4. **No data on TRMNL display**
   - Check network connectivity between Pi and TRMNL
   - Verify BYOS URL in TRMNL settings
   - Check logs for errors

## Logging

Both components create log files:

- `meshtastic-simple-byos.log` - Monitor activity and errors
- Console output for real-time status

View logs:
```bash
tail -f meshtastic-simple-byos.log
```

## Development

**Project structure:**
```
├── mesh_simple.py      # Meshtastic monitor daemon
├── byos_server.py      # BYOS Flask server
├── CLAUDE.md          # Development guidelines
├── README.md          # This file
└── .env               # Configuration (optional)
```

**Key classes:**
- `SimpleMeshtasticBYOS` in mesh_simple.py:44 - Main monitor class
- Flask routes in byos_server.py - Web server endpoints

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- [Meshtastic](https://meshtastic.org/) - Open source mesh networking platform
- [TRMNL](https://usetrmnl.com/) - E-ink display hardware
- Built for the Raspberry Pi ecosystem

## Support

For issues and questions:
- Check the troubleshooting section above
- Review the logs for specific error messages  
- Open an issue on GitHub with detailed information

---

**Happy meshing!** 📡
