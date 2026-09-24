"""Build and verify Bundle v1 TTF font Components.

One Component is one immutable BundleFS file holding several TrueType faces in
fallback order, each in its own FONT section. The layout matches
src/runtime/bundle/bundle_format.h and is accepted by bundle_reader.c:
128-byte header, TOC, metadata section first, 64-byte aligned sections and a
64 KiB aligned Bundle size. All integers are little endian.
"""
from __future__ import annotations

import json
import re
import struct

MAGIC = b'MPXBNDL\0'
VERSION = 1
FRAMEWORK_ABI_VERSION = 1
EXTENT_ALIGNMENT = 64 * 1024
SECTION_ALIGNMENT = 64
MAX_SECTIONS = 128  # MICROPIXEL_BUNDLE_MAX_SECTIONS; one is the metadata
MAX_METADATA = 4096
APP_ID_MAX_LENGTH = 64
HEADER = struct.Struct('<8sIIII64sIIIIIIIIII')
SECTION = struct.Struct('<IIIIIIIIIIII')
KIND_APP_METADATA = 3
KIND_FONT = 4
FORMAT_PACKAGE_METADATA_JSON = 7
FORMAT_STATIC_TTF = 11
FORMAT_VARIABLE_TTF = 12
REQUIRED_TTF_TABLES = (b'glyf', b'loca', b'head', b'hhea', b'hmtx', b'maxp', b'cmap')
_IDENTIFIER = re.compile(r'[a-z][a-z0-9]*([._-][a-z0-9]+)*')
_APP_ID = re.compile(r'[A-Za-z0-9_.-]{1,64}')
_SEMVER = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')


def fnv1a32(data: bytes) -> int:
    value = 0x811C9DC5
    for byte in data:
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return value


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _check_ttf(name: str, data: bytes, variable: bool) -> None:
    if len(data) < 12 or data[:4] != b'\x00\x01\x00\x00':
        raise ValueError(f'{name}: not a TrueType (glyf) font')
    count = int.from_bytes(data[4:6], 'big')
    if count == 0 or count > (len(data) - 12) // 16:
        raise ValueError(f'{name}: invalid table directory')
    tags = [data[12 + i * 16:16 + i * 16] for i in range(count)]
    if len(set(tags)) != len(tags) or not set(REQUIRED_TTF_TABLES) <= set(tags):
        raise ValueError(f'{name}: duplicate or missing required TrueType tables')
    if not variable and b'fvar' in tags:
        raise ValueError(f'{name}: variable font in a static TTF Component')


def build(app_id: str, version: str, faces: list[tuple[str, bytes]], *, display_name: str,
          languages: list[str], font_bundle: str, charset: str, variable: bool = False) -> bytes:
    """Return the Bundle bytes; `faces` is the fallback chain, primary face first.

    `variable` allows OpenType variations (FreeType consumers only).
    """
    if not _APP_ID.fullmatch(app_id) or not _SEMVER.fullmatch(version):
        raise ValueError('invalid Component id or version')
    if not 0 < len(faces) < MAX_SECTIONS or len({name for name, _ in faces}) != len(faces):
        raise ValueError(f'a font Component needs 1..{MAX_SECTIONS - 1} uniquely named faces')
    for name in [font_bundle, charset] + [name for name, _ in faces]:
        if not _IDENTIFIER.fullmatch(name) or len(name) >= APP_ID_MAX_LENGTH:
            raise ValueError(f'invalid identifier: {name}')
    ids = [fnv1a32(name.encode('ascii')) for name, _ in faces]
    if 0 in ids or len(set(ids)) != len(ids):
        raise ValueError('face names must hash to distinct, non-zero section ids')
    for name, data in faces:
        _check_ttf(name, data, variable)
    fmt = FORMAT_VARIABLE_TTF if variable else FORMAT_STATIC_TTF
    metadata = json.dumps({
        'schema_version': 1,
        'package_type': 'component',
        'component_type': 'font',
        'version': version,
        'display_name': {'default': 'en', 'values': {'en': display_name}},
        'languages': languages,
        'font_bundle': font_bundle,
        'charset': charset,
        'font': {'faces': [name for name, _ in faces], 'format': 'ttf-variable' if variable else 'ttf'},
    }, ensure_ascii=False, separators=(',', ':')).encode()
    if len(metadata) > MAX_METADATA:
        raise ValueError('Component metadata exceeds 4096 bytes')

    sections = [(KIND_APP_METADATA, 0, FORMAT_PACKAGE_METADATA_JSON, metadata)]
    sections += [(KIND_FONT, face_id, fmt, data) for face_id, (_, data) in zip(ids, faces)]
    cursor = HEADER.size + len(sections) * SECTION.size
    toc, placements = bytearray(), []
    for kind, section_id, fmt, data in sections:
        cursor = _align(cursor, SECTION_ALIGNMENT)
        toc += SECTION.pack(kind, section_id, cursor, len(data), fnv1a32(data), fmt, 0, 0, 0, 0, 0, 0)
        placements.append((cursor, data))
        cursor += len(data)
    size = _align(cursor, EXTENT_ALIGNMENT)
    encoded_id = app_id.encode('ascii')
    fields = [MAGIC, VERSION, HEADER.size, size, HEADER.size, encoded_id.ljust(APP_ID_MAX_LENGTH, b'\0'),
              len(encoded_id), len(sections), FRAMEWORK_ABI_VERSION, 0]
    header_hash = fnv1a32(HEADER.pack(*fields, 0, 0, 0, 0, 0, 0))
    image = bytearray(size)
    image[:HEADER.size] = HEADER.pack(*fields, header_hash, 0, 0, 0, 0, 0)
    image[HEADER.size:HEADER.size + len(toc)] = toc
    for offset, data in placements:
        image[offset:offset + len(data)] = data
    return bytes(image)


def parse(data: bytes) -> tuple[str, dict, list[tuple[str, bytes]]]:
    """Verify a Component and return (app id, metadata, faces in fallback order)."""
    if len(data) < HEADER.size:
        raise ValueError('truncated Bundle header')
    fields = list(HEADER.unpack_from(data))
    magic, version, header_size, size, toc_offset, raw_id, id_length, count, abi, launch, header_hash = fields[:11]
    if (magic, version, header_size, abi, launch) != (MAGIC, VERSION, HEADER.size, FRAMEWORK_ABI_VERSION, 0):
        raise ValueError('not a Bundle v1 font Component')
    if size != len(data) or toc_offset != HEADER.size or not 0 < count <= MAX_SECTIONS or any(fields[11:]):
        raise ValueError('invalid Bundle header fields')
    fields[10] = 0
    if fnv1a32(HEADER.pack(*fields)) != header_hash:
        raise ValueError('Bundle header hash mismatch')
    app_id = raw_id[:id_length].decode('ascii')
    toc_end = toc_offset + count * SECTION.size
    metadata, fonts, formats, spans = None, {}, set(), []
    for index in range(count):
        kind, section_id, offset, length, digest, fmt, *rest = SECTION.unpack_from(data, toc_offset + index * SECTION.size)
        if any(rest) or length == 0 or offset < toc_end or offset % SECTION_ALIGNMENT or offset + length > size:
            raise ValueError(f'section {index} has an invalid placement')
        if any(offset < end and start < offset + length for start, end in spans):
            raise ValueError(f'section {index} overlaps another section')
        spans.append((offset, offset + length))
        body = data[offset:offset + length]
        if fnv1a32(body) != digest:
            raise ValueError(f'section {index} hash mismatch')
        if kind == KIND_APP_METADATA and fmt == FORMAT_PACKAGE_METADATA_JSON and section_id == 0 and metadata is None:
            metadata = json.loads(body)
        elif kind == KIND_FONT and fmt in (FORMAT_STATIC_TTF, FORMAT_VARIABLE_TTF) and section_id and section_id not in fonts:
            fonts[section_id] = body
            formats.add(fmt)
        else:
            raise ValueError(f'section {index} is not allowed in a TTF font Component')
    if metadata is None or metadata.get('package_type') != 'component' or metadata.get('component_type') != 'font':
        raise ValueError('missing font Component metadata')
    names = metadata['font']['faces']
    ids = [fnv1a32(name.encode('ascii')) for name in names]
    variable = metadata['font']['format'] == 'ttf-variable'
    if (metadata['font']['format'] not in ('ttf', 'ttf-variable') or set(ids) != set(fonts) or len(ids) != len(fonts)
            or formats != {FORMAT_VARIABLE_TTF if variable else FORMAT_STATIC_TTF}):
        raise ValueError('declared faces do not match the FONT sections')
    faces = [(name, fonts[face_id]) for name, face_id in zip(names, ids)]
    for name, body in faces:
        _check_ttf(name, body, variable)
    return app_id, metadata, faces
