#!/usr/bin/env python3
"""Inject recommendations.json into index.html as const RECS (Top 20 flagged terms by spend).

Usage: python3 apply_recs.py [index.html] [recommendations.json]
Keys are "Cluster|search term". Rank = position by combined spend among all flagged terms.
Prints the current Top 20 terms that are missing a recommendation (write them after each refresh).
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))


def inject(s, recs_path):
    R = json.load(open(recs_path))
    j = s.find('const GROUPED=') + len('const GROUPED='); e = s.find(';\n', j)
    G = sorted(json.loads(s[j:e]), key=lambda d: -d['cost'])
    rank = {d['cluster'] + '|' + d['st']: i + 1 for i, d in enumerate(G)}
    out = {k: {'rank': rank[k], 'recs': v} for k, v in R.items() if not k.startswith('_') and k in rank}
    missing = [d['cluster'] + '|' + d['st'] for d in G[:20] if d['cluster'] + '|' + d['st'] not in R]
    stale = [k for k in R if not k.startswith('_') and k not in rank]
    j = s.find('const RECS=') + len('const RECS='); e = s.find(';\n', j)
    s = s[:j] + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + s[e:]
    return s, missing, stale


if __name__ == '__main__':
    html = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'index.html')
    recs = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, 'recommendations.json')
    s, missing, stale = inject(open(html).read(), recs)
    open(html, 'w').write(s)
    print('RECS injected. Top-20 missing recs:', missing or 'none', '| stale keys:', stale or 'none')
