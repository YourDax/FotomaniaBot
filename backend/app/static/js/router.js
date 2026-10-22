/* Маршрутизация по #hash, состояние сервера и сводка. */
import { loadCampaigns, loadMessageTemplates, openCampaignForm } from './campaigns.js';
import { loadContacts } from './contacts.js';
import { $, api, qa, S } from './core.js';
import { refreshDashboard } from './dashboard.js';
import { loadSchools } from './schools.js';
import { openTasks, startAutoRefresh, stopAutoRefresh } from './tasks.js';
import { toast } from './ui.js';

// --- Маршрутизация и навигация --------------------------------------------

export const ROUTES = {
  home: { title: 'Обзор', hint: 'Сводка по школам, контактам и рассылкам' },
  schools: { title: 'Школы и классы', hint: 'Структура школ с контактами КР и РК по классам' },
  contacts: { title: 'Контакты КР и РК', hint: 'Единый список с поиском, фильтрами и массовыми действиями' },
  import: { title: 'Импорт таблицы', hint: 'Загрузка XLSX или CSV с автоматическим определением столбцов' },
  campaigns: { title: 'Рассылки', hint: 'Создание рассылок и управление подготовкой сообщений' },
  tasks: { title: 'Задания рассылки', hint: 'Подготовка сообщений в MAX и подтверждение результата' },
  settings: { title: 'Настройки', hint: 'Состояние сервера и внешний вид' },
};

export function toggleSidebar(open) {
  $('sidebar').classList.toggle('open', open);
  $('scrim').classList.toggle('hidden', !open);
}

export function go(route, params = {}) {
  const target = ROUTES[route] ? route : 'home';
  S.route = target;
  qa('.view').forEach((view) => view.classList.add('hidden'));
  const section = $('route-' + target);
  if (section) section.classList.remove('hidden');
  qa('.nav button').forEach((button) => {
    const active = button.dataset.route === target
      || (target === 'tasks' && button.dataset.route === 'campaigns');
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  $('viewTitle').textContent = ROUTES[target].title;
  $('viewHint').textContent = ROUTES[target].hint;
  toggleSidebar(false);
  if (location.hash !== '#' + target) history.replaceState(null, '', '#' + target);
  if (target === 'schools') loadSchools().catch((error) => toast(error.message, 'error'));
  if (target === 'contacts') loadContacts().catch((error) => toast(error.message, 'error'));
  if (target === 'campaigns') {
    loadContacts().catch(() => {});
    loadCampaigns()
      .then(() => { if (!S.campaigns.length) openCampaignForm(); }) // первой рассылке сразу показываем форму
      .catch((error) => toast(error.message, 'error'));
    loadMessageTemplates().catch(() => {});
  }
  if (target === 'home') refreshDashboard().catch(() => {});
  if (target === 'settings') checkHealth(true);
  if (target === 'tasks') {
    const campaignId = params.campaignId || S.tasksUi.campaignId;
    openTasks(campaignId).catch((error) => toast(error.message, 'error'));
    startAutoRefresh();
    checkHealth(true);
  } else {
    stopAutoRefresh();
  }
}

// --- Здоровье, статистика, настройки --------------------------------------

// Состояние вкладки MAX в подключённом браузере: [тон, подпись, пояснение].
const MAX_STATES = {
  ready: ['ok', 'MAX: подключён', 'вкладка MAX открыта'],
  no_tab: ['warn', 'MAX: нет вкладки', 'в браузере нет открытой вкладки MAX — откройте web.max.ru и войдите'],
  offline: ['err', 'MAX: браузер не запущен', 'браузер с отладочным портом не найден — он запустится при первой подготовке сообщения'],
};

export function renderHealth() {
  const data = S.health;
  const ok = Boolean(data && data.status === 'ok');
  const pill = $('healthPill');
  const sidePill = $('sideHealthPill');
  pill.className = 'pill ' + (ok ? 'ok' : 'err');
  pill.innerHTML = `<span class="dot"></span>${ok ? 'сервер работает' : 'сервер недоступен'}`;
  sidePill.className = 'pill ' + (ok ? 'ok' : 'err');
  sidePill.innerHTML = `<span class="dot"></span>${ok ? 'online' : 'offline'}`;
  $('homeStatusServer').textContent = ok ? 'доступен' : 'нет ответа — проверьте, запущено ли приложение';
  const [maxTone, maxLabel, maxHint] = (data && MAX_STATES[data.max]) || ['', 'MAX: —', 'состояние неизвестно'];
  const maxPill = $('maxPill');
  maxPill.className = 'pill ' + maxTone;
  maxPill.innerHTML = `<span class="dot"></span><span class="pill-text">${maxLabel}</span>`;
  maxPill.title = maxHint;
  $('homeStatusMax').textContent = maxHint;
  $('settingsMax').textContent = maxHint;
  $('homeStatusWorker').textContent = data ? (data.worker ? 'активен' : 'не запущен') : '—';
  $('homeStatusIntegration').textContent = data ? String(data.integration || '—') : '—';
  $('homeStatusMode').textContent = data ? (data.mode === 'manual' ? 'ручной' : String(data.mode || '—')) : '—';
  $('settingsWorker').textContent = data ? (data.worker ? 'активен' : 'не запущен') : '—';
  $('settingsIntegration').textContent = data ? String(data.integration || '—') : '—';
  $('settingsMode').textContent = data ? 'ручной (автоотправка выключена)' : '—';
}

export async function checkHealth(silent = false) {
  try {
    S.health = await api('/health');
  } catch (error) {
    S.health = null;
    if (!silent) toast(error.message, 'error');
  }
  renderHealth();
  return S.health;
}
