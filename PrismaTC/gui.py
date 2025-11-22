import dearpygui.dearpygui as dpg
import threading
from typing import Optional, Callable
from safe_print import safe_print
import os
from minimize_to_tray import TrayManager

class ManiaGUI:
	
	def __init__(self, width: int = 1000, height: int = 600):
		self.width = width
		self.height = height
		self.viewport = None
		self.log_entry_count = 0
		self.log_mode = "Normal"

		self.on_start_bot: Optional[Callable] = None
		self.on_stop_bot: Optional[Callable] = None
		self.on_exit: Optional[Callable] = None
		self.on_offset_change: Optional[Callable[[int], None]] = None
		self.on_timing_shift_change: Optional[Callable[[int], None]] = None
		self.on_osu_unlock_scan: Optional[Callable] = None
		self.on_osu_unlock_unlock: Optional[Callable] = None

		self.title_bar_drag = False
		self._running = False
		self.tray_manager = TrayManager(
			on_restore_callback=self._on_tray_restore,
			on_exit_callback=self._on_tray_exit
		)
	
	def initialize(self) -> None:
		dpg.create_context()
		self.viewport = dpg.create_viewport(
			title="PrismaTC",
			width=self.width,
			height=self.height,
			decorated=False,
			resizable=False
		)
		dpg.set_viewport_small_icon("src/logo.ico")
		dpg.set_viewport_large_icon("src/logo.ico")
		dpg.setup_dearpygui()
		
		self._apply_theme()
		self._load_icon_texture()
		self._build_gui()
		
		self.drag_offset_x = 0
		self.drag_offset_y = 0
		self.is_dragging = False
	
	def _load_icon_texture(self) -> None:
		icon_path = os.path.join(os.path.dirname(__file__), "src", "logo.png")
		if os.path.exists(icon_path):
			width, height, channels, data = dpg.load_image(icon_path)
			with dpg.texture_registry():
				dpg.add_static_texture(width=width, height=height, default_value=data, tag="icon_texture")
	
	def _apply_theme(self) -> None:
		with dpg.theme() as global_theme:
			with dpg.theme_component(dpg.mvAll):
				dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (16, 16, 16, 255))
				dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 255, 255, 255))
				dpg.add_theme_color(dpg.mvThemeCol_Button, (50, 50, 50, 255))
				dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (70, 70, 70, 255))
				dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (90, 90, 90, 255))
				dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (30, 30, 30, 255))
				dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (20, 20, 20, 255))
				dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg, (10, 10, 10, 255))
				dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, (60, 60, 60, 255))
				dpg.add_theme_color(dpg.mvThemeCol_Header, (40, 40, 40, 255))
				dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (50, 50, 50, 255))
				dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (60, 60, 60, 255))
		
		dpg.bind_theme(global_theme)
	
	def _build_gui(self) -> None:
		with dpg.window(
			label="osu! Mania Bot",
			width=self.width,
			height=self.height,
			no_collapse=True,
			no_move=True,
			no_resize=True,
			no_close=False,
			no_title_bar=False,
			on_close=self._exit_program,
			tag="primary"
		):
			with dpg.group(horizontal=True, tag="top_bar_group"):
				if dpg.does_item_exist("icon_texture"):
					dpg.add_image("icon_texture", width=20, height=20)
					dpg.add_spacer(width=5)
				dpg.add_text("PrismaTC", tag="title_text")
				dpg.add_spacer(width=760 if dpg.does_item_exist("icon_texture") else 810)
				dpg.add_button(label="_", width=50, callback=self._minimize_to_tray, tag="minimize_button")
				dpg.add_button(label="X", width=50, callback=self._exit_program, tag="x_button")
			
			dpg.add_separator()
			
			with dpg.group(horizontal=True):
				with dpg.child_window(width=480, height=-1, border=True, tag="status_panel"):
					dpg.add_text("Status", tag="status_header")
					dpg.add_separator()
					
					dpg.add_text("Game State: Waiting...", tag="game_state_label")
					dpg.add_text("osu! Status: Not Connected", tag="osu_status_label")
					dpg.add_separator()
					
					dpg.add_text("Current Beatmap", tag="beatmap_header")
					dpg.add_text("Title: None", tag="beatmap_title", wrap=450)
					dpg.add_text("Difficulty: None", tag="beatmap_difficulty")
					dpg.add_text("Mapper: None", tag="beatmap_mapper")
					dpg.add_text("Mode: None", tag="beatmap_mode")
					dpg.add_text("Keys: None", tag="beatmap_keys")
					dpg.add_text("Map ID: None", tag="beatmap_id")
					dpg.add_text("", tag="map_error_message", color=(255, 50, 50))
					dpg.add_text("", tag="mode_not_supported", color=(255, 50, 50))
					dpg.add_separator()
					
					dpg.add_text("Mods: NM", tag="mods_label")
					dpg.add_text("Speed: 1.00x", tag="speed_label")
					dpg.add_text("Audio Time: 00:00.000", tag="audio_time_label")
					dpg.add_separator()
					
					dpg.add_text("Gameplay Stats", tag="gameplay_header")
					dpg.add_text("Score: N/A", tag="gameplay_score")
					dpg.add_text("Combo: N/A", tag="gameplay_combo")
					dpg.add_text("Accuracy: N/A", tag="gameplay_accuracy")
					dpg.add_text("HP: N/A", tag="gameplay_hp")
					dpg.add_text("Hits: N/A", tag="gameplay_hits")
					dpg.add_separator()
					
					dpg.add_text("Bot Status: Idle", tag="bot_status_label")
					dpg.add_text("First Note: N/A", tag="first_note_label")
					dpg.add_separator()
					dpg.add_text("\n\n\n\n\n\nMade by Zerqqc")
    				
				with dpg.group(width=-1):
					with dpg.child_window(width=-1, height=280, border=True, tag="controls_panel"):
						dpg.add_text("Controls")
						dpg.add_separator()
						

						dpg.add_text("Settings")
						
						dpg.add_input_int(
							label="Offset (ms)",
							tag="offset_input",
							default_value=30,
							min_value=0,
							max_value=500,
							callback=self._offset_changed,
							width=150
						)
      
						dpg.add_input_int(
							label="Timing Shift (ms)",
							tag="timing_shift_input",
							default_value=0,
							min_value=-100,
							max_value=100,
							callback=self._timing_shift_changed,
							width=150
						)

						dpg.add_separator()
						
						with dpg.collapsing_header(label="Keyboard Shortcuts", default_open=False):
							dpg.add_text("Q - Enable/Disable bot")
							dpg.add_text("< > - Adjust timing shift")
							dpg.add_text("[ ] - Adjust offset")
						
						with dpg.collapsing_header(label="Osu Unlocker", default_open=False):
							dpg.add_button(label="Scan Account Status", tag="osu_unlock_scan_button", width=-1, callback=self._osu_unlock_scan_clicked)
							dpg.add_separator()
							dpg.add_text("Account Locked: Not Scanned", tag="osu_unlock_locked_status")
							dpg.add_text("Unlock Date: Not Scanned", tag="osu_unlock_date_status")
							dpg.add_separator()
							dpg.add_button(label="Unlock Account", tag="osu_unlock_button", width=-1, show=False, callback=self._osu_unlock_unlock_clicked)
					
					with dpg.child_window(width=-1, height=-1, border=True, tag="log_panel"):
						with dpg.group(horizontal=True):
							dpg.add_text("Logs")
							dpg.add_spacer(width=315)
							dpg.add_button(label="Minimal", width=60, callback=self._toggle_log_mode, tag="log_mode_button")
							dpg.add_button(label="Clear", width=50, callback=self._clear_logs)
		
						dpg.add_separator()
						
						with dpg.child_window(autosize_x=True, height=-1, tag="log_content_window"):
							with dpg.group(tag="log_content"):
								dpg.add_text("Bot initialized. Waiting for osu!...")
		
		dpg.set_primary_window("primary", True)
	
	def _on_titlebar_mouse_down(self, *args) -> None:
		if not dpg.is_mouse_button_down(0):
			return
		_, y = dpg.get_mouse_pos()
		self.title_bar_drag = (-2 <= y <= 25)
	
	def _on_titlebar_drag(self, *args) -> None:
		if not self.title_bar_drag:
			return
		
		data = args[-1] if args else None
		if isinstance(data, (list, tuple)):
			if len(data) >= 3:
				dx, dy = data[1], data[2]
			elif len(data) == 2:
				dx, dy = data[0], data[1]
			else:
				return
		else:
			return
		
		pos = dpg.get_viewport_pos()
		new_x, new_y = pos[0] + dx, pos[1] + dy
		dpg.configure_viewport(self.viewport, x_pos=new_x, y_pos=new_y)
	
	def _start_bot_clicked(self, *args) -> None:
		if self.on_start_bot:
			self.on_start_bot()
	
	def _stop_bot_clicked(self, *args) -> None:
		if self.on_stop_bot:
			self.on_stop_bot()
	
	def _offset_changed(self, *args) -> None:
		if self.on_offset_change:
			sender = args[0] if args else None
			value = dpg.get_value(sender) if sender else 30
			self.on_offset_change(value)
	
	def _timing_shift_changed(self, *args) -> None:
		if self.on_timing_shift_change:
			sender = args[0] if args else None
			value = dpg.get_value(sender) if sender else 0
			self.on_timing_shift_change(value)
	
	def _osu_unlock_scan_clicked(self, *args) -> None:
		if self.on_osu_unlock_scan:
			self.on_osu_unlock_scan()
	
	def _osu_unlock_unlock_clicked(self, *args) -> None:
		if self.on_osu_unlock_unlock:
			self.on_osu_unlock_unlock()
	
	def _toggle_log_mode(self, *args) -> None:
		if self.log_mode == "Normal":
			self.log_mode = "Minimal"
			if dpg.does_item_exist("log_mode_button"):
				dpg.set_item_label("log_mode_button", "Normal")
			self.log_message("Log mode: Minimal (reduced logs)", color=(100, 200, 255))
		else:
			self.log_mode = "Normal"
			if dpg.does_item_exist("log_mode_button"):
				dpg.set_item_label("log_mode_button", "Minimal")
			self.log_message("Log mode: Normal (detailed logs)", color=(100, 200, 255))
	
	def _clear_logs(self, *args) -> None:
		self.log_entry_count = 0
		dpg.delete_item("log_content", children_only=True)
		self.log_message("Logs cleared.")
	
	def _exit_program(self, *args) -> None:
		if self.on_exit:
			self.on_exit()
		self.stop()
	
	def _minimize_to_tray(self, *args) -> None:
		self.tray_manager.minimize_to_tray()
	
	def _on_tray_restore(self) -> None:
		pass
	
	def _on_tray_exit(self) -> None:
		if self.on_exit:
			self.on_exit()
		self.stop()
	
	def _should_show_in_minimal(self, message: str) -> bool:
		critical_keywords = [
			"ERROR", "FATAL", "WARNING", "STOPPED", "STARTED",
			"Bot ENABLED", "Bot DISABLED", "Prepared beatmap",
			"Game state changed", "Humanize:", "Bot Status:",
			"Player died", "Map fixed", "Detected PAUSE", "Detected UNPAUSE",
			"Detected RESTART", "Bot execution completed"
		]
		
		for keyword in critical_keywords:
			if keyword in message:
				return True
		verbose_keywords = [
			"[TIMING]", "[PAUSE]", "Stopping bot", "Δ:", "Audio timer",
			"Will resume from", "Resetting for restart", "audio:",
			"Timing shift:", "Offset:", "Waiting for audio"
		]
		
		for keyword in verbose_keywords:
			if keyword in message:
				return False
		return True
	
	def log_message(self, message: str, color: tuple = (255, 255, 255)) -> None:
		safe_print(message)
		if self.log_mode == "Minimal" and not self._should_show_in_minimal(message):
			return
		
		if dpg.does_item_exist("log_content"):
			self.log_entry_count += 1
			text_id = dpg.add_text(message, parent="log_content", tag=f"log_entry_{self.log_entry_count}")
			if color != (255, 255, 255):
				dpg.configure_item(text_id, color=color)
			if dpg.does_item_exist("log_content_window"):
				dpg.set_y_scroll("log_content_window", -1.0)
	
	def update_game_state(self, state_name: str) -> None:
		if dpg.does_item_exist("game_state_label"):
			dpg.set_value("game_state_label", f"Game State: {state_name}")
	
	def update_osu_status(self, connected: bool, pid: Optional[int] = None) -> None:
		if dpg.does_item_exist("osu_status_label"):
			if connected and pid:
				dpg.set_value("osu_status_label", f"osu! Status: Connected (PID {pid})")
			elif connected:
				dpg.set_value("osu_status_label", "osu! Status: Connected")
			else:
				dpg.set_value("osu_status_label", "osu! Status: Not Connected")
	
	def update_beatmap_info(self, title: str, difficulty: str, mapper: str, 
	                        mode: str, keys: int, map_id: int, cs_keys: int = None, 
	                        position_keys: int = None, original_position_keys: int = None, has_error: bool = False, 
	                        error_message: str = "", is_mania: bool = True) -> None:
		if dpg.does_item_exist("beatmap_title"):
			dpg.set_value("beatmap_title", f"Title: {title}")
		if dpg.does_item_exist("beatmap_difficulty"):
			dpg.set_value("beatmap_difficulty", f"Difficulty: {difficulty}")
		if dpg.does_item_exist("beatmap_mapper"):
			dpg.set_value("beatmap_mapper", f"Mapper: {mapper}")
		
		if dpg.does_item_exist("beatmap_mode"):
			if is_mania and cs_keys is not None:
				dpg.set_value("beatmap_mode", f"Mode: Mania {cs_keys}K (CS-based)")
			else:
				dpg.set_value("beatmap_mode", f"Mode: {mode}")
		
		if dpg.does_item_exist("beatmap_keys"):
			if is_mania and position_keys is not None:
				if original_position_keys is not None and original_position_keys > cs_keys:
					dpg.set_value("beatmap_keys", f"Keys: {position_keys}K (fixed from {original_position_keys} positions)")
				else:
					dpg.set_value("beatmap_keys", f"Keys: {position_keys}K")
			elif is_mania:
				dpg.set_value("beatmap_keys", f"Keys: {keys}K")
			else:
				dpg.set_value("beatmap_keys", "Keys: N/A")
		
		if dpg.does_item_exist("beatmap_id"):
			dpg.set_value("beatmap_id", f"Map ID: {map_id}")
		if dpg.does_item_exist("map_error_message"):
			if is_mania and has_error and error_message:
				dpg.set_value("map_error_message", f"{error_message}")
				dpg.configure_item("map_error_message", color=(255, 200, 0))
			else:
				dpg.set_value("map_error_message", "")
		if dpg.does_item_exist("mode_not_supported"):
			if not is_mania:
				dpg.set_value("mode_not_supported", "MAP MODE NOT SUPPORTED")
			else:
				dpg.set_value("mode_not_supported", "")
	
	def clear_beatmap_info(self) -> None:
		if dpg.does_item_exist("beatmap_title"):
			dpg.set_value("beatmap_title", "Title: None")
		if dpg.does_item_exist("beatmap_difficulty"):
			dpg.set_value("beatmap_difficulty", "Difficulty: None")
		if dpg.does_item_exist("beatmap_mapper"):
			dpg.set_value("beatmap_mapper", "Mapper: None")
		if dpg.does_item_exist("beatmap_mode"):
			dpg.set_value("beatmap_mode", "Mode: None")
		if dpg.does_item_exist("beatmap_keys"):
			dpg.set_value("beatmap_keys", "Keys: None")
		if dpg.does_item_exist("beatmap_id"):
			dpg.set_value("beatmap_id", "Map ID: None")
		if dpg.does_item_exist("map_error_message"):
			dpg.set_value("map_error_message", "")
		if dpg.does_item_exist("mode_not_supported"):
			dpg.set_value("mode_not_supported", "")
	
	def update_mods(self, mods_string: str, speed_multiplier: float) -> None:
		if dpg.does_item_exist("mods_label"):
			dpg.set_value("mods_label", f"Mods: {mods_string}")
		if dpg.does_item_exist("speed_label"):
			dpg.set_value("speed_label", f"Speed: {speed_multiplier:.2f}x")
	
	def update_audio_time(self, audio_time_ms: int) -> None:
		if dpg.does_item_exist("audio_time_label"):
			minutes = audio_time_ms // 60000
			seconds = (audio_time_ms % 60000) // 1000
			milliseconds = audio_time_ms % 1000
			dpg.set_value("audio_time_label", f"Audio Time: {minutes:02d}:{seconds:02d}.{milliseconds:03d}")
	
	def update_gameplay_data(self, score: int, combo: int, max_combo: int, accuracy: float, hp: float, 
	                          hit_300: int, hit_100: int, hit_50: int, hit_miss: int, hit_geki: int, hit_katu: int) -> None:
		if dpg.does_item_exist("gameplay_score"):
			dpg.set_value("gameplay_score", f"Score: {score:,}")
		
		if dpg.does_item_exist("gameplay_combo"):
			dpg.set_value("gameplay_combo", f"Combo: {combo}x / {max_combo}x")
		
		if dpg.does_item_exist("gameplay_accuracy"):
			dpg.set_value("gameplay_accuracy", f"Accuracy: {accuracy*100:.2f}%")
		
		if dpg.does_item_exist("gameplay_hp"):
			dpg.set_value("gameplay_hp", f"HP: {hp*100:.1f}%")
		
		if dpg.does_item_exist("gameplay_hits"):
			dpg.set_value("gameplay_hits", f"Hits: {hit_geki}g / {hit_300} / {hit_katu}k / {hit_100} / {hit_50} / {hit_miss}x")
	
	def clear_gameplay_data(self) -> None:
		if dpg.does_item_exist("gameplay_score"):
			dpg.set_value("gameplay_score", "Score: N/A")
		if dpg.does_item_exist("gameplay_combo"):
			dpg.set_value("gameplay_combo", "Combo: N/A")
		if dpg.does_item_exist("gameplay_accuracy"):
			dpg.set_value("gameplay_accuracy", "Accuracy: N/A")
		if dpg.does_item_exist("gameplay_hp"):
			dpg.set_value("gameplay_hp", "HP: N/A")
		if dpg.does_item_exist("gameplay_hits"):
			dpg.set_value("gameplay_hits", "Hits: N/A")
	
	def update_bot_status(self, status: str) -> None:
		if dpg.does_item_exist("bot_status_label"):
			dpg.set_value("bot_status_label", f"Bot Status: {status}")
	
	def update_first_note_time(self, time_ms: int) -> None:
		if dpg.does_item_exist("first_note_label"):
			dpg.set_value("first_note_label", f"First Note: {time_ms} ms")
	
	def update_timing_shift(self, shift_ms: int) -> None:
		if dpg.does_item_exist("timing_shift_input"):
			dpg.set_value("timing_shift_input", shift_ms)
	
	def get_offset(self) -> int:
		if dpg.does_item_exist("offset_input"):
			return dpg.get_value("offset_input")
		return 30
	
	def set_offset(self, value: int) -> None:
		if dpg.does_item_exist("offset_input"):
			dpg.set_value("offset_input", value)
	
	def _handle_window_drag(self) -> None:
		mouse_local_x, mouse_local_y = dpg.get_mouse_pos(local=True)
		
		if dpg.is_mouse_button_down(0):
			if not self.is_dragging:
				if 0 <= mouse_local_y <= 25:
					self.is_dragging = True
					self.drag_offset_x = mouse_local_x
					self.drag_offset_y = mouse_local_y
			
			if self.is_dragging:
				vp_x, vp_y = dpg.get_viewport_pos()
				delta_x = mouse_local_x - self.drag_offset_x
				delta_y = mouse_local_y - self.drag_offset_y
				new_x = int(vp_x + delta_x)
				new_y = int(vp_y + delta_y)
				dpg.configure_viewport(self.viewport, x_pos=new_x, y_pos=new_y)
		else:
			self.is_dragging = False
	
	def run(self) -> None:
		self._running = True
		dpg.show_viewport()
		
		import time
		time.sleep(0.2)
		self.tray_manager.find_window_handle("PrismaTC")
		
		while dpg.is_dearpygui_running():
			self._handle_window_drag()
			dpg.render_dearpygui_frame()
		dpg.destroy_context()
	
	def stop(self) -> None:
		self._running = False
		self.tray_manager.cleanup()
		
		if hasattr(dpg, "stop_dearpygui"):
			dpg.stop_dearpygui()
		dpg.destroy_context()
	
	def is_running(self) -> bool:
		return self._running
	
	def update_osu_unlock_status(self, locked: bool, unlock_date: str = "None") -> None:
		if dpg.does_item_exist("osu_unlock_locked_status"):
			dpg.set_value("osu_unlock_locked_status", f"Account Locked: {locked}")
		if dpg.does_item_exist("osu_unlock_date_status"):
			dpg.set_value("osu_unlock_date_status", f"Unlock Date: {unlock_date}")
		
		if dpg.does_item_exist("osu_unlock_button"):
			dpg.configure_item("osu_unlock_button", show=locked)
