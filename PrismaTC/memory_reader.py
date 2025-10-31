import ctypes
import ctypes.wintypes as wintypes
import struct
from typing import Optional, Tuple, List
from dataclasses import dataclass
from enum import IntEnum
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import os
import psutil
from safe_print import safe_print


PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ('dwSize', wintypes.DWORD),
        ('cntUsage', wintypes.DWORD),
        ('th32ProcessID', wintypes.DWORD),
        ('th32DefaultHeapID', ctypes.POINTER(wintypes.ULONG)),
        ('th32ModuleID', wintypes.DWORD),
        ('cntThreads', wintypes.DWORD),
        ('th32ParentProcessID', wintypes.DWORD),
        ('pcPriClassBase', wintypes.LONG),
        ('dwFlags', wintypes.DWORD),
        ('szExeFile', ctypes.c_char * 260)
    ]


class GameState(IntEnum):
    MENU = 0
    MAP_EDIT = 1
    PLAY = 2
    EXIT = 3
    SELECT_EDIT = 4
    SONG_SELECT = 5
    SELECT_DRAWINGS = 6
    RESULT_SCREEN = 7
    UPDATE = 8
    BUSY = 9
    UNKNOWN = 10
    LOBBY = 11
    MULTIPLAYER_ROOM = 12
    SONG_SELECT_MULTIPLAYER = 13
    RANKING_VS = 14
    ONLINE_SELECTION = 15
    OPTIONS_OFFSET_WIZARD = 16
    RANKING_TAG_COOP = 17
    RANKING_TEAM = 18
    BEATMAP_SCAN = 19
    PACKAGE_UPDATER = 20
    BENCHMARK = 21
    TOURNEY = 22
    CHARTS = 23


class Gamemode(IntEnum):
    OSU = 0
    TAIKO = 1
    CATCH = 2
    MANIA = 3


class OsuMods(IntEnum):
    NOMOD = 0
    NO_FAIL = 1 << 0        # NF
    EASY = 1 << 1           # EZ
    TOUCH_DEVICE = 1 << 2   # TD
    HIDDEN = 1 << 3         # HD
    HARD_ROCK = 1 << 4      # HR
    SUDDEN_DEATH = 1 << 5   # SD
    DOUBLE_TIME = 1 << 6    # DT
    RELAX = 1 << 7          # RX
    HALF_TIME = 1 << 8      # HT
    NIGHTCORE = 1 << 9      # NC (includes DT)
    FLASHLIGHT = 1 << 10    # FL
    AUTOPLAY = 1 << 11      # AT
    SPUN_OUT = 1 << 12      # SO
    AUTOPILOT = 1 << 13     # AP
    PERFECT = 1 << 14       # PF (includes SD)
    KEY4 = 1 << 15          # 4K
    KEY5 = 1 << 16          # 5K
    KEY6 = 1 << 17          # 6K
    KEY7 = 1 << 18          # 7K
    KEY8 = 1 << 19          # 8K
    FADE_IN = 1 << 20       # FI
    RANDOM = 1 << 21        # RD
    CINEMA = 1 << 22        # CN
    TARGET = 1 << 23        # TG
    KEY9 = 1 << 24          # 9K
    KEY10 = 1 << 25         # 10K
    KEY1 = 1 << 26          # 1K
    KEY3 = 1 << 27          # 3K
    KEY2 = 1 << 28          # 2K
    SCORE_V2 = 1 << 29      # v2
    MIRROR = 1 << 30        # MR

MOD_BIT_VALUES = [
    'NF',   # 0
    'EZ',   # 1
    'TD',   # 2
    'HD',   # 3
    'HR',   # 4
    'SD',   # 5
    'DT',   # 6
    'RX',   # 7
    'HT',   # 8
    'NC',   # 9
    'FL',   # 10
    'AT',   # 11
    'SO',   # 12
    'AP',   # 13
    'PF',   # 14
    '4K',   # 15
    '5K',   # 16
    '6K',   # 17
    '7K',   # 18
    '8K',   # 19
    'FI',   # 20
    'RD',   # 21
    'CN',   # 22
    'TG',   # 23
    '9K',   # 24
    '10K',  # 25
    '1K',   # 26
    '3K',   # 27
    '2K',   # 28
    'v2',   # 29
    'MR'    # 30
]

MOD_ORDER = {
    'nf': 0, 'ez': 1, 'hd': 2, 'dt': 3, 'nc': 3, 'ht': 3,
    'hr': 4, 'so': 5, 'sd': 5, 'pf': 5, 'fl': 6, 'td': 7
}


def parse_mods(mods_number: int, ordered: bool = True) -> Tuple[str, List[str], float]:
    if mods_number == 0:
        return ('', [], 1.0)
    
    mods_list = []
    
    for bit_index in range(31):
        bit_value = 1 << bit_index
        if mods_number & bit_value:
            if bit_index < len(MOD_BIT_VALUES):
                mods_list.append(MOD_BIT_VALUES[bit_index])
    
    speed_multiplier = 1.0
    if 'DT' in mods_list or 'NC' in mods_list:
        speed_multiplier = 1.5
    elif 'HT' in mods_list:
        speed_multiplier = 0.75
    if ordered:
        mods_list.sort(key=lambda x: MOD_ORDER.get(x.lower(), 99))
    
    mods_string = ''.join(mods_list)
    mods_string = mods_string.replace('DTNC', 'NC').replace('NCDT', 'NC')
    mods_string = mods_string.replace('SDPF', 'PF').replace('PFSD', 'PF')
    mods_string = mods_string.replace('ATCN', 'CN').replace('CNAT', 'CN')

    if mods_string:
        mods_array = [mods_string[i:i+2] for i in range(0, len(mods_string), 2)]
    else:
        mods_array = []
    
    return (mods_string, mods_array, speed_multiplier)


@dataclass
class Pattern:
    name: str
    signature: bytes
    mask: bytes
    offset: int = 0


@dataclass
class BeatmapInfo:
    checksum: str
    filename: str
    folder: str
    artist: str
    title: str
    difficulty: str
    creator: str
    map_id: int
    set_id: int
    ranked_status: int
    ar: float
    cs: float
    hp: float
    od: float
    object_count: int
    selected_gamemode: int
    beatmap_mode: int


@dataclass
class MenuMods:
    mods_number: int
    mods_string: str
    mods_array: List[str]
    speed_multiplier: float


@dataclass
class GameplayData:
    player_name: str
    score: int
    combo: int
    max_combo: int
    accuracy: float
    hp: float
    hp_smooth: float
    hit_300: int
    hit_100: int
    hit_50: int
    hit_miss: int
    hit_geki: int
    hit_katu: int


class OsuMemoryReader:
    
    def __init__(self, debug: bool = False):
        self.process_handle: Optional[int] = None
        self.process_id: Optional[int] = None
        self.base_addresses: dict = {}
        self.debug = debug
        self._songs_folder_cache: Optional[str] = None

        self.patterns = {
            'baseAddr': self._create_pattern('F8 01 74 04 83 65'),
            'playTimeAddr': self._create_pattern('5E 5F 5D C3 A1 ?? ?? ?? ?? 89 ?? 04'),
            'statusPtr': self._create_pattern('48 83 F8 04 73 1E', offset=-0x4),
            'chatCheckerPtr': self._create_pattern('8B CE 83 3D ?? ?? ?? ?? 00 75 ?? 80', offset=0x4),
            'skinDataAddr': self._create_pattern('74 2C 85 FF 75 28 A1 ?? ?? ?? ?? 8D 15'),
            'menuModsPtr': self._create_pattern('C8 FF ?? ?? ?? ?? ?? 81 0D ?? ?? ?? ?? ?? 08 00 00', offset=0x9),
            'rulesetsAddr': self._create_pattern('7D 15 A1 ?? ?? ?? ?? 85 C0'),
        }
        
        self.kernel32 = ctypes.windll.kernel32
        self.psapi = ctypes.windll.psapi
    
    def _create_pattern(self, pattern_str: str, offset: int = 0) -> Pattern:
        bytes_list = pattern_str.split(' ')
        signature = bytes([int(b, 16) if b != '??' else 0x00 for b in bytes_list])
        mask = bytes([0x01 if b != '??' else 0x00 for b in bytes_list])
        return Pattern('', signature, mask, offset)
    
    def find_process(self, process_name: str = "osu!.exe") -> Optional[int]:
        snapshot = self.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1:
            return None
        
        process_entry = PROCESSENTRY32()
        process_entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        
        if self.kernel32.Process32First(snapshot, ctypes.byref(process_entry)):
            while True:
                if process_entry.szExeFile.decode('utf-8', errors='ignore') == process_name:
                    self.kernel32.CloseHandle(snapshot)
                    return process_entry.th32ProcessID
                
                if not self.kernel32.Process32Next(snapshot, ctypes.byref(process_entry)):
                    break
        
        self.kernel32.CloseHandle(snapshot)
        return None
    
    def open_process(self, pid: int) -> bool:
        self.process_id = pid
        self.process_handle = self.kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        return self.process_handle is not None and self.process_handle != 0
    
    def close_process(self):
        if self.process_handle:
            self.kernel32.CloseHandle(self.process_handle)
            self.process_handle = None
    
    def read_memory(self, address: int, size: int) -> Optional[bytes]:
        if not self.process_handle:
            return None
        
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t(0)
        
        success = self.kernel32.ReadProcessMemory(
            self.process_handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(bytes_read)
        )
        
        if success and bytes_read.value == size:
            return buffer.raw
        return None
    
    def read_int(self, address: int) -> Optional[int]:
        data = self.read_memory(address, 4)
        if data:
            return struct.unpack('<I', data)[0]
        return None
    
    def read_float(self, address: int) -> Optional[float]:
        data = self.read_memory(address, 4)
        if data:
            return struct.unpack('<f', data)[0]
        return None
    
    def read_byte(self, address: int) -> Optional[int]:
        data = self.read_memory(address, 1)
        if data:
            return struct.unpack('<B', data)[0]
        return None
    
    def read_pointer(self, address: int) -> Optional[int]:
        ptr1 = self.read_int(address)
        if ptr1 and ptr1 != 0:
            ptr2 = self.read_int(ptr1)
            return ptr2
        return None
    
    def read_csharp_string(self, address: int) -> Optional[str]:
        if not address or address == 0:
            return None
        
        length = self.read_int(address + 0x4)
        if not length or length <= 0 or length > 1000:
            return None
        
        string_data = self.read_memory(address + 0x8, length * 2)
        if string_data:
            try:
                return string_data.decode('utf-16-le').rstrip('\x00')
            except:
                return None
        return None
    
    def parse_beatmap_mode(self, osu_path: str) -> int:
        try:
            if not osu_path:
                return -1
            with open(osu_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('Mode:') or line.startswith('Mode :'):
                        mode_str = line.split(':', 1)[1].strip()
                        try:
                            return int(mode_str)
                        except ValueError:
                            return -1
                    if line == '[Difficulty]':
                        break
            return 0
        except Exception as e:
            if self.debug:
                safe_print(f"[DEBUG] Error parsing beatmap mode: {e}")
            return -1
    
    def pattern_scan(self, pattern: Pattern) -> Optional[int]:
        if not self.process_handle:
            return None

        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD),
                ("Type", wintypes.DWORD)
            ]
        
        mbi = MEMORY_BASIC_INFORMATION()
        address = 0
        
        PAGE_EXECUTE_READ = 0x20
        PAGE_EXECUTE_READWRITE = 0x40
        PAGE_READWRITE = 0x04
        PAGE_READONLY = 0x02
        MEM_COMMIT = 0x1000
        MEM_IMAGE = 0x1000000

        pattern_len = len(pattern.signature)
        first_byte = None
        first_byte_mask = None
        for i in range(pattern_len):
            if pattern.mask[i] == 0x01:
                first_byte = pattern.signature[i]
                first_byte_mask = i
                break
        
        while True:
            result = self.kernel32.VirtualQueryEx(
                self.process_handle,
                ctypes.c_void_p(address),
                ctypes.byref(mbi),
                ctypes.sizeof(mbi)
            )
            
            if result == 0:
                break
            
            base_address = ctypes.cast(mbi.BaseAddress, ctypes.c_void_p).value or 0
            region_size = mbi.RegionSize
            state = mbi.State
            protect = mbi.Protect
            mem_type = mbi.Type
            
            address = base_address + region_size
            
            if state != MEM_COMMIT:
                continue
            
            if protect not in [PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE, PAGE_READWRITE, PAGE_READONLY]:
                continue
            
            if region_size > 100 * 1024 * 1024:
                continue
            
            if mem_type != MEM_IMAGE and protect not in [PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE]:
                if region_size > 1 * 1024 * 1024:
                    continue

            chunk_size = 65536
            for offset in range(0, region_size, chunk_size):
                read_size = min(chunk_size + pattern_len, region_size - offset)
                chunk = self.read_memory(base_address + offset, read_size)
                
                if not chunk or len(chunk) < pattern_len:
                    continue

                if first_byte is not None:
                    search_pos = 0
                    while True:
                        pos = chunk.find(first_byte, search_pos)
                        if pos == -1 or pos > len(chunk) - pattern_len:
                            break
                        match_start = pos - first_byte_mask
                        if match_start < 0 or match_start + pattern_len > len(chunk):
                            search_pos = pos + 1
                            continue
                        

                        match = True
                        for j in range(pattern_len):
                            if pattern.mask[j] == 0x01:
                                if chunk[match_start + j] != pattern.signature[j]:
                                    match = False
                                    break
                        
                        if match:
                            return base_address + offset + match_start + pattern.offset
                        
                        search_pos = pos + 1
                else:
                    for i in range(len(chunk) - pattern_len + 1):
                        match = True
                        for j in range(pattern_len):
                            if pattern.mask[j] == 0x01:
                                if chunk[i + j] != pattern.signature[j]:
                                    match = False
                                    break
                        
                        if match:
                            return base_address + offset + i + pattern.offset
            
            if address >= 0x7FFFFFFF0000:
                break
        
        return None
    
    def scan_all_patterns(self, parallel: bool = True) -> bool:
        safe_print("Scanning for memory patterns...")
        start_time = time.time()
        success_count = 0
        
        if parallel:
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_name = {
                    executor.submit(self.pattern_scan, pattern): name 
                    for name, pattern in self.patterns.items()
                }
                
                for future in as_completed(future_to_name):
                    name = future_to_name[future]
                    try:
                        address = future.result()
                        if address:
                            self.base_addresses[name] = address
                            safe_print(f"  ✓ {name:20s} -> 0x{address:X}")
                            success_count += 1
                        else:
                            safe_print(f"  ✗ {name:20s} -> Not found!")
                            if self.debug:
                                pattern = self.patterns[name]
                                sig_str = ' '.join([f'{b:02X}' if pattern.mask[i] else '??' 
                                                  for i, b in enumerate(pattern.signature)])
                                safe_print(f"    Pattern: {sig_str}")
                    except Exception as e:
                        safe_print(f"  ✗ {name:20s} -> Error: {e}")
                        if self.debug:
                            import traceback
                            traceback.print_exc()
        else:
            for name, pattern in self.patterns.items():
                safe_print(f"  Scanning for {name}...", end=' ', flush=True)
                
                try:
                    address = self.pattern_scan(pattern)
                    if address:
                        self.base_addresses[name] = address
                        safe_print(f"Found at 0x{address:X}")
                        success_count += 1
                    else:
                        safe_print("Not found!")
                        if self.debug:
                            sig_str = ' '.join([f'{b:02X}' if pattern.mask[i] else '??' 
                                              for i, b in enumerate(pattern.signature)])
                            safe_print(f"    Pattern: {sig_str}")
                except Exception as e:
                    safe_print(f"Error: {e}")
                    if self.debug:
                        import traceback
                        traceback.print_exc()
        
        elapsed = time.time() - start_time
        safe_print(f"\nFound {success_count}/{len(self.patterns)} patterns in {elapsed:.2f}s")
        return success_count >= 3
    
    def get_beatmap_info(self) -> Optional[BeatmapInfo]:
        if 'baseAddr' not in self.base_addresses:
            return None
        
        base_addr = self.base_addresses['baseAddr']
        beatmap_addr = self.read_pointer(base_addr - 0xC)
        if not beatmap_addr or beatmap_addr == 0:
            return None

        selected_gamemode = self.read_pointer(base_addr - 0x33)
        if selected_gamemode is None:
            selected_gamemode = 0
        
        if self.debug:
            safe_print(f"[DEBUG] Selected gamemode raw value: {selected_gamemode}")
        
        checksum_ptr = self.read_int(beatmap_addr + 0x6C)
        checksum = self.read_csharp_string(checksum_ptr) if checksum_ptr else ""
        
        filename_ptr = self.read_int(beatmap_addr + 0x90)
        filename = self.read_csharp_string(filename_ptr) if filename_ptr else ""
        
        folder_ptr = self.read_int(beatmap_addr + 0x78)
        folder = self.read_csharp_string(folder_ptr) if folder_ptr else ""
        
        artist_ptr = self.read_int(beatmap_addr + 0x18)
        artist = self.read_csharp_string(artist_ptr) if artist_ptr else ""
        
        title_ptr = self.read_int(beatmap_addr + 0x24)
        title = self.read_csharp_string(title_ptr) if title_ptr else ""
        
        difficulty_ptr = self.read_int(beatmap_addr + 0xAC)
        difficulty = self.read_csharp_string(difficulty_ptr) if difficulty_ptr else ""
        
        creator_ptr = self.read_int(beatmap_addr + 0x7C)
        creator = self.read_csharp_string(creator_ptr) if creator_ptr else ""
        
        map_id = self.read_int(beatmap_addr + 0xC8) or 0
        set_id = self.read_int(beatmap_addr + 0xCC) or 0
        ranked_status = self.read_int(beatmap_addr + 0x12C) or 0
        object_count = self.read_int(beatmap_addr + 0xF8) or 0
        
        ar = self.read_float(beatmap_addr + 0x2C) or 0.0
        cs = self.read_float(beatmap_addr + 0x30) or 0.0
        hp = self.read_float(beatmap_addr + 0x34) or 0.0
        od = self.read_float(beatmap_addr + 0x38) or 0.0

        beatmap_mode = -1
        if folder and filename:
            songs_folder = self.get_songs_folder()
            if songs_folder:
                import os
                osu_file_path = os.path.join(songs_folder, folder, filename)
                beatmap_mode = self.parse_beatmap_mode(osu_file_path)
                
                if self.debug:
                    safe_print(f"[DEBUG] Beatmap mode from file: {beatmap_mode}")
                    safe_print(f"[DEBUG] .osu path: {osu_file_path}")
        
        return BeatmapInfo(
            checksum=checksum,
            filename=filename,
            folder=folder,
            artist=artist,
            title=title,
            difficulty=difficulty,
            creator=creator,
            map_id=map_id,
            set_id=set_id,
            ranked_status=ranked_status,
            ar=ar,
            cs=cs,
            hp=hp,
            od=od,
            object_count=object_count,
            selected_gamemode=selected_gamemode,
            beatmap_mode=beatmap_mode
        )
    
    def get_game_state(self) -> Optional[GameState]:
        if 'statusPtr' not in self.base_addresses:
            return None
        
        status_ptr = self.base_addresses['statusPtr']
        status = self.read_pointer(status_ptr)
        
        if status is not None:
            try:
                return GameState(status)
            except ValueError:
                return GameState.UNKNOWN
        return None
    
    def get_audio_time(self) -> Optional[int]:
        if 'playTimeAddr' not in self.base_addresses:
            return None
        
        play_time_addr = self.base_addresses['playTimeAddr']
        ptr1 = self.read_int(play_time_addr + 0x5)
        if ptr1 and ptr1 != 0:
            play_time = self.read_int(ptr1)
            return play_time
        return None
    
    def get_skin_folder(self) -> Optional[str]:
        if 'skinDataAddr' not in self.base_addresses:
            return None
        
        skin_data_addr = self.base_addresses['skinDataAddr']
        skin_osu_addr = self.read_int(skin_data_addr + 0x7)
        
        if skin_osu_addr and skin_osu_addr != 0:
            skin_osu_base = self.read_int(skin_osu_addr)
            if skin_osu_base and skin_osu_base != 0:
                skin_folder_ptr = self.read_int(skin_osu_base + 0x44)
                if skin_folder_ptr:
                    return self.read_csharp_string(skin_folder_ptr)
        return None
    
    def get_songs_folder(self) -> Optional[str]:

        if self._songs_folder_cache:
            return self._songs_folder_cache
        
        try:
            try:
                if self.process_id:
                    process = psutil.Process(self.process_id)
                    exe_path = process.exe()
                    osu_dir = os.path.dirname(exe_path)
                    songs_path = os.path.join(osu_dir, "Songs")
                    if os.path.exists(songs_path) and os.path.isdir(songs_path):
                        if self.debug:
                            safe_print(f"[DEBUG] Found Songs folder from process: {songs_path}")
                        self._songs_folder_cache = songs_path
                        return songs_path
            except:
                pass

            if self.debug:
                safe_print(f"[DEBUG] Songs folder not found")
            return None
        except Exception as e:
            if self.debug:
                safe_print(f"[DEBUG] Error getting songs folder: {e}")
            return None
    
    def get_menu_mods(self) -> Optional[MenuMods]:

        if 'menuModsPtr' not in self.base_addresses:
            return None
        
        menu_mods_ptr = self.base_addresses['menuModsPtr']
        mods_value = self.read_pointer(menu_mods_ptr)
        
        if mods_value is None:
            return None

        mods_string, mods_array, speed_mult = parse_mods(mods_value)
        
        return MenuMods(
            mods_number=mods_value,
            mods_string=mods_string if mods_string else "NM",
            mods_array=mods_array if mods_array else ["NM"],
            speed_multiplier=speed_mult
        )
    
    def read_double(self, address: int) -> Optional[float]:
        data = self.read_memory(address, 8)
        if data:
            return struct.unpack('<d', data)[0]
        return None
    
    def read_short(self, address: int) -> Optional[int]:
        data = self.read_memory(address, 2)
        if data:
            return struct.unpack('<H', data)[0]
        return None
    
    def get_gameplay_data(self) -> Optional[GameplayData]:
        if 'rulesetsAddr' not in self.base_addresses:
            return None
        
        try:
            rulesets_addr = self.base_addresses['rulesetsAddr']
            
            ptr1 = self.read_int(rulesets_addr - 0xB)
            if not ptr1 or ptr1 == 0:
                return None
            
            ruleset_addr = self.read_int(ptr1 + 0x4)
            if not ruleset_addr or ruleset_addr == 0:
                return None
            
            gameplay_base = self.read_int(ruleset_addr + 0x68)
            if not gameplay_base or gameplay_base == 0:
                return None
            
            score_base = self.read_int(gameplay_base + 0x38)
            if not score_base or score_base == 0:
                return None
            
            hp_bar_base = self.read_int(gameplay_base + 0x40)
            if not hp_bar_base or hp_bar_base == 0:
                return None
            
            player_name_ptr = self.read_int(score_base + 0x28)
            player_name = self.read_csharp_string(player_name_ptr) if player_name_ptr and player_name_ptr != 0 else ""
            
            score = self.read_int(ruleset_addr + 0x100) or 0
            
            hp_smooth_raw = self.read_double(hp_bar_base + 0x14) or 0.0
            hp_raw = self.read_double(hp_bar_base + 0x1C) or 0.0
            
            hp = max(0.0, min(1.0, hp_raw / 200.0))
            hp_smooth = max(0.0, min(1.0, hp_smooth_raw / 200.0))
            
            accuracy_ptr = self.read_int(gameplay_base + 0x48)
            if accuracy_ptr and accuracy_ptr != 0:
                accuracy_raw = self.read_double(accuracy_ptr + 0xC)
                accuracy = (accuracy_raw / 100.0) if accuracy_raw is not None else 1.0
            else:
                accuracy = 1.0
            
            hit_100 = self.read_short(score_base + 0x88) or 0
            hit_300 = self.read_short(score_base + 0x8A) or 0
            hit_50 = self.read_short(score_base + 0x8C) or 0
            hit_geki = self.read_short(score_base + 0x8E) or 0
            hit_katu = self.read_short(score_base + 0x90) or 0
            hit_miss = self.read_short(score_base + 0x92) or 0
            
            combo = self.read_short(score_base + 0x94) or 0
            max_combo = self.read_short(score_base + 0x68) or 0
            
            return GameplayData(
                player_name=player_name,
                score=score,
                combo=combo,
                max_combo=max_combo,
                accuracy=accuracy,
                hp=hp,
                hp_smooth=hp_smooth,
                hit_300=hit_300,
                hit_100=hit_100,
                hit_50=hit_50,
                hit_miss=hit_miss,
                hit_geki=hit_geki,
                hit_katu=hit_katu
            )
        
        except Exception as e:
            if self.debug:
                safe_print(f"[DEBUG] Error reading gameplay data: {e}")
            return None
