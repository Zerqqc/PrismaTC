import ctypes
import os
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

import configparser
import psutil

from memory_reader import GameState, MenuMods, GameplayData, OsuMemoryReader
from gui import ManiaGUI
from safe_print import safe_print

import keyboard


class HitObject(ctypes.Structure):
	_fields_ = [
		("x", ctypes.c_int),
		("y", ctypes.c_int),
		("timestamp", ctypes.c_int),
		("object_type", ctypes.c_int),
		("end_time", ctypes.c_int),
	]

@dataclass
class BeatmapSession:
	identifier: str
	map_id: int
	title: str
	difficulty: str
	path: str
	keys: int
	lane_positions: List[int]
	hit_objects: List[HitObject]
	first_hit_time: int
	first_hit_time_original: int
	mods_string: str
	speed_multiplier: float


def auto_detect_osu_songs_dir() -> str:
	try:
		for process in psutil.process_iter(["pid", "name", "exe"]):
			name = process.info.get("name")
			if name and name.lower() == "osu!.exe":
				exe_path = process.info.get("exe")
				if exe_path:
					osu_dir = os.path.dirname(exe_path)
					songs_dir = os.path.join(osu_dir, "Songs")
					if os.path.isdir(songs_dir):
						return songs_dir
	except Exception:
		pass

	try:
		appdata = os.environ.get("LOCALAPPDATA", "")
		if appdata:
			fallback_dir = os.path.join(appdata, "osu!", "Songs")
			if os.path.isdir(fallback_dir):
				return fallback_dir
	except Exception:
		pass

	return ""


def parse_osu_file(file_path: str, speed_multiplier: float = 1.0) -> List[HitObject]:
	hit_objects: List[HitObject] = []
	try:
		with open(file_path, "r", encoding="utf-8") as osu_file:
			in_hit_object_section = False
			for raw_line in osu_file:
				line = raw_line.strip()
				if not in_hit_object_section:
					if line == "[HitObjects]":
						in_hit_object_section = True
					continue

				if not line:
					break

				parts = line.split(",")
				if len(parts) < 5:
					continue

				try:
					x = int(parts[0])
					y = int(parts[1])
					timestamp = int(int(parts[2]) / speed_multiplier)
					object_type = int(parts[3])
				except ValueError:
					continue

				is_hold = bool(object_type & 128)
				end_time = timestamp
				if is_hold and len(parts) >= 6:
					hold_data = parts[5].split(":")[0]
					try:
						end_time = int(int(hold_data) / speed_multiplier)
					except ValueError:
						end_time = timestamp

				hit_objects.append(HitObject(x, y, timestamp, object_type, end_time))
	except FileNotFoundError:
		pass
	except Exception:
		pass

	hit_objects.sort(key=lambda obj: obj.timestamp)
	return hit_objects


def get_lane_positions(hit_objects: List[HitObject]) -> List[int]:
	original_positions = sorted({obj.x for obj in hit_objects})
	return original_positions


def map_x_to_cs_position(x: int, cs_keys: int) -> int:
	position_width = 512 / cs_keys
	position = int(x / position_width)
	return min(position, cs_keys - 1)


def remap_hit_objects_to_cs_positions(hit_objects: List[HitObject], cs_keys: int) -> List[HitObject]:
	position_width = 512 / cs_keys
	remapped_objects = []
	
	for obj in hit_objects:
		position_index = map_x_to_cs_position(obj.x, cs_keys)
		new_x = int((position_index + 0.5) * position_width)
		remapped_objects.append(
			HitObject(
				x=new_x,
				y=obj.y,
				timestamp=obj.timestamp,
				object_type=obj.object_type,
				end_time=obj.end_time
			)
		)
	
	return remapped_objects


def get_first_hit_time_original(file_path: str) -> int:
	try:
		with open(file_path, "r", encoding="utf-8") as osu_file:
			in_hit_object_section = False
			for raw_line in osu_file:
				line = raw_line.strip()
				if not in_hit_object_section:
					if line == "[HitObjects]":
						in_hit_object_section = True
					continue
				if not line:
					break
				parts = line.split(",")
				if len(parts) >= 5:
					try:
						return int(parts[2])
					except ValueError:
						continue
	except Exception:
		pass
	return 0


class ManiaBotController:
	def __init__(self, use_gui: bool = True) -> None:
		self.base_dir = os.path.dirname(os.path.abspath(__file__))
		self.config_path = os.path.join(self.base_dir, "config.ini")
		self.config = configparser.ConfigParser()
		if os.path.exists(self.config_path):
			self.config.read(self.config_path, encoding="utf-8")

		self.dll = self._load_mania_dll()
		self.reader = OsuMemoryReader(debug=False)

		self.offset = self._get_config_int("bot", "offset", 30)
		self.timing_shift = self._get_config_int("bot", "timing_shift", 0)
		self.start_lead_ms = 0

		self.songs_dir = self._resolve_songs_dir()

		self.active_session: Optional[BeatmapSession] = None
		self.click_thread: Optional[threading.Thread] = None
		self.script_running = False
		self.shutdown = False
		self.last_state: Optional[GameState] = None
		self.last_log_time = 0.0
		self.last_timing_log = 0.0
		self.state_lock = threading.RLock()
		self.play_state_entry_time = 0.0

		self.resume_pending = False
		self.resume_target_index = 0
		self.resume_target_time = 0
		self.audio_timer_stabilized = False

		self.last_audio_time: Optional[int] = None
		self.audio_freeze_start_time: Optional[float] = None
		self.audio_freeze_value: Optional[int] = None
		self.is_paused = False
		self.pause_detection_enabled = False
		self.player_died = False

		self.use_gui = use_gui
		self.gui: Optional[ManiaGUI] = None
		self.bot_enabled = True
		if self.use_gui:
			self.gui = ManiaGUI()
			self.gui.on_start_bot = self._gui_start_bot
			self.gui.on_stop_bot = self._gui_stop_bot
			self.gui.on_exit = self._gui_exit
			self.gui.on_offset_change = self._gui_offset_changed
			self.gui.on_timing_shift_change = self._gui_timing_shift_changed
		
		self.custom_keybinds = self._parse_custom_keybinds()
		self.shortcuts = self._parse_shortcuts()

		if self.timing_shift:
			self.dll.setTimingShift(ctypes.c_int(self.timing_shift))
		self.dll.setOffset(ctypes.c_int(self.offset))

		self.keyboard_listener_thread: Optional[threading.Thread] = None
		if keyboard is None:
			safe_print("Keyboard module not available. Shortcut keys disabled.")
		else:
			self.keyboard_listener_thread = threading.Thread(target=self._keyboard_listener, daemon=True)
			self.keyboard_listener_thread.start()

		safe_print("osu! Mania Bot initialized successfully!")

	def _log(self, message: str, color: tuple = (255, 255, 255)) -> None:
		if self.gui and hasattr(self.gui, 'log_message'):
			try:
				self.gui.log_message(message, color)
			except Exception:
				safe_print(message)
		else:
			safe_print(message)
	
	def _gui_start_bot(self) -> None:
		if not self.active_session:
			self._log("Cannot start: No mania beatmap detected. Please select a mania map in osu!")
			return
		if self.script_running:
			self._log("Bot is already running!")
			return
		self._log("Waiting for audio time to reach first note...")
		if self.gui:
			self.gui.update_bot_status("Waiting for audio sync...")
	
	def _gui_stop_bot(self) -> None:
		if self.script_running:
			self._stop_click_thread("manual stop via GUI")
		else:
			self._log("Bot is not running.")
	
	def _gui_exit(self) -> None:
		self.shutdown = True
		self._stop_click_thread("shutdown")
		self.reader.close_process()
	
	def _gui_offset_changed(self, new_offset: int) -> None:
		self.offset = new_offset
		self.dll.setOffset(ctypes.c_int(self.offset))
		self._log(f"Offset changed to {self.offset} ms")
	
	def _gui_timing_shift_changed(self, new_timing_shift: int) -> None:
		self.timing_shift = new_timing_shift
		self.dll.setTimingShift(ctypes.c_int(self.timing_shift))
		self._log(f"Timing shift changed to {self.timing_shift} ms")
	
	def _get_config_int(self, section: str, option: str, fallback: int) -> int:
		try:
			if self.config.has_section(section):
				return self.config.getint(section, option, fallback=fallback)
			return fallback
		except ValueError:
			return fallback

	def _save_config_value(self, section: str, option: str, value: str) -> None:
		if not self.config.has_section(section):
			self.config.add_section(section)
		self.config.set(section, option, value)
		try:
			with open(self.config_path, "w", encoding="utf-8") as config_file:
				self.config.write(config_file)
		except Exception:
			pass

	def _resolve_songs_dir(self) -> Optional[str]:
		stored_dir = self.config.get("osu", "songs_dir", fallback=None)
		if stored_dir and os.path.isdir(stored_dir):
			return stored_dir

		detected = auto_detect_osu_songs_dir()
		if detected:
			self._save_config_value("osu", "songs_dir", detected)
			return detected

		return None

	def _parse_custom_keybinds(self) -> dict:
		custom_keybinds = {}
		if not self.config.has_section("keybinds"):
			return custom_keybinds
		try:
			for key in self.config["keybinds"]:
				if key.startswith("mode_") and key.endswith("k"):
					mode_str = self.config["keybinds"][key].strip()
					if not mode_str or mode_str.startswith(";"):
						continue
					try:
						if mode_str.startswith("[") and mode_str.endswith("]"):
							mode_str = mode_str[1:-1]
						
						key_chars = [k.strip().upper() for k in mode_str.split(",")]
						
						vk_codes = []
						for char in key_chars:
							if len(char) == 1 and char.isalpha():
								vk_code = ord(char)
								vk_codes.append(vk_code)
							else:
								safe_print(f"Invalid key '{char}' in {key}, skipping this keybind")
								vk_codes = []
								break
						
						if vk_codes:
							mode_number = int(key[5:-1])
							if mode_number <= 18:
								custom_keybinds[mode_number] = vk_codes
								safe_print(f"Loaded custom keybind for {mode_number}K: {key_chars}")
							else:
								safe_print(f"Warning: {mode_number}K exceeds maximum of 18 keys, skipping")
					except Exception as e:
						safe_print(f"Error parsing {key}: {e}")
						continue
		except Exception as e:
			safe_print(f"Error in _parse_custom_keybinds: {e}")
			import traceback
			traceback.print_exc()
		
		return custom_keybinds
	
	def _parse_shortcuts(self) -> dict:
		shortcuts = {
			"timing_shift_decrease": "left",
			"timing_shift_increase": "right",
			"offset_decrease": "[",
			"offset_increase": "]",
			"toggle_bot": "q"
		}
		
		if not self.config.has_section("shortcuts"):
			return shortcuts
		
		try:
			if self.config.has_option("shortcuts", "timing_shift_bind"):
				bind_str = self.config.get("shortcuts", "timing_shift_bind").strip()
				if bind_str and not bind_str.startswith(";"):
					if bind_str.startswith("[") and bind_str.endswith("]"):
						bind_str = bind_str[1:-1]
					keys = [k.strip().lower() for k in bind_str.split(",")]
					if len(keys) == 2:
						shortcuts["timing_shift_decrease"] = keys[0]
						shortcuts["timing_shift_increase"] = keys[1]
			
			if self.config.has_option("shortcuts", "offset_bind"):
				bind_str = self.config.get("shortcuts", "offset_bind").strip()
				if bind_str and not bind_str.startswith(";"):
					if bind_str.startswith("[") and bind_str.endswith("]"):
						bind_str = bind_str[1:-1]
					keys = [k.strip().lower() for k in bind_str.split(",")]
					if len(keys) == 2:
						shortcuts["offset_decrease"] = keys[0]
						shortcuts["offset_increase"] = keys[1]
			
			if self.config.has_option("shortcuts", "toggle_bot_bind"):
				bind_str = self.config.get("shortcuts", "toggle_bot_bind").strip()
				if bind_str and not bind_str.startswith(";"):
					shortcuts["toggle_bot"] = bind_str.lower()
					
		except Exception as e:
			safe_print(f"Error parsing shortcuts: {e}")
			import traceback
			traceback.print_exc()
		
		return shortcuts

	def _load_mania_dll(self) -> ctypes.CDLL:
		dll_path = os.path.join(self.base_dir, "main.dll")
		if not os.path.isfile(dll_path):
			raise FileNotFoundError(f"main.dll not found at {dll_path}")

		dll = ctypes.CDLL(dll_path)
		dll.clickHitObjects.argtypes = (
			ctypes.POINTER(HitObject),
			ctypes.c_int,
			ctypes.c_int,
			ctypes.c_int,
			ctypes.c_int,
			ctypes.c_bool,
			ctypes.c_int,
			ctypes.c_int,
			ctypes.POINTER(ctypes.c_uint16),
		)
		dll.setStopClicking.argtypes = [ctypes.c_bool]
		dll.setTimingShift.argtypes = [ctypes.c_int]
		dll.setOffset.argtypes = [ctypes.c_int]
		dll.setHumanizeOffsetBoost.argtypes = [ctypes.c_bool]
		dll.setHumanizeForceMiss.argtypes = [ctypes.c_bool]
		dll.setHumanizePressSooner.argtypes = [ctypes.c_bool]
		dll.setHumanizePressLater.argtypes = [ctypes.c_bool]
		return dll

	def run(self) -> None:
		if self.use_gui and self.gui:
			self.bot_thread = threading.Thread(target=self._run_bot_logic, daemon=True)
			self.bot_thread.start()
			
			try:
				self.gui.initialize()
				self.gui.set_offset(self.offset)
				self.gui.update_timing_shift(self.timing_shift)
				self.gui.run()
			except Exception as e:
				safe_print(f"GUI ERROR: {e}")
				import traceback
				traceback.print_exc()
				input("Press Enter to exit...")
		else:
			self._run_bot_logic()
	
	def _run_bot_logic(self) -> None:
		self._log("Mania bot started. Waiting for osu!...")
		try:
			while not self.shutdown:
				if not self._ensure_reader_ready():
					self._sleep_with_stop(1.0)
					continue
				try:
					self._tick()
				except Exception as exc:
					self._log(f"Error during main loop: {exc}")
					self._sleep_with_stop(0.5)
					continue

		except KeyboardInterrupt:
			self._log("Stopping bot...")
		finally:
			self.shutdown = True
			self._stop_click_thread("shutdown")
			self.reader.close_process()

	def _sleep_with_stop(self, seconds: float) -> None:
		end_time = time.time() + seconds
		while not self.shutdown and time.time() < end_time:
			time.sleep(0.05)

	def _is_osu_focused(self) -> bool:
		try:
			import win32gui
			import win32process

			if not self.reader or not self.reader.process_id:
				return False
			
			hwnd = win32gui.GetForegroundWindow()
			if not hwnd:
				return False
			
			_, pid = win32process.GetWindowThreadProcessId(hwnd)
			
			return pid == self.reader.process_id
		except Exception:
			return False
	
	def _keyboard_listener(self) -> None:
		if keyboard is None:
			return
		
		key_states = {
			"toggle_bot": False,
			"timing_shift_decrease": False,
			"timing_shift_increase": False,
			"offset_decrease": False,
			"offset_increase": False,
			"humanize_offset_boost": False,
			"humanize_force_miss": False,
			"humanize_press_sooner": False,
			"humanize_press_later": False
		}
		
		while not self.shutdown:
			try:
				if self._is_osu_focused():
					toggle_key = self.shortcuts["toggle_bot"]
					toggle_pressed = keyboard.is_pressed(toggle_key)
					if toggle_pressed and not key_states["toggle_bot"]:
						self.bot_enabled = not self.bot_enabled
						if self.bot_enabled:
							self._log(f"Bot ENABLED ({toggle_key.upper()})", color=(100, 255, 100))
							if self.gui:
								self.gui.update_bot_status("Enabled - Ready")
						else:
							self._log(f"Bot DISABLED ({toggle_key.upper()})", color=(255, 100, 100))
							if self.script_running:
								self._stop_click_thread("bot disabled via toggle key")
							if self.gui:
								self.gui.update_bot_status("Disabled")
					key_states["toggle_bot"] = toggle_pressed
				else:
					key_states["toggle_bot"] = False
				
				shortcuts_enabled = (
					self.last_state == GameState.PLAY and 
					self._is_osu_focused()
				)
				
				if not shortcuts_enabled:
					for key in key_states:
						key_states[key] = False
					time.sleep(0.05)
					continue

				ts_dec_key = self.shortcuts["timing_shift_decrease"]
				ts_dec_pressed = keyboard.is_pressed(ts_dec_key)
				if ts_dec_pressed and not key_states["timing_shift_decrease"]:
					self.timing_shift -= 1
					self.dll.setTimingShift(ctypes.c_int(self.timing_shift))
					self._log(f"Timing shift: {self.timing_shift} ms (earlier)", color=(100, 200, 255))
					if self.gui:
						try:
							self.gui.update_timing_shift(self.timing_shift)
						except Exception:
							pass
				key_states["timing_shift_decrease"] = ts_dec_pressed

				ts_inc_key = self.shortcuts["timing_shift_increase"]
				ts_inc_pressed = keyboard.is_pressed(ts_inc_key)
				if ts_inc_pressed and not key_states["timing_shift_increase"]:
					self.timing_shift += 1
					self.dll.setTimingShift(ctypes.c_int(self.timing_shift))
					self._log(f"Timing shift: {self.timing_shift} ms (later)", color=(100, 200, 255))
					if self.gui:
						try:
							self.gui.update_timing_shift(self.timing_shift)
						except Exception:
							pass
				key_states["timing_shift_increase"] = ts_inc_pressed

				offset_dec_key = self.shortcuts["offset_decrease"]
				offset_dec_pressed = keyboard.is_pressed(offset_dec_key)
				if offset_dec_pressed and not key_states["offset_decrease"]:
					self.offset = max(0, self.offset - 1)
					self.dll.setOffset(ctypes.c_int(self.offset))
					self._log(f"Offset: {self.offset} ms", color=(100, 255, 100))
					if self.gui:
						try:
							self.gui.set_offset(self.offset)
						except Exception:
							pass
				key_states["offset_decrease"] = offset_dec_pressed
				
				offset_inc_key = self.shortcuts["offset_increase"]
				offset_inc_pressed = keyboard.is_pressed(offset_inc_key)
				if offset_inc_pressed and not key_states["offset_increase"]:
					self.offset += 1
					self.dll.setOffset(ctypes.c_int(self.offset))
					self._log(f"Offset: {self.offset} ms", color=(100, 255, 100))
					if self.gui:
						try:
							self.gui.set_offset(self.offset)
						except Exception:
							pass
				key_states["offset_increase"] = offset_inc_pressed
				
				shift_pressed = keyboard.is_pressed('shift')
				if shift_pressed != key_states["humanize_offset_boost"]:
					self.dll.setHumanizeOffsetBoost(ctypes.c_bool(shift_pressed))
					if shift_pressed:
						self._log("Humanize: Offset +50% ACTIVE (SHIFT)", color=(255, 200, 100))
						if self.gui:
							boosted_offset = int(self.offset * 1.5)
							self.gui.set_offset(boosted_offset)
					else:
						self._log("Humanize: Offset +50% deactivated", color=(150, 150, 150))
						if self.gui:
							self.gui.set_offset(self.offset)
					key_states["humanize_offset_boost"] = shift_pressed
				
				alt_pressed = keyboard.is_pressed('alt')
				if alt_pressed != key_states["humanize_force_miss"]:
					self.dll.setHumanizeForceMiss(ctypes.c_bool(alt_pressed))
					if alt_pressed:
						self._log("Humanize: Force miss ACTIVE (ALT)", color=(255, 100, 100))
					else:
						self._log("Humanize: Force miss deactivated", color=(150, 150, 150))
					key_states["humanize_force_miss"] = alt_pressed
				
				ctrl_pressed = keyboard.is_pressed('ctrl')
				if ctrl_pressed != key_states["humanize_press_sooner"]:
					self.dll.setHumanizePressSooner(ctypes.c_bool(ctrl_pressed))
					if ctrl_pressed:
						self._log("Humanize: Press 10% sooner ACTIVE (CTRL)", color=(100, 200, 255))
					else:
						self._log("Humanize: Press 10% sooner deactivated", color=(150, 150, 150))
					key_states["humanize_press_sooner"] = ctrl_pressed
				
				caps_pressed = keyboard.is_pressed('caps lock')
				if caps_pressed != key_states["humanize_press_later"]:
					self.dll.setHumanizePressLater(ctypes.c_bool(caps_pressed))
					if caps_pressed:
						self._log("Humanize: Press 10% later ACTIVE (CAPS)", color=(255, 150, 200))
					else:
						self._log("Humanize: Press 10% later deactivated", color=(150, 150, 150))
					key_states["humanize_press_later"] = caps_pressed
				
				time.sleep(0.05)
			except RuntimeError as exc:
				self._log(f"Keyboard listener halted: {exc}")
				break
			except Exception as exc:
				self._log(f"Keyboard listener error: {exc}")
				time.sleep(0.5)

	def _log_timing_status(self, audio_time: int, delta_to_first: int) -> None:
		if not self.active_session or abs(delta_to_first) > 20000:
			return

		if self.gui:
			self.gui.update_audio_time(audio_time)

		now = time.time()
		if now - self.last_timing_log >= 0.5:
			message = (
				f"[TIMING] audio: {audio_time} ms | first hit: {self.active_session.first_hit_time_original} ms | "
				f"Δ: {delta_to_first} ms"
			)
			if not self.gui:
				safe_print(message)
			self.last_timing_log = now

	def _ensure_reader_ready(self) -> bool:
		if self.reader.process_handle:
			if self.gui:
				self.gui.update_osu_status(True, self.reader.process_id)
			return True

		pid = self.reader.find_process("osu!.exe")
		if not pid:
			self._throttled_log("osu! is not running. Waiting...")
			if self.gui:
				self.gui.update_osu_status(False)
			return False

		if not self.reader.open_process(pid):
			self._log("Failed to open osu! process. Try running as Administrator.")
			if self.gui:
				self.gui.update_osu_status(False)
			return False

		self._log(f"Opened osu! process (PID {pid}). Scanning for patterns...")
		if not self.reader.scan_all_patterns():
			self._log("Warning: Not all memory patterns were found. Functionality may be limited.")
		else:
			self._log("Memory patterns ready.")
		
		if self.gui:
			self.gui.update_osu_status(True, pid)
		return True

	def _tick(self) -> None:
		state = self.reader.get_game_state()
		if state and state != self.last_state:
			self._log(f"Game state changed: {state.name}")
			if self.gui:
				self.gui.update_game_state(state.name)
			
			if state != GameState.PLAY:
				self._stop_click_thread("state change")
				self.audio_timer_stabilized = False
				self.pause_detection_enabled = False
				self.is_paused = False
				self.last_audio_time = None
				self.audio_freeze_start_time = None
				self.audio_freeze_value = None
				self.resume_pending = False
			else:
				self.play_state_entry_time = time.time()
				self.audio_timer_stabilized = False
				self.pause_detection_enabled = False
				self.is_paused = False
				self.last_audio_time = None
				self.audio_freeze_start_time = None
				self.audio_freeze_value = None
				self.resume_pending = False
				self.player_died = False
				self._log("Entered PLAY state. Waiting for audio timer to stabilize...")
			self.last_state = state

		audio_time = self.reader.get_audio_time()
		if audio_time is not None and self.gui:
			self.gui.update_audio_time(audio_time)

		mods = self.reader.get_menu_mods()
		beatmap = self.reader.get_beatmap_info()

		if self.gui and mods:
			self.gui.update_mods(mods.mods_string, mods.speed_multiplier)
		
		if state == GameState.PLAY:
			gameplay = self.reader.get_gameplay_data()
			if gameplay:
				if self.gui:
					self.gui.update_gameplay_data(
						score=gameplay.score,
						combo=gameplay.combo,
						max_combo=gameplay.max_combo,
						accuracy=gameplay.accuracy,
						hp=gameplay.hp,
						hit_300=gameplay.hit_300,
						hit_100=gameplay.hit_100,
						hit_50=gameplay.hit_50,
						hit_miss=gameplay.hit_miss,
						hit_geki=gameplay.hit_geki,
						hit_katu=gameplay.hit_katu
					)
				
				if gameplay.hp <= 0.0 and not self.player_died:
					has_nofail = False
					if mods:
						from memory_reader import OsuMods
						has_nofail = bool(mods.mods_number & OsuMods.NO_FAIL)
					
					if not has_nofail:
						self.player_died = True
						self._log("Player died. Stopping bot...", color=(255, 100, 100))
						if self.script_running:
							self._stop_click_thread("player death")
						if self.gui:
							self.gui.update_bot_status("Stopped (Player Died)")
		else:
			if self.gui:
				self.gui.clear_gameplay_data()
			self.player_died = False

		if beatmap and beatmap.filename:
			identifier = f"{beatmap.folder}/{beatmap.filename}"
			if beatmap.beatmap_mode != 3:
				if self.gui:
					mode_names = {0: "osu!standard", 1: "Taiko", 2: "Catch", 3: "Mania"}
					mode_name = mode_names.get(beatmap.beatmap_mode, f"Unknown ({beatmap.beatmap_mode})")
					
					self.gui.update_beatmap_info(
						title=f"{beatmap.artist} - {beatmap.title}",
						difficulty=beatmap.difficulty,
						mapper=beatmap.creator,
						mode=mode_name,
						keys=0,
						map_id=beatmap.map_id,
						is_mania=False
					)
					self.gui.update_bot_status("Idle (non-mania map)")
				
				if self.active_session:
					self._log(f"Detected {mode_names.get(beatmap.beatmap_mode, 'non-mania')} beatmap. Bot idle.")
				
				self.active_session = None
				self.last_timing_log = 0.0
			else:
				needs_refresh = False
				if not self.active_session:
					needs_refresh = True
				elif identifier != self.active_session.identifier or beatmap.map_id != self.active_session.map_id:
					needs_refresh = True
				else:
					current_speed = mods.speed_multiplier if mods else 1.0
					if abs(current_speed - self.active_session.speed_multiplier) > 0.01:
						needs_refresh = True

				if needs_refresh:
					self._prepare_session(beatmap, mods)
		else:
			self.active_session = None
			self.last_timing_log = 0.0

		if state != GameState.PLAY:
			if self.is_paused:
				self.is_paused = False
			return

		if not self.active_session:
			if self.is_paused:
				self.is_paused = False
			return

		if audio_time is None:
			return

		if not self.audio_timer_stabilized:
			if self.is_paused:
				self.is_paused = False
			time_since_play_entry = time.time() - self.play_state_entry_time
			
			if time_since_play_entry < 0.2:
				return
			
			if -5000 <= audio_time < self.active_session.first_hit_time_original:
				self.audio_timer_stabilized = True
				self.pause_detection_enabled = True
				self._log(f"Audio timer stabilized at {audio_time} ms. Waiting for first hit at {self.active_session.first_hit_time_original} ms...")
			elif time_since_play_entry > 3.0:
				if audio_time < self.active_session.first_hit_time_original - 1000:
					self.audio_timer_stabilized = True
					self.pause_detection_enabled = True
					self._log(f"Audio timer timeout - forcing stabilization at {audio_time} ms.")
				else:
					return
			else:
				return
		
		if audio_time < 0:
			return
		
		if self.pause_detection_enabled:
			self._detect_pause(audio_time)

		if self.is_paused:
			return

		if self.resume_pending and not self.script_running:
			if not self.bot_enabled:
				self.resume_pending = False
				return
			
			time_to_resume_target = self.resume_target_time - audio_time
			
			if abs(time_to_resume_target) <= 20:
				self.resume_pending = False
				self._start_click_thread_from_position(audio_time, self.resume_target_index, time_to_resume_target)
			return

		time_to_first = self.active_session.first_hit_time_original - audio_time

		self._log_timing_status(audio_time, time_to_first)

		if not self.script_running:
			if self.bot_enabled and abs(time_to_first) <= 20:
				self._start_click_thread(audio_time, time_to_first)

	def _prepare_session(self, beatmap, mods: Optional[MenuMods]) -> None:
		if self.script_running:
			self._stop_click_thread("new beatmap")

		songs_from_memory = self.reader.get_songs_folder()
		if songs_from_memory and os.path.isdir(songs_from_memory) and songs_from_memory != self.songs_dir:
			self.songs_dir = songs_from_memory
			self._save_config_value("osu", "songs_dir", songs_from_memory)

		songs_dir = self.songs_dir
		if not songs_dir or not os.path.isdir(songs_dir):
			self._log("Songs directory not set. Cannot prepare beatmap.")
			self.active_session = None
			self.last_timing_log = 0.0
			return

		map_path = os.path.join(songs_dir, beatmap.folder, beatmap.filename)
		if not os.path.isfile(map_path):
			self._log(f"Beatmap file not found at {map_path}")
			self.active_session = None
			self.last_timing_log = 0.0
			return

		speed_multiplier = mods.speed_multiplier if mods else 1.0
		mods_string = mods.mods_string if mods else "NM"

		hit_objects = parse_osu_file(map_path, speed_multiplier)
		if not hit_objects:
			self._log("No hit objects parsed from beatmap. Waiting for next map.", color=(255, 0, 0))
			self.active_session = None
			self.last_timing_log = 0.0
			return

		lane_positions = get_lane_positions(hit_objects)
		
		cs_keys = max(1, int(round(beatmap.cs)))
		original_position_keys = len(lane_positions) if lane_positions else cs_keys
		original_lane_positions = lane_positions.copy()
		
		has_map_bug = original_position_keys != cs_keys
		
		if has_map_bug:
			hit_objects = remap_hit_objects_to_cs_positions(hit_objects, cs_keys)
			
			position_width = 512 / cs_keys
			lane_positions = []
			for i in range(cs_keys):
				position_center = int((i + 0.5) * position_width)
				lane_positions.append(position_center)
			
			keys = cs_keys
			position_keys = cs_keys
		else:
			position_keys = original_position_keys
			if position_keys > 9:
				keys = cs_keys
			else:
				keys = position_keys
		
		first_hit_time = hit_objects[0].timestamp
		first_hit_time_original = get_first_hit_time_original(map_path)

		identifier = f"{beatmap.folder}/{beatmap.filename}"
		self.active_session = BeatmapSession(
			identifier=identifier,
			map_id=beatmap.map_id,
			title=f"{beatmap.artist} - {beatmap.title}",
			difficulty=beatmap.difficulty,
			path=map_path,
			keys=keys,
			lane_positions=lane_positions if lane_positions else [],
			hit_objects=hit_objects,
			first_hit_time=first_hit_time,
			first_hit_time_original=first_hit_time_original,
			mods_string=mods_string,
			speed_multiplier=speed_multiplier,
		)
		self.last_timing_log = 0.0
		
		self._log(" ==[ ! ]== Prepared beatmap:")
		self._log(f"  Title: {self.active_session.title}")
		self._log(f"  Difficulty: {self.active_session.difficulty}")
		self._log(f"  Map ID: {beatmap.map_id}")
		if has_map_bug:
			self._log(f"  Map fixed: {original_position_keys} positions -> {cs_keys}K", color=(255, 200, 0))
		
		self._log(f"  First note: {first_hit_time_original} ms | Speed: {speed_multiplier:.2f}x")
		
		if self.gui:
			error_message = ""
			if has_map_bug:
				error_message = f"Map fixed: {original_position_keys} positions -> {cs_keys}K"
			
			self.gui.update_beatmap_info(
				title=self.active_session.title,
				difficulty=beatmap.difficulty,
				mapper=beatmap.creator,
				mode=f"Mania {keys}K",
				keys=keys,
				map_id=beatmap.map_id,
				cs_keys=cs_keys,
				position_keys=position_keys,
				original_position_keys=original_position_keys if has_map_bug else None,
				has_error=has_map_bug,
				error_message=error_message
			)
			self.gui.update_first_note_time(first_hit_time_original)
			self.gui.update_bot_status("Ready - Waiting for PLAY state")

	def _start_click_thread(self, audio_time: int, delta_to_first: int) -> None:
		self._start_click_thread_from_position(audio_time, 0, delta_to_first)
	
	def _start_click_thread_from_position(self, audio_time: int, start_index: int = 0, delta_to_first: int = 0) -> None:
		with self.state_lock:
			if not self.active_session or self.script_running or not self.active_session.hit_objects:
				return
			session_snapshot = self.active_session
			self.script_running = True

		start_adjustment = int(audio_time / session_snapshot.speed_multiplier)
		
		if start_index == 0:
			self._log(f"=== BOT STARTED === Audio: {audio_time} ms | Δ: {delta_to_first} ms")
		else:
			target_note = session_snapshot.hit_objects[start_index] if start_index < len(session_snapshot.hit_objects) else None
			if target_note:
				target_time_original = int(target_note.timestamp * session_snapshot.speed_multiplier)
				self._log(f"=== BOT RESUMED === From note index {start_index} | Audio: {audio_time} ms | Target note: {target_time_original} ms", color=(100, 255, 100))
			else:
				self._log(f"=== BOT RESUMED === From note index {start_index} | Audio: {audio_time} ms", color=(100, 255, 100))
		
		if self.gui:
			self.gui.update_bot_status("Running")

		self.dll.setOffset(ctypes.c_int(self.offset))
		self.dll.setTimingShift(ctypes.c_int(self.timing_shift))
		self.dll.setStopClicking(ctypes.c_bool(False))

		def worker(session: BeatmapSession, start_time_adjustment: int, from_index: int) -> None:
			try:
				total = len(session.hit_objects) - from_index
				if total <= 0:
					self._log("No notes to play from this position.")
					return
				
				array_type = HitObject * total
				hit_array = array_type(*session.hit_objects[from_index:])
				
				custom_keys_ptr = None
				if session.keys in self.custom_keybinds:
					vk_codes = self.custom_keybinds[session.keys]
					custom_keys_array = (ctypes.c_uint16 * len(vk_codes))(*vk_codes)
					custom_keys_ptr = ctypes.cast(custom_keys_array, ctypes.POINTER(ctypes.c_uint16))
				
				self.dll.clickHitObjects(
					hit_array,
					ctypes.c_int(total),
					ctypes.c_int(0),
					ctypes.c_int(0),
					ctypes.c_int(start_time_adjustment),
					ctypes.c_bool(True),
					ctypes.c_int(self.offset),
					ctypes.c_int(session.keys),
					custom_keys_ptr,
				)
				self._log("Bot execution completed.")
			except Exception as exc:
				self._log(f"Error while running bot: {exc}")
			finally:
				self.dll.setStopClicking(ctypes.c_bool(False))
				with self.state_lock:
					self.script_running = False
					self.click_thread = None
				if self.gui:
					self.gui.update_bot_status("Idle")

		thread = threading.Thread(
			target=worker,
			args=(session_snapshot, start_adjustment, start_index),
			daemon=True,
		)
		with self.state_lock:
			self.click_thread = thread
		thread.start()

	def _stop_click_thread(self, reason: str) -> None:
		with self.state_lock:
			if not self.script_running:
				return
			thread = self.click_thread
			self.script_running = False
			self.click_thread = None

		self._log(f"Stopping bot ({reason})...")
		self.dll.setStopClicking(ctypes.c_bool(True))
		if thread and thread.is_alive():
			thread.join(timeout=2.0)
		self.dll.setStopClicking(ctypes.c_bool(False))
		self.last_timing_log = 0.0
		
		if reason != "pause detected":
			self.audio_timer_stabilized = False
		
		if self.gui:
			self.gui.update_bot_status("Stopped")

	def _detect_pause(self, audio_time: int) -> None:
		now = time.time()
		
		if self.last_audio_time is None:
			self.last_audio_time = audio_time
			return
		
		audio_delta = audio_time - self.last_audio_time
		
		if audio_delta > 0:
			if self.is_paused:
				self._log(f"[PAUSE] Detected UNPAUSE - Audio resumed from {audio_time} ms (delta: +{audio_delta}ms)", color=(100, 255, 100))
				self.audio_freeze_start_time = None
				self.audio_freeze_value = None
				self._handle_unpause(audio_time)
			else:
				self.audio_freeze_start_time = None
				self.audio_freeze_value = None
		
		elif audio_delta == 0:
			if not self.is_paused:
				if self.audio_freeze_start_time is None:
					self.audio_freeze_start_time = now
					self.audio_freeze_value = audio_time
				else:
					freeze_duration = now - self.audio_freeze_start_time
					if freeze_duration >= 0.2:
						self._log(f"[PAUSE] Detected PAUSE at {audio_time} ms", color=(255, 255, 0))
						self.is_paused = True
						
						if self.script_running:
							self._log(f"[PAUSE] Stopping bot execution", color=(255, 255, 0))
							self._stop_click_thread("pause detected")
						
						if self.gui:
							self.gui.update_bot_status("Paused")
		
		elif audio_delta < -100 or audio_time <= 0:
			self._log(f"[PAUSE] Detected RESTART - Audio jumped from {self.last_audio_time} to {audio_time} ms", color=(255, 150, 0))
			self._handle_restart()
			
			self.audio_freeze_start_time = None
			self.audio_freeze_value = None
			self.is_paused = False
		
		self.last_audio_time = audio_time
	
	def _handle_unpause(self, audio_time: int) -> None:
		if not self.active_session:
			return
		
		self.is_paused = False
		
		next_note_index = 0
		next_note_time = 0
		for i, hit_obj in enumerate(self.active_session.hit_objects):
			original_timestamp = int(hit_obj.timestamp * self.active_session.speed_multiplier)
			if original_timestamp > audio_time:
				next_note_index = i
				next_note_time = original_timestamp
				break
		
		if next_note_index >= len(self.active_session.hit_objects):
			self._log(f"[PAUSE] No more notes to play after unpause", color=(255, 200, 0))
			if self.gui:
				self.gui.update_bot_status("Completed")
			return
		
		self.resume_pending = True
		self.resume_target_index = next_note_index
		self.resume_target_time = next_note_time
		
		self._log(f"[PAUSE] Will resume from note index {next_note_index} (target time: {next_note_time} ms)", color=(100, 255, 100))
		
		if self.gui:
			self.gui.update_bot_status("Resuming...")
	
	def _handle_restart(self) -> None:
		self._log(f"[PAUSE] Resetting for restart...", color=(255, 150, 0))
		
		if self.script_running:
			self._stop_click_thread("restart detected")
		
		self.audio_timer_stabilized = False
		self.play_state_entry_time = time.time()
		self.last_audio_time = None
		self.resume_pending = False
		
		if self.gui:
			self.gui.update_bot_status("Ready - Waiting for audio sync...")
	
	def _throttled_log(self, message: str, interval: float = 5.0) -> None:
		now = time.time()
		if now - self.last_log_time >= interval:
			self._log(message)
			self.last_log_time = now


if __name__ == "__main__":
	try:
		controller = ManiaBotController(use_gui=True)
		controller.run()
	except Exception as e:
		safe_print(f"\nFATAL ERROR: {e}")
		import traceback
		traceback.print_exc()
		input("\nPress Enter to exit...")

