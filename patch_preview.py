"""Patches preview/index.html: data-tag Attribute + aufklappbarer Kriegsverlauf (lokal, kein Render)."""
import json
import re
from pathlib import Path

BASE = Path(__file__).parent

# --- Spieler laden ---
players = json.loads((BASE / 'player_stats.json').read_text(encoding='utf-8'))
name_to_tag = {p['name']: p['tag'] for p in players}

# --- Kriegsverlauf aus lokalem Cache laden ---
cache_path = BASE / 'warlog_cache.json'
if cache_path.exists():
    warlog_by_tag = json.loads(cache_path.read_text(encoding='utf-8'))
    print(f'Kriegsdaten geladen: {len(warlog_by_tag)} Spieler aus warlog_cache.json')
else:
    warlog_by_tag = {}
    print('HINWEIS: warlog_cache.json fehlt – bitte zuerst prefetch_warlog.py ausführen.')

# --- HTML laden ---
html = (BASE / 'preview' / 'index.html').read_text(encoding='utf-8')

# --- data-tag Attribute einsetzen ---
matched = 0
for name, tag in name_to_tag.items():
    escaped = re.escape(name)
    pattern = rf"(<tr>)(<td class='name-col'><span class='name-inline'>{escaped}[\s<])"
    repl = rf"<tr class='player-row' data-tag='{tag}'>\2"
    new_html, count = re.subn(pattern, repl, html)
    if count:
        html = new_html
        matched += count

print(f'data-tag injected: {matched} von {len(name_to_tag)} Spielern')

# --- Kriegsdaten als JS-Variable einbetten ---
warlog_json = json.dumps(dict(warlog_by_tag), ensure_ascii=False)

expand_code = f"""
<script>var WARLOG_DATA = {warlog_json};</script>
<style>
.player-row {{ cursor: pointer; }}
.player-row:hover td {{ background: rgba(167,139,250,0.06) !important; }}
.player-row.expanded td {{ background: rgba(124,58,237,0.08) !important; }}
.war-history-row {{ display: none; }}
.war-history-row.open {{ display: table-row; }}
.war-history-inner {{
  padding: 12px 16px 14px;
  background: rgba(15,12,35,0.75);
  border-left: 3px solid #7c3aed;
}}
.war-history-inner h4 {{
  margin: 0 0 10px; color: #a78bfa; font-size: 0.88em; font-weight: 700;
}}
.war-hist-table {{
  width: 100%; border-collapse: collapse; font-size: 0.82em; max-width: 580px;
}}
.war-hist-table th {{
  text-align: center; color: #64748b; font-weight: 600;
  padding: 4px 10px; border-bottom: 1px solid rgba(255,255,255,0.08);
  font-size: 0.82em; text-transform: uppercase;
}}
.war-hist-table td {{
  text-align: center; padding: 5px 10px;
  border-bottom: 1px solid rgba(255,255,255,0.04); color: #e2e8f0;
}}
.fame-bar-wrap {{
  display: inline-block; width: 44px; height: 4px;
  background: rgba(255,255,255,0.1); border-radius: 2px;
  vertical-align: middle; margin-left: 5px;
}}
.fame-bar {{ height: 100%; border-radius: 2px; background: #7c3aed; }}
.war-expand-icon {{
  float: right; opacity: 0.35; font-size: 0.65em; margin-top: 4px;
  transition: transform 0.2s, opacity 0.2s; pointer-events: none;
}}
.player-row.expanded .war-expand-icon {{ transform: rotate(180deg); opacity: 0.85; }}
.no-war-data {{ color: #64748b; font-size: 0.85em; margin: 4px 0 0; }}
</style>
<script>
(function(){{
  function fameColor(f) {{
    return f >= 3600 ? '#10b981' : f >= 2800 ? '#fbbf24' : f >= 1600 ? '#f97316' : '#ef4444';
  }}
  function deckColor(d) {{
    return d >= 14 ? '#10b981' : d >= 8 ? '#fbbf24' : '#ef4444';
  }}
  function fmtDate(s) {{
    if (!s || s.length < 8) return '-';
    return s.slice(6,8) + '.' + s.slice(4,6) + '.' + s.slice(0,4);
  }}
  function buildTable(wars) {{
    if (!wars || !wars.length) return '<p class="no-war-data">Keine Kriegsdaten vorhanden.</p>';
    var maxF = Math.max.apply(null, wars.map(function(w){{ return w.fame || 0; }}));
    var rows = wars.slice(0,12).map(function(w) {{
      var f = w.fame || 0, d = w.decks_used || 0;
      var pct = maxF > 0 ? Math.round(f / maxF * 100) : 0;
      return '<tr>'
        + '<td>' + fmtDate(w.created_date) + '</td>'
        + '<td style="color:' + fameColor(f) + ';font-weight:700;">' + f
        + ' <span class="fame-bar-wrap"><span class="fame-bar" style="width:' + pct + '%"></span></span></td>'
        + '<td style="color:' + deckColor(d) + ';">' + d + '/16</td>'
        + '<td>' + (w.boat_attacks || 0) + '</td>'
        + '<td>' + (w.our_rank ? '#' + w.our_rank : '-') + '</td>'
        + '</tr>';
    }}).join('');
    return '<table class="war-hist-table"><thead><tr>'
      + '<th>Datum</th><th>Fame</th><th>Decks</th><th>Boot</th><th>Platz</th>'
      + '</tr></thead><tbody>' + rows + '</tbody></table>';
  }}

  function toggleRow(playerRow) {{
    var tag = playerRow.getAttribute('data-tag');
    if (!tag) return;
    var next = playerRow.nextElementSibling;
    if (!next || !next.classList.contains('war-history-row')) {{
      var tr = document.createElement('tr');
      tr.className = 'war-history-row';
      var td = document.createElement('td');
      td.colSpan = playerRow.cells.length;
      var inner = document.createElement('div');
      inner.className = 'war-history-inner';
      var wars = WARLOG_DATA[tag] || [];
      inner.innerHTML = '<h4>Kriegsverlauf</h4>' + buildTable(wars);
      td.appendChild(inner);
      tr.appendChild(td);
      playerRow.parentNode.insertBefore(tr, playerRow.nextSibling);
      next = tr;
    }}
    var open = next.classList.toggle('open');
    playerRow.classList.toggle('expanded', open);
  }}

  document.addEventListener('click', function(e) {{
    var row = e.target.closest('.player-row');
    if (row) toggleRow(row);
  }});

  document.querySelectorAll('.player-row').forEach(function(row) {{
    var first = row.cells[0];
    if (first) {{
      var icon = document.createElement('span');
      icon.className = 'war-expand-icon';
      icon.textContent = '▼';
      first.appendChild(icon);
    }}
  }});
}})();
</script>
"""

html = html.replace('</body>', expand_code + '\n</body>')
(BASE / 'preview' / 'index.html').write_text(html, encoding='utf-8')
print('Done — preview/index.html gepatcht (lokal, kein Render).')
