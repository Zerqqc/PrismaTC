import os
import shutil
import struct
from pathlib import Path
from datetime import datetime
import psutil


def ticks_to_datetime(ticks):
	if ticks == 0:
		return None
	unix_timestamp = (ticks / 10000000) - 62135596800
	dt = datetime.fromtimestamp(unix_timestamp)
	return dt.strftime("%Y-%m-%d %H:%M:%S")


class OsuUnlocker:
	def __init__(self, db_path=None):
		self.db_path = Path(db_path) if db_path else None
		self.data = None
		self.version = None
		self.backup_path = None
		self.parse_offset = 0
		
		self.account_locked = None
		self.unlock_date = None
		self.player_name = None
	
	def find_osu_database(self):
		try:
			for process in psutil.process_iter(["pid", "name", "exe"]):
				name = process.info.get("name")
				if name and name.lower() == "osu!.exe":
					exe_path = process.info.get("exe")
					if exe_path:
						osu_dir = os.path.dirname(exe_path)
						db_path = os.path.join(osu_dir, "osu!.db")
						if os.path.isfile(db_path):
							self.db_path = Path(db_path)
							return True
		except Exception:
			pass
		
		return False
	
	def read_account_status(self):
		if not self.db_path or not self.db_path.exists():
			return False, "Database file not found"
		
		try:
			self.data = bytearray(self.db_path.read_bytes())
			self.parse_offset = 0
			
			self.version = struct.unpack_from("<I", self.data, 0)[0]
			self.parse_offset += 4
			
			folder_count = struct.unpack_from("<I", self.data, self.parse_offset)[0]
			self.parse_offset += 4
			
			unlocked_byte = self.data[self.parse_offset]
			self.account_locked = (unlocked_byte == 0x00)
			self.parse_offset += 1
			
			unlock_ticks = struct.unpack_from("<Q", self.data, self.parse_offset)[0]
			if self.account_locked and unlock_ticks > 0:
				self.unlock_date = ticks_to_datetime(unlock_ticks)
			else:
				self.unlock_date = None
			self.parse_offset += 8
			
			name_start = self.parse_offset
			if self.data[self.parse_offset] == 0x0B:
				len_uleb = 0
				shift = 0
				u_off = self.parse_offset + 1
				while True:
					byte = self.data[u_off]
					len_uleb |= (byte & 0x7F) << shift
					u_off += 1
					if byte < 0x80:
						break
					shift += 7
				name_len = len_uleb
				name_bytes = self.data[u_off : u_off + name_len]
				try:
					self.player_name = name_bytes.decode("utf-8")
				except Exception:
					self.player_name = "Unknown"
				self.parse_offset = u_off + name_len
			else:
				self.player_name = "Empty"
				self.parse_offset += 1
			
			return True, "Success"
			
		except Exception as e:
			return False, f"Error reading database: {str(e)}"
	
	def create_backup(self):
		if not self.db_path:
			return False
		
		self.backup_path = self.db_path.with_suffix(".db.bak")
		try:
			shutil.copy2(self.db_path, self.backup_path)
			return True
		except Exception:
			return False
	
	def unlock_account(self):
		if not self.data:
			return False, "No data loaded. Read account status first."
		
		if not self.create_backup():
			return False, "Failed to create backup"
		
		try:
			self.parse_offset = 0
			
			self.parse_offset += 4
			
			self.parse_offset += 4
			
			self.data[self.parse_offset] = 0x01
			self.parse_offset += 1
			
			struct.pack_into("<Q", self.data, self.parse_offset, 0)
			self.parse_offset += 8
			
			self.db_path.write_bytes(self.data)
			
			self.account_locked = False
			self.unlock_date = None
			
			return True, "Account unlocked successfully"
			
		except Exception as e:
			return False, f"Error unlocking account: {str(e)}"
	
	def get_status_text(self):
		if self.account_locked is None:
			return "Not scanned yet"
		
		status = {
			"locked": self.account_locked,
			"unlock_date": self.unlock_date if self.unlock_date else "None",
			"player_name": self.player_name if self.player_name else "Unknown"
		}
		return status
