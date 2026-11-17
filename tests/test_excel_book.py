"""브라우저 엑셀 도우미가 시트를 다시 읽는지 확인한다."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "src" / "site_audit" / "static" / "xlsx.js"

NODE = r"""
const fs = require("fs");
const vm = require("vm");
const context = {
  console,
  TextEncoder,
  TextDecoder,
  Uint8Array,
  Blob,
  Response,
  CompressionStream,
  DecompressionStream,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
const xlsx = context.SiteXlsx;
const marker = "가나다 & <태그> \"인용\"\n둘째 줄";
const chunk = "원본-" + "가".repeat(25000) + "-끝";
(async () => {
  const bytes = await xlsx.writeWorkbook([
    { name: "요약", rows: [["항목", "값"], ["주소", "https://example.com/uk"]] },
    { name: "결과", rows: [["메뉴", "주소"], ["세탁기", marker]] },
    { name: "원본", rows: [["부분"], [chunk.slice(0, 20000)], [chunk.slice(20000)]] },
  ]);
  const book = await xlsx.readWorkbook(bytes);
  const result = book.sheets["결과"];
  const raw = book.sheets["원본"].slice(1).map((row) => row[0]).join("");
  if (!book.sheets["요약"]) throw new Error("요약 없음");
  if (!result || result[1][1] !== marker) throw new Error("결과 셀 불일치");
  if (raw !== chunk) throw new Error("원본 조각 불일치");
  let rejected = false;
  try {
    await xlsx.readWorkbook(new Uint8Array([1, 2, 3, 4]));
  } catch (error) {
    rejected = true;
  }
  if (!rejected) throw new Error("잘못된 파일을 통과시킴");
  const named = xlsx.fileName({
    country: "영국",
    when: "2026. 11. 16. 16시 51분 6초",
  });
  if (named !== "하위전체-검수-영국-20261116165106.xlsx") throw new Error(named);
  const colon = xlsx.fileName({
    country: "영국",
    when: "2026. 11. 16. 16:51:06",
  });
  if (colon !== "하위전체-검수-영국-20261116165106.xlsx") throw new Error(colon);
  console.log("ok");
})().catch((error) => {
  console.error(error && error.stack || error);
  process.exit(1);
});
"""


class ExcelBookTest(unittest.TestCase):
    def test_roundtrip(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node 없음")
        result = subprocess.run(
            [node, "-e", NODE, str(XLSX)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
