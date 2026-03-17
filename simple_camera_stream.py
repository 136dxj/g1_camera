#!/usr/bin/env python3
"""
Simple Camera Stream - TCP/UDP
===============================

Direct image transmission between two known IPs.

Server (Robot):
    python simple_camera_stream.py server --port 8888

Client (PC):
    python simple_camera_stream.py client --host ROBOT_IP --port 8888
"""

import os
import sys
import time
import socket
import struct
import argparse
import threading

import cv2
import numpy as np
from camera import find_cameras, CameraFinder

# ========================================================
# Server (Robot)
# ========================================================

def run_server(host="0.0.0.0", port=8888, camera_path="/dev/video0",
               width=640, height=480, fps=30, protocol="tcp"):
    """
    Run camera server.

    Args:
        host: Server host (use "0.0.0.0" for all interfaces)
        port: Server port
        camera_path: Camera device path
        width: Image width
        height: Image height
        fps: Target FPS
        protocol: "tcp" or "udp"
    """

    # Open camera
    print(f"\n[Server] Opening camera: {camera_path}")
    cap = cv2.VideoCapture(camera_path, cv2.CAP_V4L2)

    if not cap.isOpened():
        print(f"[Server] ERROR: Failed to open camera {camera_path}")
        return

    # Configure camera
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

    # Warm up
    print("[Server] Warming up camera...")
    for _ in range(5):
        cap.read()
        time.sleep(0.05)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[Server] Camera ready: {actual_w}x{actual_h}")

    # Get local IP
    local_ip = get_local_ip()
    print(f"[Server] Local IP: {local_ip}")

    # Start server
    if protocol == "tcp":
        run_tcp_server(cap, host, port, local_ip)
    else:
        run_udp_server(cap, host, port, local_ip)


def run_tcp_server(cap, host, port, local_ip):
    """Run TCP streaming server."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Try to bind
    bind_host = host
    try:
        server_sock.bind((bind_host, port))
    except OSError as e:
        print(f"[Server] Failed to bind {bind_host}:{port} - {e}")
        if bind_host == "0.0.0.0":
            bind_host = local_ip
            print(f"[Server] Retrying with {bind_host}")
            server_sock.bind((bind_host, port))

    server_sock.listen(1)

    display_ip = bind_host if bind_host != "0.0.0.0" else local_ip
    print(f"\n[Server] TCP listening on: {display_ip}:{port}")
    print(f"[Server] Waiting for client...\n")

    # Accept client
    conn, addr = server_sock.accept()
    print(f"[Server] Client connected: {addr[0]}:{addr[1]}")

    # Send frames
    last_time = time.time()
    frame_count = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                print("[Server] Failed to read frame")
                time.sleep(0.1)
                continue

            # Encode to JPEG
            result, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not result or jpeg is None:
                print("[Server] Failed to encode frame")
                continue
            jpeg_bytes = jpeg.tobytes()

            # Send size + data
            size = struct.pack("!I", len(jpeg_bytes))
            conn.sendall(size + jpeg_bytes)

            # FPS counter
            frame_count += 1
            if time.time() - last_time >= 1.0:
                fps = frame_count / (time.time() - last_time)
                print(f"[Server] Streaming: {fps:.1f} FPS, size: {len(jpeg_bytes)} bytes")
                frame_count = 0
                last_time = time.time()

    except (ConnectionResetError, BrokenPipeError):
        print(f"\n[Server] Client disconnected")
    except KeyboardInterrupt:
        print("\n[Server] Stopped")
    finally:
        conn.close()
        server_sock.close()
        cap.release()


def run_udp_server(cap, host, port, local_ip):
    """Run UDP streaming server."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Try to bind
    bind_host = host
    try:
        server_sock.bind((bind_host, port))
    except OSError as e:
        print(f"[Server] Failed to bind {bind_host}:{port} - {e}")
        if bind_host == "0.0.0.0":
            bind_host = local_ip
            print(f"[Server] Retrying with {bind_host}")
            server_sock.bind((bind_host, port))

    display_ip = bind_host if bind_host != "0.0.0.0" else local_ip
    print(f"\n[Server] UDP listening on: {display_ip}:{port}")
    print(f"[Server] Waiting for client ping...\n")

    clients = set()
    last_time = time.time()
    frame_count = 0

    try:
        while True:
            # Check for new clients
            try:
                server_sock.settimeout(0.01)
                data, addr = server_sock.recvfrom(1024)
                if addr not in clients:
                    clients.add(addr)
                    print(f"[Server] Client registered: {addr[0]}:{addr[1]}")
            except socket.timeout:
                pass

            # Send to all clients
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            # Encode to JPEG
            result, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not result or jpeg is None:
                continue
            jpeg_bytes = jpeg.tobytes()
            size = struct.pack("!I", len(jpeg_bytes))
            data = size + jpeg_bytes

            for client_addr in list(clients):
                try:
                    server_sock.sendto(data, client_addr)
                except:
                    clients.discard(client_addr)

            # FPS counter
            frame_count += 1
            if time.time() - last_time >= 1.0:
                fps = frame_count / (time.time() - last_time)
                print(f"[Server] Streaming: {fps:.1f} FPS to {len(clients)} client(s)")
                frame_count = 0
                last_time = time.time()

    except KeyboardInterrupt:
        print("\n[Server] Stopped")
    finally:
        server_sock.close()
        cap.release()


# ========================================================
# Client (PC)
# ========================================================

def run_client(host, port=8888, protocol="tcp", save_dir=None):
    """
    Run camera client.

    Args:
        host: Server IP address (robot IP)
        port: Server port
        protocol: "tcp" or "udp"
        save_dir: Optional directory to save frames
    """
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)

    print(f"\n[Client] Connecting to {host}:{port} ({protocol.upper()})")

    if protocol == "tcp":
        run_tcp_client(host, port, save_dir)
    else:
        run_udp_client(host, port, save_dir)


def run_tcp_client(host, port, save_dir):
    """Run TCP client."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)

    try:
        sock.connect((host, port))
        print(f"[Client] Connected! Press 'q' to quit")
    except Exception as e:
        print(f"[Client] Connection failed: {e}")
        return

    buffer = b""
    frame_count = 0
    last_save_time = 0

    try:
        while True:
            # Receive frame size
            size_data = recv_all(sock, 4)
            if not size_data:
                break

            size = struct.unpack("!I", size_data)[0]

            # Receive JPEG data
            jpeg_data = recv_all(sock, size)
            if not jpeg_data:
                break

            # Decode
            frame = cv2.imdecode(np.frombuffer(jpeg_data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue

            # Display
            cv2.imshow(f"Camera - {host}", frame)
            key = cv2.waitKey(1) & 0xFF

            if key == ord('q'):
                break
            elif key == ord('s') and save_dir:
                filepath = f"{save_dir}/frame_{frame_count:06d}.jpg"
                cv2.imwrite(filepath, frame)
                print(f"[Client] Saved: {filepath}")
                frame_count += 1

            # Auto save
            if save_dir and time.time() - last_save_time > 0.1:
                filepath = f"{save_dir}/auto_{frame_count:06d}.jpg"
                cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                frame_count += 1
                last_save_time = time.time()

    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        cv2.destroyAllWindows()


def run_udp_client(host, port, save_dir):
    """Run UDP client."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.1)

    # Send ping to register
    sock.sendto(b"PING", (host, port))
    print(f"[Client] Registered with server. Press 'q' to quit")

    buffer = b""
    frame_count = 0
    last_save_time = 0

    try:
        while True:
            try:
                data, _ = sock.recvfrom(65536)
                buffer += data

                # Process complete frames
                while len(buffer) >= 4:
                    size = struct.unpack("!I", buffer[:4])[0]

                    if len(buffer) >= 4 + size:
                        jpeg_data = buffer[4:4+size]
                        buffer = buffer[4+size:]

                        frame = cv2.imdecode(np.frombuffer(jpeg_data, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            cv2.imshow(f"Camera - {host}", frame)
                            key = cv2.waitKey(1) & 0xFF

                            if key == ord('q'):
                                raise KeyboardInterrupt()
                            elif key == ord('s') and save_dir:
                                filepath = f"{save_dir}/frame_{frame_count:06d}.jpg"
                                cv2.imwrite(filepath, frame)
                                print(f"[Client] Saved: {filepath}")
                                frame_count += 1

                            if save_dir and time.time() - last_save_time > 0.1:
                                filepath = f"{save_dir}/auto_{frame_count:06d}.jpg"
                                cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                                frame_count += 1
                                last_save_time = time.time()
                    else:
                        break

            except socket.timeout:
                # Send keepalive ping
                sock.sendto(b"PING", (host, port))

    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        cv2.destroyAllWindows()


def recv_all(sock, size):
    """Receive exactly size bytes."""
    data = b""
    while len(data) < size:
        packet = sock.recv(size - len(data))
        if not packet:
            return None
        data += packet
    return data


def get_local_ip():
    """Get local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


# ========================================================
# Main
# ========================================================

def main():
    parser = argparse.ArgumentParser(description="Simple Camera Stream")
    parser.add_argument("mode", choices=["server", "client"],
                        help="Mode: server (robot) or client (PC)")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Server host (0.0.0.0 for all, or specific IP)")
    parser.add_argument("--port", type=int, default=8888,
                        help="Port number")
    parser.add_argument("--camera", default="/dev/video0",
                        help="Camera device (server only)")
    parser.add_argument("--width", type=int, default=640,
                        help="Image width (server only)")
    parser.add_argument("--height", type=int, default=480,
                        help="Image height (server only)")
    parser.add_argument("--fps", type=int, default=30,
                        help="Target FPS (server only)")
    parser.add_argument("--protocol", choices=["tcp", "udp"],
                        default="tcp", help="Protocol")
    parser.add_argument("--save-dir", type=str, default=None,
                        help="Save frames to directory (client only)")

    args = parser.parse_args()

    if args.mode == "server":
        print("[Step 1] Discovering cameras...")
        finder = find_cameras(verbose=True)

        if not finder.uvc_rgb_video_paths:
            print("\nNo cameras found! Exiting.")
            return

        # Step 2: Open first camera
        print("\n[Step 2] Opening first camera...")
        vpath = finder.uvc_rgb_video_paths[0]
        run_server(
            host=args.host,
            port=args.port,
            camera_path=vpath,
            width=args.width,
            height=args.height,
            fps=args.fps,
            protocol=args.protocol
        )
    else:
        if args.host == "0.0.0.0":
            print("[Error] Please specify robot IP with --host")
            print("Example: python simple_camera_stream.py client --host 192.168.1.100")
            return

        run_client(
            host=args.host,
            port=args.port,
            protocol=args.protocol,
            save_dir=args.save_dir
        )


if __name__ == "__main__":
    main()
