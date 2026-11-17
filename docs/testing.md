# Testing Guide

<!-- 새 프로젝트: 테스트 구조·스크립트를 분석한 뒤 채운다. 추측으로 완성하지 않는다. -->

## Test Strategy

<!-- TODO: 단위/통합/E2E 중 무엇을 쓰는지, 언제 어떤 테스트를 쓰는지 -->

## Test Structure

<!-- TODO: 소스 인접(*.test.ts)인지 tests/ 분리인지, 주요 경로 -->

## Running Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

단위 테스트는 `tests/test_audit.py`, `tests/test_fetch.py`, `tests/test_excel_book.py`. 네트워크 없이 주소 거부, 하위 페이지, 깨진 이미지, UFN 기준 없음, 호스트 호출 간격과 차단 중단, 엑셀 시트 왕복을 확인한다.

## Unit Tests

<!-- TODO: 작성 위치, 네이밍, 권장 패턴 -->

## Integration Tests

<!-- TODO: 범위, 환경(DB/컨테이너 등), 작성 방법 -->

## E2E Tests

<!-- TODO: 있으면 도구·실행 방법. 없으면 "없음" -->

## Test Data

<!-- TODO: fixture, mock, seed 사용법 -->

## Coverage

<!-- TODO: coverage 기준이 있으면 기입. 없으면 "강제 기준 없음" -->
