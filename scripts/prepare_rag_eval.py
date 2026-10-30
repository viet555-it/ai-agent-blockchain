"""Resolve manually curated gold evidence against an existing index, before evaluation.

Run only when deliberately creating a new benchmark version. Never derives gold
labels from retriever output. Frozen JSONL/lock are the evaluation inputs.
"""

import json
from pathlib import Path

from rag.index import IndexStore, fingerprint
from rag.loaders import content_hash


def main():
    root = Path(__file__).resolve().parents[1]
    target = root / "eval/rag_dataset.jsonl"
    lock_path = root / "eval/rag_eval_lock.json"
    if target.exists() or lock_path.exists():
        raise RuntimeError("Benchmark already frozen; create a new version explicitly instead of overwriting")
    from rag.settings import RAGSettings
    store = IndexStore(RAGSettings.load("config/rag.json", root=root).index_dir)
    active = store.active()
    data = store.collection().get(include=["documents", "metadatas"])
    catalog = {row_id: dict(content=text, metadata=json.loads(meta["record_json"]))
               for row_id, text, meta in zip(data["ids"], data["documents"], data["metadatas"], strict=False)}
    rows = []

    def add(split, category, group, query, *, signature=None, doc=None, evidence=(), scope="deployment", overrides=None, note=""):
        gold = []
        for row_id, record in catalog.items():
            meta = record["metadata"]
            if signature:
                chosen = meta["doc_id"] in {"agenttoken-sepolia-abi", "agenttoken-abi-guide"} and meta.get("function_signature") == signature
            else:
                chosen = meta["doc_id"] == doc and any(phrase in record["content"] for phrase in evidence)
            if chosen:
                gold.append(row_id)
        no_match = category in {"scope", "outside"}
        if not no_match and not gold:
            raise ValueError(f"No evidence for {group}")
        rows.append(dict(id=f"{split}-{len(rows)+1:02}", split=split, category=category, group_id=group,
                         query=query, mode=scope, scope_overrides=overrides or {}, expect_empty=no_match,
                         gold_doc_ids=sorted({catalog[i]["metadata"]["doc_id"] for i in gold}),
                         gold_chunk_ids=sorted(gold), rationale=note or ("Exact ABI interface and corresponding guide section" if signature else "Evidence phrases: " + " | ".join(evidence))))

    for split, items in {
        "dev": [("transfer", "Hàm transfer(address,uint256) nhận tham số và trả gì?", "transfer(address,uint256)"),
                ("transferfrom", "transferFrom(address,address,uint256)", "transferFrom(address,address,uint256)"),
                ("balance", "balanceOf(address)", "balanceOf(address)"),
                ("decimals", "decimals()", "decimals()"),
                ("approve", "What does approve(address,uint256) return?", "approve(address,uint256)"),
                ("validatorfrom", "validateTransferFrom(address,address,uint256,address)", "validateTransferFrom(address,address,uint256,address)")],
        "holdout": [("name", "What is the output type and mutability of name()?", "name()"),
                    ("symbol", "symbol() có nhận input không và trả kiểu gì?", "symbol()"),
                    ("owner", "ABI owner() trả về địa chỉ hay số nguyên?", "owner()"),
                    ("supply", "totalSupply() returns which ABI type?", "totalSupply()"),
                    ("cap", "cap() là view hay nonpayable trong ABI?", "cap()"),
                    ("lastclaim", "lastFaucetClaim(address) nhận input gì?", "lastFaucetClaim(address)")],
    }.items():
        for group, query, sig in items:
            add(split, "abi", group, query, signature=sig)

    web = [
        ("dev", "float", "How should I handle decimal token amounts without floats?", "web3-token-units", ["từ chối float"]),
        ("dev", "units", "Đổi 1.5 token với 6 decimals thành raw units theo ví dụ helper thế nào?", "web3-token-units", ['to_token_units("1.5", 6)']),
        ("dev", "checksum", "Checksum địa chỉ có xác nhận đúng mạng không?", "web3-addresses", ["không chứng minh địa chỉ"]),
        ("dev", "simulation", "Do I sign and broadcast during an eth_call simulation?", "web3-simulation", ["không ký hoặc broadcast"]),
        ("holdout", "native", "ETH gửi trong transaction value có cùng đơn vị với amount AGNT trong calldata không?", "web3-token-units", ["AGNT không trở thành ETH"]),
        ("holdout", "gas", "Gas limit khác maxFeePerGas và phí thực trả trong receipt thế nào?", "web3-simulation", ["Gas limit là số đơn vị"]),
        ("holdout", "zero_units", "Chuyển đổi lượng zero thành raw zero có tự chứng minh contract sẽ chấp nhận giao dịch không?", "web3-token-units", ["Chuyển đổi lượng zero"]),
        ("holdout", "caller", "When spender is provided, which from caller does the simulation helper use?", "web3-simulation", ["Nếu truyền spender"]),
    ]
    for split, group, query, doc, evidence in web:
        add(split, "web3", group, query, doc=doc, evidence=evidence)
    faucet = "agenttoken-faucet-admin-source"
    transfers = "agenttoken-transfers-source"
    source = [
        ("dev", "faucet_limit", "Theo source faucet có giới hạn bao nhiêu và chờ bao lâu?", faucet, ["không quá `FAUCET_AMOUNT_LIMIT`", "lastFaucetClaim[msg.sender] + faucetCooldown"]),
        ("dev", "self_spend", "Trong source transferFrom có cần allowance khi spender chính là sender không?", transfers, ["self-spending vẫn cần allowance"]),
        ("dev", "owner_limit", "Owner có thể đổi hạn mức chuyển token trong source không?", faucet, ["yêu cầu newLimit > 0"]),
        ("dev", "supply_cap", "Mint token vượt supply cap thì source xử lý thế nào?", faucet, ["Source khai báo cap"]),
        ("holdout", "zero_transfer", "Theo source transfer lượng zero với sender và recipient hợp lệ được test chấp nhận không?", transfers, ["Zero transfer với sender/recipient hợp lệ"]),
        ("holdout", "unlimited", "Does unlimited allowance decrease after transferFrom in the source tests?", transfers, ["unlimited allowance"]),
        ("holdout", "zero_mint", "Source mint của owner có yêu cầu amount lớn hơn zero riêng như faucet không?", faucet, ["Không có điều kiện amount > 0 riêng"]),
        ("holdout", "ownership", "Theo source chuyển ownership có tự chuyển balance ETH hoặc AGNT không?", faucet, ["không tự chuyển balance ETH"]),
    ]
    for split, group, query, doc, evidence in source:
        add(split, "source", group, query, doc=doc, evidence=evidence, scope="source")
    for split, group, query, mode, overrides in [
        ("dev", "old_address", "validateTransferFrom(address,address,uint256,address)", "deployment", {"contract_address": "0xDf7B0c367817f97d756441da6047a1Da91cC6Fff"}),
        ("dev", "other_chain", "transfer(address,uint256)", "deployment", {"chain_id": 1}),
        ("dev", "other_doc_version", "decimals()", "deployment", {"doc_version": "absent-version"}),
        ("holdout", "other_abi", "symbol()", "deployment", {"abi_hash": "sha256:" + "0" * 64}),
        ("holdout", "other_source", "mint(address,uint256)", "source", {"doc_version": "absent-source-version"}),
        ("holdout", "unknown_address", "name()", "deployment", {"contract_address": "0x1111111111111111111111111111111111111111"}),
    ]:
        add(split, "scope", group, query, scope=mode, overrides=overrides, note="No approved matching contract/source scope; general Web3 cannot supply this interface")
    for split, group, query in [
        ("dev", "cooking", "Cách nấu phở bò ngon"),
        ("dev", "weather", "What is the weather forecast for tomorrow in Hanoi?"),
        ("dev", "unknown_transfer", "transfer(bytes32,uint256)"),
        ("holdout", "biology", "Quá trình quang hợp trong lá cây diễn ra như thế nào?"),
        ("holdout", "guitar", "How do I tune a six string acoustic guitar?"),
        ("holdout", "unknown_approve", "approve(bytes32,uint256)"),
    ]:
        add(split, "outside", group, query, note="Topic or ABI overload is absent from the approved corpus")
    rows.sort(key=lambda row: (row["split"] != "dev", row["id"]))
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    gold_ids = {i for row in rows for i in row["gold_chunk_ids"]}
    gold = {i: catalog[i] for i in sorted(gold_ids)}
    gold_path = root / "eval/rag_gold_catalog.json"
    gold_path.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lock = dict(schema_version=1, dataset_hash=content_hash(target.read_text(encoding="utf-8")),
                gold_catalog_hash=content_hash(gold_path.read_text(encoding="utf-8")),
                config_hash=content_hash((root / "config/rag.json").read_text(encoding="utf-8")),
                index_fingerprint=active["fingerprint"], source_manifest_hash=active["source_manifest_hash"],
                embedding=active["embedding"], benchmark_k=5, benchmark_queries=100,
                runtime_hashes={name: content_hash((root / name).read_text(encoding="utf-8"))
                                for name in ("rag/retriever.py",
                                             *sorted(path.relative_to(root).as_posix()
                                                     for path in (root / "rag/retrieval").glob("*.py")),
                                             "eval/run_rag_eval.py")},
                policy="Freeze before dev/holdout runs. No tuning on holdout. P5/P6-exposed intents assigned to dev; curated local benchmark, not an external independent test set.")
    lock["lock_hash"] = fingerprint(lock)
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(cases=len(rows), gold_chunks=len(gold), lock_hash=lock["lock_hash"])))


if __name__ == "__main__":
    main()
