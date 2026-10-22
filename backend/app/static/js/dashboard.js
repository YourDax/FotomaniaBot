/* Обзор и настройки интерфейса. */
import { loadCampaigns } from './campaigns.js';
import { $, qa, S, savePrefs } from './core.js';
import { checkHealth } from './router.js';
import { loadSchools } from './schools.js';

// --- Обзор ------------------------------------------------------------------

export function renderDashboard() {
  const classes = S.schools.reduce((sum, school) => sum + (school.classes || []).length, 0);
  let kr = 0;
  let rk = 0;
  S.schools.forEach((school) => (school.classes || []).forEach((item) => (item.contacts || [])
    .forEach((contact) => { if (contact.role === 'KR') kr += 1; else rk += 1; })));
  $('kpiSchools').textContent = S.schools.length;
  $('kpiClassesHint').textContent = `классов: ${classes}`;
  $('kpiKr').textContent = kr;
  $('kpiRk').textContent = rk;
  $('kpiCampaigns').textContent = S.campaigns.length;

  let inWork = 0;
  let review = 0;
  S.campaigns.forEach((campaign) => {
    if (['RUNNING', 'WAITING_REVIEW'].includes(campaign.status)) inWork += 1;
    const counts = campaign.status_counts || {};
    review += (counts.REQUIRES_REVIEW || 0) + (counts.PENDING || 0) + (counts.PROCESSING || 0);
  });
  $('kpiCampaignsHint').textContent = `в работе: ${inWork}`;
  $('kpiReview').textContent = review;
}

export async function refreshDashboard() {
  await Promise.all([loadSchools(), loadCampaigns(), checkHealth(true)]);
}

// --- Настройки интерфейса ---------------------------------------------------

export function applyTheme(theme) {
  S.prefs.theme = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = S.prefs.theme;
  $('themeSelect').value = S.prefs.theme;
  savePrefs();
}

// Меню слева: выбор пользователя запоминается; пока выбора нет, на экранах уже 1180 px оно свёрнуто.
const AUTO_COLLAPSE_BELOW = 1180;

export function applySidebar() {
  const stored = S.prefs.sidebarCollapsed;
  const collapsed = typeof stored === 'boolean' ? stored : window.innerWidth < AUTO_COLLAPSE_BELOW;
  document.querySelector('.app').classList.toggle('sidebar-collapsed', collapsed);
  const toggle = $('sidebarToggle');
  const label = collapsed ? 'Развернуть меню' : 'Свернуть меню';
  toggle.setAttribute('aria-expanded', String(!collapsed));
  toggle.setAttribute('aria-label', label);
  toggle.title = label;
  // В свёрнутом виде подписи пунктов видны только во всплывающих подсказках.
  qa('.nav button').forEach((button) => {
    if (collapsed) button.title = button.querySelector('.nav-label').textContent;
    else button.removeAttribute('title');
  });
}

export function toggleSidebarCollapsed() {
  S.prefs.sidebarCollapsed = !document.querySelector('.app').classList.contains('sidebar-collapsed');
  savePrefs();
  applySidebar();
}

export function applyPrefs() {
  applyTheme(S.prefs.theme);
  applySidebar();
  S.collapsed = new Set(Array.isArray(S.prefs.collapsed) ? S.prefs.collapsed : []);
  $('refreshInterval').value = String(S.prefs.refreshMs);
  $('pageSizeDefault').value = String(S.prefs.pageSize);
  S.contactsUi.pageSize = S.prefs.pageSize;
  $('contactPageSize').value = String(S.prefs.pageSize);
  // Фильтры и сортировка контактов переживают перезагрузку страницы.
  const saved = S.prefs.contacts || {};
  Object.assign(S.contactsUi, {
    q: saved.q || '',
    school: saved.school || '',
    klass: saved.klass || '',
    role: saved.role || '',
    optedOut: saved.optedOut || '',
    sort: saved.sort || '',
    dir: saved.dir === 'desc' ? 'desc' : 'asc',
  });
  $('contactSearch').value = S.contactsUi.q;
  $('contactRole').value = S.contactsUi.role;
  $('contactOptOut').value = S.contactsUi.optedOut;
  $('taskPageSize').value = String(Math.min(S.prefs.pageSize, 100));
  S.tasksUi.pageSize = Number($('taskPageSize').value);
}
