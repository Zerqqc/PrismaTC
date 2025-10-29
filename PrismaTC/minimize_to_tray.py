import os
import threading
from typing import Optional
from safe_print import safe_print

try:
	from pystray import Icon, Menu, MenuItem
	from PIL import Image
	import win32gui
	import win32con
	PYSTRAY_AVAILABLE = True
	WIN32_AVAILABLE = True
except ImportError:
	PYSTRAY_AVAILABLE = False
	WIN32_AVAILABLE = False
	Icon = None


class TrayManager:
	
	def __init__(self, on_restore_callback=None, on_exit_callback=None):
		self.on_restore_callback = on_restore_callback
		self.on_exit_callback = on_exit_callback
		self.tray_icon = None
		self.tray_thread = None
		self.is_minimized = False
		self.hwnd = None
	
	def find_window_handle(self, window_title: str = "PrismaTC") -> Optional[int]:
		if not WIN32_AVAILABLE:
			return None
		
		def callback(hwnd, windows):
			if win32gui.IsWindowVisible(hwnd):
				title = win32gui.GetWindowText(hwnd)
				if window_title in title:
					windows.append(hwnd)
			return True
		
		windows = []
		win32gui.EnumWindows(callback, windows)
		
		if windows:
			self.hwnd = windows[0]
			return self.hwnd
		return None
	
	def minimize_to_tray(self) -> bool:
		if not PYSTRAY_AVAILABLE:
			return False
		
		if not self.hwnd:
			self.find_window_handle()
		
		if self.hwnd and WIN32_AVAILABLE:
			win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
		
		self._create_tray_icon()
		self.is_minimized = True
		return True
	
	def restore_from_tray(self) -> bool:
		if self.hwnd and WIN32_AVAILABLE:
			win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
			win32gui.SetForegroundWindow(self.hwnd)
		
		self._stop_tray_icon()
		self.is_minimized = False
		
		if self.on_restore_callback:
			self.on_restore_callback()
		
		return True
	
	def _create_tray_icon(self) -> None:
		if self.tray_icon is not None:
			return
		
		icon_path = os.path.join(os.path.dirname(__file__), "src", "logo.png")
		if os.path.exists(icon_path):
			image = Image.open(icon_path)
		else:
			image = Image.new('RGB', (64, 64), color=(100, 150, 255))
		
		def on_restore(icon, item):
			self.restore_from_tray()
		
		def on_quit(icon, item):
			icon.stop()
			if self.on_exit_callback:
				self.on_exit_callback()
		
		menu = Menu(
			MenuItem('Restore', on_restore, default=True),
			MenuItem('Exit', on_quit)
		)
		
		self.tray_icon = Icon("PrismaTC", image, "PrismaTC", menu)
		self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
		self.tray_thread.start()
	
	def _stop_tray_icon(self) -> None:
		if self.tray_icon is not None:
			self.tray_icon.stop()
			self.tray_icon = None
	
	def cleanup(self) -> None:
		self._stop_tray_icon()
