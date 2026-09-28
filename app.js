const views = [...document.querySelectorAll('.view')];
const navItems = [...document.querySelectorAll('.nav-item')];
const pageTitle = document.getElementById('pageTitle');
const toast = document.getElementById('toast');
const sidebar = document.getElementById('sidebar');
const overlay = document.getElementById('mobileOverlay');
let toastTimer;

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
}

function showView(name, updateHash = true) {
  const target = document.getElementById(`view-${name}`) || document.getElementById('view-overview');
  views.forEach(view => view.classList.toggle('active', view === target));
  navItems.forEach(item => item.classList.toggle('active', item.dataset.view === target.id.replace('view-', '')));
  pageTitle.textContent = target.dataset.title;
  document.title = `${target.dataset.title} — ARSIA`;
  if (updateHash) history.replaceState(null, '', `#${target.id.replace('view-', '')}`);
  window.scrollTo({ top: 0, behavior: 'smooth' });
  sidebar.classList.remove('open');
  overlay.classList.remove('show');
}

navItems.forEach(item => item.addEventListener('click', () => showView(item.dataset.view)));
document.querySelectorAll('[data-go]').forEach(button => button.addEventListener('click', () => showView(button.dataset.go)));

document.getElementById('menuButton').addEventListener('click', event => {
  const open = sidebar.classList.toggle('open');
  overlay.classList.toggle('show', open);
  event.currentTarget.setAttribute('aria-expanded', String(open));
});
overlay.addEventListener('click', () => {
  sidebar.classList.remove('open');
  overlay.classList.remove('show');
});

document.getElementById('resetButton').addEventListener('click', () => {
  document.querySelectorAll('.toolbar select').forEach(select => select.selectedIndex = 0);
  showToast('Filters reset to all Australia');
});
document.querySelectorAll('.toolbar select').forEach(select => select.addEventListener('change', () => showToast(`Dashboard updated for ${select.value}`)));

document.querySelectorAll('.segmented').forEach(group => {
  group.querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
    group.querySelectorAll('button').forEach(item => item.classList.remove('active'));
    button.classList.add('active');
  }));
});

document.querySelectorAll('[data-map-mode]').forEach(button => button.addEventListener('click', () => {
  const heat = button.dataset.mapMode === 'heat';
  document.getElementById('heatLayer').classList.toggle('hidden', !heat);
  document.getElementById('pointLayer').classList.toggle('hidden', heat);
  showToast(heat ? 'Heatmap view enabled' : 'Crash clusters enabled');
}));

const layerCounts = { fatal: 5724, serious: 42306, other: 70452 };
document.querySelectorAll('[data-layer]').forEach(input => input.addEventListener('change', () => {
  const total = [...document.querySelectorAll('[data-layer]:checked')].reduce((sum, item) => sum + layerCounts[item.dataset.layer], 0);
  document.getElementById('visibleIncidents').textContent = total.toLocaleString();
  showToast('Map layers updated');
}));

document.getElementById('locateButton').addEventListener('click', () => showToast('Location preview is simulated in this prototype'));
document.getElementById('compareButton').addEventListener('click', () => showToast('Select up to three units from the full app to compare'));

const unitRows = [...document.querySelectorAll('#unitTable tbody tr')];
function filterUnits() {
  const term = document.getElementById('unitSearch').value.toLowerCase();
  const risk = document.querySelector('[data-risk].active')?.dataset.risk || 'all';
  unitRows.forEach(row => {
    row.hidden = !(row.textContent.toLowerCase().includes(term) && (risk === 'all' || row.dataset.risk === risk));
  });
}
document.getElementById('unitSearch').addEventListener('input', filterUnits);
document.querySelectorAll('button[data-risk]').forEach(button => button.addEventListener('click', filterUnits));

document.getElementById('searchInput').addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    showView('units');
    document.getElementById('unitSearch').value = event.currentTarget.value;
    filterUnits();
    showToast(`Showing matches for “${event.currentTarget.value}”`);
  }
});

document.getElementById('runChecksButton').addEventListener('click', event => {
  event.currentTarget.disabled = true;
  event.currentTarget.textContent = 'Checking…';
  setTimeout(() => {
    event.currentTarget.disabled = false;
    event.currentTarget.textContent = '↻ Run quality checks';
    document.getElementById('lastChecked').textContent = 'Just now';
    showToast('12 quality checks completed');
  }, 900);
});

document.getElementById('exportButton').addEventListener('click', () => {
  const rows = [['Metric','Value'],['Total crashes','118482'],['Fatal crashes','5724'],['Serious injuries','42306'],['Rate per 100k','45.7']];
  const csv = rows.map(row => row.join(',')).join('\n');
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  link.download = 'arsia-dashboard-export.csv';
  link.click();
  URL.revokeObjectURL(link.href);
  showToast('Mock dashboard data exported');
});

const initial = location.hash.replace('#', '') || 'overview';
showView(initial, false);
