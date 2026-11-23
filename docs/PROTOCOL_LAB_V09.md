# Flipper Zero RAG v0.9 — Protocol Lab

> **Read-only/offline, privacy-by-default.** This is a static structural/documentary checker, not a decoder, key recovery tool, firmware compatibility oracle, RF transmitter, hardware controller, or security assessment of a physical system.

## Scope and motivation

The preceding releases provide a protocol ontology (v0.6), versioned firmware graph (v0.7), and development assistant (v0.8). **v0.9 adds local file-format diagnostics** to distinguish malformed headers, missing fields, inconsistent lengths, and structural warnings from assumed firmware support. Reports contain only a conservative allowlist of metadata and diagnostic codes, not captured values.

### Supported formats and reviewed specifications

| Format | Core checks | Source |
| --- | --- | --- |
| `.sub` | Key, RAW, BinRAW; Flipper File Format headers, versions, Hz, presets, RAW duration grammar, BinRAW byte counts | [SubGhz format](https://developer.flipper.net/flipperzero/doxygen/subghz_file_format.html) |
| `.nfc` | Filetype/version, device type, UID hex length where documented, ATQA/SAK lengths | [NFC format](https://developer.flipper.net/flipperzero/doxygen/nfc_file_format.html) |
| `.rfid` | Key type, Data hex, format version | [LF RFID format](https://developer.flipper.net/flipperzero/doxygen/lfrfid_file_format.html) |
| `.ir` | Multiple remote buttons, parsed/raw, supported IR protocol names, frequency/duty cycle, maximum 1024 raw timings | [Infrared format](https://developer.flipper.net/flipperzero/doxygen/infrared_file_format.html) |
| `.irtest` | Test fixture arrays (`parsed_array`/`raw`), element count and timing structure | [Infrared test fixtures](https://developer.flipper.net/flipperzero/doxygen/infrared_file_format.html) |
| `.ibtn` | v1/v2, Dallas ROM (8-byte) and protocol-dependent SRAM/EEPROM/Data | [iButton format](https://developer.flipper.net/flipperzero/doxygen/ibutton_file_format.html) |
| `.fam` | Parse-only AST, literal appid and apptype, explicit warning for external build commands; **never run** Python manifest | [Flipper App Manifest](https://developer.flipper.net/flipperzero/doxygen/app_manifests.html) |
| `.proto` | Basic syntax and brace integrity, message/service/enum counts; NOT a replacement for protoc | [Protocol Buffers specification](https://protobuf.dev/programming-guides/proto3/) |
| `.txt` (BadUSB, explicit `--type badusb`) | Only a deliberately shallow static command/delay audit; no script execution or emulation | [BadUSB format](https://developer.flipper.net/flipperzero/doxygen/badusb_file_format.html) |

**Important:** The source format documentation is updated over time. Rules in this release reflect the cited public documentation inspected on 23 November 2026; older and newer community firmware can extend these formats. `VERSION_UNVERIFIED` is a warning, **not a claim that a file cannot load**. A structurally valid file is not evidence of a compatible device, decodable transmission, legitimate access, or an authorized operation.

## Offline workflow

Install using the repository's existing prerequisites (`pip install -e '.[dev]'`). These commands do **not** need Ollama, an API key, network access, a Flipper device, or write access to the firmware:

```bash
# Available rules and references
flipper-rag lab formats

# Inspect a single file (prints sanitized JSON by default)
flipper-rag lab analyze --file examples/protocol_lab/demo-ir.ir

# Save sanitized reports in Markdown or HTML
flipper-rag lab analyze --file examples/protocol_lab/demo-nfc.nfc --report markdown --output data/nfc-report.md
flipper-rag lab analyze --file examples/protocol_lab/demo-ir.ir --report html --output data/ir-report.html

# Inspect up to 200 files without following symlinks
flipper-rag lab batch --directory examples/protocol_lab --output data/lab-batch.json

# Compare *structure*, not UID/key/data values
flipper-rag lab compare --before examples/protocol_lab/demo-ir.ir --after examples/protocol_lab/demo-ir.ir

# Explicitly index a REDACTED summary in local RAG (optional)
flipper-rag lab analyze --file examples/protocol_lab/demo-sub.sub --index-redacted

# Analyze BadUSB text only when explicitly selected (not by ordinary .txt extension)
flipper-rag lab analyze --file my-script.txt --type badusb
```

A report destination is never overwritten by default. `--overwrite` is available for an existing report file; **the original input file cannot be overwritten**. `lab analyze` returns exit code `2` for invalid input or structural errors and `0` otherwise. In `batch` it returns `2` if at least one inspected file is invalid. HTML reports are standalone (no JavaScript), with a restrictive Content Security Policy.

### Web UI and API

Run with the normal localhost-first command:

```bash
uvicorn flipper_rag.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/lab`. Choose an input and its format, inspect error codes, then download a JSON, Markdown or HTML report. **The browser sends the selected text to that same local server, not to third-party services.** The server does not save the text unless you separately invoke the CLI indexing option. Do not deploy the API on the public internet without authentication/TLS, request-size controls and authorization.

Read-only endpoints:

- `GET /api/lab/formats` — supported formats with official references.
- `POST /api/lab/analyze` — `{ "filename":"capture.nfc", "content":"...", "file_format":null }`; returns structural findings without original payloads.
- `POST /api/lab/report` — same input with `"output":"markdown"|"html"|"json"`; returns a redacted string and MIME type.

The API never accepts a server filesystem path, and the analyzer never executes scripts, launches subcommands, connects to hardware, queries upstream sites or tries to decrypt content.

## Diagnostics and privacy guarantees

A finding contains `code`, `severity` (`error`/`warning`/`info`), `line`, a fixed explanation and optional remediation; it does not contain input values. Examples: `FIELD_REQUIRED`, `HEX_INVALID`, `NFC_UID_LENGTH`, `RAW_PULSE_INVALID`, `BINRAW_LENGTH`, `IR_DUTY`, `FAM_EXECUTABLE`, `VERSION_UNVERIFIED`.

Output schema version **1** includes `format`, `status` (`valid`, `warnings`, `invalid`), safe structural `metadata`, aggregated `counts`, `findings`, `official_reference`, and disclaimers. A file's original name and absolute path are **not** included. UID, key bytes, NFC blocks, card sectors, IR commands, addresses, ROM/EEPROM data, raw timings, Sub-GHz `Key`, BadUSB `STRING` values, and arbitrary manifest contents remain excluded from API/CLI reports.

The optional `--index-redacted` path indexes only `privacy_summary(result)` as a local source `protocol-lab-redacted` and classifies it as `trust=local` and `firmware_channel=unversioned`; it does not claim official verification or release compatibility. **Do not** ingest raw credential/capture files directly through general-purpose text import paths.

## Security limits

- Max 2,000,000 bytes per file and 30,000 lines, with limits on parsed fields; batch defaults to at most 200 files. UTF-8 text only; binary/NUL input is rejected. Symbolic links are not followed.
- This is **not a cryptographic validator** and cannot prove whether an observed signal, tag, or key is genuine, recover hidden information or determine whether a physical device will work.
- Sub-GHz frequency checks check broad numeric plausibility only; they are NOT a region-specific legality table or permission to transmit.
- `.fam` is parsed using Python's AST without `eval`/`exec`; dangerous embedded build commands are flagged but are never run.
- `.proto` checking is deliberately limited; use the official `protoc` compiler to validate imported schema semantics, options and nested types.
- Report generation escapes HTML. All data from an examined file is untrusted, and reports should never be treated as instructions for an LLM to obey.
- Fixture files in `examples/protocol_lab` are purely synthetic and must not be used as real signals or credentials.

## Verification

```bash
python -m pytest -q tests/test_protocol_lab_v09.py
python -m compileall -q src
flipper-rag lab analyze --file examples/protocol_lab/demo-ir.ir
flipper-rag lab batch --directory examples/protocol_lab
```

The test suite covers versioned headers, all supported formats, malformed data, zero execution, hidden payloads, batch limits, symlinks, redacted reports, CLI commands and HTTP endpoints. No device/emulation/firmware integration tests are claimed by this module. It intentionally remains independent of proprietary datasets and sensitive capture samples.
