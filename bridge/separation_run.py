# SPDX-License-Identifier: GPL-3.0-or-later
"""L'exécuteur de la séparation (docs/separation.md §5) — lancé en PROCESSUS SÉPARÉ, jamais dans le bridge.

Un crash du runtime n'emporte pas le rack, on l'annule en le tuant, et sa priorité se baisse sans toucher au bridge.
Le même chemin pour tout fichier ONNX qui respecte le contrat (§3) : rien ici ne connaît un moteur.

    python -m bridge.separation_run inspect <model.onnx>        → JSON {meta, inputs, outputs} sur stdout
    python -m bridge.separation_run run <spec.json>             → stems dans spec.outdir, progression dans spec.workdir

spec = {model, input (PCM float32 stéréo entrelacé, 44,1 kHz), n (échantillons par canal), outdir, workdir, threads}.
Chaque segment fait est gardé dans `workdir` : un job tué reprend au premier segment manquant (§5).
Sorties : `<stem>.f32` (même format que l'entrée), `result.json` {stems, load_s, compute_s, segments}.
Code de retour : 0 ok, 2 contrat non respecté, 3 NaN/Inf, 1 autre erreur — la raison dans `error.json`."""
import json
import os
import sys
import time

CONTRACT = "1"


class ContractError(Exception):
    pass


class NanError(Exception):
    pass


def _session(model, threads):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = max(1, int(threads or 1))
    so.inter_op_num_threads = 1
    so.log_severity_level = 3
    return ort.InferenceSession(model, so, providers=["CPUExecutionProvider"])


def describe(sess):
    """Ce que le fichier DIT de lui : métadonnées golem.*, entrée, sorties. Lu, jamais déclaré ailleurs."""
    meta = dict(sess.get_modelmeta().custom_metadata_map or {})
    ins = [{"name": i.name, "shape": [d if isinstance(d, int) else None for d in i.shape], "type": i.type}
           for i in sess.get_inputs()]
    outs = [{"name": o.name, "shape": [d if isinstance(d, int) else None for d in o.shape], "type": o.type}
            for o in sess.get_outputs()]
    return {"meta": meta, "inputs": ins, "outputs": outs}


def check_contract(d):
    """§3 : une entrée float32 [1,2,segment], des sorties float32 [1,2,segment], les métadonnées obligatoires.
    Rend (sample_rate, segment, overlap, noms des sorties). Lève ContractError avec une raison lisible (anglais)."""
    m = d["meta"]
    if m.get("golem.contract") != CONTRACT:
        raise ContractError("golem.contract must be \"%s\"" % CONTRACT)
    try:
        sr, seg = int(m["golem.sample_rate"]), int(m["golem.segment"])
    except (KeyError, ValueError):
        raise ContractError("golem.sample_rate and golem.segment are required (integers)")
    if sr <= 0 or seg < 1024:
        raise ContractError("golem.segment must be at least 1024 samples")
    ov = int(m.get("golem.overlap") or seg // 4)
    if not 0 <= ov < seg // 2 + 1:
        raise ContractError("golem.overlap must be between 0 and half a segment")
    if len(d["inputs"]) != 1:
        raise ContractError("the model must have exactly one input")
    i = d["inputs"][0]
    if i["type"] != "tensor(float)" or len(i["shape"]) != 3 or i["shape"][1] not in (2, None):
        raise ContractError("the input must be float32 [1, 2, segment]")
    if i["shape"][2] not in (seg, None):
        raise ContractError("the input length must equal golem.segment")
    names = []
    for o in d["outputs"]:
        if o["type"] != "tensor(float)" or len(o["shape"]) != 3:
            raise ContractError("every output must be float32 [1, 2, segment]")
        names.append(o["name"])
    return sr, seg, ov, names


def _fade(seg, ov):
    import numpy as np
    w = np.ones(seg, np.float32)
    if ov:
        r = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, ov, dtype=np.float32))).astype(np.float32)
        w[:ov] = r
        w[-ov:] = r[::-1]
    return w


def run(spec):
    import numpy as np
    t0 = time.monotonic()
    sess = _session(spec["model"], spec.get("threads"))
    sr, seg, ov, names = check_contract(describe(sess))
    if sr != int(spec.get("sample_rate", 44100)):
        raise ContractError("golem.sample_rate %d is not supported yet (44100 only)" % sr)
    load_s = time.monotonic() - t0
    n = int(spec["n"])
    mix = np.fromfile(spec["input"], dtype=np.float32)
    if mix.size != 2 * n:
        raise ContractError("input size does not match n")
    mix = mix.reshape(n, 2).T
    work, out = spec["workdir"], spec["outdir"]
    os.makedirs(work, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    step = seg - ov
    starts = list(range(0, max(1, n - ov), step)) if n > seg else [0]
    fade = _fade(seg, ov)
    acc = np.zeros((len(names), 2, n + seg), np.float32)
    wsum = np.zeros(n + seg, np.float32)
    t1 = time.monotonic()
    computed = 0
    for k, st in enumerate(starts):
        cache = os.path.join(work, "seg-%05d.npy" % k)
        y = None
        if os.path.exists(cache):
            try:
                y = np.load(cache)
                if y.shape != (len(names), 2, seg):
                    y = None
            except Exception:
                y = None
        if y is None:
            chunk = np.zeros((1, 2, seg), np.float32)
            part = mix[:, st:st + seg]
            chunk[0, :, :part.shape[1]] = part
            outs = sess.run(None, {sess.get_inputs()[0].name: chunk})
            y = np.stack([np.asarray(o, np.float32).reshape(2, seg) for o in outs])
            if not np.isfinite(y).all():
                raise NanError("the engine returned NaN or Inf (segment %d)" % k)
            np.save(cache + ".tmp.npy", y)
            os.replace(cache + ".tmp.npy", cache)
            computed += 1
        w = fade.copy()
        if k == 0 and ov:
            w[:ov] = 1
        if k == len(starts) - 1 and ov:
            w[-ov:] = 1
        acc[:, :, st:st + seg] += y * w
        wsum[st:st + seg] += w
        with open(os.path.join(work, "progress.json"), "w") as f:
            json.dump({"done": k + 1, "total": len(starts)}, f)
    y = acc[:, :, :n] / np.maximum(wsum[:n], 1e-8)
    for i, name in enumerate(names):
        y[i].T.astype(np.float32).tofile(os.path.join(out, name + ".f32"))
    res = {"stems": names, "load_s": round(load_s, 3), "compute_s": round(time.monotonic() - t1, 3),
           "segments": len(starts), "computed": computed}
    with open(os.path.join(out, "result.json"), "w") as f:
        json.dump(res, f)
    return res


def main(argv):
    if len(argv) == 3 and argv[1] == "inspect":
        print(json.dumps(describe(_session(argv[2], 1))))
        return 0
    if len(argv) == 3 and argv[1] == "run":
        with open(argv[2]) as f:
            spec = json.load(f)
        try:
            run(spec)
            return 0
        except (ContractError, NanError, Exception) as e:
            code = 2 if isinstance(e, ContractError) else 3 if isinstance(e, NanError) else 1
            os.makedirs(spec["outdir"], exist_ok=True)
            with open(os.path.join(spec["outdir"], "error.json"), "w") as f:
                json.dump({"code": code, "why": str(e)[:500]}, f)
            return code
    print("usage: separation_run inspect <model.onnx> | run <spec.json>", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
