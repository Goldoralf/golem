# SPDX-License-Identifier: GPL-3.0-or-later
"""Les moteurs de TEST de la séparation (docs/separation.md §12) — écrits par nous, sans réseau appris, donc sans données
d'entraînement. Jamais listés ni livrés : ils prouvent que le chemin ONNX et le chemin programme sont génériques (§1.1).

- `band_split_onnx` : trois bandes par filtres FIR fixes (`low` < 300 Hz, `mid` jusqu'à 3 kHz, `high` = le reste) ;
  la somme des trois est le mix, exactement.
- `copies_onnx` : rend N copies du mix — le faux que le test doit refuser.
- `nan_on_silence_onnx` : divise par l'énergie de l'entrée — NaN sur du silence, le piège vécu au spike R0.
- `split_program` : un programme qui écrit `low.wav` et `high.wav` (moyenne glissante) — l'autre porte."""
import os
import stat
import sys
import textwrap

import numpy as np


def _fir_lowpass(fc, sr=44100, taps=255):
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * fc / sr * n) * np.hamming(taps)
    return (h / h.sum()).astype(np.float32)


def _meta(model, seg, **extra):
    import onnx
    for k, v in {"golem.contract": "1", "golem.sample_rate": "44100", "golem.segment": str(seg), **extra}.items():
        p = model.metadata_props.add()
        p.key, p.value = k, v


def band_split_onnx(path, seg=44100 * 4, nan=False):
    import onnx
    from onnx import TensorProto, helper, numpy_helper
    taps = 255
    w = np.stack([_fir_lowpass(300), _fir_lowpass(3000)])[:, None, :]          # [2, 1, K]
    nodes = [
        helper.make_node("Reshape", ["mix", "shp_c"], ["x2"]),                    # [2, 1, S] : un canal = un lot
        helper.make_node("Conv", ["x2", "w"], ["lp"], pads=[taps // 2, taps // 2]),   # [2, 2, S]
        helper.make_node("Slice", ["lp", "s0", "s1", "ax1"], ["lp300"]),
        helper.make_node("Slice", ["lp", "s1", "s2", "ax1"], ["lp3k"]),
        helper.make_node("Sub", ["lp3k", "lp300"], ["bp"]),
        helper.make_node("Sub", ["x2", "lp3k"], ["hp"]),
        helper.make_node("Reshape", ["lp300", "shp_o"], ["low0" if nan else "low"]),
        helper.make_node("Reshape", ["bp", "shp_o"], ["mid"]),
        helper.make_node("Reshape", ["hp", "shp_o"], ["high"]),
    ]
    if nan:
        nodes += [helper.make_node("Mul", ["mix", "mix"], ["sq"]),
                  helper.make_node("ReduceMean", ["sq"], ["e"], keepdims=1),
                  helper.make_node("Div", ["e", "e"], ["one"]),
                  helper.make_node("Mul", ["low0", "one"], ["low"])]
    inits = [numpy_helper.from_array(w, "w"),
             numpy_helper.from_array(np.array([2, 1, seg], np.int64), "shp_c"),
             numpy_helper.from_array(np.array([1, 2, seg], np.int64), "shp_o"),
             numpy_helper.from_array(np.array([0], np.int64), "s0"),
             numpy_helper.from_array(np.array([1], np.int64), "s1"),
             numpy_helper.from_array(np.array([2], np.int64), "s2"),
             numpy_helper.from_array(np.array([1], np.int64), "ax1")]
    io = lambda name: helper.make_tensor_value_info(name, TensorProto.FLOAT, [1, 2, seg])
    g = helper.make_graph(nodes, "band-split", [io("mix")], [io("low"), io("mid"), io("high")], inits)
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 17)])
    m.ir_version = 8
    _meta(m, seg, **{"golem.licence": "test engine, no learned weights"})
    onnx.save(m, path)
    return path


def copies_onnx(path, seg=44100 * 4, n=3):
    import onnx
    from onnx import TensorProto, helper
    names = ["a", "b", "c"][:n]
    nodes = [helper.make_node("Identity", ["mix"], [o]) for o in names]
    io = lambda name: helper.make_tensor_value_info(name, TensorProto.FLOAT, [1, 2, seg])
    m = helper.make_model(helper.make_graph(nodes, "copies", [io("mix")], [io(o) for o in names]),
                          opset_imports=[helper.make_opsetid("", 17)])
    m.ir_version = 8
    _meta(m, seg)
    onnx.save(m, path)
    return path


def nan_on_silence_onnx(path, seg=44100 * 4):
    """Le séparateur par bandes, dont `low` est multiplié par e/e (e = énergie du segment) : identique sur un vrai
    signal, 0/0 = NaN sur du silence — le piège vécu au spike R0 (annexe A)."""
    return band_split_onnx(path, seg, nan=True)


def no_contract_onnx(path, seg=44100):
    import onnx
    from onnx import TensorProto, helper
    io = lambda name: helper.make_tensor_value_info(name, TensorProto.FLOAT, [1, 2, seg])
    m = helper.make_model(helper.make_graph([helper.make_node("Identity", ["mix"], ["a"])], "x", [io("mix")], [io("a")]),
                          opset_imports=[helper.make_opsetid("", 17)])
    m.ir_version = 8
    onnx.save(m, path)
    return path


def split_program(path):
    """Un programme (porte §4) : lit {input}, écrit low.wav et high.wav dans {outdir}. Python pur, sans numpy."""
    src = textwrap.dedent('''\
        #!%s
        import sys, wave, array, os
        args = sys.argv[1:]
        inp, out = args[args.index("--in") + 1], args[args.index("--out") + 1]
        w = wave.open(inp, "rb"); ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        x = array.array("h", w.readframes(n)); w.close()
        low = array.array("h", [0]) * len(x); acc = [0.0] * ch; a = 0.02
        for i, v in enumerate(x):
            c = i %% ch; acc[c] += a * (v - acc[c]); low[i] = int(acc[c])
        high = array.array("h", [max(-32768, min(32767, x[i] - low[i])) for i in range(len(x))])
        for name, d in (("low", low), ("high", high)):
            o = wave.open(os.path.join(out, name + ".wav"), "wb"); o.setnchannels(ch); o.setsampwidth(2)
            o.setframerate(sr); o.writeframes(d.tobytes()); o.close()
        ''' % sys.executable)
    with open(path, "w") as f:
        f.write(src)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def mix_clip(path, seconds=30, sr=44100):
    """Un « morceau » synthétique : trois partiels dans trois bandes + un souffle léger, stéréo, écrit par ffmpeg."""
    import subprocess
    t = np.arange(seconds * sr) / sr
    l = 0.3 * np.sin(2 * np.pi * 110 * t) + 0.3 * np.sin(2 * np.pi * 1000 * t) + 0.3 * np.sin(2 * np.pi * 7000 * t)
    r = 0.3 * np.sin(2 * np.pi * 82 * t) + 0.3 * np.sin(2 * np.pi * 1500 * t) + 0.3 * np.sin(2 * np.pi * 6000 * t)
    rng = np.random.default_rng(1)
    x = np.stack([l, r], 1) + 0.01 * rng.standard_normal((len(t), 2))
    raw = path + ".f32"
    x.astype(np.float32).tofile(raw)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", raw, path], check=True)
    os.unlink(raw)
    return path
