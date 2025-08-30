import mmap
import zlib
from pathlib import Path
from shutil import rmtree
from time import perf_counter
from m4bf import BigFile

# Known files with a full match
skip_files = {'data.m4b': '4278266197', 'patch.m4b': '819109030', 'video_2.m4b': '924741414',
              'video_3.m4b': '911390073', 'video_5.m4b': '1869515520', 'video_8.m4b': '2470812484',
              'dutch_sound.m4b': '2783523831', 'english_sound.m4b': '2235901206', 'french_sound.m4b': '2502813462',
              'german_sound.m4b': '2762367769', 'italian_sound.m4b': '3448582312', 'spanish_sound.m4b': '3083087471'}

def print_green(s: str) -> None:
    print(f"\033[92m{s}\033[0m")


def print_red(s: str) -> None:
    print(f"\033[91m{s}\033[0m")


def crc32sum(path: Path) -> int:
    with path.open("rb") as bf, mmap.mmap(bf.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        return zlib.crc32(mm) & 0xffffffff


def print_files(bf: BigFile) -> str:
    return '\n'.join(
        f'{name} {offset} {offset:08X}' for node, name, size, offset in sorted(bf.files(), key=lambda t: t[3]))

test_path = r'C:\Games\Myst IV\!Downloads\Myst IV\setup_myst_4_revelation_1.03_hotfix_2_(22142)'

for f in Path(test_path).rglob('*.m4b'):
    if 'myst4tools' in f.parts: continue
    if skip_files.get(f.name, False): continue
    outpath = Path(f.stem)
    new_file = Path('_'.join(f.parts[-2:]))
    name_easy = new_file.name.removeprefix(testpath.parts[-1])
    old_bf = BigFile(f)
    old_crc = crc32sum(f)
    old_bf.extract(outpath)
    new_bf = BigFile(outpath, new_file)
    new_crc = crc32sum(new_file)
    rmtree(outpath)
    if old_crc != new_crc:
        print_red(f"{new_file} is mismatched!")
    else:
        print_green(f'{new_file} is matched!')
    new_file.unlink()
