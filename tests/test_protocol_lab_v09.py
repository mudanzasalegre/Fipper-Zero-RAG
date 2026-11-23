"""Protocol Lab v0.9: structural correctness and non-disclosure regressions."""
from __future__ import annotations

from pathlib import Path
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from flipper_rag.protocol_lab import (FORMATS, MAX_BYTES, analyze_text, analyze_bytes, analyze_file,
                                       analyze_directory, compare_results, privacy_summary, render_report)
from flipper_rag.lab_cli import add_parser, run, _write_report
from flipper_rag.lab_api import attach_lab

SUB = """Filetype: Flipper SubGhz Key File
Version: 1
Frequency: 433920000
Preset: FuriHalSubGhzPresetOok650Async
Protocol: Princeton
Bit: 24
Key: AA BB CC DD EE FF 11 22
TE: 400
"""
RAW = """Filetype: Flipper SubGhz RAW File
Version: 1
Frequency: 433920000
Preset: FuriHalSubGhzPresetOok650Async
Protocol: RAW
RAW_Data: 10 -20 30 -40
RAW_Data: 50 -60
"""
NFC = """Filetype: Flipper NFC device
Version: 4
Device type: ISO14443-3A
UID: 04 48 6A 32 33 58 80
ATQA: 00 44
SAK: 00
"""
RFID = """Filetype: Flipper RFID key
Version: 1
Key type: EM4100
Data: 01 23 45 67 89
"""
IBTN = """Filetype: Flipper iButton key
Version: 2
Protocol: DS1990
Rom Data: 08 DE AD BE EF FA CE 4E
"""
IR = """Filetype: IR signals file
Version: 1
#
name: Button_1
type: parsed
protocol: NECext
address: EE 87 00 00
command: 5D A0 00 00
#
name: Button_2
type: raw
frequency: 38000
duty_cycle: 0.33
data: 500 3432 500 485
"""
FAM = """App(
    appid="hello_world",
    apptype=FlipperAppType.EXTERNAL,
    entry_point="hello_app",
    fap_category="Examples",
)
"""
PROTO = '''syntax = "proto3";
package flipper;
message Demo { string name = 1; uint32 count = 2; }
service Example { rpc Ping(Demo) returns (Demo); }
'''


@pytest.mark.parametrize("filename,body,expected", [
    ("foo.sub", SUB, "valid"), ("foo.sub", RAW, "valid"),
    ("foo.nfc", NFC, "valid"), ("foo.rfid", RFID, "valid"),
    ("foo.ir", IR, "valid"), ("foo.ibtn", IBTN, "valid"),
    ("application.fam", FAM, "valid"), ("rpc.proto", PROTO, "valid"),
])
def test_valid_formats(filename, body, expected):
    result = analyze_text(body,filename=filename)
    assert result["status"] == expected, result["findings"]
    assert result["official_reference"].startswith("https://")
    assert result["source"].startswith("archivo ")
    assert result["schema_version"] == 1


def test_redacts_sub_keys_uid_and_ir_commands():
    for filename,body,secret in [
        ("a.sub",SUB,"AA BB CC DD EE FF 11 22"),
        ("a.nfc",NFC,"04 48 6A 32 33 58 80"),
        ("a.ir",IR,"EE 87 00 00"),
        ("a.rfid",RFID,"01 23 45 67 89"),
        ("a.ibtn",IBTN,"08 DE AD BE EF FA CE 4E"),
    ]:
        result=analyze_text(body,filename=filename)
        assert secret not in json.dumps(result)
        assert secret not in privacy_summary(result)
        for kind in ("markdown","json","html"):
            assert secret not in render_report(result,output=kind)


def test_raw_timings_and_out_of_order_polarity():
    r=analyze_text(RAW,filename="test.sub")
    assert r["counts"]["raw_intervals"] == 6
    assert r["counts"]["raw_lines"] == 2
    bad=analyze_text(RAW.replace("-20", "0"), filename="test.sub")
    assert any(x["code"] == "RAW_PULSE_INVALID" for x in bad["findings"])
    assert bad["status"] == "invalid"
    anomaly=analyze_text(RAW.replace("-20","20"),filename="test.sub")
    assert "RAW_POLARITY" in {x["code"] for x in anomaly["findings"]}


def test_binraw_blocks():
    text=SUB.replace("Protocol: Princeton\nBit: 24\nKey: AA BB CC DD EE FF 11 22\nTE: 400", "Protocol: BinRAW\nBit: 16\nTE: 200\nBit_RAW: 16\nData_RAW: FF 00")
    r=analyze_text(text,filename="x.sub")
    assert r["status"] == "valid",r
    assert r["counts"]["binraw_blocks"] == 1
    failed=analyze_text(text.replace("Bit_RAW: 16","Bit_RAW: 32"),filename="x.sub")
    assert "BINRAW_LENGTH" in {f["code"] for f in failed["findings"]}


def test_sub_presets_and_unknown_protocols_are_conservative():
    bad=analyze_text(SUB.replace("FuriHalSubGhzPresetOok650Async","unknown_preset"),filename="x.sub")
    assert "PRESET_UNVERIFIED" in {f["code"] for f in bad["findings"]}
    raw_secret="VERYSECRETLEAK999"
    r=analyze_text(SUB.replace("Princeton",raw_secret),filename="x.sub")
    assert raw_secret not in json.dumps(r)
    assert "SUB_PROTOCOL_UNVERIFIED" in {f["code"] for f in r["findings"]}


def test_nfc_lengths_and_non_whitelisted_type():
    bad=analyze_text(NFC.replace("04 48 6A 32 33 58 80", "04 48 6A"),filename="nfc.nfc")
    assert bad["status"]=="invalid"
    assert "NFC_UID_LENGTH" in {f["code"] for f in bad["findings"]}
    unknown=analyze_text(NFC.replace("ISO14443-3A", "MY_SECRET_NUMBER"),filename="nfc.nfc")
    assert "MY_SECRET_NUMBER" not in json.dumps(unknown)
    assert "NFC_DEVICE_UNVERIFIED" in {f["code"] for f in unknown["findings"]}


def test_rfid_hex_and_unknown_id_redaction():
    bad=analyze_text(RFID.replace("01 23 45 67 89", "01 Z2"),filename="test.rfid")
    assert bad["status"] == "invalid"
    unknown=analyze_text(RFID.replace("EM4100", "MY_PRIVATE_ID_123"),filename="test.rfid")
    assert "MY_PRIVATE_ID_123" not in json.dumps(unknown)


def test_ibutton_v1_deprecated_and_dallas_rom_size():
    v1="Filetype: Flipper iButton key\nVersion: 1\nKey type: Dallas\nData: AA BB\n"
    r=analyze_text(v1,filename="a.ibtn")
    assert r["status"]=="warnings"
    assert "IBTN_LEGACY" in {x["code"] for x in r["findings"]}
    bad=analyze_text(IBTN.replace("08 DE AD BE EF FA CE 4E", "AA BB"),filename="x.ibtn")
    assert "HEX_LENGTH" in {x["code"] for x in bad["findings"]}


def test_infrared_multiples_and_irtest():
    r=analyze_text(IR,filename="r.ir")
    assert r["counts"]["signals"] == 2
    assert r["counts"]["parsed_signals"] == 1
    assert r["counts"]["raw_signals"] == 1
    irtest="Filetype: IR test file\nVersion: 1\nname: decoder_expected1\ntype: parsed_array\ncount: 1\nprotocol: NEC\naddress: 00 00 00 00\ncommand: 01 00 00 00\n"
    assert analyze_text(irtest,filename="fixture.irtest")["status"]=="valid"
    bad=analyze_text(IR.replace("duty_cycle: 0.33", "duty_cycle: 1.5"),filename="r.ir")
    assert "IR_DUTY" in {x["code"] for x in bad["findings"]}


def test_manifest_is_ast_only_and_never_executes(tmp_path):
    marker=tmp_path/"executed"
    script=f'__import__("pathlib").Path("{marker}").touch()\n'+FAM
    r=analyze_text(script,filename="application.fam")
    assert "FAM_EXECUTABLE" in {x["code"] for x in r["findings"]}
    assert not marker.exists()
    assert str(marker) not in json.dumps(r)
    ext=analyze_text(FAM.replace('fap_category="Examples",','fap_extbuild=("echo RISKY",),'),filename="a.fam")
    assert "FAM_EXTERNAL_BUILD" in {x["code"] for x in ext["findings"]}


def test_proto_valid_and_malformed():
    good=analyze_text(PROTO,filename="x.proto")
    assert good["metadata"]["syntax"] == "proto3"
    assert good["counts"]["messages"] == 1
    wrong=analyze_text(PROTO.replace("}","",1),filename="x.proto")
    assert wrong["status"] == "invalid"


def test_badusb_only_explicit_and_no_script_execution():
    text="STRING SECRET_PASS_123\nDELAY 300\n"
    with pytest.raises(ValueError):analyze_text(text,filename="a.txt")
    r=analyze_text(text,filename="a.txt",file_format="badusb")
    assert r["counts"]["commands"] == 2
    assert "SECRET_PASS_123" not in json.dumps(r)


@pytest.mark.parametrize("data,kwargs", [
    (b"\x00binary",{}), (b"\xff\xfe",{}),
    (b"a"*(MAX_BYTES+1),{}),
])
def test_invalid_input_bytes(data,kwargs):
    with pytest.raises(ValueError):analyze_bytes(data,filename="x.nfc",**kwargs)


def test_unknown_format_and_empty_file():
    with pytest.raises(ValueError):analyze_text("abc", filename="a.bat")
    r=analyze_text("",filename="b.ir")
    assert r["status"] == "invalid"
    assert r["findings"][0]["code"] == "EMPTY_FILE"


def test_batch_and_symlink_skip(tmp_path):
    (tmp_path/"a.sub").write_text(SUB)
    (tmp_path/"b.nfc").write_text(NFC)
    (tmp_path/"not-supported.txt").write_text("random")
    (tmp_path/"link.sub").symlink_to(tmp_path/"a.sub")
    result=analyze_directory(tmp_path)
    assert len(result) == 2
    assert len(analyze_directory(tmp_path,limit=1)) == 1
    with pytest.raises(ValueError):analyze_file(tmp_path/"link.sub")


def test_comparison_never_exposes_payload_changes():
    first=analyze_text(SUB,filename="f.sub")
    last=analyze_text(SUB.replace("AA BB CC DD EE FF 11 22","AA BB CC DD 00 00 00 00"),filename="f.sub")
    result=compare_results(first,last)
    assert result["metadata_changes"]=={}
    assert "AA BB" not in json.dumps(result)


def test_render_markdown_html_and_reference():
    r=analyze_text(NFC,filename="n.nfc")
    md=render_report(r,output="markdown")
    assert "## Diagnósticos" in md
    assert "https://developer.flipper.net" in md
    html=render_report(r,output="html")
    assert "Content-Security-Policy" in html
    assert "<pre>" in html
    assert "04 48 6A" not in html
    with pytest.raises(ValueError):render_report(r,output="pdf")


def test_render_html_escapes_injected_caller_values():
    r=analyze_text("",filename="foo.sub")
    r["findings"][0]["message"]='<img src=x onerror=alert(1)>'
    assert '<img src=x' not in render_report(r,output="html")


def test_write_report_never_overwrites_input(tmp_path):
    p=tmp_path/"a.ir";p.write_text(IR)
    with pytest.raises(ValueError):_write_report(p,"hello",[p])
    out=tmp_path/"report.md";out.write_text("existing")
    with pytest.raises(ValueError):_write_report(out,"hello",[p])
    _write_report(out,"new",[p],overwrite=True)
    assert out.read_text()=="new"


def test_cli_analyze_and_compare(tmp_path,capsys):
    import argparse
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="command",required=True);add_parser(sub)
    a=tmp_path/"a.sub";a.write_text(SUB)
    b=tmp_path/"b.sub";b.write_text(RAW)
    args=p.parse_args(["lab","analyze","--file",str(a)])
    assert run(args)==0
    assert json.loads(capsys.readouterr().out)["status"] == "valid"
    args=p.parse_args(["lab","compare","--before",str(a),"--after",str(b)])
    assert run(args)==0
    comparison=json.loads(capsys.readouterr().out)
    assert comparison["metadata_changes"]["protocol"]["after"] == "RAW"
    args=p.parse_args(["lab","batch","--directory",str(tmp_path)])
    assert run(args)==0
    assert json.loads(capsys.readouterr().out)["files_analyzed"]==2


def test_api_endpoints_are_bounded_and_do_not_echo_secrets():
    app=FastAPI();attach_lab(app)
    client=TestClient(app)
    formats=client.get("/api/lab/formats")
    assert formats.status_code==200 and "nfc" in formats.json()["formats"]
    assert "Protocol Lab" in client.get("/lab").text
    body={"filename":"foo.nfc","content":NFC}
    resp=client.post("/api/lab/analyze",json=body)
    assert resp.status_code==200 and resp.json()["status"] == "valid"
    assert "04 48 6A" not in resp.text
    report=client.post("/api/lab/report",json={**body,"output":"markdown"})
    assert report.status_code==200
    assert "04 48 6A" not in report.text
    assert client.post("/api/lab/analyze",json={"filename":"secret.bat","content":"foo"}).status_code==422
    assert client.post("/api/lab/analyze",json={"filename":"x.sub","content":"a"*(MAX_BYTES+1)}).status_code==422


def test_redacted_summary_is_safe_to_index():
    r=analyze_text(NFC,filename="raw.nfc")
    txt=privacy_summary(r)
    assert "UID:" not in txt
    assert "04 48 6A" not in txt
    assert "ISO14443" in txt


def test_proto_duplicate_fields_rejected():
    bad='syntax = "proto3";\nmessage X {\n  string alpha = 1;\n  string beta = 1;\n}\n'
    result=analyze_text(bad,filename="example.proto")
    assert result["status"] == "invalid"
    assert "PROTO_DUPLICATE_TAG" in {x["code"] for x in result["findings"]}


def test_proto_reserved_field_number_rejected():
    bad='syntax = "proto3";\nmessage X {\n  uint32 foo = 19000;\n}\n'
    result=analyze_text(bad,filename="example.proto")
    assert "PROTO_FIELD_NUMBER" in {x["code"] for x in result["findings"]}


def test_explicit_indexing_only_writes_redacted_content(tmp_path,capsys):
    import argparse
    from flipper_rag.storage import Store
    from flipper_rag.config import Settings
    from flipper_rag.models import Embedder
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="command",required=True);add_parser(sub)
    f=tmp_path/"secret-card.nfc";f.write_text(NFC)
    store=Store(tmp_path/"test.sqlite3")
    settings=Settings(db_path=store.path,embed_provider="none",chat_provider="none",ann_enabled=False)
    embedder=Embedder(settings)
    assert store.stats()["documents"] == 0
    args=p.parse_args(["lab","analyze","--file",str(f),"--index-redacted"])
    assert run(args,store,embedder)==0
    rendered=capsys.readouterr().out
    assert "04 48 6A 32" not in rendered
    assert "secret-card.nfc" not in rendered
    assert store.stats()["documents"] == 1
    with store.connect() as con:
        chunks=con.execute("SELECT content FROM chunks").fetchall()
        assert chunks
        assert all("04 48 6A" not in r[0] and "secret-card" not in r[0] for r in chunks)


def test_cli_and_real_api_integration(tmp_path,capsys,monkeypatch):
    from flipper_rag.cli import main
    main(["lab","formats"])
    assert "infrared" in capsys.readouterr().out.lower()
    from flipper_rag.api import app
    c=TestClient(app)
    assert c.get("/api/lab/formats").status_code == 200
    assert c.get("/lab").status_code == 200


def test_batch_and_comparison_html_export_never_show_secret():
    from flipper_rag.protocol_lab import render_batch_report, render_comparison
    before=analyze_text(SUB,filename="secret.sub")
    after=analyze_text(SUB.replace("Princeton","RAW").replace("Key: AA BB CC DD EE FF 11 22","RAW_Data: 10 -20"),filename="secret.sub")
    batch={"schema_version":1,"files_analyzed":2,"totals":{"valid":1,"warnings":1,"invalid":0},"reports":[before,after]}
    for func,obj in ((render_batch_report,batch),(render_comparison,compare_results(before,after))):
        md=func(obj,output="markdown")
        html=func(obj,output="html")
        assert "#" in md and "Content-Security-Policy" in html
        for sensitive in ("AA BB CC", "secret.sub"):
            assert sensitive not in md and sensitive not in html
