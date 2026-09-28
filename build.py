#!/usr/bin/env python3
"""Rebuild the Keyword Cannibalization report (read-only GAQL via Funnel Gate).

Usage: python3 build.py [DATE_RANGE]   (default LAST_30_DAYS)
Reuses the HTML/JS template in index.html, replaces header, summary table and data arrays.
Logic per skills/keyword-cannibalization-alert/SKILL.md:
  - ENABLED campaigns + ENABLED ad groups + ENABLED keywords only
  - search terms with status EXCLUDED / ADDED_EXCLUDED dropped
  - per cluster, group by lowercased search term, drop terms with < 30 impressions
  - flag terms matched by >= 2 distinct keyword texts
"""
import json, subprocess, sys, re, datetime, collections, os

FG_DIR = "/Users/diegomalamute/repos/funnel-fighters/funnel-fighters/action-service"
CUSTOMER = "3746504118"
RANGE = sys.argv[1] if len(sys.argv) > 1 else "LAST_30_DAYS"
HERE = os.path.dirname(os.path.abspath(__file__))

CLUSTERS = [
    ("Agents", ["-agent_"]),
    ("Project", ["-project[_-]"]),
    ("Task", ["-task[_-]"]),
    ("Canada", ["ca-en-"]),
    ("EU1", ["eu1-en-prm-workos-work_mgmt-all_categories"]),
    ("Competitors", ["-comp1-", "-comp_"]),
    ("To Do", ["-to_do_list-"]),
    ("Calendar", ["-shared_calendar-", "-schedule-", "_calendar--"]),
    ("Gantt", ["-gantt[_-]"]),
    ("Marketing", ["-marketer-"]),
    ("General", ["-general-"]),
    ("Management", ["-management-"]),
    ("Logistic", ["-order_", "-construction_", "-production_"]),
]


def q(query, reason):
    p = {"requester": "nymeria", "action": "gaql_query", "platform": "google_ads",
         "scope": {"customer_id": CUSTOMER, "query": query},
         "trail": {"reasoning": reason},
         "initiator": {"name": "Alex Abramovich", "context": "SEM Team & Nymera WhatsApp group"}}
    r = subprocess.run(["python3", "funnel_gate.py", json.dumps(p)], capture_output=True, text=True, cwd=FG_DIR)
    d = json.loads(r.stdout)
    if not d.get("success"):
        raise RuntimeError(r.stdout[:1500])
    return d["result"].get("results", [])


def money(v):
    if isinstance(v, str) and "$" in v:
        return float(v.replace("$", "").replace(",", ""))
    return float(v or 0) / 1e6


def geo(camp):
    return camp.split("-")[0].upper()


def pull(pattern):
    rx = f"(?i).*{pattern}.*"
    rows = q(f"""SELECT search_term_view.search_term, segments.keyword.info.text, segments.keyword.info.match_type,
        campaign.name, ad_group.name, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions
        FROM search_term_view WHERE segments.date DURING {RANGE}
        AND campaign.name REGEXP_MATCH '{rx}' AND campaign.status = 'ENABLED' AND ad_group.status = 'ENABLED'
        AND search_term_view.status NOT IN ('EXCLUDED', 'ADDED_EXCLUDED')""",
             f"Keyword cannibalization report refresh ({RANGE}) - search terms {pattern}")
    enabled = q(f"""SELECT ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, ad_group.name, campaign.name FROM keyword_view
        WHERE campaign.name REGEXP_MATCH '{rx}' AND campaign.status = 'ENABLED' AND ad_group.status = 'ENABLED'
        AND ad_group_criterion.status = 'ENABLED' AND ad_group_criterion.negative = FALSE""",
               f"Keyword cannibalization report refresh - enabled keywords {pattern}")
    ps = {(r["adGroupCriterion"]["keyword"]["text"].lower(), r["adGroupCriterion"]["keyword"]["matchType"], r["adGroup"]["name"], r["campaign"]["name"]) for r in enabled if "adGroupCriterion" in r}
    return rows, ps


def main():
    PIVOT, FLAT, GROUPED, SUMMARY = [], [], [], []
    for cname, pats in CLUSTERS:
        seen = set(); raw = []; err = None
        for pat in pats:
            try:
                rows, ps = pull(pat)
            except Exception as e:
                err = str(e)[:200]; print("ERR", cname, pat, err, flush=True); continue
            for r in rows:
                if "searchTermView" not in r:
                    continue
                kwi = r.get("segments", {}).get("keyword", {}).get("info", {})
                kw = kwi.get("text")
                if not kw:
                    continue
                camp = r["campaign"]["name"]; ag = r["adGroup"]["name"]
                if (kw.lower(), kwi.get("matchType"), ag, camp) not in ps:  # ENABLED keywords only (drops paused + removed)
                    continue
                st = r["searchTermView"]["searchTerm"].lower()
                key = (st, kw.lower(), kwi.get("matchType"), camp, ag)
                if key in seen:
                    continue  # campaign matched two patterns of the same cluster
                seen.add(key)
                m = r["metrics"]
                raw.append(dict(st=st, kw=kw, mt=kwi.get("matchType"), camp=camp, ag=ag,
                                imp=int(m.get("impressions", 0)), cl=int(m.get("clicks", 0)),
                                cost=money(m.get("costMicros", 0)), conv=float(m.get("conversions", 0))))
        by = collections.defaultdict(list)
        for x in raw:
            by[x["st"]].append(x)
        flagged = 0; fi = fc = 0; fcost = 0.0
        for st, xs in by.items():
            imp = sum(x["imp"] for x in xs)
            if imp < 30:
                continue
            kws = {x["kw"].lower() for x in xs}
            if len(kws) < 2:
                continue
            flagged += 1
            cl = sum(x["cl"] for x in xs); cost = sum(x["cost"] for x in xs); conv = sum(x["conv"] for x in xs)
            geos = sorted({geo(x["camp"]) for x in xs})
            nkw = len(kws)
            fi += imp; fc += cl; fcost += cost
            PIVOT.append(dict(st=st, cluster=cname, nkw=nkw, imp=imp, cl=cl, cost=cost, conv=conv, geos=geos))
            GROUPED.append(dict(st=st, nkw=nkw, geos=geos, camps=sorted({x["camp"] for x in xs}), cluster=cname,
                                imp=imp, cl=cl, cost=cost, conv=conv,
                                e=[[x["kw"], x["mt"], x["camp"], x["ag"], x["imp"], x["cl"], x["cost"], x["conv"]] for x in xs]))
            for x in xs:
                FLAT.append(dict(st=st, kw=x["kw"], mt=x["mt"], camp=x["camp"], ag=x["ag"], imp=x["imp"], cl=x["cl"],
                                 cost=x["cost"], conv=x["conv"], cluster=cname, geos=geos, nkw=nkw))
        SUMMARY.append(dict(cluster=cname, terms=len(by), flagged=flagged, imp=fi, cl=fc, cost=fcost, err=err))
        print(cname, "terms", len(by), "flagged", flagged, "cost", round(fcost), flush=True)

    for L in (PIVOT, GROUPED):
        L.sort(key=lambda d: (-d["nkw"], -d["cost"]))
    FLAT.sort(key=lambda d: (-d["nkw"], d["st"], -d["cost"]))

    s = open(os.path.join(HERE, "index.html")).read()
    now = datetime.datetime.now()
    s = re.sub(r'<div class="sub">.*?</div>',
               f'<div class="sub">Account: Main ({CUSTOMER}) · Period: Last 30 Days · Generated: {now.strftime("%B %-d, %Y %H:%M")} · 13 BigBrain-Aligned Clusters</div>',
               s, count=1)
    tf = sum(x["flagged"] for x in SUMMARY); tcost = sum(x["cost"] for x in SUMMARY)
    fmtc = lambda v: "${:,.2f}".format(v)
    s = re.sub(r'<div class="kpi-v a" id="k1f">.*?</div>', f'<div class="kpi-v a" id="k1f">{tf:,}</div>', s, count=1)
    s = re.sub(r'<div class="kpi-v a" id="k1c">.*?</div>', f'<div class="kpi-v a" id="k1c">{fmtc(tcost)}</div>', s, count=1)
    s = re.sub(r'<div class="kpi-v" id="k1r">.*?</div>', f'<div class="kpi-v" id="k1r">{len(FLAT):,}</div>', s, count=1)
    rows = ""
    for i, x in enumerate(SUMMARY):
        alt = "alt" if i % 2 else ""
        name = x["cluster"]
        if x["err"]:
            cell = f'<td>{name}</td>'; fl = f'<td class="n zero">error</td>'
        elif x["flagged"]:
            cell = f'<td class="click" onclick="go2(\'{name}\')">{name}</td>'
            fl = f'<td class="n {"high" if x["flagged"] > 100 else ""}">{x["flagged"]:,}</td>'
        else:
            cell = f'<td>{name}</td>'; fl = '<td class="n zero">0</td>'
        rows += (f'<tr class="{alt}">{cell}<td class="n">{x["terms"]:,}</td>{fl}<td class="n">{x["imp"]:,}</td>'
                 f'<td class="n">{x["cl"]:,}</td><td class="n">{fmtc(x["cost"])}</td></tr>')
    rows += (f'<tr style="border-top:2px solid var(--border);font-weight:600"><td>TOTAL</td>'
             f'<td class="n">{sum(x["terms"] for x in SUMMARY):,}</td><td class="n a">{tf:,}</td>'
             f'<td class="n">{sum(x["imp"] for x in SUMMARY):,}</td><td class="n">{sum(x["cl"] for x in SUMMARY):,}</td>'
             f'<td class="n a">{fmtc(tcost)}</td></tr>')
    a = s.find('<th class="n">Spend</th>')
    b0 = s.find('<tbody>', a) + len('<tbody>')
    b1 = s.find('</tbody>', b0)
    s = s[:b0] + "\n" + rows + s[b1:]

    def put(s, name, data):
        j = s.find('const ' + name + '=') + len('const ' + name + '=')
        e = s.find(';\n', j)
        return s[:j] + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + s[e:]
    for name, data in (("PIVOT", PIVOT), ("FLAT", FLAT), ("GROUPED", GROUPED)):
        s = put(s, name, data)
    open(os.path.join(HERE, "index.html"), "w").write(s)
    json.dump(SUMMARY, open("/tmp/cannibal_summary.json", "w"))
    print("DONE flagged", tf, "cost", round(tcost), "flat", len(FLAT), flush=True)


if __name__ == "__main__":
    main()
