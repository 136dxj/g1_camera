#!/usr/bin/env python3
# Copyright 2025 Unitree Robotics
# Simplified Camera Control Module
# Dependencies: opencv-python, uvc (pupil-labs-uvc), numpy

import os
import glob
import time
import subprocess
import platform
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
import cv2
import numpy as np


# ========================================================
# UVC Driver Management
# ========================================================
def reload_uvc_driver():
    """Reload the UVC video driver."""
    try:
        subprocess.run("sudo modprobe -r uvcvideo", shell=True, check=True, capture_output=True)
        time.sleep(0.5)
        subprocess.run("sudo modprobe uvcvideo debug=0", shell=True, check=True, capture_output=True)
        time.sleep(0.5)
        print("[UVC Driver] Reloaded successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[UVC Driver] Warning: Failed to reload driver: {e}")


# ========================================================
# Camera Finder
# ========================================================
class CameraFinder:
    """
    Discover connected cameras and their properties.

    Attributes:
        video_paths: List of all /dev/videoX devices
        uvc_rgb_cameras: Dict of RGB-capable UVC cameras with metadata
        rs_serial_numbers: List of RealSense camera serial numbers (if enabled)
    """

    def __init__(self, realsense_enable: bool = False, verbose: bool = False):
        """
        Initialize camera finder.

        Args:
            realsense_enable: Whether to search for RealSense cameras
            verbose: Print detailed camera information
        """
        self.verbose = verbose
        self.rs_serial_numbers = []

        # Reload UVC driver for clean device discovery
        reload_uvc_driver()

        # List UVC devices
        try:
            import uvc
            self.uvc_devices = uvc.device_list()
            self.uid_map = {dev["uid"]: dev for dev in self.uvc_devices}
        except ImportError:
            print("[CameraFinder] Warning: uvc module not available. Install with: pip install pupil-labs-uvc")
            self.uvc_devices = []
            self.uid_map = {}

        # List all video devices
        self.video_paths = self._list_video_paths()

        # RealSense support
        if realsense_enable:
            self.rs_serial_numbers = self._list_realsense_serial_numbers()
            self.rs_video_paths = self._list_realsense_video_paths()
        else:
            self.rs_video_paths = []

        # List RGB-capable UVC cameras
        self.uvc_rgb_video_paths = self._list_uvc_rgb_video_paths()
        self.uvc_rgb_cameras = {}

        for vpath in self.uvc_rgb_video_paths:
            self.uvc_rgb_cameras[vpath] = {
                "video_id": int(vpath.replace("/dev/video", "")),
                "physical_path": self._get_ppath_from_vpath(vpath),
                "uid": self._get_uid_from_ppath(self._get_ppath_from_vpath(vpath)),
                "serial_number": self._get_serial_from_vpath(vpath),
                "dev_info": self.uid_map.get(self._get_uid_from_ppath(self._get_ppath_from_vpath(vpath)))
            }

        if self.verbose:
            self.info()

    # --------------------------------------------------------
    # Private methods
    # --------------------------------------------------------
    def _list_video_paths(self) -> List[str]:
        """List all /dev/video* devices."""
        base = "/sys/class/video4linux/"
        if not os.path.exists(base):
            return []
        return [f"/dev/{x}" for x in sorted(os.listdir(base)) if x.startswith("video")]

    def _list_uvc_rgb_video_paths(self) -> List[str]:
        """List UVC cameras that can output RGB."""
        return [p for p in self.video_paths if self._is_like_rgb(p) and p not in self.rs_video_paths]

    def _list_realsense_video_paths(self) -> List[str]:
        """List RealSense camera video devices."""
        def _read_text(path: str) -> Optional[str]:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read().strip()
            except Exception:
                return None

        def _parent_usb_device_sysdir(video_sysdir: str) -> Optional[str]:
            d = os.path.realpath(os.path.join(video_sysdir, "device"))
            for _ in range(10):
                if d is None or d == "/" or not os.path.isdir(d):
                    break
                id_vendor = _read_text(os.path.join(d, "idVendor"))
                id_product = _read_text(os.path.join(d, "idProduct"))
                if id_vendor and id_product:
                    return d
                d_next = os.path.dirname(d)
                if d_next == d:
                    break
                d = d_next
            return None

        ports = []
        for devnode in sorted(glob.glob("/dev/video*")):
            sysdir = f"/sys/class/video4linux/{os.path.basename(devnode)}"
            name = _read_text(os.path.join(sysdir, "name"))
            usb_dir = _parent_usb_device_sysdir(sysdir)
            vendor_id = _read_text(os.path.join(usb_dir, "idVendor")) if usb_dir else None

            # Match RealSense by name and Intel vendor ID
            if name and "realsense" in name.lower() and (vendor_id or "").lower() in ("8086", "32902"):
                ports.append(devnode)

        return ports

    def _list_realsense_serial_numbers(self) -> List[str]:
        """Get serial numbers of connected RealSense cameras."""
        try:
            import pyrealsense2 as rs
        except ImportError:
            print("[CameraFinder] pyrealsense2 not installed. RealSense cameras will not be detected.")
            return []

        ctx = rs.context()
        devices = ctx.query_devices()
        serials = []
        for dev in devices:
            try:
                serials.append(dev.get_info(rs.camera_info.serial_number))
            except Exception:
                continue
        return serials

    def _get_ppath_from_vpath(self, video_path: str) -> Optional[str]:
        """Get physical sysfs path from video device path."""
        sysfs_path = f"/sys/class/video4linux/{os.path.basename(video_path)}/device"
        return os.path.realpath(sysfs_path)

    def _get_uid_from_ppath(self, physical_path: Optional[str]) -> Optional[str]:
        """Get UVC UID (bus:dev) from physical path."""
        if physical_path is None:
            return None

        def read_file(path: str) -> Optional[str]:
            return open(path).read().strip() if os.path.exists(path) else None

        busnum_file = os.path.join(physical_path, "busnum")
        devnum_file = os.path.join(physical_path, "devnum")

        if not (os.path.exists(busnum_file) and os.path.exists(devnum_file)):
            parent = os.path.dirname(physical_path)
            busnum_file = os.path.join(parent, "busnum")
            devnum_file = os.path.join(parent, "devnum")

        if os.path.exists(busnum_file) and os.path.exists(devnum_file):
            bus = read_file(busnum_file)
            dev = read_file(devnum_file)
            return f"{bus}:{dev}" if bus and dev else None
        return None

    def _get_serial_from_vpath(self, video_path: str) -> Optional[str]:
        """Get serial number from video device path."""
        vpath_cam = self.uvc_rgb_cameras.get(video_path, {})
        if vpath_cam.get("dev_info"):
            return vpath_cam["dev_info"].get("serialNumber")
        return None

    def _is_like_rgb(self, video_path: str) -> bool:
        """Test if device can output RGB frames."""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return False
        ret, frame = cap.read()
        cap.release()
        return ret and frame is not None and frame.ndim == 3 and frame.shape[2] == 3

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------
    def info(self) -> None:
        """Print detailed camera information."""
        print("=" * 80)
        print("Camera Discovery Results")
        print("=" * 80)

        print(f"\n[All Video Devices]: {len(self.video_paths)} found")
        for vpath in self.video_paths:
            print(f"  - {vpath}")

        print(f"\n[RGB-capable UVC Cameras]: {len(self.uvc_rgb_cameras)} found")
        for vpath, info in self.uvc_rgb_cameras.items():
            print(f"\n  Device: {vpath}")
            print(f"    Video ID:      {info['video_id']}")
            print(f"    Physical Path: {info['physical_path']}")
            print(f"    UID:           {info['uid']}")
            print(f"    Serial Number: {info['serial_number']}")

        if self.rs_serial_numbers:
            print(f"\n[RealSense Cameras]: {len(self.rs_serial_numbers)} found")
            for serial in self.rs_serial_numbers:
                print(f"  - Serial: {serial}")

        print("=" * 80)

    def get_uid_by_serial(self, serial_number: str) -> Optional[str]:
        """Get UVC UID by serial number."""
        for cam in self.uvc_rgb_cameras.values():
            if cam.get("serial_number") == str(serial_number):
                return cam.get("uid")
        return None

    def get_uid_by_physical_path(self, physical_path: str) -> Optional[str]:
        """Get UVC UID by physical path."""
        for cam in self.uvc_rgb_cameras.values():
            if cam.get("physical_path") == physical_path:
                return cam.get("uid")
        return None

    def get_vpath_by_serial(self, serial_number: str) -> Optional[str]:
        """Get video device path by serial number."""
        matches = []
        for cam in self.uvc_rgb_cameras.values():
            if cam.get("serial_number") == str(serial_number):
                vpath = f"/dev/video{cam.get('video_id')}"
                matches.append(vpath)
        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(f"Multiple cameras found with serial {serial_number}: {matches}")
        return matches[0]

    def get_vpath_by_physical_path(self, physical_path: str) -> Optional[str]:
        """Get video device path by physical path."""
        base = "/sys/class/video4linux/"
        matches = []
        for v in os.listdir(base):
            sys_path = os.path.realpath(os.path.join(base, v, "device"))
            if sys_path == physical_path:
                vpath = f"/dev/{v}"
                if self._is_like_rgb(vpath):
                    matches.append(vpath)
        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(f"Multiple devices found for path {physical_path}: {matches}")
        return matches[0]

    def is_serial_exist(self, serial_number: str) -> bool:
        """Check if serial number exists."""
        return any(cam.get("serial_number") == str(serial_number) for cam in self.uvc_rgb_cameras.values())

    def is_rs_serial_exist(self, serial_number: str) -> bool:
        """Check if RealSense serial number exists."""
        return str(serial_number) in self.rs_serial_numbers


# ========================================================
# Base Camera Class
# ========================================================
class BaseCamera:
    """Base class for all camera types."""

    def __init__(self, name: str, img_shape: tuple, fps: int):
        """
        Initialize base camera.

        Args:
            name: Camera name/identifier
            img_shape: Image shape as (height, width)
            fps: Frames per second
        """
        self.name = name
        self.img_shape = img_shape  # (H, W)
        self.fps = fps
        self.is_opened = False
        self._frame_count = 0
        self._start_time = None

    def read(self) -> Optional[np.ndarray]:
        """
        Read a frame from the camera.

        Returns:
            BGR image as numpy array, or None if failed
        """
        raise NotImplementedError

    def read_jpeg(self) -> Optional[bytes]:
        """
        Read a frame as JPEG bytes.

        Returns:
            JPEG encoded frame as bytes, or None if failed
        """
        frame = self.read()
        if frame is not None:
            ok, buf = cv2.imencode(".jpg", frame)
            if ok:
                return buf.tobytes()
        return None

    def save(self, filepath: Optional[str] = None,
             format: str = "png",
             quality: int = 95,
             prefix: Optional[str] = None) -> Optional[str]:
        """
        Capture and save a frame to file.

        Args:
            filepath: Full path to save the image. If None, auto-generates based on prefix
            format: Image format ("png", "jpg", "jpeg", "bmp", "tiff")
            quality: JPEG quality (1-100), only used for JPEG format
            prefix: Custom prefix for auto-generated filename (defaults to camera name)

        Returns:
            Path to saved file, or None if capture failed
        """
        frame = self.read()
        if frame is None:
            print(f"[{self.name}] Failed to capture frame for saving.")
            return None

        # Generate filepath if not provided
        if filepath is None:
            if prefix is None:
                prefix = self.name.replace(" ", "_").replace("/", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # ms precision
            ext = "." + format.lower().replace("jpeg", "jpg")
            filepath = f"{prefix}_{timestamp}{ext}"

        # Ensure directory exists
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Save with format-specific options
        save_path = str(filepath)
        if format.lower() in ("jpg", "jpeg"):
            params = [cv2.IMWRITE_JPEG_QUALITY, quality]
        elif format.lower() == "png":
            params = [cv2.IMWRITE_PNG_COMPRESSION, 9]
        else:
            params = []

        success = cv2.imwrite(save_path, frame, params)

        if success:
            print(f"[{self.name}] Saved: {save_path} (shape={frame.shape})")
            return save_path
        else:
            print(f"[{self.name}] Failed to save: {save_path}")
            return None

    def save_batch(self, count: int,
                   interval: float = 0.1,
                   directory: str = "captured_frames",
                   format: str = "png") -> List[str]:
        """
        Capture and save multiple frames.

        Args:
            count: Number of frames to capture
            interval: Delay between captures in seconds
            directory: Directory to save frames
            format: Image format

        Returns:
            List of saved file paths
        """
        saved_paths = []
        prefix = self.name.replace(" ", "_").replace("/", "_")

        for i in range(count):
            filepath = f"{directory}/{prefix}_{i:04d}.{format.lower().replace('jpeg', 'jpg')}"
            path = self.save(filepath, format=format)
            if path:
                saved_paths.append(path)
            if i < count - 1:
                time.sleep(interval)

        print(f"[{self.name}] Saved {len(saved_paths)}/{count} frames to {directory}/")
        return saved_paths

    def release(self) -> None:
        """Release camera resources."""
        raise NotImplementedError

    def get_fps_actual(self) -> float:
        """Get actual FPS since camera started."""
        if self._start_time is None or self._frame_count == 0:
            return 0.0
        elapsed = time.time() - self._start_time
        return self._frame_count / elapsed if elapsed > 0 else 0.0

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', shape={self.img_shape}, fps={self.fps})"


# ========================================================
# UVC Camera
# ========================================================
class UVCCamera(BaseCamera):
    """UVC camera using pupil-labs-uvc library."""

    def __init__(self, uid: str, img_shape: tuple = (480, 640), fps: int = 30, name: str = "UVC"):
        """
        Initialize UVC camera.

        Args:
            uid: UVC device UID (e.g., "001:002") or use CameraFinder to get it
            img_shape: Image shape as (height, width)
            fps: Frames per second
            name: Camera name
        """
        super().__init__(name, img_shape, fps)

        try:
            import uvc
        except ImportError:
            raise ImportError("uvc module not installed. Install with: pip install pupil-labs-uvc")

        self.uid = uid
        self.cap = None

        try:
            self.cap = uvc.Capture(self.uid)
            self.cap.frame_mode = self._find_mode(img_shape[1], img_shape[0], fps)
            self.is_opened = True
            self._start_time = time.time()
            print(f"[UVCCamera] {self} initialized successfully.")
        except Exception as e:
            self.cap = None
            raise RuntimeError(f"[UVCCamera] Failed to open camera {name}: {e}")

    def _find_mode(self, width: int, height: int, fps: int):
        """Find matching UVC mode."""
        for m in self.cap.available_modes:
            if m.width == width and m.height == height and m.fps == fps and m.format_name == "MJPG":
                return m
        # Fallback to first matching resolution
        for m in self.cap.available_modes:
            if m.width == width and m.height == height:
                return m
        raise ValueError(f"No UVC mode found for {width}x{height}@{fps}fps")

    def read(self) -> Optional[np.ndarray]:
        """Read a BGR frame."""
        if self.cap is None:
            return None

        frame = self.cap.get_frame_robust()
        if frame is not None and frame.bgr is not None:
            self._frame_count += 1
            return frame.bgr
        return None

    def read_jpeg(self) -> Optional[bytes]:
        """Read JPEG frame directly from camera (faster)."""
        if self.cap is None:
            return None

        frame = self.cap.get_frame_robust()
        if frame is not None and frame.jpeg_buffer is not None:
            self._frame_count += 1
            return bytes(frame.jpeg_buffer)
        return None

    def release(self) -> None:
        """Release camera."""
        if self.cap is not None:
            try:
                # Note: stop_streaming and close may hang if USB disconnected
                # self.cap.stop_streaming()
                # self.cap.close()
                pass
            except Exception as e:
                print(f"[UVCCamera] Warning during release: {e}")
            self.cap = None
            self.is_opened = False
            print(f"[UVCCamera] {self.name} released.")


# ========================================================
# OpenCV Camera
# ========================================================
class OpenCVCamera(BaseCamera):
    """Camera using OpenCV VideoCapture with V4L2 backend."""

    def __init__(self, video_path: str, img_shape: tuple = (480, 640), fps: int = 30, name: str = "OpenCV"):
        """
        Initialize OpenCV camera.

        Args:
            video_path: Video device path (e.g., "/dev/video0")
            img_shape: Image shape as (height, width)
            fps: Frames per second
            name: Camera name
        """
        super().__init__(name, img_shape, fps)

        self.video_path = video_path
        self.cap = cv2.VideoCapture(video_path, cv2.CAP_V4L2)

        # Configure camera
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, img_shape[0])
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, img_shape[1])
        self.cap.set(cv2.CAP_PROP_FPS, fps)

        # Verify camera works
        if not self.cap.isOpened() or not self._test_read():
            self.cap.release()
            raise RuntimeError(f"[OpenCVCamera] Failed to open camera {name} at {video_path}")

        self.is_opened = True
        self._start_time = time.time()
        print(f"[OpenCVCamera] {self} initialized successfully.")

    def _test_read(self) -> bool:
        """Test if camera can read frames."""
        ret, _ = self.cap.read()
        return ret

    def read(self) -> Optional[np.ndarray]:
        """Read a BGR frame."""
        if self.cap is None:
            return None

        ret, frame = self.cap.read()
        if ret:
            self._frame_count += 1
            return frame
        return None

    def release(self) -> None:
        """Release camera."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None
            self.is_opened = False
            print(f"[OpenCVCamera] {self.name} released.")


# ========================================================
# RealSense Camera
# ========================================================
class RealSenseCamera(BaseCamera):
    """Intel RealSense camera using pyrealsense2."""

    def __init__(self, serial_number: str, img_shape: tuple = (480, 640), fps: int = 30,
                 enable_depth: bool = False, name: str = "RealSense"):
        """
        Initialize RealSense camera.

        Args:
            serial_number: Camera serial number
            img_shape: Image shape as (height, width)
            fps: Frames per second
            enable_depth: Enable depth stream
            name: Camera name
        """
        super().__init__(name, img_shape, fps)

        try:
            import pyrealsense2 as rs
        except ImportError:
            raise ImportError("pyrealsense2 not installed. Install from: https://github.com/IntelRealSense/librealsense")

        self.serial_number = serial_number
        self.enable_depth = enable_depth
        self.latest_depth = None
        self.pipeline = None
        self.align = None

        try:
            self.align = rs.align(rs.stream.color)
            self.pipeline = rs.pipeline()
            config = rs.config()
            config.enable_device(serial_number)

            # Enable color stream
            config.enable_stream(rs.stream.color, img_shape[1], img_shape[0], rs.format.bgr8, fps)

            # Enable depth stream if requested
            if enable_depth:
                config.enable_stream(rs.stream.depth, img_shape[1], img_shape[0], rs.format.z16, fps)

            profile = self.pipeline.start(config)
            device = profile.get_device()

            if enable_depth and device:
                depth_sensor = device.first_depth_sensor()
                self.depth_scale = depth_sensor.get_depth_scale()

            self.is_opened = True
            self._start_time = time.time()
            print(f"[RealSenseCamera] {self} initialized successfully.")
        except Exception as e:
            if self.pipeline:
                try:
                    self.pipeline.stop()
                except:
                    pass
            raise RuntimeError(f"[RealSenseCamera] Failed to open camera {name}: {e}")

    def read(self) -> Optional[np.ndarray]:
        """Read a BGR frame."""
        if self.pipeline is None:
            return None

        try:
            frames = self.pipeline.wait_for_frames()
            aligned_frames = self.align.process(frames)
            color_frame = aligned_frames.get_color_frame()

            if not color_frame:
                return None

            # Get depth frame if enabled
            if self.enable_depth:
                depth_frame = aligned_frames.get_depth_frame()
                if depth_frame:
                    self.latest_depth = np.asanyarray(depth_frame.get_data())
                else:
                    self.latest_depth = None

            frame = np.asanyarray(color_frame.get_data())
            self._frame_count += 1
            return frame
        except Exception:
            return None

    def get_depth(self) -> Optional[np.ndarray]:
        """Get latest depth frame."""
        return self.latest_depth

    def release(self) -> None:
        """Release camera."""
        if self.pipeline is not None:
            try:
                self.pipeline.stop()
            except Exception as e:
                print(f"[RealSenseCamera] Warning during release: {e}")
            self.pipeline = None
            self.is_opened = False
            print(f"[RealSenseCamera] {self.name} released.")


# ========================================================
# Convenience Functions
# ========================================================
def find_cameras(verbose: bool = True) -> CameraFinder:
    """
    Find all connected cameras.

    Args:
        verbose: Print detailed information

    Returns:
        CameraFinder instance with all camera information
    """
    return CameraFinder(realsense_enable=False, verbose=verbose)


def open_camera(identifier: str = "/dev/video0",
                camera_type: str = "opencv",
                img_shape: tuple = (480, 640),
                fps: int = 30,
                finder: Optional[CameraFinder] = None) -> BaseCamera:
    """
    Open a camera by identifier.

    Args:
        identifier: Camera identifier (video path, serial number, or physical path)
        camera_type: Camera type ("opencv", "uvc", or "realsense")
        img_shape: Image shape as (height, width)
        fps: Frames per second
        finder: CameraFinder instance (for serial/physical path lookup)

    Returns:
        Camera instance
    """
    if camera_type == "opencv":
        # If identifier looks like a serial/physical path, resolve it
        if identifier.startswith("/") and not identifier.startswith("/dev"):
            if finder is None:
                finder = CameraFinder()
            identifier = finder.get_vpath_by_physical_path(identifier)
            if identifier is None:
                raise ValueError(f"Could not resolve physical path: {identifier}")
        elif ":" in identifier or len(identifier.split("-")) > 1:
            # Looks like a serial number
            if finder is None:
                finder = CameraFinder()
            identifier = finder.get_vpath_by_serial(identifier)
            if identifier is None:
                raise ValueError(f"Could not find camera with serial: {identifier}")

        return OpenCVCamera(identifier, img_shape, fps)

    elif camera_type == "uvc":
        uid = identifier
        # If identifier is not in UID format, try to resolve
        if ":" not in identifier:
            if finder is None:
                finder = CameraFinder()
            # Try as serial number first
            uid = finder.get_uid_by_serial(identifier)
            if uid is None:
                # Try as video path
                uid = finder.get_uid_by_physical_path(identifier)
                if uid is None:
                    raise ValueError(f"Could not resolve identifier to UID: {identifier}")

        return UVCCamera(uid, img_shape, fps)

    elif camera_type == "realsense":
        return RealSenseCamera(identifier, img_shape, fps)

    else:
        raise ValueError(f"Unknown camera type: {camera_type}")


# ========================================================
# Image Save Functions
# ========================================================
def save_image(frame: np.ndarray,
               filepath: Optional[str] = None,
               format: str = "png",
               quality: int = 95,
               prefix: str = "image") -> Optional[str]:
    """
    Save a numpy array image to file.

    Args:
        frame: BGR image as numpy array
        filepath: Full path to save. If None, auto-generates with timestamp
        format: Image format ("png", "jpg", "jpeg", "bmp", "tiff")
        quality: JPEG quality (1-100)
        prefix: Prefix for auto-generated filename

    Returns:
        Path to saved file, or None if failed
    """
    if frame is None:
        print("[save_image] Error: frame is None")
        return None

    # Generate filepath if not provided
    if filepath is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        ext = "." + format.lower().replace("jpeg", "jpg")
        filepath = f"{prefix}_{timestamp}{ext}"

    # Ensure directory exists
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Format-specific parameters
    if format.lower() in ("jpg", "jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    elif format.lower() == "png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 9]
    else:
        params = []

    success = cv2.imwrite(str(filepath), frame, params)

    if success:
        print(f"[save_image] Saved: {filepath} (shape={frame.shape})")
        return str(filepath)
    else:
        print(f"[save_image] Failed to save: {filepath}")
        return None


def save_jpeg_bytes(jpeg_bytes: bytes,
                    filepath: Optional[str] = None,
                    prefix: str = "image") -> Optional[str]:
    """
    Save JPEG bytes directly to file (faster than re-encoding).

    Args:
        jpeg_bytes: JPEG encoded bytes
        filepath: Full path to save. If None, auto-generates with timestamp
        prefix: Prefix for auto-generated filename

    Returns:
        Path to saved file, or None if failed
    """
    if jpeg_bytes is None:
        print("[save_jpeg_bytes] Error: jpeg_bytes is None")
        return None

    # Generate filepath if not provided
    if filepath is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filepath = f"{prefix}_{timestamp}.jpg"

    # Ensure directory exists
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(filepath, "wb") as f:
            f.write(jpeg_bytes)
        print(f"[save_jpeg_bytes] Saved: {filepath} (size={len(jpeg_bytes)} bytes)")
        return str(filepath)
    except Exception as e:
        print(f"[save_jpeg_bytes] Failed to save: {e}")
        return None


def create_video_writer(output_path: str,
                        fourcc: str = "mp4v",
                        fps: float = 30.0,
                        frame_size: tuple = (640, 480)) -> Optional[cv2.VideoWriter]:
    """
    Create a video writer for saving frames as video.

    Args:
        output_path: Output video file path
        fourcc: FourCC codec code ("mp4v", "avc1", "xvid", "mjpa")
        fps: Frames per second
        frame_size: Frame size as (width, height)

    Returns:
        cv2.VideoWriter object, or None if failed
    """
    # Ensure directory exists
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fourcc_obj = cv2.VideoWriter_fourcc(*fourcc)
    writer = cv2.VideoWriter(str(output_path), fourcc_obj, fps, frame_size)

    if not writer.isOpened():
        print(f"[create_video_writer] Failed to create video writer: {output_path}")
        return None

    print(f"[create_video_writer] Created: {output_path} (codec={fourcc}, fps={fps}, size={frame_size})")
    return writer


# ========================================================
# Main - Example Usage
# ========================================================
def main():
    """Example usage of camera module with image saving."""

    print("\n" + "=" * 60)
    print("Camera Control Module - Example Usage")
    print("=" * 60 + "\n")

    # Step 1: Find all cameras
    print("[Step 1] Discovering cameras...")
    finder = find_cameras(verbose=True)

    if not finder.uvc_rgb_video_paths:
        print("\nNo cameras found! Exiting.")
        return

    # Step 2: Open first camera
    print("\n[Step 2] Opening first camera...")
    vpath = finder.uvc_rgb_video_paths[0]
    try:
        cam = OpenCVCamera(vpath, name="TestCamera", img_shape=(480, 640), fps=30)
    except Exception as e:
        print(f"Failed to open camera: {e}")
        return

    # Step 3: Test frame capture
    print("\n[Step 3] Capturing test frames...")
    for i in range(50):
        frame = cam.read()
        if frame is not None:
            if i == 0:
                print(f"  Frame shape: {frame.shape}")
            print(f"  Frame {i+1}: OK")
        else:
            print(f"  Frame {i+1}: Failed")
        # time.sleep(0.1)

    fps = cam.get_fps_actual()
    print(f"  Actual FPS: {fps:.1f}")

    # Step 4: Save single frame (various formats)
    print("\n[Step 4] Saving single frames...")
    cam.save("output/test_image.png", format="png")
    cam.save("output/test_image.jpg", format="jpg", quality=90)
    cam.save("output/custom_prefix.bmp", format="bmp", prefix="my_camera")

    # Also test using the standalone function
    frame = cam.read()
    if frame is not None:
        save_image(frame, "output/standalone_save.png")

    # Step 5: Save batch of frames
    print("\n[Step 5] Saving batch of frames...")
    cam.save_batch(count=5, interval=0.2, directory="output/batch", format="jpg")

    # Step 6: Save JPEG directly (faster, no re-encoding)
    print("\n[Step 6] Saving JPEG bytes directly...")
    jpeg_bytes = cam.read_jpeg()
    if jpeg_bytes:
        save_jpeg_bytes(jpeg_bytes, "output/direct_jpeg.jpg")

    # Step 7: Save video example
    print("\n[Step 7] Saving short video...")
    video_path = "output/test_video.mp4"
    writer = create_video_writer(video_path, fps=30, frame_size=(640, 480))
    if writer:
        for i in range(90):  # 3 seconds at 30fps
            frame = cam.read()
            if frame is not None:
                # Resize if needed
                if frame.shape[1] != 640 or frame.shape[0] != 480:
                    frame = cv2.resize(frame, (640, 480))
                writer.write(frame)
            time.sleep(1/30)
        writer.release()
        print(f"  Video saved: {video_path}")

    # Step 8: Cleanup
    print("\n[Step 8] Releasing camera...")
    cam.release()

    print("\n" + "=" * 60)
    print("All done! Check the 'output/' directory for saved images.")
    print("=" * 60 + "\n")


# ========================================================
# Alternative: Quick capture and save example
# ========================================================
def quick_capture_example():
    """Quick example: capture and save one frame."""
    print("\n[Quick Capture] Finding and capturing from first camera...")

    finder = find_cameras(verbose=False)
    if not finder.uvc_rgb_video_paths:
        print("No cameras found!")
        return

    # Using context manager (auto-release)
    with OpenCVCamera(finder.uvc_rgb_video_paths[0]) as cam:
        # Save with auto-generated filename
        saved_path = cam.save(format="jpg")
        print(f"Saved to: {saved_path}")

    print("Done!\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        quick_capture_example()
    else:
        main()