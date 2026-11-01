"""記録した状態に仕分けルールを当てはめ、各物体の置き場を判断させる。

1回の呼び出しで、その状態の全物体の置き場をまとめて答えさせる
（「一番大きい物だけ右へ」のように他の物体と比べるルールがあるため）。

  python decide.py runs/20261012/states.jsonl                # 全ルール
  python decide.py runs/20261012/states.jsonl --rules r01,r07
  python decide.py runs/20261012/143000/state.json --dry-run  # 送る内容だけ表示
  python decide.py runs/20261025/states.jsonl --backend astra   # 判断先を替える（fable / astra / jev）

astra（OpenAI GPT-6 Astra）は Codex CLI をヘッドレスで呼ぶ（ログイン中の ChatGPT アカウントの利用枠。キー不要）。
astra-api は同じモデルを API で呼ぶ予備。jev（TypeSafe）と astra-api は API キーが要る。環境変数か、
このフォルダの keys.env（OPENAI_API_KEY=... / TYPESAFE_API_KEY=...、git には入れない）に置く。

結果は入力と同じフォルダの decisions.jsonl に追記。済んだ組み合わせは飛ばすので、途中で止めても再開できる。
"""
import argparse
import json
import os
import signal
import subprocess
import urllib.error
import urllib.request
import tempfile
import time
from pathlib import Path

import yaml

from common import ROOT, load_config

SYSTEM = """あなたはロボットアームの仕分け係です。机の上の物体を、ルールに従って置き場（{bins}）に振り分けます。
- 机の座標は cm。俯瞰カメラで見たときの向きで、x は左→右（0〜{w}）、y は上→下（0〜{h}）。
- colors は面積の大きい順。shape は round（丸い）か angular（角ばっている）。kind は種類で、不明なら null。
- ルールで答えが一つに決まらないときも、最も妥当な置き場を選び、confidence を低くする。
- confidence は 0〜1 の自信の度合い。"""


def load_states(path):
    path = Path(path)
    if path.suffix == ".jsonl":
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()], path.parent
    with open(path) as f:
        return [json.load(f)], path.parent.parent


def scene_text(state):
    objs = [{k: o[k] for k in ("id", "colors", "shape", "kind", "area_px", "table_cm")}
            for o in state["objects"]]
    return json.dumps(objs, ensure_ascii=False)


def schema_for(state, bins):
    item = {
        "type": "object",
        "properties": {"bin": {"type": "string", "enum": bins},
                       "confidence": {"type": "number"}},
        "required": ["bin", "confidence"],
        "additionalProperties": False,
    }
    ids = [o["id"] for o in state["objects"]]
    return {"type": "object", "properties": {i: item for i in ids},
            "required": ids, "additionalProperties": False}


def decide_fable(cfg, system, user, schema):
    """Claude Code をヘッドレスで呼ぶ。API キー不要（ログイン中のアカウントの利用枠を使う）。"""
    cmd = [
        "claude", "-p", "--model", cfg["decide"]["fable_model"],
        "--tools", "", "--no-session-persistence",
        # 個人設定・hooks・MCP を読み込まないことで、入力を毎回同じにしてコストも抑える
        "--setting-sources", "", "--strict-mcp-config",
        "--system-prompt", system,
        "--output-format", "json", "--json-schema", json.dumps(schema),
        user,
    ]
    # CLAUDE.md を拾わないよう、プロジェクト外の空フォルダで実行する
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                           timeout=cfg["decide"]["timeout_s"])
    d = json.loads(p.stdout)
    if d.get("is_error") or d.get("structured_output") is None:
        raise RuntimeError(d.get("result") or p.stderr[:300])
    return d["structured_output"], {"model": cfg["decide"]["fable_model"],
                                    "cost_usd": d.get("total_cost_usd")}


def api_key(name):
    """環境変数になければ keys.env（KEY=VALUE の行）から読む。"""
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / "keys.env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError(f"{name} がありません（環境変数か {env.name} に置く）")


def post_json(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}") from None


def decide_astra(cfg, system, user, schema):
    """Codex CLI をヘッドレスで呼ぶ（fable の claude -p に相当）。

    Codex はコードを書く agent なので、system 文は本文の先頭に置き、道具を使わず答えるよう添える。
    サンドボックスは読み取り専用、セッションは残さず、個人の config.toml（hooks など）も読まない。
    """
    d = cfg["decide"]
    prompt = f"{system}\n\nこれは質問です。ファイルやコマンドは使わず、与えられた情報だけで答えてください。\n\n{user}"
    with tempfile.TemporaryDirectory() as tmp:
        sch, out = Path(tmp) / "schema.json", Path(tmp) / "answer.json"
        sch.write_text(json.dumps(schema))
        cmd = ["codex", "exec", "-m", d["astra_model"], "--ephemeral", "--ignore-user-config",
               "--skip-git-repo-check", "-s", "read-only", "-C", tmp, "--color", "never",
               "--output-schema", str(sch), "-o", str(out), "--json", prompt]
        # stdin を閉じておかないと、端末のない所から呼んだとき codex が入力の終わりを待ち続ける。
        # 時間切れのときは node の子（本体のバイナリ）ごと止めるため、プロセスグループで起動する
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        try:
            stdout, stderr = proc.communicate(timeout=cfg["decide"]["timeout_s"] * 3)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise RuntimeError("codex が時間内に答えませんでした") from None
        if proc.returncode != 0 or not out.exists():
            # codex の stderr は進行表示が多いので、ERROR の行だけ拾う（例：ワークスペースの支出上限）
            errs = [l for l in stderr.splitlines() if l.startswith("ERROR")]
            raise RuntimeError(errs[-1] if errs else (stderr or stdout)[-300:])
        answer = json.loads(out.read_text())
        # --json の行から使用トークンを拾う（費用は利用枠なので記録しない）
        usage = None
        for line in stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "turn.completed":
                usage = ev.get("usage")
    return answer, {"model": d["astra_model"], "cost_usd": None, "usage": usage}


def decide_astra_api(cfg, system, user, schema):
    """OpenAI の Responses API で同じモデルを呼ぶ予備。fable と同じ system / user / JSON スキーマを渡す。"""
    d = cfg["decide"]
    body = {
        "model": d["astra_model"],
        "instructions": system,
        "input": user,
        "text": {"format": {"type": "json_schema", "name": "sorting", "schema": schema, "strict": True}},
    }
    r = post_json("https://api.openai.com/v1/responses", body,
                  {"Authorization": f"Bearer {api_key('OPENAI_API_KEY')}"}, d["timeout_s"])
    text = next((c["text"] for item in r.get("output", []) if item.get("type") == "message"
                 for c in item.get("content", []) if c.get("type") == "output_text"), None)
    if text is None or r.get("status") == "incomplete":
        raise RuntimeError(f"出力なし: {json.dumps(r)[:300]}")
    u = r.get("usage", {})
    pin, pout = d["astra_price_per_m"]
    cost = (u.get("input_tokens", 0) * pin + u.get("output_tokens", 0) * pout) / 1e6
    return json.loads(text), {"model": r.get("model", d["astra_model"]), "cost_usd": round(cost, 5),
                              "usage": u}


def decide_jev(cfg, system, user, schema):
    """TypeSafe の System One。文章を生成せず、物体ごとに置き場を選ばせて確率をもらう。

    state に場面（system の説明＋ルール＋物体一覧）を入れ、物体 1 つにつき choice の質問を 1 つ立てる。
    質問は同じ state に対して独立に答えられる（他の物体と比べるルールでも state に全物体があるので答えられる）。
    """
    d = cfg["decide"]
    bins = list(schema["properties"][next(iter(schema["properties"]))]["properties"]["bin"]["enum"])
    ids = list(schema["properties"])
    questions = {i: {"type": "choice",
                     "instructions": f"ルールに従うと、物体 {i} はどの置き場に入れるべきか。",
                     "criteria": {b: f"置き場 {b}" for b in bins}} for i in ids}
    body = {"model": d["jev_model"], "state": f"{system}\n\n{user}", "questions": questions}
    r = post_json("https://api.typesafe.ai/v1/systemone", body,
                  {"Authorization": f"Bearer {api_key('TYPESAFE_API_KEY')}"}, d["timeout_s"])
    answer = {}
    for i in ids:
        a = r["answers"][i]
        answer[i] = {"bin": a["choice"], "confidence": round(a["confidence"], 3),
                     "probabilities": {k: round(v, 3) for k, v in a["probabilities"].items()}}
    u = r.get("usage", {})
    cost = u.get("input_tokens", 0) * d["jev_price_per_m_in"] / 1e6
    return answer, {"model": r.get("model", d["jev_model"]), "cost_usd": round(cost, 6), "usage": u}


BACKENDS = {"fable": decide_fable, "astra": decide_astra, "astra-api": decide_astra_api, "jev": decide_jev}


def decide_one(cfg, state, rule, backend=None):
    """1 つの状態に 1 つのルールを当てはめ、記録用の dict を返す（例外は呼び出し側に任せる）。"""
    backend = backend or cfg["decide"]["backend"]
    bins = cfg["bins"]
    w, h = cfg["table_cm"]["width"], cfg["table_cm"]["height"]
    system = SYSTEM.format(bins=", ".join(bins), w=w, h=h)
    user = f"ルール: {rule['text']}\n物体: {scene_text(state)}\n各物体の置き場を答えてください。"
    t0 = time.time()
    answer, meta = BACKENDS[backend](cfg, system, user, schema_for(state, bins))
    return {"state_id": state["id"], "rule_id": rule["id"], "rule": rule["text"], "backend": backend,
            "answer": answer, **meta, "latency_s": round(time.time() - t0, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("states", help="states.jsonl または state.json")
    ap.add_argument("--rules", help="カンマ区切りのルール ID（省略で全部）")
    ap.add_argument("--backend", choices=BACKENDS, help="fable / astra / astra-api / jev（既定は config.yaml の decide.backend）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    backend = args.backend or cfg["decide"]["backend"]
    with open(ROOT / "rules.yaml") as f:
        rules = yaml.safe_load(f)
    if args.rules:
        want = set(args.rules.split(","))
        rules = [r for r in rules if r["id"] in want]

    states, out_dir = load_states(args.states)
    out_path = out_dir / "decisions.jsonl"
    done = set()
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                d = json.loads(line)
                if not d.get("error"):
                    done.add((d["state_id"], d["rule_id"], d["backend"]))

    bins = cfg["bins"]
    w, h = cfg["table_cm"]["width"], cfg["table_cm"]["height"]
    system = SYSTEM.format(bins=", ".join(bins), w=w, h=h)

    for state in states:
        if not state["objects"]:
            print(f"{state['id']}: 物体なし、スキップ")
            continue
        for rule in rules:
            key = (state["id"], rule["id"], backend)
            if key in done:
                continue
            user = f"ルール: {rule['text']}\n物体: {scene_text(state)}\n各物体の置き場を答えてください。"
            if args.dry_run:
                print(f"--- {state['id']} / {rule['id']}\n{user}")
                continue
            rec = {"state_id": state["id"], "rule_id": rule["id"], "rule": rule["text"],
                   "backend": backend}
            t0 = time.time()
            try:
                answer, meta = BACKENDS[backend](cfg, system, user, schema_for(state, bins))
                rec.update(answer=answer, **meta)
            except Exception as e:  # 1件の失敗で全体を止めない。error 付きの行は次回やり直す
                rec["error"] = str(e)[:300]
            rec["latency_s"] = round(time.time() - t0, 2)
            with open(out_path, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            summary = rec.get("error") or " ".join(
                f"{k}→{v['bin']}({v['confidence']:.2f})" for k, v in rec["answer"].items())
            print(f"{state['id']} {rule['id']} [{rec['latency_s']}s] {summary}")


if __name__ == "__main__":
    main()
