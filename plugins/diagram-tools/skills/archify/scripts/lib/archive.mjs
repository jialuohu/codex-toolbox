import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { inflateRawSync } from 'node:zlib';
import { assertContained } from './paths.mjs';

const EOCD_SIGNATURE = 0x06054b50;
const CENTRAL_SIGNATURE = 0x02014b50;
const LOCAL_SIGNATURE = 0x04034b50;
const MAX_COMMENT_BYTES = 0xffff;
const UNIX_DIRECTORY = 0o040000;
const UNIX_REGULAR = 0o100000;

const CRC_TABLE = Array.from({ length: 256 }, (_, index) => {
  let value = index;
  for (let bit = 0; bit < 8; bit += 1) {
    value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : (value >>> 1);
  }
  return value >>> 0;
});

export function crc32(buffer) {
  let value = 0xffffffff;
  for (const byte of buffer) value = CRC_TABLE[(value ^ byte) & 0xff] ^ (value >>> 8);
  return (value ^ 0xffffffff) >>> 0;
}

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

function findEndRecord(buffer) {
  const earliest = Math.max(0, buffer.length - 22 - MAX_COMMENT_BYTES);
  for (let offset = buffer.length - 22; offset >= earliest; offset -= 1) {
    if (buffer.readUInt32LE(offset) !== EOCD_SIGNATURE) continue;
    const commentLength = buffer.readUInt16LE(offset + 20);
    if (offset + 22 + commentLength === buffer.length) return offset;
  }
  throw new Error('ZIP archive has no valid end-of-central-directory record');
}

function decodeName(bytes, flags) {
  if ((flags & 0x0800) === 0 && [...bytes].some((byte) => byte < 0x20 || byte > 0x7e)) {
    throw new Error('ZIP entry names must be UTF-8 or printable ASCII');
  }
  const name = bytes.toString('utf8');
  if (name.includes('\ufffd') || Buffer.from(name, 'utf8').compare(bytes) !== 0) {
    throw new Error('ZIP entry has an invalid UTF-8 name');
  }
  return name;
}

function safeArchivePath(name, directory) {
  if (!name || name.includes('\0') || /[\x00-\x1f\x7f]/.test(name)) {
    throw new Error('ZIP entry has an empty or control-character path');
  }
  if (name.includes('\\')) throw new Error(`ZIP entry uses an ambiguous backslash path: ${name}`);
  if (name.startsWith('/') || /^[A-Za-z]:/.test(name)) {
    throw new Error(`ZIP entry uses an absolute path: ${name}`);
  }
  if (name !== name.normalize('NFC')) throw new Error(`ZIP entry path is not NFC-normalized: ${name}`);
  const parts = name.split('/');
  if (directory && parts.at(-1) === '') parts.pop();
  if (parts.some((part) => !part || part === '.' || part === '..')) {
    throw new Error(`ZIP entry has an unsafe path segment: ${name}`);
  }
  if (parts[0] !== 'archify' || parts.length < 2) {
    throw new Error(`ZIP entry is outside the archify package root: ${name}`);
  }
  return parts.slice(1).join('/');
}

function entryKind(versionMadeBy, externalAttributes, name) {
  const creator = versionMadeBy >>> 8;
  const unixMode = (externalAttributes >>> 16) & 0xffff;
  const unixType = unixMode & 0o170000;
  const slashDirectory = name.endsWith('/');
  const dosDirectory = (externalAttributes & 0x10) !== 0;
  if (creator === 3 && unixType !== 0) {
    if (unixType === UNIX_DIRECTORY) {
      if (!slashDirectory) throw new Error(`ZIP directory lacks a trailing slash: ${name}`);
      return 'directory';
    }
    if (unixType !== UNIX_REGULAR) throw new Error(`ZIP entry is not a regular file: ${name}`);
    if (slashDirectory) throw new Error(`ZIP regular file has a directory path: ${name}`);
    return 'file';
  }
  if (slashDirectory || dosDirectory) {
    if (!slashDirectory) throw new Error(`ZIP directory lacks a trailing slash: ${name}`);
    return 'directory';
  }
  return 'file';
}

function treeDigest(files) {
  const hash = createHash('sha256');
  for (const file of files) {
    hash.update(file.path);
    hash.update('\0');
    hash.update(String(file.bytes));
    hash.update('\0');
    hash.update(file.sha256);
    hash.update('\n');
  }
  return hash.digest('hex');
}

export function inspectZipArchive(buffer, limits) {
  if (!Buffer.isBuffer(buffer)) throw new Error('ZIP archive must be a Buffer');
  if (buffer.length > limits.maxBytes) throw new Error('ZIP archive exceeds the compressed-size limit');
  const end = findEndRecord(buffer);
  const disk = buffer.readUInt16LE(end + 4);
  const centralDisk = buffer.readUInt16LE(end + 6);
  const entriesOnDisk = buffer.readUInt16LE(end + 8);
  const entryCount = buffer.readUInt16LE(end + 10);
  const centralSize = buffer.readUInt32LE(end + 12);
  const centralOffset = buffer.readUInt32LE(end + 16);
  if (disk !== 0 || centralDisk !== 0 || entriesOnDisk !== entryCount) {
    throw new Error('Multi-disk ZIP archives are not supported');
  }
  if (entryCount === 0 || entryCount > limits.maxEntries) {
    throw new Error('ZIP archive has an invalid number of entries');
  }
  if (centralOffset === 0xffffffff || centralSize === 0xffffffff || centralOffset + centralSize !== end) {
    throw new Error('ZIP64, overlapping, or trailing central directories are not supported');
  }

  const entries = [];
  const paths = new Set();
  const foldedPaths = new Set();
  const localOffsets = new Set();
  let cursor = centralOffset;
  let expandedBytes = 0;
  for (let index = 0; index < entryCount; index += 1) {
    if (cursor + 46 > end || buffer.readUInt32LE(cursor) !== CENTRAL_SIGNATURE) {
      throw new Error('ZIP central directory is malformed');
    }
    const versionMadeBy = buffer.readUInt16LE(cursor + 4);
    const flags = buffer.readUInt16LE(cursor + 8);
    const method = buffer.readUInt16LE(cursor + 10);
    const expectedCrc = buffer.readUInt32LE(cursor + 16);
    const compressedBytes = buffer.readUInt32LE(cursor + 20);
    const expanded = buffer.readUInt32LE(cursor + 24);
    const nameLength = buffer.readUInt16LE(cursor + 28);
    const extraLength = buffer.readUInt16LE(cursor + 30);
    const commentLength = buffer.readUInt16LE(cursor + 32);
    const entryDisk = buffer.readUInt16LE(cursor + 34);
    const externalAttributes = buffer.readUInt32LE(cursor + 38);
    const localOffset = buffer.readUInt32LE(cursor + 42);
    const recordEnd = cursor + 46 + nameLength + extraLength + commentLength;
    if (recordEnd > end || [compressedBytes, expanded, localOffset].includes(0xffffffff)) {
      throw new Error('ZIP central entry is truncated or uses ZIP64');
    }
    if (entryDisk !== 0 || (flags & ~0x0800) !== 0 || ![0, 8].includes(method)) {
      throw new Error('ZIP entry is encrypted or uses unsupported flags or compression');
    }
    const nameBytes = buffer.subarray(cursor + 46, cursor + 46 + nameLength);
    const name = decodeName(nameBytes, flags);
    const kind = entryKind(versionMadeBy, externalAttributes, name);
    const path = safeArchivePath(name, kind === 'directory');
    const folded = path.toLocaleLowerCase('en-US');
    if (paths.has(path) || foldedPaths.has(folded)) {
      throw new Error(`ZIP archive has a duplicate or case-colliding path: ${path}`);
    }
    paths.add(path);
    foldedPaths.add(folded);
    if (localOffsets.has(localOffset)) throw new Error('ZIP entries reuse a local record');
    localOffsets.add(localOffset);

    if (localOffset + 30 > centralOffset || buffer.readUInt32LE(localOffset) !== LOCAL_SIGNATURE) {
      throw new Error(`ZIP local entry is malformed: ${name}`);
    }
    const localFlags = buffer.readUInt16LE(localOffset + 6);
    const localMethod = buffer.readUInt16LE(localOffset + 8);
    const localCrc = buffer.readUInt32LE(localOffset + 14);
    const localCompressedBytes = buffer.readUInt32LE(localOffset + 18);
    const localExpandedBytes = buffer.readUInt32LE(localOffset + 22);
    const localNameLength = buffer.readUInt16LE(localOffset + 26);
    const localExtraLength = buffer.readUInt16LE(localOffset + 28);
    const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
    if (
      localFlags !== flags ||
      localMethod !== method ||
      localCrc !== expectedCrc ||
      localCompressedBytes !== compressedBytes ||
      localExpandedBytes !== expanded ||
      dataOffset + compressedBytes > centralOffset ||
      buffer.subarray(localOffset + 30, localOffset + 30 + localNameLength).compare(nameBytes) !== 0
    ) {
      throw new Error(`ZIP local and central entries disagree: ${name}`);
    }
    if (kind === 'directory' && (compressedBytes !== 0 || expanded !== 0)) {
      throw new Error(`ZIP directory contains data: ${name}`);
    }
    if (method === 0 && compressedBytes !== expanded) {
      throw new Error(`Stored ZIP entry has inconsistent sizes: ${name}`);
    }
    if (expanded > limits.maxExpandedBytes) throw new Error(`ZIP entry is too large: ${name}`);
    expandedBytes += expanded;
    if (expandedBytes > limits.maxExpandedBytes) throw new Error('ZIP archive exceeds the expansion limit');
    entries.push({
      kind,
      name,
      path,
      method,
      expectedCrc,
      compressedBytes,
      expandedBytes: expanded,
      localOffset,
      dataOffset,
    });
    cursor = recordEnd;
  }
  if (cursor !== end) throw new Error('ZIP central directory entry count is inconsistent');
  const localRanges = entries
    .map((entry) => ({ start: entry.localOffset, end: entry.dataOffset + entry.compressedBytes }))
    .sort((left, right) => left.start - right.start);
  for (let index = 1; index < localRanges.length; index += 1) {
    if (localRanges[index].start < localRanges[index - 1].end) {
      throw new Error('ZIP local entries overlap');
    }
  }
  return { entries, expandedBytes };
}

export async function extractZipArchive(buffer, destination, limits) {
  const inspected = inspectZipArchive(buffer, limits);
  const files = [];
  for (const entry of inspected.entries) {
    const output = assertContained(destination, join(destination, ...entry.path.split('/')));
    if (entry.kind === 'directory') {
      await mkdir(output, { recursive: true, mode: 0o755 });
      continue;
    }
    const compressed = buffer.subarray(entry.dataOffset, entry.dataOffset + entry.compressedBytes);
    const contents = entry.method === 0
      ? Buffer.from(compressed)
      : inflateRawSync(compressed, { maxOutputLength: entry.expandedBytes + 1 });
    if (contents.length !== entry.expandedBytes) throw new Error(`ZIP entry size is wrong: ${entry.name}`);
    if (crc32(contents) !== entry.expectedCrc) throw new Error(`ZIP entry CRC is wrong: ${entry.name}`);
    await mkdir(join(output, '..'), { recursive: true, mode: 0o755 });
    await writeFile(output, contents, { mode: 0o644, flag: 'wx' });
    files.push({ path: entry.path, bytes: contents.length, sha256: sha256(contents) });
  }
  files.sort((left, right) => left.path.localeCompare(right.path, 'en'));
  return {
    fileCount: files.length,
    expandedBytes: files.reduce((sum, file) => sum + file.bytes, 0),
    treeSha256: treeDigest(files),
  };
}

export { treeDigest };
