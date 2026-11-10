import csv, json, os, re, subprocess, sys, tempfile, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
FILE = 'nba.csv'
HEAD = ['Дата', 'GameID', 'Гости', 'Хозяева', 'Итог (гости:хозяева)', 'Победитель',
        'Макс. отрыв: команда', 'Отрыв', 'Четверть', 'Время', 'Счёт',
        'Камбэк: очков', 'Четверть', 'Время', 'Счёт', 'Отыгрались в', 'Время', 'Счёт']
SB = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='
FIX = {'GS': 'GSW', 'NY': 'NYK', 'SA': 'SAS', 'NO': 'NOP', 'UTAH': 'UTA', 'WSH': 'WAS'}
SCORE = re.compile(r'(\d{1,3})-(\d{1,3})\s+(?:TIE|[+-]\d+)')
TIME = re.compile(r'^\s*(\d{1,2}:\d{2}|:\d{2}\.\d)\b')
PER = re.compile(r'^\s*(?:(\d)(?:st|nd|rd|th)\s+)?(QUARTER|OVERTIME)', re.I)


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def pdf_text(url):
    data = fetch(url)
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        f.write(data)
        f.flush()
        return subprocess.run(['pdftotext', '-layout', f.name, '-'],
                              capture_output=True, text=True, check=True).stdout


def label(p):
    return f'Q{p}' if p <= 4 else f'OT{p - 4}'


def parse(text):
    pts, period, in_pbp, wait, clock = [], 1, False, False, ''
    for line in text.splitlines():
        if 'OFFICIAL PLAY-BY-PLAY' in line:
            in_pbp, wait = True, True
            continue
        if not in_pbp:
            continue
        if wait:
            m = PER.match(line)
            if m:
                n = int(m.group(1) or 1)
                period = n if m.group(2).upper() == 'QUARTER' else 4 + n
                wait = False
            continue
        t = TIME.match(line)
        if t:
            clock = t.group(1)
        m = SCORE.search(line)
        if m:
            pts.append((int(m.group(1)), int(m.group(2)), period, clock))
    return pts  # (хозяева, гости, период, время)


def lead(pts, sign):
    best, bi = 0, -1
    for i, (h, a, p, c) in enumerate(pts):
        d = sign * (h - a)
        if d > best:
            best, bi = d, i
    if bi < 0:
        return None
    h, a, p, c = pts[bi]
    rec = None
    for h2, a2, p2, c2 in pts[bi + 1:]:
        if sign * (h2 - a2) <= 0:
            rec = (label(p2), c2, f'{a2}:{h2}')
            break
    return {'size': best, 'p': label(p), 'c': c, 's': f'{a}:{h}', 'rec': rec}


def make_row(day, away, home, pts):
    hs, as_ = pts[-1][0], pts[-1][1]
    H, A = lead(pts, 1), lead(pts, -1)
    home_won = hs > as_
    cands = [c for c in [(H, home), (A, away)] if c[0]]
    ml, mt = max(cands, key=lambda c: c[0]['size']) if cands else (None, '-')
    cb = A if home_won else H            # победитель проигрывал = лидировал проигравший
    d = '-'
    rec = cb['rec'] if cb and cb['rec'] else (d, d, d)
    return [f'{day[:4]}-{day[4:6]}-{day[6:]}', f'{day}_{away}{home}', away, home,
            f'{as_}:{hs}', home if home_won else away,
            mt if ml else d, ml['size'] if ml else 0, ml['p'] if ml else d,
            ml['c'] if ml else d, ml['s'] if ml else d,
            cb['size'] if cb else 0, cb['p'] if cb else d, cb['c'] if cb else d,
            cb['s'] if cb else d, *rec]


def games(day):
    out = []
    for e in json.loads(fetch(SB + day)).get('events', []):
        comp = e['competitions'][0]
        if not comp['status']['type']['completed']:
            continue
        h = next(c for c in comp['competitors'] if c['homeAway'] == 'home')['team']['abbreviation']
        a = next(c for c in comp['competitors'] if c['homeAway'] == 'away')['team']['abbreviation']
        out.append((FIX.get(a, a), FIX.get(h, h)))
    return out


def process(day, away, home):
    url = f'https://statsdmz.nba.com/pdfs/{day}/{day}_{away}{home}_book.pdf'
    try:
        pts = parse(pdf_text(url))
    except Exception as e:
        print('Пропуск', url, e)
        return None
    if not pts:
        print('Нет данных в', url)
        return None
    return make_row(day, away, home, pts)


def main():
    done = set()
    if os.path.exists(FILE):
        with open(FILE, encoding='utf-8') as f:
            done = {r[1] for r in list(csv.reader(f))[1:] if len(r) > 1}

    arg = sys.argv[1] if len(sys.argv) > 1 else ''
    m = re.search(r'/(\d{8})_([A-Z]{3})([A-Z]{3})_book', arg)
    todo = []
    if m:
        todo.append(m.groups())
    else:
        now = datetime.now(ET)
        for day in [(now - timedelta(days=1)).strftime('%Y%m%d'), now.strftime('%Y%m%d')]:
            todo += [(day, a, h) for a, h in games(day)]

    rows = []
    for day, a, h in todo:
        if f'{day}_{a}{h}' in done:
            continue
        r = process(day, a, h)
        if r:
            rows.append(r)

    if not rows:
        print('Новых матчей нет')
        return
    new_file = not os.path.exists(FILE)
    with open(FILE, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HEAD)
        w.writerows(rows)
    print('Добавлено матчей:', len(rows))


main()
