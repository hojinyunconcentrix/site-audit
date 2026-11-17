/* 브라우저에서 .xlsx를 만들고 읽는다. 추가 라이브러리는 쓰지 않는다. */
(function (root) {
  const CRC_TABLE = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let crc = n;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1;
    }
    CRC_TABLE[n] = crc >>> 0;
  }

  function crc32(bytes) {
    let crc = 0xffffffff;
    for (let i = 0; i < bytes.length; i += 1) {
      crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
    }
    return (crc ^ 0xffffffff) >>> 0;
  }

  function concat(parts) {
    const size = parts.reduce((sum, part) => sum + part.length, 0);
    const out = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) {
      out.set(part, offset);
      offset += part.length;
    }
    return out;
  }

  function u16(value) {
    return Uint8Array.of(value & 255, (value >> 8) & 255);
  }

  function u32(value) {
    return Uint8Array.of(
      value & 255,
      (value >> 8) & 255,
      (value >> 16) & 255,
      (value >> 24) & 255,
    );
  }

  function readU16(bytes, offset) {
    return bytes[offset] | (bytes[offset + 1] << 8);
  }

  function readU32(bytes, offset) {
    return (
      (bytes[offset] |
        (bytes[offset + 1] << 8) |
        (bytes[offset + 2] << 16) |
        (bytes[offset + 3] << 24)) >>>
      0
    );
  }

  async function deflateRaw(bytes) {
    if (typeof CompressionStream !== "function") return null;
    const stream = new Blob([bytes])
      .stream()
      .pipeThrough(new CompressionStream("deflate-raw"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  async function inflateRaw(bytes) {
    if (typeof DecompressionStream !== "function") {
      throw new Error("이 브라우저에서는 압축된 엑셀을 열 수 없습니다.");
    }
    const stream = new Blob([bytes])
      .stream()
      .pipeThrough(new DecompressionStream("deflate-raw"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  function xmlText(value) {
    return String(value)
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function colName(index) {
    let n = index + 1;
    let name = "";
    while (n > 0) {
      const rem = (n - 1) % 26;
      name = String.fromCharCode(65 + rem) + name;
      n = Math.floor((n - 1) / 26);
    }
    return name;
  }

  function colIndex(ref) {
    const letters = String(ref || "").replace(/[^A-Za-z]/g, "").toUpperCase();
    let n = 0;
    for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64);
    return n - 1;
  }

  function sheetXml(rows) {
    const body = [];
    rows.forEach((row, rowIndex) => {
      const cells = [];
      row.forEach((value, column) => {
        if (value === null || value === undefined || value === "") return;
        const ref = `${colName(column)}${rowIndex + 1}`;
        if (typeof value === "number" && Number.isFinite(value)) {
          cells.push(`<c r="${ref}"><v>${value}</v></c>`);
          return;
        }
        cells.push(
          `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xmlText(value)}</t></is></c>`,
        );
      });
      body.push(`<row r="${rowIndex + 1}">${cells.join("")}</row>`);
    });
    return (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
      `<sheetData>${body.join("")}</sheetData></worksheet>`
    );
  }

  function workbookXml(names) {
    const sheets = names
      .map(
        (name, index) =>
          `<sheet name="${xmlText(name)}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`,
      )
      .join("");
    return (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
      `<sheets>${sheets}</sheets></workbook>`
    );
  }

  function workbookRels(count) {
    const rows = [];
    for (let index = 0; index < count; index += 1) {
      rows.push(
        `<Relationship Id="rId${index + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${index + 1}.xml"/>`,
      );
    }
    return (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      `${rows.join("")}</Relationships>`
    );
  }

  const CONTENT_TYPES =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
    '<Default Extension="xml" ContentType="application/xml"/>' +
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
    "</Types>";

  function contentTypes(count) {
    const overrides = [];
    for (let index = 0; index < count; index += 1) {
      overrides.push(
        `<Override PartName="/xl/worksheets/sheet${index + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`,
      );
    }
    return CONTENT_TYPES.replace("</Types>", `${overrides.join("")}</Types>`);
  }

  const ROOT_RELS =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
    "</Relationships>";

  async function zipStore(files) {
    const encoder = new TextEncoder();
    const locals = [];
    const centrals = [];
    let offset = 0;
    for (const file of files) {
      const name = encoder.encode(file.name);
      const raw = file.data;
      const compressed = await deflateRaw(raw);
      const method = compressed && compressed.length < raw.length ? 8 : 0;
      const data = method === 8 ? compressed : raw;
      const crc = crc32(raw);
      const local = concat([
        u32(0x04034b50),
        u16(20),
        u16(0x0800),
        u16(method),
        u16(0),
        u16(0),
        u32(crc),
        u32(data.length),
        u32(raw.length),
        u16(name.length),
        u16(0),
        name,
        data,
      ]);
      const central = concat([
        u32(0x02014b50),
        u16(20),
        u16(20),
        u16(0x0800),
        u16(method),
        u16(0),
        u16(0),
        u32(crc),
        u32(data.length),
        u32(raw.length),
        u16(name.length),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(0),
        u32(offset),
        name,
      ]);
      locals.push(local);
      centrals.push(central);
      offset += local.length;
    }
    const centralDir = concat(centrals);
    const end = concat([
      u32(0x06054b50),
      u16(0),
      u16(0),
      u16(files.length),
      u16(files.length),
      u32(centralDir.length),
      u32(offset),
      u16(0),
    ]);
    return concat([...locals, centralDir, end]);
  }

  function encodeXml(text) {
    return new TextEncoder().encode(text);
  }

  async function writeWorkbook(sheets) {
    const files = [
      { name: "[Content_Types].xml", data: encodeXml(contentTypes(sheets.length)) },
      { name: "_rels/.rels", data: encodeXml(ROOT_RELS) },
      {
        name: "xl/workbook.xml",
        data: encodeXml(workbookXml(sheets.map((sheet) => sheet.name))),
      },
      {
        name: "xl/_rels/workbook.xml.rels",
        data: encodeXml(workbookRels(sheets.length)),
      },
    ];
    sheets.forEach((sheet, index) => {
      files.push({
        name: `xl/worksheets/sheet${index + 1}.xml`,
        data: encodeXml(sheetXml(sheet.rows)),
      });
    });
    return zipStore(files);
  }

  function findEocd(bytes) {
    const start = Math.max(0, bytes.length - 22 - 65535);
    for (let offset = bytes.length - 22; offset >= start; offset -= 1) {
      if (readU32(bytes, offset) === 0x06054b50) return offset;
    }
    throw new Error("엑셀 파일이 아닙니다.");
  }

  async function unzip(bytes) {
    const eocd = findEocd(bytes);
    const count = readU16(bytes, eocd + 10);
    let cursor = readU32(bytes, eocd + 16);
    const decoder = new TextDecoder("utf-8");
    const files = new Map();
    for (let index = 0; index < count; index += 1) {
      if (readU32(bytes, cursor) !== 0x02014b50) {
        throw new Error("엑셀 파일을 읽지 못했습니다.");
      }
      const method = readU16(bytes, cursor + 10);
      const compressedSize = readU32(bytes, cursor + 20);
      const nameLength = readU16(bytes, cursor + 28);
      const extraLength = readU16(bytes, cursor + 30);
      const commentLength = readU16(bytes, cursor + 32);
      const localOffset = readU32(bytes, cursor + 42);
      const name = decoder.decode(
        bytes.subarray(cursor + 46, cursor + 46 + nameLength),
      );
      const localNameLength = readU16(bytes, localOffset + 26);
      const localExtraLength = readU16(bytes, localOffset + 28);
      const dataStart = localOffset + 30 + localNameLength + localExtraLength;
      const compressed = bytes.subarray(dataStart, dataStart + compressedSize);
      let data;
      if (method === 0) data = compressed;
      else if (method === 8) data = await inflateRaw(compressed);
      else throw new Error("이 엑셀 압축은 열 수 없습니다.");
      files.set(name.replace(/\\/g, "/"), data);
      cursor += 46 + nameLength + extraLength + commentLength;
    }
    return files;
  }

  function decodeXml(text) {
    return text
      .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
      .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) =>
        String.fromCodePoint(parseInt(hex, 16)),
      )
      .replace(/&#(\d+);/g, (_, num) => String.fromCodePoint(Number(num)))
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&apos;/g, "'")
      .replace(/&amp;/g, "&");
  }

  function innerText(xml) {
    const withoutPhonetic = xml.replace(/<rPh\b[^>]*>[\s\S]*?<\/rPh>/g, "");
    const parts = [];
    const pattern = /<t\b[^>]*>([\s\S]*?)<\/t>/g;
    let match = pattern.exec(withoutPhonetic);
    while (match) {
      parts.push(decodeXml(match[1]));
      match = pattern.exec(withoutPhonetic);
    }
    return parts.join("");
  }

  function sharedStrings(xml) {
    const values = [];
    const pattern = /<si\b[^>]*>([\s\S]*?)<\/si>/g;
    let match = pattern.exec(xml);
    while (match) {
      values.push(innerText(match[1]));
      match = pattern.exec(xml);
    }
    return values;
  }

  function sheetRows(xml, strings) {
    const rows = [];
    const rowPattern = /<row\b[^>]*>([\s\S]*?)<\/row>/g;
    let rowMatch = rowPattern.exec(xml);
    while (rowMatch) {
      const row = [];
      const cellPattern = /<c\b([^>]*)(?:\/>|>([\s\S]*?)<\/c>)/g;
      let cellMatch = cellPattern.exec(rowMatch[1]);
      while (cellMatch) {
        const attrs = cellMatch[1];
        const body = cellMatch[2] || "";
        const ref = (attrs.match(/\br="([^"]+)"/) || [])[1] || "";
        const kind = (attrs.match(/\bt="([^"]+)"/) || [])[1] || "";
        const index = colIndex(ref);
        let value = "";
        if (kind === "inlineStr") value = innerText(body);
        else if (kind === "s") {
          const pointer = Number((body.match(/<v>([\s\S]*?)<\/v>/) || [])[1]);
          value = strings[pointer] || "";
        } else {
          const raw = (body.match(/<v>([\s\S]*?)<\/v>/) || [])[1];
          value = raw === undefined ? innerText(body) : decodeXml(raw);
        }
        if (index >= 0) {
          while (row.length <= index) row.push("");
          row[index] = value;
        }
        cellMatch = cellPattern.exec(rowMatch[1]);
      }
      rows.push(row);
      rowMatch = rowPattern.exec(xml);
    }
    return rows;
  }

  function attr(tag, name) {
    const match = tag.match(new RegExp(`\\b${name}="([^"]*)"`));
    return match ? decodeXml(match[1]) : "";
  }

  async function readWorkbook(bytes) {
    const files = await unzip(bytes);
    const decoder = new TextDecoder("utf-8");
    const workbook = decoder.decode(files.get("xl/workbook.xml") || new Uint8Array());
    const rels = decoder.decode(
      files.get("xl/_rels/workbook.xml.rels") || new Uint8Array(),
    );
    const targets = new Map();
    const relPattern = /<Relationship\b[^>]*>/g;
    let rel = relPattern.exec(rels);
    while (rel) {
      const id = attr(rel[0], "Id");
      const target = attr(rel[0], "Target").replace(/^\//, "");
      const path = target.startsWith("xl/") ? target : `xl/${target}`;
      targets.set(id, path);
      rel = relPattern.exec(rels);
    }
    const stringsFile = files.get("xl/sharedStrings.xml");
    const strings = stringsFile
      ? sharedStrings(decoder.decode(stringsFile))
      : [];
    const sheets = {};
    const sheetPattern = /<sheet\b[^>]*>/g;
    let sheet = sheetPattern.exec(workbook);
    while (sheet) {
      const name = attr(sheet[0], "name");
      const id = attr(sheet[0], "r:id") || attr(sheet[0], "id");
      const path = targets.get(id);
      const file = path ? files.get(path) : null;
      sheets[name] = file ? sheetRows(decoder.decode(file), strings) : [];
      sheet = sheetPattern.exec(workbook);
    }
    return { sheets };
  }

  function fileName(record) {
    const country =
      String((record && record.country) || "나라없음")
        .replace(/[\\/:*?"<>|]+/g, "")
        .trim() || "나라없음";
    const parts = String((record && record.when) || "").match(/\d+/g) || [];
    const pad = (value) => String(value).padStart(2, "0");
    let stamp;
    if (parts.length >= 5) {
      const year = parts[0];
      const month = pad(parts[1]);
      const day = pad(parts[2]);
      const hour = pad(parts[3]);
      const minute = pad(parts[4]);
      const second = pad(parts[5] || "0");
      stamp = `${year}${month}${day}${hour}${minute}${second}`;
    } else {
      const now = new Date();
      stamp =
        String(now.getFullYear()) +
        pad(now.getMonth() + 1) +
        pad(now.getDate()) +
        pad(now.getHours()) +
        pad(now.getMinutes()) +
        pad(now.getSeconds());
    }
    return `하위전체-검수-${country}-${stamp}.xlsx`;
  }

  root.SiteXlsx = { writeWorkbook, readWorkbook, fileName };
})(typeof globalThis !== "undefined" ? globalThis : window);
