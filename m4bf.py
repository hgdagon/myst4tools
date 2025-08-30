#!/usr/bin/env python3

import sys
from struct import pack, unpack
from pathlib import Path
import mmap

# https://stackoverflow.com/a/1094933
def sizeof_fmt(num, suffix="B"):
    for unit in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
        if abs(num) < 1024.0:
            return f"{num:.4g}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.4g}Yi{suffix}"

# unpacks a length-prefixed null-terminated string
def str_unpack(f):
    len_str, = unpack('<I', f.read(4))
    return f.read(len_str).rstrip(b'\0').decode('latin1') # Try 'ascii' if fails
    
# packs a length-prefixed null-terminated string
def str_pack(s):
    len_str = len(s) + (1 if s else 0)
    return pack(f'<I{len_str}s', len_str, s.encode('latin1')) # Try 'ascii' if fails

class Node:
    def __init__(self, name:str = None):
        self.name = name

class DirNode(Node):
    def __init__(self, name: str = None):
        super().__init__(name)
        self.children: list[Node] = []

    def add(self, node: Node):
        self.children.append(node)

    @property
    def num_subdirs(self):
        return sum(isinstance(c, DirNode) for c in self.children)

    @property
    def num_files(self):
        return sum(isinstance(c, FileNode) for c in self.children)

    def size_header(self, size = 19):
        # Name
        # Number of subdirs (Byte)
        size += len(str_pack(self.name)) + 1

        for d in iter(d for d in self.children if isinstance(d, DirNode)):
            size = d.size_header(size)
        size += 4 # Number of files
        for f in iter(f for f in self.children if isinstance(f, FileNode)):
            # Name
            # Data size (Int)
            # Data offset (Int)
            size += len(str_pack(f.name)) + 4 + 4

        return size

    def read_entries(self, f):
        num_dirs, = unpack('<B', f.read(1))
        for _ in range(num_dirs):
            dnode = DirNode(str_unpack(f))
            dnode.read_entries(f)
            self.add(dnode)
        num_files, = unpack('<I', f.read(4))
        for _ in range(num_files):
            self.add(FileNode(str_unpack(f), *unpack('<II', f.read(8))))

    # If ver is Int, then the structure makes more sense
    def read_entries2(self, f):
        dnode = DirNode(str_unpack(f))
        num_dirs, = unpack('<B', f.read(1))
        self.add(dnode)
        for _ in range(num_dirs):
            dnode.read_entries2(f)
        num_files, = unpack('<I', f.read(4))
        for _ in range(num_files):
            self.add(FileNode(str_unpack(f), *unpack('<II', f.read(8))))

    def write_entries(self, f):
        f.write(pack('<B', self.num_subdirs))
        for child in self.children:
            if isinstance(child, DirNode):
                f.write(str_pack(child.name))
                child.write_entries(f)
        f.write(pack('<I', self.num_files))
        for child in self.children:
            if isinstance(child, FileNode):
                f.write(str_pack(child.name))
                f.write(pack('<I', child.size))
                f.write(pack('<I', child.offset))

    def find_node(self, path_parts: tuple):
        if not path_parts or self.name == path_parts:
            return self  # fully matched

        child = next(child for child in self.children if isinstance(child, DirNode) and child.name == path_parts[0])
        return child.find_node(path_parts[1:])

    # https://stackoverflow.com/a/59109706
    def tree(self, prefix: str = ""):
        """Recursively print the visual tree."""
        if not prefix:
            print(f"📁 {self.name}/")

        pointers = ['├── '] * (len(self.children) - 1) + ['└── ']
        for pointer, child in zip(pointers, self.children):
            if isinstance(child, FileNode):
                print(prefix + pointer + f"📄 {child.name}")
            elif isinstance(child, DirNode):
                print(prefix + pointer + f"📁 {child.name}")
                extension = ('│   ' if pointer == '├── ' else '    ')
                child.tree(prefix=prefix + extension)

    def files(self, path: Path = None):
        """Yield the name of every FileNode child recursively."""
        path = path or Path(self.name)
        for child in self.children:
            if isinstance(child, FileNode):
                yield child, path.joinpath(child.name), child.size, child.offset
            elif isinstance(child, DirNode):
                yield from child.files(path.joinpath(child.name))

    def list(self):
        for _, fname, size, offset in self.files():
            print(fname, sizeof_fmt(size), offset)

class FileNode(Node):
    def __init__(self, name:str = None, size: int = 0, offset: int = 0):
        super().__init__(name)
        self.size = size
        self.offset = offset

class BigFile(DirNode):
    def __init__(self, path: Path, path_new_bf: Path = None):
        if path.is_dir():
            super().__init__('')
            path_new_bf = path_new_bf or path.with_suffix('.m4b')
            self.from_path(path, path_new_bf)
            return
        elif path.is_file():
            self.fd = path.open('rb')
        else:
            raise ValueError(f'Links are not yet supported.')

        self.buffer = mmap.mmap(self.fd.fileno(), 0, access=mmap.ACCESS_READ)

        magic = str_unpack(self.buffer)
        version, = unpack('<I', self.buffer.read(4))
        name_root = str_unpack(self.buffer)
        if magic != 'UBI_BF_SIG' or version != 1 or name_root:
            raise ValueError(f'{path} is not a Myst IV big file.\n{magic=}\n{version=}\n{name_root=}')
        super().__init__(name_root)

        self.read_entries(self.buffer)
        self.num_entries = len(list(self.files()))

    def extract(self, path: Path | str, extract_nested: bool = False) -> bool:
        path = Path(path).resolve()

        for i, (_, name, length, offset) in enumerate(self.files(path)):
            name.parent.mkdir(parents=True, exist_ok=True)
            name.write_bytes(self.buffer[offset:offset+length])
            print(f'\033[K{name} [{sizeof_fmt(length)}] {i / self.num_entries:.0%}', end='\r')
            if extract_nested and name.suffix == '.m4b':
                BigFile(name).extract(name.with_suffix(''), True)
                name.unlink()

        print('\033[KExtracted', self.num_entries, 'entries', end='\r')
        return True

    def from_path(self, path: Path, bigfile: Path = None) -> bool:
        for root, dirnames, filenames in path.walk():
            parent_node = self.find_node(root.relative_to(path).parts)

            # Add files
            for fname in sorted(filenames):
                size = root.joinpath(fname).stat().st_size
                file_node = FileNode(fname, size=size, offset=0)
                parent_node.add(file_node)

            # Add directories
            for dname in sorted(dirnames):
                dir_node = DirNode(dname)
                parent_node.add(dir_node)

        offset = self.size_header()

        for node, name, size, _ in self.files(path):
            node.offset = offset
            offset += node.size

        with bigfile.open('wb') as f:
            f.write(str_pack('UBI_BF_SIG'))
            f.write(pack('<I', 1))
            f.write(str_pack('')) # root is nameless
            self.write_entries(f)
            for _, name, *_ in self.files(path):
                f.write(name.read_bytes())
        return True

if __name__ == '__main__':
    usage = f"""
      Usage: {sys.argv[0]} [-l] [-t] [-n] [-r] input_path [output_path]

         -l: List files in the archive. All other options will be ignored.
         -t: Print the directory tree inside the archive. All other options will be ignored.
         -n: Extract nested archives.
         -r: Recursively find all archives in input path and extract them. Ignored if input_path is a file.
 input_path: Extract archive if .m4b file or pack the contents of the directory.
output_path: If not provided, will be determined contextually.
    """

    list_files      = '-l' in sys.argv
    print_tree      = '-t' in sys.argv
    extract_nested  = '-n' in sys.argv
    recursive       = '-r' in sys.argv

    list_files and sys.argv.remove('-l')
    print_tree and sys.argv.remove('-t')
    extract_nested and sys.argv.remove('-n')
    recursive and sys.argv.remove('-r')

    if 7 > len(sys.argv) > 1:
        input = Path(sys.argv[1])

        if input.is_file() and input.suffix == '.m4b':
            if list_files:
                BigFile(input).list()

            elif print_tree:
                BigFile(input).tree()

            else:
                output = Path(sys.argv[2]) if len(sys.argv) == 3 else input.with_suffix('')
                BigFile(input).extract(output, extract_nested=extract_nested)

        elif input.is_dir():
            if list_files or print_tree:
                print('This command is for archives only.')

            elif recursive:
                for bf in input.rglob('*.m4b'):
                    output = Path(sys.argv[2]) if len(sys.argv) == 3 else bf.with_suffix('')
                    BigFile(bf).extract(output, extract_nested=extract_nested)

            else:
                output = Path(sys.argv[2]) if len(sys.argv) == 3 else input.with_suffix('.m4b')
                print(f'Will pack {input.as_posix()} to {output.as_posix()}')
                print(f'Checking {output.as_posix()}...')
                if sum(f.stat().st_size for f in input.rglob('*')) > 4294967000: # Try to assume header size
                    print(f'Cannot pack {input.as_posix()}.\nFiles are too big.')
                    sys.exit(1)
                if any(len(str(f)) > 256 for f in input.rglob('*')): # Not sure about this limitation
                    print(f'Cannot pack {input.as_posix()}.\nFilenames are too big.')
                    sys.exit(1)
                BigFile(input, output)

        else:
            print(usage)

    else:
        print(usage)
