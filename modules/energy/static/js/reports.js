// History: the battery health report tab (dialog, polling, Markdown rendering).
// Loaded as a classic script (shared global scope) in the order listed at the end of index.html.

let reportPollTimer = null;
function reportStatusBox(text, kind) {
  const box = $('reportStatus');
  box.hidden = !text;
  box.textContent = text || '';
  box.classList.toggle('error', kind === 'error');
}
function openBatteryReportDialog() {
  const retention = Number(state.settings?.history_retention_days) || 7;
  $('reportDays').value = String(Math.min(7, retention));
  $('reportDaysHint').textContent =
    `History is kept for ${retention} day${retention === 1 ? '' : 's'} (Settings → Save history period). A longer analysis takes longer to run.`;
  $('reportDaysError').hidden = true;
  const dialog = $('reportDialog');
  dialog.classList.add('open');
  dialog.setAttribute('aria-hidden', 'false');
  setTimeout(() => {
    $('reportDays').focus();
    $('reportDays').select();
  }, 50);
}
function closeReportDialog() {
  const dialog = $('reportDialog');
  dialog.classList.remove('open');
  dialog.setAttribute('aria-hidden', 'true');
}
function submitReportDialog() {
  const raw = $('reportDays').value.trim(),
    days = Number(raw);
  if (!/^\d{1,3}$/.test(raw) || days < 1 || days > 365) {
    const error = $('reportDaysError');
    error.textContent = 'Enter a whole number of days from 1 to 365';
    error.hidden = false;
    $('reportDays').focus();
    $('reportDays').select();
    return;
  }
  closeReportDialog();
  startBatteryReport(days);
}
async function startBatteryReport(days) {
  $('reportOutput').hidden = true;
  $('reportBatteryBtn').disabled = true;
  reportStatusBox(`Starting the analysis of ${days} day${days === 1 ? '' : 's'}…`);
  try {
    const r = await fetch('/api/reports/battery-health', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days })
      }),
      data = await r.json();
    if (!r.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Enter a whole number of days from 1 to 365');
    pollBatteryReport();
  } catch (e) {
    $('reportBatteryBtn').disabled = false;
    reportStatusBox(e.message, 'error');
  }
}
async function pollBatteryReport() {
  if (reportPollTimer) {
    clearTimeout(reportPollTimer);
    reportPollTimer = null;
  }
  try {
    const r = await fetch('/api/reports/battery-health', { cache: 'no-store' }),
      data = await r.json();
    if (!r.ok) throw Error(data.detail || 'Could not read the report status');
    if (data.state === 'running') {
      const secs = Math.max(0, Math.round((Date.now() - Date.parse(data.started_at)) / 1000));
      $('reportBatteryBtn').disabled = true;
      reportStatusBox(`Analysing ${data.days} day${data.days === 1 ? '' : 's'} of history… ${secs} s`);
      reportPollTimer = setTimeout(pollBatteryReport, 1500);
      return;
    }
    $('reportBatteryBtn').disabled = false;
    showBatteryReport(data);
  } catch (e) {
    $('reportBatteryBtn').disabled = false;
    reportStatusBox(e.message, 'error');
  }
}
function showBatteryReport(data) {
  if (data.state === 'error') {
    $('reportOutput').hidden = true;
    reportStatusBox(data.error || 'The report failed', 'error');
    return;
  }
  if (data.state !== 'done' || !data.markdown) {
    reportStatusBox('');
    $('reportOutput').hidden = true;
    return;
  }
  const when = new Date(data.finished_at).toLocaleString('en-GB', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  });
  reportStatusBox(`Generated ${when} · ${data.days} day${data.days === 1 ? '' : 's'} analysed · took ${data.duration_seconds} s`);
  $('reportOutput').innerHTML = reportMarkdownToHtml(data.markdown);
  $('reportOutput').hidden = false;
}
async function loadReportsTab() {
  try {
    const r = await fetch('/api/reports/battery-health', { cache: 'no-store' }),
      data = await r.json();
    if (!r.ok) return;
    if (data.state === 'running') pollBatteryReport();
    else if (data.state !== 'idle') showBatteryReport(data);
  } catch (e) {}
}
function reportMarkdownToHtml(md) {
  const inline = s =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, (m, t) => {
        const c = { OK: 'ok', ATTENTION: 'warn', CRITICAL: 'crit' }[t];
        return c ? `<b class="rep-${c}">${t}</b>` : `<b>${t}</b>`;
      })
      .replace(/`([^`]+)`/g, '<code>$1</code>');
  const cells = row =>
      row
        .replace(/^\||\|\s*$/g, '')
        .split('|')
        .map(c => c.trim()),
    lines = md.split(/\r?\n/),
    out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith('|')) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith('|')) {
        rows.push(lines[i]);
        i++;
      }
      if (rows.length >= 2)
        out.push(
          `<div class="rep-table-wrap"><table class="rep-table"><thead><tr>${cells(rows[0])
            .map(c => `<th>${inline(c)}</th>`)
            .join('')}</tr></thead><tbody>${rows
            .slice(2)
            .map(
              r =>
                `<tr>${cells(r)
                  .map(c => `<td>${inline(c)}</td>`)
                  .join('')}</tr>`
            )
            .join('')}</tbody></table></div>`
        );
      continue;
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length + 2;
      out.push(`<h${level} class="rep-h">${inline(heading[2])}</h${level}>`);
      i++;
      continue;
    }
    if (line.startsWith('- ')) {
      const items = [];
      while (i < lines.length && lines[i].startsWith('- ')) {
        items.push(lines[i].slice(2));
        i++;
      }
      out.push('<ul class="rep-list">' + items.map(t => `<li>${inline(t)}</li>`).join('') + '</ul>');
      continue;
    }
    if (line.trim()) out.push(`<p class="rep-p">${inline(line)}</p>`);
    i++;
  }
  return out.join('');
}
$('reportRun').onclick = submitReportDialog;
$('reportCancel').onclick = closeReportDialog;
$('reportDays').addEventListener('input', () => {
  $('reportDays').value = $('reportDays').value.replace(/\D/g, '');
});
$('reportDays').addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    submitReportDialog();
  } else if (event.key === 'Escape') closeReportDialog();
});
$('reportDialog').addEventListener('click', event => {
  if (event.target === $('reportDialog')) closeReportDialog();
});
// The manual (GET /manual, built from docs/MANUAL.md) opens in a window of its own so the History page keeps its place.
function openManual() {
  const popup = window.open('/manual', 'mastervoltManual', 'popup,width=960,height=900');
  if (popup) popup.focus();
  else window.open('/manual', '_blank'); // a blocked pop-up falls back to a normal tab
}
