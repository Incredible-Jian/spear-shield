"""独立抓取进程；stdout只输出JSON，绝不写数据库。GUI可强制终止超时任务。"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys

from ..config.symbols import CORE_ETFS, TRACKING_INDICES


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol")
    parser.add_argument("start")
    parser.add_argument("end")
    parser.add_argument("adjust", choices=("qfq", "none"))
    parser.add_argument("provider", choices=("akshare", "sina"))
    args = parser.parse_args()
    symbols = {s.code: s for s in (*CORE_ETFS, *TRACKING_INDICES)}
    if args.symbol not in symbols:
        parser.error("不支持的核心标的")
    try:
        with contextlib.redirect_stdout(sys.stderr):
            # 日志handler在导入时绑定流，因此也必须在重定向内部导入。
            from .akshare_provider import AkShareProvider
            from .sina_provider import SinaProvider

            provider = (
                AkShareProvider() if args.provider == "akshare" else SinaProvider()
            )
            df = provider.fetch_daily(
                symbols[args.symbol], args.start, args.end, args.adjust
            )
        print(
            json.dumps(
                {
                    "source": provider.name,
                    "data": json.loads(df.to_json(orient="records", date_format="iso")),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
