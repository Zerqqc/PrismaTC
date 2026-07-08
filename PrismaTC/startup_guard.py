"""Startup helpers to reduce intermittent Nuitka/DearPyGui launch failures."""
import ctypes
import faulthandler
import os
import sys
from typing import Optional

MUTEX_NAME = "Global\\PrismaTC_SingleInstance_v1"
ERROR_ALREADY_EXISTS = 183


def _base_dir() -> str:
	return os.path.dirname(os.path.abspath(__file__))


def enable_crash_logging() -> None:
	"""Optional dev-only crash log. Set PRISMATC_DEBUG=1 to enable prisma_startup.log."""
	if os.environ.get("PRISMATC_DEBUG", "").strip().lower() not in ("1", "true", "yes"):
		return
	try:
		log_path = os.path.join(_base_dir(), "prisma_startup.log")
		log_file = open(log_path, "a", encoding="utf-8")
		log_file.write(f"\n--- debug session start pid={os.getpid()} ---\n")
		log_file.flush()
		faulthandler.enable(file=log_file, all_threads=True)
	except Exception:
		pass


def _foreground_existing_window() -> None:
	try:
		import win32gui
		import win32con

		windows = []

		def callback(hwnd, _):
			title = win32gui.GetWindowText(hwnd)
			if title and "PrismaTC" in title:
				windows.append(hwnd)
			return True

		win32gui.EnumWindows(callback, None)
		if not windows:
			return

		hwnd = windows[0]
		win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
		win32gui.SetForegroundWindow(hwnd)
	except Exception:
		pass


def ensure_single_instance() -> bool:
	"""Return True if this process should continue; False if another instance is active."""
	kernel32 = ctypes.windll.kernel32
	kernel32.CreateMutexW(None, False, MUTEX_NAME)
	if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
		_foreground_existing_window()
		return False
	return True


def is_frozen_build() -> bool:
	return bool(getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"))