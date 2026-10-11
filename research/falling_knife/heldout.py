"""Score FROZEN.json (v1) on its held-out years. Kept to reproduce the v1 results, including the crypto failure."""

import json

from knife import Rule, evaluate, line
from sweep_all import load_class

F = json.load(open("FROZEN.json"))
out = {}
for kind in ("crypto", "equity", "fx"):
    cfg = F[kind]
    data, c = load_class(kind)
    if kind == "equity":
        data = {k: v for k, v in data.items() if k not in ("SPY", "QQQ", "IWM")}
    rule = Rule(K=cfg["K"], N=cfg["N"], Z=cfg["Z"], still=cfg["still"], dmin=cfg["dmin"])
    for name, lo, hi in (("dev", None, c["split"]), ("HELD-OUT", c["split"], None)):
        s, fires_ = evaluate(data, rule, cfg["H"], cfg["severe"], t0=lo, t1=hi)
        caught = s["fire"]["p_severe"] * s["fire"]["n"]
        nsev = s["all"]["p_severe"] * s["all"]["n"]
        print(line(f"{kind:<6} {name:<8}", s) + f"  recall {caught / nsev * 100:4.1f}%")
        out[f"{kind}_{name}"] = {"summary": s, "fires": fires_}
json.dump(out, open("heldout_results.json", "w"), default=str)
