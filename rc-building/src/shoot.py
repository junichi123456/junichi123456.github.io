"""CG をマスター .blend から撮る（v4.33）。シーンは作り直さず、マスター（dist/export/kawazanyo_master.blend）を開いてカメラ・日付・時刻を指定して撮る。

    python3 src/shoot.py --camera Z1-11a --time 15:30 --date 03-21 --eye 1600 --out dist/render/interior/zones/
    python3 src/shoot.py --camera I01,I03 --preview          # 480×270・16spp（外観は 960×540）を .cache/cg/shoot/preview/ へ
    python3 src/shoot.py --all [--kind int|ext] [--floor 1F]   # 全カメラ（撮影済みで定義・引数が同じカットは飛ばす。--force で撮り直し）

システムの python3 が bpy の python（BPY_PYTHON、既定 .venv-bpy）を子プロセスで起動する。マスターが古い（model_hash 不一致）ときは終了コード 3
（--allow-stale で警告つきで続行）。オーバーレイ（data/blend/kawazanyo_overlay.blend の Overlay コレクション）は自動で入る（--no-overlay で外す）。
他の終了コード: 1 一部のカットが失敗、2 bpy かマスターが無い、5 カメラ名が見つからない。
"""
from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import blend_master as BM  # noqa: E402

SC = BM.SHOOT_CACHE


def parse(argv=None):
    ap = argparse.ArgumentParser(description="マスター .blend から CG を撮る")
    ap.add_argument("--camera", default="", help="カメラ名（カンマ区切り・ワイルドカード Z1-*・範囲 I04-I13）")
    ap.add_argument("--all", action="store_true", help="全カメラ")
    ap.add_argument("--kind", choices=["int", "ext"], help="--all の絞り込み")
    ap.add_argument("--floor", choices=["1F", "2F"], help="--all の絞り込み")
    ap.add_argument("--date", default="", help="MM-DD（または YYYY-MM-DD）")
    ap.add_argument("--time", default="", help="HH:MM")
    ap.add_argument("--eye", type=int, default=None, help="視点の高さ（FL+mm）。視点と注視点を同じ量だけ上下")
    ap.add_argument("--res", type=int, nargs=2, metavar=("W", "H"))
    ap.add_argument("--samples", type=int)
    ap.add_argument("--time-limit", type=int, dest="time_limit")
    ap.add_argument("--exposure", type=float, help="露出（EV）を指定値にする")
    ap.add_argument("--exposure-add", type=float, dest="exposure_add", help="カメラ既定の露出に加算")
    ap.add_argument("--channels", default="", help="点灯させる照明チャンネル（L,D,F のうち。例 L,D）")
    ap.add_argument("--dim", type=float, help="点灯チャンネルの明るさ %%")
    ap.add_argument("--screens", choices=["up", "down", "auto"], help="ZIP スクリーン（up=上げる／down=下ろす／auto=直射を受ける面だけ下ろす）。省略はカメラの属性 screens")
    ap.add_argument("--sun-k", type=int, dest="sun_k", help="太陽ランプの色温度（K）。省略はカメラの属性 sun_k（無ければ白）")
    ap.add_argument("--no-overlay", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--allow-stale", action="store_true")
    ap.add_argument("--tex-dir", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--background", action="store_true", help="nohup で実行し、進捗を .cache/cg/shoot/progress.json に書く")
    ap.add_argument("--dry-run", action="store_true", help="撮るカットの一覧を出して終わる")
    ap.add_argument("--list", action="store_true", help="マスターのカメラ一覧を出す")
    ap.add_argument("--init-overlay", action="store_true", help="オーバーレイ .blend（空の Overlay コレクション）を作る")
    return ap.parse_args(argv)


# ------------------------------------------------------------------ bpy の呼び出し
def run_bpy(cmd, job, timeout=None, log_name="inspect.log"):
    py = BM.bpy_python()
    if not py:
        print("bpy が見つかりません。README の手順で .venv-bpy を作るか、環境変数 BPY_PYTHON を指定してください")
        sys.exit(2)
    SC.mkdir(parents=True, exist_ok=True)
    jp = SC / f"job_{cmd}.json"
    jp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    with open(SC / log_name, "w", encoding="utf-8") as lf:
        return subprocess.run([py, str(ROOT / "src" / "shoot_blender.py"), cmd, str(jp)], stdout=lf, stderr=subprocess.STDOUT, timeout=timeout).returncode


def inspect(args):
    res = SC / "inspect.json"
    res.unlink(missing_ok=True)
    job = dict(master=str(BM.MASTER), overlay=str(BM.OVERLAY), no_overlay=args.no_overlay, result=str(res))
    rc = run_bpy("inspect", job)
    if rc != 0 or not res.exists():
        print("マスターを開けません。ログ:", SC / "inspect.log")
        sys.exit(2)
    return json.loads(res.read_text(encoding="utf-8"))


def init_overlay():
    py = BM.bpy_python()
    BM.OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    code = ("import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\nsc=bpy.context.scene\nc=bpy.data.collections.new('Overlay')\nsc.collection.children.link(c)\n"
            "c['note']='施主の手編集用。追加オブジェクト・追加カメラ・演出ライトをここへ入れる。マスターの要素の非表示は hide_master（GLB 名・タグの JSON リスト）。'\n"
            "bpy.context.preferences.filepaths.save_version=0\nbpy.ops.wm.save_as_mainfile(filepath=%r,compress=True)\n" % str(BM.OVERLAY))
    subprocess.run([py, "-c", code], check=True, capture_output=True)
    print("作成:", BM.OVERLAY)


# ------------------------------------------------------------------ カメラの選択と定義
def select(info, args):
    cams = {c["name"]: c for c in info["cameras"]}
    order = [c["name"] for c in info["cameras"]]
    # 並びはマスターの定義順（C・I・Z）、オーバーレイは最後
    def key(n):
        p = cams[n]["props"]
        return ({"C": 0, "I": 1, "Z": 2, "R": 3, "T": 4}.get(p.get("family"), 5), n)
    order.sort(key=key)
    names = []
    if args.all:
        names = [n for n in order if (not args.kind or cams[n]["props"].get("kind", "int") == args.kind) and (not args.floor or cams[n]["props"].get("floor") == args.floor)]
    for pat in [p for p in args.camera.split(",") if p]:
        hit = [n for n in order if n == pat or fnmatch.fnmatchcase(n, pat)]
        if not hit and "-" in pat:
            a, b = pat.split("-", 1)
            if a in cams and b in cams:
                ia, ib = order.index(a), order.index(b)
                hit = order[min(ia, ib):max(ia, ib) + 1]
        if not hit:
            print("カメラが見つかりません:", pat, "（一覧: --list）")
            sys.exit(5)
        names += [n for n in hit if n not in names]
    return [cams[n] for n in names]


def synth_spec(h, cam, fr):
    """オーバーレイで足したカメラ（属性 cut_spec が無いもの）の定義を、変換と属性から作る。建物座標 mm に戻す。"""
    import yaml
    p = cam["props"]
    X, Y, Z = cam["loc"]
    a, c, s = h.alpha, math.cos(h.alpha), math.sin(h.alpha)
    ox, oy = fr.piv

    def inv(x, y):
        dx, dy = x - ox, y - oy
        return ((dx * c + dy * s) + ox) * 1000.0, ((-dx * s + dy * c) + oy) * 1000.0
    fx, fy, fz = cam["fwd"]
    cx, cy = inv(X, Y)
    tx, ty = inv(X + fx * 3.0, Y + fy * 3.0)
    Zs = yaml.safe_load((ROOT / "data" / "interior_zones.yaml").read_text(encoding="utf-8"))["settings"]
    return dict(file=cam["name"], title=p.get("title", cam["name"]), cam=[round(cx), round(cy), round(Z * 1000)], target=[round(tx), round(ty), round((Z + fz * 3.0) * 1000)],
                lens=round(cam["lens"], 2), when=p.get("when", Zs["when"]), exposure=float(p.get("exposure", Zs["exposure"])), wb=int(p.get("wb", 5000)),
                shift_y=round(cam["shift_y"], 4), shift_x=round(cam["shift_x"], 4), screens=p.get("screens", "up"))


def cam_spec(h, fr, cam):
    p = cam["props"]
    if "cut_spec" in p:
        return json.loads(p["cut_spec"])
    return synth_spec(h, cam, fr)


def lamp_override(h, spec, args):
    import lighting as LG
    when = spec["when"]
    hour = int(when[11:13]) + int(when[14:16]) / 60.0
    chs = LG.channels(h.spec, hour, spec.get("room", ""))
    on = set(c for c in args.channels.upper().split(",") if c) if args.channels else {"L", "D", "F"}
    lights = dict(spec.get("lights", {}))
    for k, (K, pct) in chs.items():
        lights[k] = [lights.get(k, [K, pct])[0], (args.dim if args.dim is not None else lights.get(k, [K, pct])[1]) if k in on else 0]
    spec["lights"] = lights


def overrides(h, spec, kind, args):
    s = copy.deepcopy(spec)
    if args.date or args.time:
        y, rest = s["when"][:4], s["when"]
        d = args.date or s["when"][5:10]
        d = d if len(d) > 5 else f"{y}-{d}"
        t = args.time or s["when"][11:16]
        s["when"] = f"{d}T{t}"
    if args.screens:
        s["screens"] = args.screens
    if args.sun_k:
        s["sun_k"] = args.sun_k
    if args.exposure is not None:
        s["exposure"] = args.exposure
    if args.exposure_add:
        s["exposure"] = s.get("exposure", 0.0) + args.exposure_add
    if args.eye is not None and kind == "int" and not s.get("ortho_scale"):
        fl = h.fl["2F"] if s["cam"][2] > h.fl["2F"] else h.fl["1F"]
        dz = (fl + args.eye) - s["cam"][2]
        s["cam"] = [s["cam"][0], s["cam"][1], s["cam"][2] + dz]
        s["target"] = [s["target"][0], s["target"][1], s["target"][2] + dz]
    if kind == "int" and (args.channels or args.dim is not None):
        lamp_override(h, s, args)
    return s


# ------------------------------------------------------------------ 設定の組み立て
def settings_for(fam, Z, spec, args):
    st = Z["settings"]
    ic = spec["interior_cg"]
    if fam in ("R", "T"):                                   # v4.34 各室の斜めカット・天井視点（data/interior_rooms.yaml）
        import render_rooms as RR
        rs = RR.load()["settings"]
        k = "room" if fam == "R" else "plan"
        pv, base = rs[k]["preview"], dict(res=list(rs[k]["resolution"]), samples=rs[k]["samples"], tl=rs[k]["time_limit"], adapt=rs["adaptive_threshold"])
    elif fam == "Z":
        pv, base = st["preview"], dict(res=list(st["resolution"]), samples=st["samples"], tl=st["time_limit"], adapt=st["adaptive_threshold"])
    elif fam == "C":
        cg = spec["cg"]
        pv, base = dict(resolution=[960, 540], samples=16, time_limit=90), dict(res=list(cg["resolution"]), samples=cg["samples"], tl=cg["time_limit"], adapt=0.03)
    else:
        pv, base = st["preview"], dict(res=list(ic["resolution"]), samples=ic["samples"], tl=ic["time_limit"], adapt=ic["adaptive_threshold"])
    if args.preview:
        base.update(res=list(pv["resolution"]), samples=pv["samples"], tl=pv["time_limit"])
    if args.res:
        base["res"] = list(args.res)
    if args.samples:
        base["samples"] = args.samples
    if args.time_limit is not None:
        base["tl"] = args.time_limit
    return base


def interior_cfg(h, specs, base, out_dir, assets):
    import render_interior as RI
    sp = copy.deepcopy(h.spec)
    ic = sp["interior_cg"]
    ic["cuts"] = {cid: {**s, "file": cid} for cid, s in specs.items()}
    ic["resolution"], ic["samples"], ic["time_limit"], ic["adaptive_threshold"] = list(base["res"]), base["samples"], base["tl"], base["adapt"]
    ns = types.SimpleNamespace(only=None, preview=False, size=None, samples=None, scene_only=False, no_glb=True)
    cfg, its = RI.interior_cfg(h, sp, ns, assets, out_dir, BM.MASTER)
    return cfg, its


def ext_cfg(h, specs, base, out_dir, assets):
    import render_cg as RC
    sp = copy.deepcopy(h.spec)
    cuts = {}
    lat, lon, tz = sp["cg"]["site"]["lat"], sp["cg"]["site"]["lon"], sp["cg"]["site"]["tz"]
    for cid, s in specs.items():
        s = dict(s)
        s["res"], s["samples"], s["time_limit"] = list(base["res"]), base["samples"], base["tl"]
        if "kind" not in s or s.get("_time_set"):
            el, _ = RC.sun_position(s["when"], lat, lon, tz)
            s["kind"] = "day" if el > 3 else "dusk"
        s.pop("_time_set", None)
        cuts[cid] = s
    sp["cg"]["cuts"] = cuts
    ns = types.SimpleNamespace(only=None, preview=False, size=None, samples=None, scene_only=False, no_glb=True)
    cfg = RC.build_cfg(h, sp, ns, assets, out_dir)
    cfg["adaptive_threshold"] = base["adapt"]
    return cfg


# ------------------------------------------------------------------ 進捗・ログ
class Progress:
    def __init__(self, total):
        self.d = dict(pid=os.getpid(), total=total, done=0, failed=0, skipped=0, current="", started=time.strftime("%Y-%m-%dT%H:%M:%S"), updated="", finished=False)
        self.write()

    def write(self, **kw):
        self.d.update(kw)
        self.d["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        SC.mkdir(parents=True, exist_ok=True)
        (SC / "progress.json").write_text(json.dumps(self.d, ensure_ascii=False, indent=1), encoding="utf-8")


def fail_log(cid, msg):
    SC.mkdir(parents=True, exist_ok=True)
    with open(SC / "failed.log", "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\t{cid}\t{msg}\n")


def read_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default
    except ValueError:                       # Blender が raw.json を書いている途中（半端な JSON）を読んだとき。次の周期でもう一度読む
        return default


def write_json(p, d):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def args_hash(spec, base, seed, overlay_sha, preview):
    return hashlib.sha1(json.dumps([spec, base, seed, overlay_sha, preview], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


# ------------------------------------------------------------------ 本体
def main(argv=None):
    args = parse(argv)
    if args.init_overlay:
        init_overlay()
        return 0
    if not BM.MASTER.exists():
        print("マスター .blend がありません:", BM.MASTER, "\n  python3 src/build.py（または --blend-only）で生成してください")
        return 2
    if args.background:
        rest = [a for a in (argv if argv is not None else sys.argv[1:]) if a != "--background"]
        SC.mkdir(parents=True, exist_ok=True)
        lf = open(SC / "shoot.log", "a", encoding="utf-8")
        p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *rest], stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        print(f"バックグラウンドで開始（pid {p.pid}）。進捗: {SC / 'progress.json'}／ログ: {SC / 'shoot.log'}")
        return 0
    info = inspect(args)
    P = info["props"]
    cur_hash = BM.model_hash()
    stale = P.get("model_hash") != cur_hash
    if stale and not args.allow_stale:
        print(f"マスターが古い（model_hash 不一致）。python3 src/build.py --blend-only で再生成してください（--allow-stale で警告つきで続行）")
        return 3
    hand_edited = P.get("gen_signature") != P.get("gen_signature_now")
    if hand_edited:
        print("警告: マスターが手で保存し直されています（gen_signature 不一致）。次の build で上書きされます。手編集はオーバーレイへ（docs/export_howto.md）")
    if args.list:
        for c in info["cameras"]:
            p = c["props"]
            print(f"{c['name']:<10} {p.get('kind', '?'):<4} {p.get('floor', ''):<3} {p.get('when', '')}  {p.get('title', '')}{'  [overlay]' if c['overlay'] else ''}")
        return 0
    cams = select(info, args)
    if not cams:
        print("--camera か --all を指定してください")
        return 5
    import yaml
    from house import House
    import render_cg as RC
    import render_interior as RI
    import render_zones as RZ
    h = House(ROOT)
    Z = RZ.load()
    RZ._CUTS.update(Z["cuts"])
    fr = RC.Frame(h)
    master = dict(file=BM.MASTER.name, model_version=P.get("model_version"), model_hash=P.get("model_hash"), generated_at=P.get("generated_at"))
    overlay_sha = hashlib.sha1(BM.OVERLAY.read_bytes()).hexdigest()[:12] if (info["overlay"] and not args.no_overlay) else ""
    tex = BM.tex_dir(args.tex_dir)
    tex_def = {**h.spec["cg"]["textures"], **h.spec["interior_cg"]["textures"]}
    assets = RC.fetch_assets({"cg": {"textures": tex_def, "hdri": h.spec["cg"]["hdri"]}}, tex, use_textures=True)
    # ---- カットごとの定義
    plan = {}
    defs_z = RZ.cut_defs(h, Z)
    for cam in cams:
        p = cam["props"]
        fam = p.get("family") or "X"
        kind = p.get("kind", "int")
        spec = overrides(h, cam_spec(h, fr, cam), kind, args)
        if args.date or args.time:
            spec["_time_set"] = True
        base = settings_for(fam if fam != "X" else "I", Z, h.spec, args)
        plan[cam["name"]] = dict(cam=cam, fam=fam, kind=kind, spec=spec, base=base, def_hash=p.get("def_hash", ""), ah=args_hash(spec, base, args.seed, overlay_sha, args.preview))
    # ---- 出力先・スキップ
    out_root = Path(args.out) if args.out else None
    odir = {"C": out_root or ROOT / "dist" / "render", "I": out_root or ROOT / "dist" / "render" / "interior", "X": out_root or ROOT / "dist" / "render" / "interior",
            "Z": out_root or ROOT / "dist" / "render" / "interior" / "zones", "R": out_root or ROOT / "dist" / "render" / "interior", "T": out_root or ROOT / "dist" / "render" / "interior"}
    if args.preview:
        odir = {k: SC / "preview" for k in odir}
    if args.out and not args.preview:
        RZ.OUT = Path(args.out)
    logs = {}

    def lg(fam):
        key = "Z" if fam == "Z" else "CI"
        if key not in logs:
            if fam == "Z":
                logs[key] = RZ.read_log() if not args.preview else dict(cuts={})
            else:
                logs[key] = {}
        return logs[key]

    def lp(fam):
        return odir[fam] / ("render_log_zones.json" if fam == "Z" else "render_log.json")

    def final_path(cid, pl):
        if pl["fam"] == "Z":
            return odir["Z"] / RZ.jpg_name(cid, Z["cuts"][cid]) if not args.preview else odir["Z"] / f"{cid}.jpg"
        return odir[pl["fam"]] / (pl["spec"]["file"] + ".png")

    def entry_of(cid, pl):
        if pl["fam"] == "Z":
            return lg("Z")["cuts"].get(cid)
        f = lp(pl["fam"])
        d = logs.setdefault(("log", str(f)), read_json(f, dict(cuts=[])))
        return next((c for c in d.get("cuts", []) if c.get("id") == cid), None)

    want = dict(def_hash=None, model_hash=P.get("model_hash"))
    todo, skipped = [], []
    for cid, pl in plan.items():
        e = entry_of(cid, pl) if not args.preview else None
        sk = (e or {}).get("shoot") or {}
        legacy_ok = (pl["fam"] == "Z" and e and not sk and e.get("def_hash") == pl["def_hash"] and not (args.date or args.time or args.eye is not None or args.exposure is not None
                     or args.exposure_add or args.channels or args.dim is not None or args.res or args.samples or args.time_limit is not None) and e.get("status") in ("ok", "flag"))
        if legacy_ok and not args.force and not args.preview and final_path(cid, pl).exists():
            skipped.append(cid)
        elif not args.force and not args.preview and e and sk.get("def_hash") == pl["def_hash"] and sk.get("model_hash") == want["model_hash"] and sk.get("args_hash") == pl["ah"] \
                and final_path(cid, pl).exists() and e.get("status", "ok") in ("ok", "flag"):
            skipped.append(cid)
        else:
            todo.append(cid)
    print(f"対象 {len(plan)} カット、撮るのは {len(todo)} カット（撮影済み・同条件のため飛ばす {len(skipped)}）")
    if args.dry_run:
        print("撮る:", ",".join(todo) or "なし", "／飛ばす:", ",".join(skipped) or "なし")
        return 0
    prog = Progress(len(todo))
    prog.write(skipped=len(skipped))
    if not todo:
        prog.write(finished=True)
        return 0
    # ---- 事前検査と設定ファイル（family ごと）
    work = SC / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    its = None
    fails = []
    cfgs, meta = [], {}
    import furniture
    its = furniture.items(h)
    for fam in ("C", "I", "X", "Z", "R", "T"):
        ids = [c for c in todo if plan[c]["fam"] == fam]
        if not ids:
            continue
        base = plan[ids[0]]["base"]
        if fam == "C":
            cfg = ext_cfg(h, {c: plan[c]["spec"] for c in ids}, base, work / "png_C", assets)
        else:
            cfg, _ = interior_cfg(h, {c: plan[c]["spec"] for c in ids}, base, work / f"png_{fam}", assets)
            clear = RI.camera_clearance(h, its, cfg["cuts"])
            bad = [c for c in ids if clear[c]["mm"] < 150 and fam != "T"]          # T は天井面に立つ正投影（離隔は対象外）
            for c in bad:
                fails.append(c)
                fail_log(c, f"カメラが壁・家具に近すぎます（{clear[c]['mm']}mm < 150）")
            cfg["cuts"] = [c for c in cfg["cuts"] if c["id"] not in bad]
            meta[fam] = dict(clear=clear)
            if fam == "Z":
                d2 = {c: copy.deepcopy(defs_z[c]) for c in ids}
                for c in ids:
                    d2[c]["spec"] = {**plan[c]["spec"], "file": c}
                pre = RZ.pre_checks(h, its, {**defs_z, **d2}, Z)
                for c in ids:
                    if pre[c]["errors"] and c not in fails:
                        fails.append(c)
                        fail_log(c, "検査に不適合: " + ";".join(pre[c]["errors"]))
                cfg["cuts"] = [c for c in cfg["cuts"] if c["id"] not in fails]
                meta[fam].update(defs=d2, pre=pre)
        cfg["_fam"] = fam
        cp = work / f"cfg_{fam}.json"
        write_json(cp, cfg)
        cfgs.append(dict(family=fam, cfg=str(cp)))
        meta.setdefault(fam, {})["cfg"] = cfg
    todo = [c for c in todo if c not in fails]
    prog.write(failed=len(fails))
    # ---- 撮影（マスターを 1 回開く）
    raw_path = work / "raw.json"
    job = dict(master=str(BM.MASTER), overlay=str(BM.OVERLAY), no_overlay=args.no_overlay, tex_dir=str(tex), cfgs=cfgs, raw_log=str(raw_path), seed=args.seed)
    py = BM.bpy_python()
    SC.mkdir(parents=True, exist_ok=True)
    (work / "job_shoot.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    t_start = time.time()
    done = set()
    with open(SC / "blender.log", "w", encoding="utf-8") as bl:
        proc = subprocess.Popen([py, str(ROOT / "src" / "shoot_blender.py"), "shoot", str(work / "job_shoot.json")], stdout=bl, stderr=subprocess.STDOUT)
        while True:
            alive = proc.poll() is None
            raw = read_json(raw_path, None)
            if raw:
                for r in raw["cuts"]:
                    cid = r["id"]
                    if cid in done:
                        continue
                    done.add(cid)
                    try:
                        finish(h, Z, RZ, RC, RI, plan[cid], r, raw, meta, odir, args, master, hand_edited, stale, P, lg, lp, logs, final_path(cid, plan[cid]), cid)
                        prog.write(done=len(done), current=cid)
                        print(f"done {cid} ({r['render_seconds']} s)", flush=True)
                    except Exception as e:                      # noqa: BLE001
                        import traceback
                        traceback.print_exc()
                        fails.append(cid)
                        fail_log(cid, f"後処理に失敗: {type(e).__name__}: {e}")
            if not alive:
                break
            time.sleep(2)
    raw = read_json(raw_path, dict(cuts=[], failed=[]))
    for f in raw.get("failed", []):
        fails.append(f["id"])
        fail_log(f["id"], f["error"])
    for c in todo:
        if c not in done and c not in fails:
            fails.append(c)
            fail_log(c, f"Blender 終了コード {proc.returncode}・画像なし")
    flush_logs(h, RZ, args, logs, lg, lp, odir, master, raw, plan, meta, time.time() - t_start)
    prog.write(failed=len(fails), finished=True, current="")
    print(f"完了: 撮影 {len(done)}・飛ばし {len(skipped)}・失敗 {len(fails)}（{round(time.time() - t_start)} 秒）。失敗の記録: {SC / 'failed.log'}")
    return 1 if fails else 0


def pv_log(d, cid, e):
    p = Path(d) / "preview_log.json"
    lg_ = read_json(p, {})
    lg_[cid] = e
    write_json(p, lg_)


def finish(h, Z, RZ, RC, RI, pl, r, raw, meta, odir, args, master, hand_edited, stale, P, lg, lp, logs, fpath, cid):
    """1 カットの後処理（検査・注記の帯・保存・ログ）。"""
    fam = pl["fam"]
    cfg = meta[fam]["cfg"]
    cut = next(c for c in cfg["cuts"] if c["id"] == cid)
    shoot = dict(def_hash=pl["def_hash"], model_hash=P.get("model_hash"), args_hash=pl["ah"], seed=args.seed)
    flags = []
    if stale:
        flags.append("stale_master")
    if hand_edited:
        flags.append("master_hand_edited")
    pal_mm = []
    if fam != "C":
        mc = raw.get("material_colors", {})
        for k, v in cfg["interior"]["palette"].items():
            if k in mc and any(abs(a - b) > 0.002 for a, b in zip(mc[k], v["rgb"])):
                pal_mm.append(k)
    raw_png = Path(r["file"])
    fpath.parent.mkdir(parents=True, exist_ok=True)
    if fam == "Z":
        d = meta["Z"]["defs"][cid]
        cut["_palette_mismatch"] = pal_mm
        r["channels"] = cut["ch"]
        e = RZ.finish_cut(h, Z, meta["Z"]["defs"], cid, r, cut, meta["Z"]["clear"][cid], meta["Z"]["pre"][cid], raw, False) if not args.preview else None
        if args.preview:
            RZ.band_image(raw_png, d, dict(channels=cut["ch"]), Z, fpath, Z["settings"]["jpeg_quality"], Z["settings"]["band_px"])
            pv_log(fpath.parent, cid, dict(palette_mismatch=pal_mm, flags=flags, render_seconds=r["render_seconds"], channels=cut["ch"]))
            return
        else:
            shutil.copy(RZ.jpg_path(cid), fpath) if RZ.jpg_path(cid) != fpath else None
        e.update(master=master, shoot=shoot, shoot_flags=flags, texture_fallbacks=r.get("texture_fallbacks", []), palette_mismatch=pal_mm)
        if not args.preview:
            L = lg("Z")
            L["cuts"][cid] = e
        return
    shutil.copy(raw_png, fpath)
    RC.post_process(str(fpath))
    r = dict(r)
    r["file"] = str(fpath)
    if fam in ("I", "X") and not args.preview:
        ic = h.spec["interior_cg"]
        if ic.get("annotation_band", 0):
            RI.annotate(str(fpath), cut, h.spec, ic["annotation_band"], RI.accent_note(h, cut))
    r.setdefault("time_limit", cut["time_limit"])
    r["time_limit_hit"] = r["render_seconds"] >= r["time_limit"] - 3
    r["when"] = pl["spec"]["when"]
    r.update(id=cid, status="ok", master=master, shoot=shoot, shoot_flags=flags, palette_mismatch=pal_mm)
    if args.preview:
        pv_log(fpath.parent, cid, dict(palette_mismatch=pal_mm, flags=flags, render_seconds=r["render_seconds"], channels=cut.get("ch")))
        return
    f = lp(fam)
    d = logs.setdefault(("log", str(f)), read_json(f, dict(cuts=[])))
    d["cuts"] = [c for c in d.get("cuts", []) if c.get("id") != cid] + [r]


def flush_logs(h, RZ, args, logs, lg, lp, odir, master, raw, plan, meta, secs):
    if args.preview:
        return
    for key, d in list(logs.items()):
        if isinstance(key, tuple):
            d["master"] = master
            d["last_shoot"] = dict(at=time.strftime("%Y-%m-%dT%H:%M:%S"), seconds=round(secs, 1), seed=args.seed, material_colors_checked=len(raw.get("material_colors", {})))
            d["texture_missing"] = raw.get("texture_missing", [])
            order = [c for c in list(h.spec["cg"]["cuts"]) + list(h.spec["interior_cg"]["cuts"])]
            d["cuts"] = sorted(d["cuts"], key=lambda c: order.index(c["id"]) if c.get("id") in order else 99)
            write_json(key[1], d)
    if "Z" in logs:
        L = logs["Z"]
        L["master"] = master
        L["version"] = "v4.30"
        RZ.write_log(L)


if __name__ == "__main__":
    sys.exit(main())
