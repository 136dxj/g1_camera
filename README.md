## Acknowledgments

This project was developed in collaboration with **GLM-4.6V**.

---

Developed with assistance from GLM-4.6V by Zhipu AI.
# Teleimager - Network Camera Streaming

Simple camera streaming module for transmitting video over TCP/UDP networks.

## Features

- **Automatic Camera Discovery** - Auto-detects UVC cameras on the system
- **TCP Streaming** - Reliable transmission with connection guarantee
- **UDP Streaming** - Low-latency transmission for real-time applications
- **Frame Rate Control** - Separate capture FPS and streaming FPS
- **Cross-platform** - Works on Linux, macOS, Windows

## Installation

```bash
# Install dependencies
pip install opencv-python numpy

# Or with conda
conda install opencv numpy
```

## Quick Start

### Robot (Server) - Send Camera Stream

```bash
# Start TCP server (default)
python simple_camera_stream.py server

# Start UDP server (low latency)
python simple_camera_stream.py server --protocol udp

# Custom configuration
python simple_camera_stream.py server --protocol tcp --port 8888 --width 1280 --height 720 --fps 30
```

### PC (Client) - Receive Camera Stream

```bash
# Replace ROBOT_IP with actual robot IP address
python simple_camera_stream.py client --host ROBOT_IP

# Example: robot IP is 192.168.1.100
python simple_camera_stream.py client --host 192.168.1.100

# Receive and save frames
python simple_camera_stream.py client --host 192.168.1.100 --save-dir ./captured --no-display
```

## Command Line Options

### Server Options (Robot)

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `0.0.0.0` | Server host address |
| `--port` | `8888` | Server port |
| `--camera` | `/dev/video0` | Camera device path |
| `--width` | `640` | Image width |
| `--height` | `480` | Image height |
| `--fps` | `30` | Camera capture FPS |
| `--streaming-fps` | `30` | Network streaming FPS (0 = unlimited) |
| `--protocol` | `tcp` | Protocol: `tcp` or `udp` |

### Client Options (PC)

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | Required | Server IP address (robot IP) |
| `--port` | `8888` | Server port |
| `--protocol` | `tcp` | Protocol: `tcp` or `udp` |
| `--no-display` | `False` | Don't display video window |
| `--save-dir` | `None` | Directory to save frames |
| `--save-fps` | `10` | FPS for saving frames |

## Usage Examples

### Example 1: Basic Streaming

```bash
# Robot
python simple_camera_stream.py server --port 8888

# PC (assuming robot IP is 192.168.123.164)
python simple_camera_stream.py client --host 192.168.123.164 --port 8888
```

### Example 2: High Quality Video

```bash
# Robot - 1080p at 30 FPS
python simple_camera_stream.py server --width 1920 --height 1080 --fps 30

# PC - receive and display
python simple_camera_stream.py client --host 192.168.123.164
```

### Example 3: Low Latency Streaming

```bash
# Robot - UDP with reduced streaming FPS
python simple_camera_stream.py server --protocol udp --streaming-fps 15

# PC - UDP receiver
python simple_camera_stream.py client --host 192.168.123.164 --protocol udp
```

### Example 4: Save Frames to Disk

```bash
# PC - save every 5th frame
python simple_camera_stream.py client --host 192.168.123.164 --save-dir ./frames --save-fps 6 --no-display
```

### Example 5: Different Capture and Streaming FPS

```bash
# Robot - Capture at 60 FPS, stream at 15 FPS
# Useful for high-speed local processing with lower bandwidth transmission
python simple_camera_stream.py server --fps 60 --streaming-fps 15
```

## Network Setup

### Finding Robot IP

```bash
# On robot
ip addr show
# or
hostname -I
```

### Testing Connectivity

```bash
# From PC, test if robot is reachable
ping ROBOT_IP

# Test if port is accessible (requires netcat)
nc -zv ROBOT_IP 8888
```

## Protocol Comparison

| Protocol | Latency | Reliability | Use Case |
|----------|---------|-------------|----------|
| **TCP** | Low | High | General streaming, reliable delivery |
| **UDP** | Lowest | Low | Real-time control, lowest latency |

## Troubleshooting

### "Failed to connect" (Client)

- Check robot IP address: `ping ROBOT_IP`
- Verify server is running on robot
- Check firewall settings

### "No cameras found" (Server)

- Verify camera is connected: `ls /dev/video*`
- Check camera permissions: `sudo usermod -a -G video $USER`
- Try specific camera: `--camera /dev/video0`

### "Invalid frame dimensions" Error

- Camera may be sending invalid resolution
- Try different resolution: `--width 640 --height 480`
- Check camera compatibility with v4l2

### Low FPS / Lag

- Reduce streaming FPS: `--streaming-fps 15`
- Lower resolution: `--width 640 --height 480`
- Use UDP instead of TCP
- Check network bandwidth

## Files

- `simple_camera_stream.py` - Main streaming script
- `camera.py` - Camera discovery and control module
- `camera_stream.py` - Advanced streaming with HTTP support

## Keyboard Controls

When viewing stream on client:
- **q** - Quit
- **s** - Save current frame (if `--save-dir` is set)

## System Requirements

- Python 3.7+
- OpenCV 4.x
- NumPy
- Network connection between devices
