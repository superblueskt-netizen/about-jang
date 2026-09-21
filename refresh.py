#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh.py — 내 기록으로 사이트 숫자와 문단 후보를 다시 만드는 장치

리추얼 기록(필수)과 출석·제출 현황 파일(선택)을 넣고 돌리면
  1) site-data.json        : 사이트에 박히는 숫자들
  2) paragraph-candidates.md : 사이트 본문에 넣을 문단 후보
  3) (선택) index.html 안의 숫자 블록을 직접 갈아끼움
을 다시 만든다. 과정이 끝난 뒤에도 기록만 새로 받아 돌리면 사이트가 갱신된다.

사용법
  python3 refresh.py ritual-history.txt
  python3 refresh.py ritual-history.txt --attendance 출석.txt --progress 제출현황.txt --html index.html

리추얼 기록은 내보내기 텍스트(.txt)와 JSON(.json)을 둘 다 받는다.
외부 라이브러리 없음. 파이썬 3.8+ 면 동작한다.
"""

import json, re, sys, datetime, pathlib, argparse
from collections import Counter

MASK = "(이름 가림)"

# ── 입력 읽기 ───────────────────────────────────────────────────────────
def load(path):
    """리추얼 기록을 읽는다. 내보내기 텍스트(.txt)와 JSON(.json)을 모두 받는다."""
    raw = pathlib.Path(path).read_text(encoding="utf-8")
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    return parse_text(raw)

def parse_text(raw):
    """내보내기 텍스트를 읽는다.

        ## 2026-09-04
        [아침]
        - 호흡: 5분
        [마무리]
        - 강점 행동: 실천했다

    '## 날짜'로 하루가 시작하고, '[아침]'/'[마무리]'로 칸이 갈리고,
    '- 항목: 값' 한 줄이 기록 하나다. '#'로 시작하는 머리말은 건너뛴다.
    """
    days, cur, box = [], None, None
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("## "):
            cur = {"date": s[3:].strip(), "open": [], "close": []}
            days.append(cur)
            box = None
        elif s in ("[아침]", "[마무리]"):
            box = "open" if s == "[아침]" else "close"
            # 칸을 열었다는 사실 자체를 기록한다. 내용이 비어 있어도 '냈다'로 센다.
            cur[box + "_seen"] = True
        elif s.startswith("- ") and cur is not None and box:
            cur[box].append(s[2:].strip())
    return {"days": days}

# ── 읽기 ────────────────────────────────────────────────────────────────
def field(lines, prefix):
    """'호흡: 3.4분' 같은 줄에서 prefix 뒤의 값을 꺼낸다."""
    for s in lines or []:
        if s.startswith(prefix):
            return s.split(":", 1)[1].strip() if ":" in s else ""
    return None

def all_fields(lines, prefix):
    out = []
    for s in lines or []:
        if s.startswith(prefix):
            out.append(s.split(":", 1)[1].strip() if ":" in s else "")
    return out

def minutes(raw):
    """'4.65분' → 4.65. 가려진 값('(이름 가림).53분')은 버린다."""
    if not raw or MASK in raw:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", raw)
    return float(m.group(1)) if m else None

# ── 집계 ────────────────────────────────────────────────────────────────
def compute(data):
    days = data.get("days", [])
    days = sorted(days, key=lambda d: d["date"])
    dates = [d["date"] for d in days]

    # 칸을 낸 날 = 내용이 있거나, 칸 자체가 열려 있던 날
    morning = [d for d in days if d.get("open") or d.get("open_seen")]
    evening = [d for d in days if d.get("close") or d.get("close_seen")]

    # 강점 행동 — 자기동기력 지표
    acts = [field(d.get("close"), "강점 행동") for d in days]
    acts = [a for a in acts if a]
    c = Counter(acts)
    done, partial, missed = c.get("실천했다", 0), c.get("일부 실천했다", 0), c.get("못 했다", 0)
    rated = done + partial + missed

    # 회복탄력성 지표 — '못 했다' 다음 기록일에 다시 '실천했다'로 돌아온 비율
    seq = [(d["date"], field(d.get("close"), "강점 행동")) for d in days if field(d.get("close"), "강점 행동")]
    bounce_ok = bounce_total = 0
    for i, (_, a) in enumerate(seq[:-1]):
        if a == "못 했다":
            bounce_total += 1
            if seq[i + 1][1] in ("실천했다", "일부 실천했다"):
                bounce_ok += 1

    # 호흡
    mins = [minutes(field(d.get("open"), "호흡")) for d in days]
    mins = [m for m in mins if m is not None]

    # 동료 피드백 — 받은 장점 + 받은 감사
    peer = 0
    for d in days:
        for n in range(1, 9):
            peer += len(all_fields(d.get("open"), f"동료 {n}가 말해 준 내 장점"))
            peer += len(all_fields(d.get("close"), f"동료 {n}가 나눈 감사"))

    # 연속 기록 (기록이 있는 날 기준 최장 연속)
    streak = best = 0
    prev = None
    for d in days:
        cur = datetime.date.fromisoformat(d["date"])
        streak = streak + 1 if prev and (cur - prev).days <= 3 else 1
        best = max(best, streak)
        prev = cur

    start, end = dates[0], dates[-1]
    weeks = round(((datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days + 1) / 7, 1)

    # 주의: 실행 시각 같은 값은 넣지 않는다. 같은 입력이면 항상 같은 결과가 나와야 한다.
    return {
        "based_on": end,          # 기준일 = 입력 기록의 마지막 날
        "period_start": start,
        "period_end": end,
        "weeks": weeks,
        "total_days": len(days),
        "morning_days": len(morning),
        "evening_days": len(evening),
        "act_done": done,
        "act_partial": partial,
        "act_missed": missed,
        "act_rated": rated,
        "act_rate": round((done + partial) / rated * 100) if rated else 0,
        "bounce_back": bounce_ok,
        "bounce_total": bounce_total,
        "bounce_rate": round(bounce_ok / bounce_total * 100) if bounce_total else 0,
        "breath_total_min": round(sum(mins), 1),
        "breath_days": len(mins),
        "peer_feedback": peer,
        "longest_streak": best,
    }

# ── 출석·제출 현황 ──────────────────────────────────────────────────────
# 두 파일은 '- 항목: 숫자' 한 줄짜리 형식이다. 사람이 손으로 고칠 수 있게 일부러
# 단순하게 뒀다. 없으면 그 출처의 숫자만 빠지고 나머지는 그대로 나온다.
ATT_KEYS = {"수업일": "class_days", "출석": "present", "지각": "late",
            "병가": "sick", "무단결석": "absent", "결석": "absent"}
PRG_KEYS = {"전체 과제": "total", "마스터 승인": "approved",
            "진행 중": "in_progress", "현재 주차": "week", "전체 주차": "weeks_total"}

def read_counts(path, keys, prefix):
    if not path:
        return {}
    out = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip().lstrip("-").strip()
        if s.startswith("#") or ":" not in s:
            continue
        k, v = s.split(":", 1)
        name = keys.get(k.strip())
        if not name:
            continue
        m = re.search(r"(\d+(?:\.\d+)?)", v)
        if m:
            out[prefix + name] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
    return out

def derive(s):
    """두 파일이 들어왔을 때만 계산되는 값."""
    if s.get("att_class_days"):
        s["att_rate"] = round(s.get("att_present", 0) / s["att_class_days"] * 100)
        # 병가는 무단결석과 다르게 센다. 둘을 합쳐서 하나로 뭉개지 않는다.
        s["att_excused"] = s.get("att_sick", 0)
    if s.get("prg_total"):
        s["prg_rate"] = round(s.get("prg_approved", 0) / s["prg_total"] * 100)

# ── 문단 후보 ───────────────────────────────────────────────────────────
def candidates(data, s):
    days = sorted(data.get("days", []), key=lambda d: d["date"])
    def recent(lines_key, prefix, n=4):
        out = []
        for d in reversed(days):
            v = field(d.get(lines_key), prefix)
            if v and MASK not in v:
                out.append((d["date"], v))
            if len(out) >= n:
                break
        return out

    L = []
    L.append("# 문단 후보 — 기준일 %s\n" % s["based_on"])
    L.append("사이트 본문에 그대로 붙이거나 다듬어 쓸 후보입니다. "
             "숫자는 site-data.json 과 같은 계산에서 나옵니다.\n")
    L.append("승인한 문장만 사이트에 올립니다. 같은 입력이면 이 파일도 항상 같게 나옵니다.\n")

    L.append("\n## 후보 A — 지속의 숫자로 여는 문단\n")
    L.append(f"> {s['period_start']}부터 {s['period_end']}까지 {s['total_days']}일을 기록했다. "
             f"아침 {s['morning_days']}번, 마무리 {s['evening_days']}번. "
             f"그중 {s['act_rated']}일은 그날 지키기로 한 강점을 실제로 지켰는지까지 적었고, "
             f"{s['act_rate']}%의 날에 지켰다고 적을 수 있었다. "
             f"못 한 날도 {s['act_missed']}번 있었다. 그 숫자를 지우지 않고 남겨 둔 것이 이 기록의 핵심이다.\n")

    L.append("\n## 후보 B — 회복탄력성 문단\n")
    if s["bounce_total"]:
        L.append(f"> 지키지 못한 날이 {s['bounce_total']}번 있었고, 그 다음 기록일에 "
                 f"{s['bounce_back']}번 다시 지켰다. {s['bounce_rate']}%다. "
                 f"나는 넘어지지 않는 사람이 아니라, 넘어진 다음 날 같은 자리로 돌아오는 사람이다.\n")
    else:
        L.append("> (아직 '못 했다'로 적은 날이 없어 회복 지표를 계산할 수 없습니다.)\n")

    L.append("\n## 후보 C — 자기조절력 문단 (최근 '나에게 남기는 말')\n")
    for d, v in recent("close", "나에게 남기는 말"):
        L.append(f"- {d} — {v}\n")

    L.append("\n## 후보 D — 자기동기력 문단 (최근 '오늘 지킬 강점·가치')\n")
    for d, v in recent("open", "오늘 지킬 강점·가치"):
        L.append(f"- {d} — {v}\n")

    L.append("\n## 후보 E — 대인관계력 문단 (최근 '내가 나눈 감사')\n")
    for d, v in recent("close", "내가 나눈 감사"):
        L.append(f"- {d} — {v}\n")

    L.append("\n## 후보 F — 강점이 드러난 장면 (최근)\n")
    for d, v in recent("open", "강점이 드러난 일화"):
        L.append(f"- {d} — {v}\n")

    return "".join(L)

# ── index.html 숫자 갈아끼우기 ──────────────────────────────────────────
def patch_html(path, s):
    p = pathlib.Path(path)
    if not p.exists():
        print(f"  ! {path} 없음 — 건너뜀")
        return
    html = p.read_text(encoding="utf-8")
    n = 0
    for k, v in s.items():
        # <span data-stat="k">…</span>, <div class="v" data-stat="k">…</div> 등
        # 태그 종류와 다른 속성이 있어도 찾도록 한다.
        pat = re.compile(
            r'(<(\w+)\b[^>]*\bdata-stat="%s"[^>]*>)(.*?)(</\2>)' % re.escape(k), re.S)
        html, cnt = pat.subn(lambda m: m.group(1) + str(v) + m.group(4), html)
        n += cnt
    p.write_text(html, encoding="utf-8")
    print(f"  · {path} 숫자 {n}곳 갱신")

# ── main ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="세 가지 기록으로 사이트 숫자·문단 후보를 다시 만든다")
    ap.add_argument("ritual", help="리추얼 기록 (.txt 내보내기 또는 .json)")
    ap.add_argument("--attendance", help="출석 숫자 파일 (선택) — 출처 「내 출석 기록」")
    ap.add_argument("--progress", help="과제 제출 현황 파일 (선택) — 출처 「내 제출 현황」")
    ap.add_argument("--html", help="숫자를 갈아끼울 index.html 경로 (선택)")
    ap.add_argument("--out", default=".", help="결과를 쓸 폴더 (기본: 현재 폴더)")
    a = ap.parse_args()

    data = load(a.ritual)
    s = compute(data)
    s.update(read_counts(a.attendance, ATT_KEYS, "att_"))
    s.update(read_counts(a.progress, PRG_KEYS, "prg_"))
    derive(s)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    (out / "site-data.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "paragraph-candidates.md").write_text(
        candidates(data, s), encoding="utf-8")

    print(f"기록 {s['total_days']}일 ({s['period_start']} ~ {s['period_end']}, 약 {s['weeks']}주)")
    print(f"  · site-data.json")
    print(f"  · paragraph-candidates.md")
    if a.html:
        patch_html(a.html, s)
    line = f"실천 {s['act_rate']}% · 회복 {s['bounce_rate']}% · 동료 피드백 {s['peer_feedback']}건"
    if "att_rate" in s:
        line += f" · 출석 {s['att_rate']}%"
    if "prg_rate" in s:
        line += f" · 승인 {s['prg_approved']}/{s['prg_total']}"
    print(line)

if __name__ == "__main__":
    main()
