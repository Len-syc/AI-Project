"""ingest CLI：把爬取数据转换为领域知识包。
用法示例见 app/ingest/README.md。"""
import argparse
import json
import sys

from app import config
from app.ingest import get_converter
from app.ingest.base import validate_policy
from app.tools.registry import get_domain


def iter_raw(path: str):
    with open(path, encoding="utf-8") as f:
        first = f.read(1)
        f.seek(0)
        if first == "[":                       # JSON 数组
            for item in json.load(f):
                yield item
        else:                                  # JSONL
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def main():
    ap = argparse.ArgumentParser(description="爬取数据 → 领域知识包")
    ap.add_argument("--raw", required=True, help="爬取数据文件（.json 数组或 .jsonl）")
    ap.add_argument("--domain", required=True, help="目标领域包 id（app/domains/ 下）")
    ap.add_argument("--converter", default="llm_guide", help="转换器名")
    ap.add_argument("--dry-run", action="store_true", help="只校验不写入")
    args = ap.parse_args()

    pack = get_domain(args.domain)
    if pack is None:
        sys.exit(f"领域包 {args.domain} 不存在（app/domains/ 下现有: "
                 f"{list(__import__('app.tools.registry', fromlist=['load_domains']).load_domains())}）")
    converter_cls = get_converter(args.converter)
    converter = converter_cls()

    policy_path = f"{config.DOMAINS_DIR}/{args.domain}/policies.json"
    with open(policy_path, encoding="utf-8") as f:
        doc = json.load(f)
    existing_ids = {p["id"] for p in doc["policies"]}

    ok, updated, skipped = 0, 0, 0
    for i, raw in enumerate(iter_raw(args.raw), 1):
        rid = raw.get("id") or f"auto-{i}"
        try:
            data = converter.convert(raw)
        except Exception as e:
            print(f"[跳过] {rid}: 转换失败 {e}")
            skipped += 1
            continue
        if not data:
            print(f"[跳过] {rid}: 转换器返回空")
            skipped += 1
            continue
        data["id"] = data.get("id") or rid
        policy, err = validate_policy(data)
        if policy is None:
            print(f"[拒绝] {data['id']}: {err}")
            skipped += 1
            continue
        if policy.id in existing_ids:
            doc["policies"] = [p for p in doc["policies"] if p["id"] != policy.id]
            updated += 1
        else:
            ok += 1
        doc["policies"].append(policy.model_dump())
        print(f"[通过] {policy.id}: {policy.name}")

    if args.dry_run:
        print(f"\ndry-run：新增 {ok}，更新 {updated}，跳过/拒绝 {skipped}，未写入文件")
        return
    doc["policies"].sort(key=lambda p: p["id"])
    with open(policy_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"\n完成：新增 {ok}，更新 {updated}，跳过/拒绝 {skipped} → {policy_path}")


if __name__ == "__main__":
    main()
